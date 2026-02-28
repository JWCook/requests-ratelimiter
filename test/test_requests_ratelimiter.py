"""
General rate-limiting behavior is covered by pyrate-limiter unit tests. These tests should cover
additional behavior specific to requests-ratelimiter.
"""

import pickle
from time import sleep
from unittest.mock import MagicMock, patch

import pytest
from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate, SQLiteBucket
from requests import PreparedRequest, Session
from requests_cache import CacheMixin

from requests_ratelimiter import LimiterMixin, LimiterSession
from requests_ratelimiter.buckets import prepare_sqlite_kwargs
from requests_ratelimiter.requests_ratelimiter import _convert_rate
from test.conftest import (
    MOCKED_URL,
    MOCKED_URL_429,
    MOCKED_URL_500,
    MOCKED_URL_ALT_HOST,
    get_mock_session,
    mount_mock_adapter,
    SQLITE_BUCKET_KWARGS,
)

patch_sleep = patch('pyrate_limiter.limiter.sleep', side_effect=sleep)


class CustomSession(LimiterMixin, Session):
    """Custom Session that adds an extra class attribute"""

    def __init__(self, *args, flag: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.flag = flag


@patch_sleep
@pytest.mark.parametrize(
    'session_factory',
    [
        lambda: LimiterSession(per_second=5),
        lambda: CustomSession(per_second=5, flag=True),
    ],
    ids=['LimiterSession', 'CustomSession'],
)
def test_rate_limit_enforcement(mock_sleep, session_factory):
    session = mount_mock_adapter(session_factory())

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


def test_custom_session_preserves_attributes():
    session = CustomSession(per_second=5, flag=True)
    assert session.flag is True


@patch_sleep
def test_limiter_adapter(mock_sleep, limiter_adapter_session: tuple) -> None:
    session, adapter = limiter_adapter_session

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
def test_custom_limiter(mock_sleep):
    bucket = InMemoryBucket([Rate(5, Duration.SECOND)])
    limiter = Limiter(bucket)
    session = get_mock_session(limiter=limiter)

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
@pytest.mark.parametrize(
    'url, session_kwargs, expect_sleep',
    [
        (MOCKED_URL_429, {}, True),  # default: 429 fills bucket
        (MOCKED_URL_500, {'limit_statuses': [500]}, True),  # custom status fills bucket
        (MOCKED_URL_429, {'limit_statuses': []}, False),  # disabled: no fill on 429
    ],
)
def test_limit_status_handling(mock_sleep, url, session_kwargs, expect_sleep):
    """Bucket is filled (or not) depending on the response status and limit_statuses config"""
    session = get_mock_session(per_second=5, **session_kwargs)

    session.get(url)
    assert mock_sleep.called is False

    session.get(url)
    assert mock_sleep.called is expect_sleep


@patch_sleep
def test_429__per_host(mock_sleep):
    """With per_host, after receiving a 429 response, only that bucket should be filled"""
    session = get_mock_session(per_second=5, per_host=True)

    session.get(MOCKED_URL_429)

    # A 429 from one host should not affect requests for a different host
    session.get(MOCKED_URL_ALT_HOST)
    assert mock_sleep.called is False

    # But a second request to the original host should be delayed (its bucket was filled)
    session.get(MOCKED_URL_429)
    assert mock_sleep.called is True


@pytest.mark.parametrize(
    'limit, interval, expected_limit, expected_interval',
    [
        (5, 1, 5, 1),
        (0.5, 1, 1, 2),
        (1, 0.5, 2, 1),  # 1 req/0.5ms -> 2 req/1ms
        (0.001, 1, 1, 1000),
    ],
)
def test_convert_rate(limit, interval, expected_limit, expected_interval):
    rate = _convert_rate(limit, interval)
    assert rate.limit == expected_limit
    assert rate.interval == expected_interval


@patch_sleep
def test_sqlite_backend(mock_sleep, tmp_path):
    """Check that the SQLite backend works as expected"""
    session = get_mock_session(
        per_second=5,
        bucket_class=SQLiteBucket,
        bucket_kwargs={'path': tmp_path / 'rate_limit.db', **SQLITE_BUCKET_KWARGS},
    )

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
def test_custom_bucket(mock_sleep, tmp_path):
    """With custom buckets, each session can be called independently without triggering rate
    limiting but requires a common backend such as sqlite
    """
    ratelimit_path = tmp_path / 'rate_limit.db'

    session_a = get_mock_session(
        per_second=5,
        bucket_name='a',
        bucket_class=SQLiteBucket,
        bucket_kwargs={'path': ratelimit_path, **SQLITE_BUCKET_KWARGS},
    )
    session_b = get_mock_session(
        per_second=5,
        bucket_name='b',
        bucket_class=SQLiteBucket,
        bucket_kwargs={'path': ratelimit_path, **SQLITE_BUCKET_KWARGS},
    )

    for _ in range(5):
        session_a.get(MOCKED_URL)
        session_b.get(MOCKED_URL)
    assert mock_sleep.called is False

    session_a.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
def test_cache_with_limiter(mock_sleep, tmp_path_factory):
    """Check that caching integration works as expected"""

    class CachedLimiterSession(CacheMixin, LimiterMixin, Session):
        """
        Session class with caching and rate-limiting behavior. Accepts arguments for both
        LimiterSession and CachedSession.
        """

    cache_path = tmp_path_factory.mktemp('pytest') / 'cache.db'
    ratelimit_path = tmp_path_factory.mktemp('pytest') / 'rate_limit.db'

    session = CachedLimiterSession(
        per_second=5,
        cache_name=str(cache_path),
        bucket_class=SQLiteBucket,
        bucket_kwargs={'path': ratelimit_path, **SQLITE_BUCKET_KWARGS},
    )
    session = mount_mock_adapter(session)

    for _ in range(10):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False


def test_inherited_session_attributes():
    """Inherited Session attributes are present and initialised by the base Session."""
    session = LimiterSession(per_second=5)
    assert session.headers is not None
    assert session.cookies is not None
    assert session.auth is None  # Session default
    assert session.hooks is not None


def test_pickling_and_unpickling():
    session = LimiterSession(per_second=5)
    unpickled_session = pickle.loads(pickle.dumps(session))

    assert unpickled_session.per_host == session.per_host
    assert unpickled_session.bucket_name == session.bucket_name
    assert unpickled_session.limit_statuses == session.limit_statuses
    assert unpickled_session._default_bucket == session._default_bucket


# Tests for lifecycle of bucket factory leaker thread:
#
# pyrate-limiter 4 introduced a background `Leaker` thread per `BucketFactory`.
# Because `LimiterMixin` creates the `BucketFactory` internally, it must also be
# responsible for tearing it down. Without an explicit `close()` override, every
# `LimiterAdapter` or `LimiterSession` that is discarded after use leaves a
# daemon thread running until the process exits.
#
# The tests below verify that `LimiterMixin.close()` stops the Leaker and
# behaves as expected.


def _assert_leaker_stopped(leaker, bucket_factory) -> None:
    """Assert that a Leaker thread has been stopped and cleared from the bucket factory."""
    assert leaker._stop_event.is_set()
    assert bucket_factory._leaker is None


def test_limiter_adapter_close_stops_leaker(limiter_adapter_session: tuple) -> None:
    """LimiterAdapter.close() stops the Leaker thread."""
    session, adapter = limiter_adapter_session
    assert adapter.limiter.bucket_factory._leaker is None  # no thread before first request

    session.get(MOCKED_URL)
    leaker = adapter.limiter.bucket_factory._leaker
    assert leaker is not None
    assert leaker.is_alive()

    adapter.close()
    _assert_leaker_stopped(leaker, adapter.limiter.bucket_factory)


def test_limiter_session_close_stops_leaker():
    """LimiterSession.close() stops the Leaker thread spawned on the first request."""
    session = get_mock_session(per_second=5)
    assert session.limiter.bucket_factory._leaker is None  # no thread before first request

    session.get(MOCKED_URL)
    leaker = session.limiter.bucket_factory._leaker
    assert leaker is not None
    assert leaker.is_alive()

    session.close()
    _assert_leaker_stopped(leaker, session.limiter.bucket_factory)


def test_limiter_session_context_manager_stops_leaker():
    """Using LimiterSession as a context manager stops the Leaker on __exit__."""
    with get_mock_session(per_second=5) as session:
        session.get(MOCKED_URL)
        leaker = session.limiter.bucket_factory._leaker
        assert leaker is not None

    _assert_leaker_stopped(leaker, session.limiter.bucket_factory)  # __exit__ calls close()


def test_session_close_cascades_to_limiter_adapter(limiter_adapter_session: tuple) -> None:
    """Closing a Session cascades to LimiterAdapter.close(), stopping the Leaker."""
    session, adapter = limiter_adapter_session

    session.get(MOCKED_URL)
    leaker = adapter.limiter.bucket_factory._leaker
    assert leaker is not None
    assert leaker.is_alive()

    session.close()
    _assert_leaker_stopped(leaker, adapter.limiter.bucket_factory)


def test_close_before_any_request_and_idempotent():
    """close() before any request is a safe no-op; calling it twice does not raise."""
    session = LimiterSession(per_second=5)
    assert session.limiter.bucket_factory._leaker is None
    session.close()  # no Leaker was ever created — must not raise
    session.close()  # second call must also be safe


@patch_sleep
def test_fill_bucket_with_custom_limiter(mock_sleep):
    """_fill_bucket falls back to limiter.buckets() when a custom Limiter is provided"""
    bucket = InMemoryBucket([Rate(5, Duration.SECOND)])
    limiter = Limiter(bucket)
    session = get_mock_session(limiter=limiter)
    session.get(MOCKED_URL_429)
    session.get(MOCKED_URL_429)
    assert mock_sleep.called


@patch_sleep
def test_pickling_preserves_rate_limiting(mock_sleep):
    """Unpickled session can make requests and enforces rate limits"""
    session = get_mock_session(per_second=5)
    unpickled = pickle.loads(pickle.dumps(session))
    # Re-mount mock adapter since it's not preserved through pickling
    unpickled = mount_mock_adapter(unpickled)
    for _ in range(5):
        unpickled.get(MOCKED_URL)
    assert mock_sleep.called is False
    unpickled.get(MOCKED_URL)
    assert mock_sleep.called is True


def test_fill_bucket_no_bucket_logs_warning(caplog):
    """_fill_bucket with no available bucket logs a warning and returns cleanly"""
    mock_limiter = MagicMock()
    del mock_limiter.bucket_factory.__getitem__  # no dict-like access
    mock_limiter.buckets.return_value = []
    session = LimiterSession.__new__(LimiterSession)
    session.limiter = mock_limiter
    session.per_host = False
    session._default_bucket = 'test'
    session.bucket_name = None
    req = PreparedRequest()
    req.url = MOCKED_URL
    with caplog.at_level('WARNING', logger='requests_ratelimiter'):
        session._fill_bucket(req)
    assert 'No buckets available' in caplog.text


@patch_sleep
def test_custom_bucket_class(mock_sleep):
    """A custom AbstractBucket subclass works end-to-end"""

    class MyBucket(InMemoryBucket):
        pass

    session = get_mock_session(per_second=5, bucket_class=MyBucket)
    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False
    session.get(MOCKED_URL)
    assert mock_sleep.called is True


def test_bucket_name_overrides_per_host():
    """Explicit bucket_name takes priority over per_host=True"""
    session = LimiterSession(per_second=5, bucket_name='fixed', per_host=True)
    req = PreparedRequest()
    req.url = MOCKED_URL
    assert session._bucket_name(req) == 'fixed'


@pytest.mark.parametrize(
    'kwargs, bucket_name, expected',
    [
        ({'path': '/tmp/x.db'}, None, {'db_path': '/tmp/x.db'}),
        ({}, 'mybucket', {'table': 'bucket_mybucket'}),
        ({'path': '/tmp/x.db', 'unknown_key': 'val'}, None, {'db_path': '/tmp/x.db'}),
        ({'table': 'custom'}, 'mybucket', {'table': 'custom'}),  # explicit table not overridden
    ],
)
def test_prepare_sqlite_kwargs(kwargs, bucket_name, expected):
    result = prepare_sqlite_kwargs(kwargs, bucket_name)
    assert result == expected


def test_max_delay_logs_warning(caplog):
    with caplog.at_level('WARNING', logger='requests_ratelimiter'):
        LimiterSession(per_second=5, max_delay=10)
    assert 'max_delay' in caplog.text


@patch_sleep
def test_burst_allows_consecutive_requests(mock_sleep):
    """burst=3 allows 3 rapid consecutive requests before enforcing per-second limit"""
    session = get_mock_session(per_second=1, burst=3)
    for _ in range(3):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False
    session.get(MOCKED_URL)
    assert mock_sleep.called is True
