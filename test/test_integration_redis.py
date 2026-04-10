"""
Integration tests for LimiterSession with a Redis backend, validating the per-host fix (issue #147).

Previously, HostBucketFactory._create_bucket() did not support RedisBucket, causing all hosts to
share a single Redis key. The fix uses _sanitize_name(host) as the Redis bucket_key, giving each
host its own key.

Requires: a Redis server at localhost:6379
Optionally uses httpbin at localhost:8080 for end-to-end tests against a real HTTP server.
Run with: docker compose up -d && pytest -m redis
"""

import time

import pytest
import redis as redis_lib

from pyrate_limiter import Rate
from requests_ratelimiter import LimiterSession, RedisBucket
from requests_ratelimiter.buckets import HostBucketFactory

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
HTTPBIN_URL = 'http://localhost:8080'


def _httpbin_available() -> bool:
    try:
        import urllib.request

        urllib.request.urlopen(f'{HTTPBIN_URL}/get', timeout=2)
        return True
    except Exception:
        return False


def _redis_available() -> bool:
    try:
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


if not _redis_available():
    pytest.skip(
        f'Redis not available at {REDIS_HOST}:{REDIS_PORT}',
        allow_module_level=True,
    )


@pytest.fixture(scope='module')
def redis_client():
    """Yield a real Redis connection; flush the test keyspace before and after."""
    r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.mark.redis
@pytest.mark.parametrize(
    'host1, host2, expected_key1, expected_key2',
    [
        ('127.0.0.1:8001', '127.0.0.1:8002', '127_0_0_1_8001', '127_0_0_1_8002'),
        (
            'myapp:127.0.0.1:8001',
            'myapp:127.0.0.1:8002',
            'myapp_127_0_0_1_8001',
            'myapp_127_0_0_1_8002',
        ),
    ],
    ids=['no_prefix', 'with_bucket_name_prefix'],
)
def test_redis__bucket_keys(redis_client, host1, host2, expected_key1, expected_key2):
    """Each host gets its own sanitized Redis bucket_key (issue #147).

    We check bucket_key directly on the returned objects since Redis only creates the key
    when an item is first written. The prefixed case simulates what LimiterSession._bucket_name()
    produces when bucket_name='myapp' is set alongside per_host=True.
    """
    factory = HostBucketFactory(
        rates=[Rate(5, 1000)],
        bucket_class=RedisBucket,
        bucket_init_kwargs={'redis': redis_client},
    )
    bucket1 = factory._create_bucket(host1)
    bucket2 = factory._create_bucket(host2)

    assert bucket1.bucket_key == expected_key1, f'Unexpected key: {bucket1.bucket_key}'
    assert bucket2.bucket_key == expected_key2, f'Unexpected key: {bucket2.bucket_key}'


@pytest.mark.integration
@pytest.mark.redis
@pytest.mark.parametrize(
    'bucket_name, expected_max_elapsed',
    [
        (None, 2.0),
        ('myapp', 2.0),
    ],
    ids=['no_prefix', 'with_bucket_name_prefix'],
)
def test_redis__per_host_isolation(
    redis_client, rate_limit_servers, bucket_name, expected_max_elapsed
):
    """With per_host=True and RedisBucket, each host gets an independent rate limit bucket.

    Core regression test for issue #147: before the fix, all hosts shared one Redis key, so
    alternating requests between two hosts would still consume the shared bucket.
    """
    url1, url2 = rate_limit_servers
    session = LimiterSession(
        per_second=1,
        burst=1,
        per_host=True,
        bucket_name=bucket_name,
        bucket_class=RedisBucket,
        bucket_kwargs={'redis': redis_client},
    )

    start = time.monotonic()
    statuses = [session.get(url).status_code for url in [url1, url2, url1, url2]]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200, 200], f'Expected all 200s, got: {statuses}'
    # If #147 were still broken (shared bucket at 1 req/sec), elapsed would be >= 2s
    assert elapsed < expected_max_elapsed, (
        f'Expected < {expected_max_elapsed}s with per-host Redis isolation, got: {elapsed:.2f}s'
    )


@pytest.mark.integration
@pytest.mark.redis
def test_redis__per_host_disabled(redis_client, rate_limit_servers):
    """With per_host=False and RedisBucket, all hosts share a single Redis key."""
    url1, url2 = rate_limit_servers
    session = LimiterSession(
        per_second=1,
        burst=1,
        per_host=False,
        bucket_class=RedisBucket,
        bucket_kwargs={'redis': redis_client},
    )

    start = time.monotonic()
    statuses = [session.get(url).status_code for url in [url1, url2, url1]]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed >= 2.0, f'Expected >= 2s with shared Redis bucket, got: {elapsed:.2f}s'


# Redis + httpbin combined: end-to-end validation with a real HTTP server and real Redis backend
_httpbin = pytest.mark.skipif(
    not _httpbin_available(), reason='httpbin not available at localhost:8080'
)


@_httpbin
@pytest.mark.redis
def test_redis_httpbin__respects_rate_limit(redis_client):
    """LimiterSession with RedisBucket throttles real requests to httpbin within the configured rate."""
    session = LimiterSession(
        per_second=2,
        burst=1,
        bucket_class=RedisBucket,
        bucket_kwargs={'redis': redis_client},
    )

    start = time.monotonic()
    statuses = [session.get(f'{HTTPBIN_URL}/get').status_code for _ in range(3)]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed >= 1.0, f'Expected >= 1s for 3 requests at 2/s with burst=1, got: {elapsed:.2f}s'


@_httpbin
@pytest.mark.redis
def test_redis_httpbin__fill_bucket_on_429(redis_client):
    """A 429 from httpbin triggers Redis bucket-filling, adding a delay before the next request."""
    session = LimiterSession(
        per_second=100,
        burst=100,
        bucket_class=RedisBucket,
        bucket_kwargs={'redis': redis_client},
    )

    start = time.monotonic()
    r1 = session.get(f'{HTTPBIN_URL}/status/429')
    assert r1.status_code == 429

    r2 = session.get(f'{HTTPBIN_URL}/get')
    elapsed = time.monotonic() - start
    session.close()

    assert r2.status_code == 200
    assert elapsed >= 1.0, (
        f'Expected >= 1s delay after Redis bucket-fill on 429, got: {elapsed:.2f}s'
    )


@_httpbin
@pytest.mark.redis
def test_redis_httpbin__per_host_isolation(redis_client):
    """With per_host=True and RedisBucket, distinct netloc strings get separate Redis keys.

    'localhost' and '127.0.0.1' both resolve to the same httpbin server, but are rate-limited
    independently. With a shared bucket at 1/s, 4 requests would require >= 3s of waiting.
    """
    url_a = 'http://localhost:8080/get'
    url_b = 'http://127.0.0.1:8080/get'
    session = LimiterSession(
        per_second=1,
        burst=1,
        per_host=True,
        bucket_class=RedisBucket,
        bucket_kwargs={'redis': redis_client},
    )

    start = time.monotonic()
    statuses = [session.get(url).status_code for url in [url_a, url_b, url_a, url_b]]
    elapsed = time.monotonic() - start
    session.close()

    assert statuses == [200, 200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed < 3.0, f'Expected < 3s with per-host Redis isolation, got: {elapsed:.2f}s'
