"""
Integration tests for LimiterSession rate-limiting behavior, run against a local httpbin instance.

Requires: httpbin running at localhost:8080
Run with: docker compose up -d && pytest -m integration
"""

import time

import pytest

from requests_ratelimiter import LimiterSession

HTTPBIN_URL = 'http://localhost:8080'


def _httpbin_available() -> bool:
    try:
        import urllib.request

        urllib.request.urlopen(f'{HTTPBIN_URL}/get', timeout=2)
        return True
    except Exception:
        return False


if not _httpbin_available():
    pytest.skip(
        f'httpbin not available at {HTTPBIN_URL}',
        allow_module_level=True,
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    'method, path, json_body',
    [
        ('GET', '/get', None),
        ('POST', '/anything', {'key': 'value', 'count': 42}),
    ],
)
def test_ratelimit__request_succeeds(method, path, json_body):
    """Requests reach the real server and return the expected response."""
    session = LimiterSession(per_second=10)
    response = session.request(method, f'{HTTPBIN_URL}{path}', json=json_body)
    session.close()

    assert response.status_code == 200
    body = response.json()
    assert body['method'] == method
    if json_body is not None:
        assert body['json'] == json_body


@pytest.mark.integration
def test_ratelimit__respects_limit():
    """LimiterSession throttles requests to stay within the configured rate.

    At 2 req/sec with burst=1, 3 sequential requests must take at least 1 second.
    """
    session = LimiterSession(per_second=2, burst=1)

    start = time.monotonic()
    statuses = [session.get(f'{HTTPBIN_URL}/get').status_code for _ in range(3)]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed >= 1.0, f'Expected >= 1s for 3 requests at 2/s with burst=1, got: {elapsed:.2f}s'


@pytest.mark.integration
def test_ratelimit__burst_allows_rapid_requests():
    """With a large burst, multiple requests complete without inter-request waiting."""
    session = LimiterSession(per_second=5, burst=5)

    start = time.monotonic()
    statuses = [session.get(f'{HTTPBIN_URL}/get').status_code for _ in range(5)]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200, 200, 200], f'Expected all 200s, got: {statuses}'
    # At 5 req/sec the inter-request delay is 200ms; 5 requests within burst should take well under 1s of waiting
    assert elapsed < 1.5, f'Expected < 1.5s for burst of 5 at 5/s, got: {elapsed:.2f}s'


@pytest.mark.integration
def test_ratelimit__fill_bucket_on_429():
    """A 429 from the server triggers bucket-filling, adding a delay before the next request.

    We configure a high rate limit so the client doesn't self-throttle, then hit /status/429
    directly. The 429 handler fills the bucket, causing the next request to be delayed.
    """
    session = LimiterSession(per_second=100, burst=100)

    start = time.monotonic()
    r1 = session.get(f'{HTTPBIN_URL}/status/429')
    assert r1.status_code == 429

    r2 = session.get(f'{HTTPBIN_URL}/get')
    elapsed = time.monotonic() - start
    session.close()

    assert r2.status_code == 200
    assert elapsed >= 1.0, f'Expected >= 1s delay after 429 bucket-fill, got: {elapsed:.2f}s'


@pytest.mark.integration
def test_ratelimit__no_limit_statuses_skips_fill():
    """With limit_statuses=[], a 429 response does not trigger bucket-filling."""
    session = LimiterSession(per_second=2, burst=1, limit_statuses=[])

    start = time.monotonic()
    r1 = session.get(f'{HTTPBIN_URL}/status/429')
    r2 = session.get(f'{HTTPBIN_URL}/get')
    elapsed = time.monotonic() - start
    session.close()

    assert r1.status_code == 429
    assert r2.status_code == 200
    # Without bucket-filling, only the normal ~0.5s rate-limit wait applies
    assert elapsed < 1.5, f'Expected < 1.5s without bucket-filling, got: {elapsed:.2f}s'


@pytest.mark.integration
def test_ratelimit__per_host_isolation():
    """With per_host=True, each distinct netloc gets its own rate limit bucket.

    'localhost' and '127.0.0.1' both resolve to the same httpbin server but are tracked
    separately, so alternating requests between them don't consume a shared bucket.
    """
    url_a = f'{HTTPBIN_URL}/get'
    url_b = 'http://127.0.0.1:8080/get'
    session = LimiterSession(per_second=1, burst=1, per_host=True)

    start = time.monotonic()
    statuses = [session.get(url).status_code for url in [url_a, url_b, url_a, url_b]]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200, 200], f'Expected all 200s, got: {statuses}'
    # With a shared bucket at 1/s, 4 requests would require >= 3s; isolated buckets finish faster
    assert elapsed < 3.0, f'Expected < 3s with per-host isolation, got: {elapsed:.2f}s'


@pytest.mark.integration
def test_ratelimit__per_host_disabled():
    """With per_host=False, all requests share one bucket regardless of hostname."""
    url_a = f'{HTTPBIN_URL}/get'
    url_b = 'http://127.0.0.1:8080/get'
    session = LimiterSession(per_second=1, burst=1, per_host=False)

    start = time.monotonic()
    statuses = [session.get(url).status_code for url in [url_a, url_b, url_a]]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed >= 2.0, f'Expected >= 2s with shared bucket, got: {elapsed:.2f}s'
