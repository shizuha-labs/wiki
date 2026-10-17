"""WIKI-56: the Wiki must expose a per-request status-class series so QA can
compute the service 5xx rate for an exact window.

Previously the Wiki exposed blackbox probe status + attachment/security
counters but no request-total/status series — QA could see sampled health
failures but not request-level 5xx volume/rate.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.test.client import RequestFactory

from wiki.request_metrics import (
    RequestStatusMetricsMiddleware,
    _status_class,
    record_request_status,
    render_request_status_metrics,
    request_status_metrics,
)
from wiki.security_events import boundary_event_metrics


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def mget(self, keys):
        return [self.store.get(k, 0) for k in keys]


class Wiki56RequestStatusMetricsTests(TestCase):
    def test_status_class_bucketing(self):
        self.assertEqual(_status_class(200), '2xx')
        self.assertEqual(_status_class(301), '3xx')
        self.assertEqual(_status_class(404), '4xx')
        self.assertEqual(_status_class(502), '5xx')
        self.assertEqual(_status_class(600), 'other')

    def test_record_and_render_5xx_rate(self):
        fake = _FakeRedis()
        with patch('wiki.request_metrics._metrics_redis_client', return_value=fake):
            # Simulate a window: 90 requests, 9 of them 5xx.
            for _ in range(81):
                record_request_status(200)
            for _ in range(9):
                record_request_status(502)
            text = render_request_status_metrics()

        # PromQL-queryable: total, 5xx count, and ratio.
        self.assertIn('wiki_http_requests_total{service="wiki",status="2xx"} 81', text)
        self.assertIn('wiki_http_requests_total{service="wiki",status="5xx"} 9', text)
        # sum(rate(wiki_http_requests_total{status="5xx"}[5m]))
        #   / sum(rate(wiki_http_requests_total[5m])) = 9/90 = 0.10
        total = 81 + 9
        self.assertEqual(total, 90)
        self.assertEqual(9 / total, 0.10)

    def test_middleware_records_response_status(self):
        fake = _FakeRedis()
        rf = RequestFactory()
        request = rf.get('/api/health/')

        def get_response(req):
            from django.http import HttpResponse
            return HttpResponse(status=503)

        mw = RequestStatusMetricsMiddleware(get_response)
        with patch('wiki.request_metrics._metrics_redis_client', return_value=fake):
            resp = mw(request)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(fake.store.get('wiki:metrics:http_requests:5xx'), 1)

    def test_endpoint_renders_prometheus_text(self):
        fake = _FakeRedis()
        fake.store['wiki:metrics:http_requests:5xx'] = 3
        with patch('wiki.request_metrics._metrics_redis_client', return_value=fake):
            resp = request_status_metrics(MagicMock())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('# TYPE wiki_http_requests_total counter', body)
        self.assertIn('wiki_http_requests_total{service="wiki",status="5xx"} 3', body)

    def test_redis_outage_fails_open(self):
        client = MagicMock()
        client.mget.side_effect = RuntimeError('redis down')
        with patch('wiki.request_metrics._metrics_redis_client', return_value=client):
            text = render_request_status_metrics()
        # Fails open: counters render as 0 with a probe_errors gauge, no raise.
        self.assertIn('wiki_http_requests_total{service="wiki",status="5xx"} 0', text)
        self.assertIn('wiki_http_requests_probe_errors{service="wiki"} 1', text)

    def test_scraped_security_events_path_carries_request_series(self):
        # WIKI-56 deploy-verify residual: Prometheus scrapes
        # /api/metrics/security-events/ (the ServiceMonitor target), so the
        # per-request status-class series must be served on that path too —
        # otherwise the PromQL 5xx-rate contract is unprovable.
        fake = _FakeRedis()
        fake.store['wiki:metrics:http_requests:5xx'] = 7
        with patch('wiki.request_metrics._metrics_redis_client', return_value=fake):
            resp = boundary_event_metrics(MagicMock())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Both series families on the scraped path.
        self.assertIn('platform_boundary_event_producer_total', body)
        self.assertIn('wiki_http_requests_total{service="wiki",status="5xx"} 7', body)

    def test_scraped_path_survives_request_metrics_backend_outage(self):
        # The boundary-metrics scrape must not break when the request-metrics
        # backend is down (best-effort append).
        client = MagicMock()
        client.mget.side_effect = RuntimeError('redis down')
        with patch('wiki.request_metrics._metrics_redis_client', return_value=client):
            resp = boundary_event_metrics(MagicMock())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('platform_boundary_event_producer_total', body)
        self.assertIn('wiki_http_requests_probe_errors{service="wiki"} 1', body)
