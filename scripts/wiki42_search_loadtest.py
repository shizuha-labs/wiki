"""WIKI-42 load generator — concurrent multi-word searches against a replica.

Fires the audit-style traffic that OOMKilled prod (multi-word queries whose
terms hit the multi-MB heavy-tail pages) and reports status distribution,
latency percentiles, and whether the replica survived.

Usage (from anywhere with HTTP reach to the target):
    python scripts/wiki42_search_loadtest.py http://127.0.0.1:8000 [requests_per_worker] [concurrency]

For an authenticated production probe, set WIKI_LOADTEST_BEARER_TOKEN.  The
token is consumed only as an Authorization header and is never printed.

Pass criteria (asserted): the preflight proves both a valid search and bounded
400 rejection, every load response is 200 or 429 (shed), zero 5xx / connection
failures, and a 16-way burst observes at least one 429.  The serving container
must not restart (checked by the caller via docker/kubectl, not this script).
"""
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

QUERIES = [
    'deploy runbook postgres replica',
    'memory incident rollback audit',
    'giant audit export retrieval',
    'kubernetes replica memory incident rollback',
    'search vector index headline excerpt',
    'runbook deploy audit pipeline forgejo origin',
]


TIMEOUT_SECONDS = 20


def request(base, query):
    url = f'{base}/api/search/?q=' + urllib.parse.quote(query)
    req = urllib.request.Request(url)
    token = os.environ.get('WIKI_LOADTEST_BEARER_TOKEN', '').strip()
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read()
            code = resp.status
            n = len(json.loads(body)) if code == 200 else 0
    except urllib.error.HTTPError as e:
        code, n, body = e.code, 0, e.read()
    except Exception:
        code, n, body = -1, 0, b''
    return code, time.monotonic() - start, n, len(body)


def worker(base, requests_per_worker, worker_id, barrier, out, lock):
    barrier.wait()
    for i in range(requests_per_worker):
        result = request(base, QUERIES[(worker_id + i) % len(QUERIES)])
        with lock:
            out.append(result)


def main():
    base = sys.argv[1].rstrip('/')
    requests_per_worker = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 16

    control_ok = request(base, QUERIES[0])
    control_reject = request(base, 'x' * 201)
    print(f'preflight valid={control_ok[0]} reject={control_reject[0]}')
    if control_ok[0] not in (200, 429) or control_reject[0] != 400:
        print('FAIL: preflight did not prove valid and bounded-rejection paths')
        sys.exit(1)

    out, lock = [], threading.Lock()
    barrier = threading.Barrier(concurrency)
    threads = [threading.Thread(
        target=worker,
        args=(base, requests_per_worker, worker_id, barrier, out, lock),
    ) for worker_id in range(concurrency)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - t0

    codes = {}
    for code, _, _, _ in out:
        codes[code] = codes.get(code, 0) + 1
    lat = sorted(e for c, e, _, _ in out if c == 200)
    payloads = [p for c, _, _, p in out if c == 200]
    print(f'requests={len(out)} wall={wall:.1f}s codes={codes}')
    if lat:
        print(f'latency p50={statistics.median(lat)*1000:.0f}ms '
              f'p95={lat[int(len(lat)*0.95)-1]*1000:.0f}ms max={lat[-1]*1000:.0f}ms')
        print(f'payload max={max(payloads)}B mean={sum(payloads)//len(payloads)}B')

    bad = {c: n for c, n in codes.items() if c not in (200, 429)}
    if bad:
        print(f'FAIL: unexpected statuses {bad}')
        sys.exit(1)
    if concurrency >= 16 and codes.get(429, 0) == 0:
        print('FAIL: overloaded burst queued instead of exercising the 429 admission gate')
        sys.exit(1)
    print('PASS: all responses 200/429, no errors')


if __name__ == '__main__':
    main()
