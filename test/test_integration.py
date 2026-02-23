"""
Integration tests for LimiterSession rate-limiting behavior, run against a local HTTP server
"""

import itertools
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from requests_ratelimiter import LimiterSession


class _RateLimitServer(HTTPServer):
    """HTTPServer that enforces a 1 req/sec sliding-window rate limit."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()


class _RateLimitHandler(BaseHTTPRequestHandler):
    server: _RateLimitServer

    def log_message(self, format: str, *args) -> None: ...

    def do_GET(self) -> None:
        now = time.monotonic()
        with self.server._lock:
            # Drop timestamps outside the 1-second sliding window
            while self.server._timestamps and now - self.server._timestamps[0] > 1.0:
                self.server._timestamps.popleft()

            if self.server._timestamps:
                self.send_response(429)
                self.end_headers()
                return

            self.server._timestamps.append(now)

        self.send_response(200)
        self.end_headers()


def _start_rate_limit_server() -> tuple[_RateLimitServer, str]:
    """Start a local HTTP server that enforces 1 req/sec; return (server, base_url)."""
    server = _RateLimitServer(('127.0.0.1', 0), _RateLimitHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return server, f'http://{host}:{port}/'


@pytest.fixture
def rate_limit_server():
    """Start a local HTTP server that enforces 1 req/sec and yield the base URL."""
    server, url = _start_rate_limit_server()
    yield url
    server.shutdown()


@pytest.fixture
def rate_limit_servers():
    """Start two independent rate-limiting servers and yield their base URLs."""
    servers = [_start_rate_limit_server() for _ in range(2)]
    yield [url for _, url in servers]
    for server, _ in servers:
        server.shutdown()


def _make_session(**kwargs) -> LimiterSession:
    return LimiterSession(**kwargs)


def test_ratelimit__respects_limit(rate_limit_server):
    """Client should self-throttle so that all requests succeed (no 429s received).

    With per_second=1 and burst=1, the client waits ~1 second between requests,
    so 3 sequential requests should take at least 2 seconds total.
    """
    session = _make_session(per_second=1, burst=1)

    start = time.monotonic()
    statuses = [session.get(rate_limit_server).status_code for _ in range(3)]
    elapsed = time.monotonic() - start

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    assert elapsed >= 2.0, f'Expected >= 2s for 3 requests at 1/s, got: {elapsed:.2f}s'


def test_ratelimit__server_returns_429(rate_limit_server):
    """When the client bypasses rate-limiting, the server should return 429 responses"""
    # limit_statuses=[] disables the bucket-filling behavior that would otherwise delay next request
    session = _make_session(per_second=1000, burst=1000, limit_statuses=[])
    statuses = [session.get(rate_limit_server).status_code for _ in range(3)]

    assert statuses[0] == 200, f'Expected first request to succeed, got: {statuses[0]}'
    assert 429 in statuses, f'Expected at least one 429, got: {statuses}'


def test_ratelimit__fill_bucket_on_429(rate_limit_server):
    """A 429 response should trigger bucket-filling, delaying the next request"""
    session = _make_session(per_second=5, burst=5)
    start = time.monotonic()
    statuses = [session.get(rate_limit_server).status_code for _ in range(3)]
    elapsed = time.monotonic() - start

    assert statuses[0] == 200, f'Expected first request to succeed, got: {statuses[0]}'
    assert statuses[1] == 429, f'Expected second request to get 429, got: {statuses[1]}'
    assert elapsed >= 1.0, f'Expected >= 1s delay after 429 (bucket-filling), got: {elapsed:.2f}s'


def test_ratelimit__per_host_isolation(rate_limit_servers):
    """With per_host=True (default), each host has its own bucket"""
    url1, url2 = rate_limit_servers
    session = _make_session(per_second=1, burst=1, per_host=True)

    # Alternate between the two hosts; neither bucket should fill up
    start = time.monotonic()
    statuses = [
        session.get(url).status_code for url in itertools.islice(itertools.cycle([url1, url2]), 4)
    ]
    elapsed = time.monotonic() - start

    assert statuses == [200, 200, 200, 200], f'Expected all 200s, got: {statuses}'
    # With isolated buckets, 4 alternating requests should complete well under 2s
    assert elapsed < 2.0, f'Expected < 2s with per-host isolation, got: {elapsed:.2f}s'


def test_ratelimit__per_host_disabled(rate_limit_servers):
    """With per_host=False, all hosts share a single bucket"""
    url1, url2 = rate_limit_servers
    session = _make_session(per_second=1, burst=1, per_host=False)

    # Alternate between two hosts; the shared bucket throttles after the first request
    start = time.monotonic()
    statuses = [
        session.get(url).status_code for url in itertools.islice(itertools.cycle([url1, url2]), 3)
    ]
    elapsed = time.monotonic() - start

    assert statuses == [200, 200, 200], f'Expected all 200s, got: {statuses}'
    # Shared bucket at 1 req/sec means 3 requests take at least 2 seconds
    assert elapsed >= 2.0, f'Expected >= 2s with shared bucket, got: {elapsed:.2f}s'
