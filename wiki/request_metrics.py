"""WIKI-56: per-request HTTP status metrics for the Wiki service.

The Wiki exposed blackbox probe status plus attachment-cleanup/security
counters, but no request-total/status series — so QA could see sampled health
failures but could not compute the L8-required service 5xx rate for an exact
window. This adds a bounded per-request status-class counter (2xx/3xx/4xx/5xx)
persisted to Redis and rendered as Prometheus text, so a PromQL query can
return total requests, 5xx count, and 5xx ratio for an arbitrary range.

The counter is deliberately bounded (one key per status class, not per
endpoint/status) to keep cardinality flat and avoid leaking request detail.
"""

from __future__ import annotations

import logging

import redis
from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

_STATUS_CLASSES = ('2xx', '3xx', '4xx', '5xx', 'other')
_METRIC_KEY = 'wiki:metrics:http_requests:{status_class}'


def _metrics_redis_client():
    url = getattr(settings, 'CONNECT_SECURITY_EVENT_METRICS_REDIS_URL', '') or getattr(
        settings, 'CELERY_BROKER_URL', 'redis://redis:6379/5',
    )
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )


def _status_class(code: int) -> str:
    if 200 <= code < 300:
        return '2xx'
    if 300 <= code < 400:
        return '3xx'
    if 400 <= code < 500:
        return '4xx'
    if 500 <= code < 600:
        return '5xx'
    return 'other'


def record_request_status(code: int) -> bool:
    """Increment the status-class counter for one completed request.

    Best-effort: a metrics write must never break the request path.
    """
    try:
        _metrics_redis_client().incr(_METRIC_KEY.format(status_class=_status_class(code)))
        return True
    except Exception:
        logger.exception('WIKI-56 failed to record request status code=%s', code)
        return False


def render_request_status_metrics() -> str:
    counts = {cls: 0 for cls in _STATUS_CLASSES}
    probe_errors = 0
    try:
        client = _metrics_redis_client()
        values = client.mget([_METRIC_KEY.format(status_class=cls) for cls in _STATUS_CLASSES])
        counts.update({
            cls: int(raw or 0)
            for cls, raw in zip(_STATUS_CLASSES, values)
        })
    except Exception:
        probe_errors = 1
        logger.exception('WIKI-56 failed to collect request-status metrics')
    lines = [
        '# HELP wiki_http_requests_total HTTP requests completed by status class.',
        '# TYPE wiki_http_requests_total counter',
    ]
    lines.extend(
        f'wiki_http_requests_total{{service="wiki",status="{cls}"}} {counts[cls]}'
        for cls in _STATUS_CLASSES
    )
    lines.extend([
        '# HELP wiki_http_requests_probe_errors Request-status metric backend collection errors.',
        '# TYPE wiki_http_requests_probe_errors gauge',
        f'wiki_http_requests_probe_errors{{service="wiki"}} {probe_errors}',
    ])
    return '\n'.join(lines) + '\n'


def request_status_metrics(request):
    return HttpResponse(
        render_request_status_metrics(),
        content_type='text/plain; version=0.0.4; charset=utf-8',
    )


class RequestStatusMetricsMiddleware:
    """Record every completed request's status class into the counter.

    Placed late in the middleware stack so the status reflects the final
    response (including 4xx/5xx raised by inner middleware/views).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        record_request_status(response.status_code)
        return response
