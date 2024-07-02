"""
General rate-limiting behavior is covered by pyrate-limiter unit tests. These tests should cover
additional behavior specific to requests-ratelimiter.
"""

from test.conftest import (
    MOCKED_URL,
    MOCKED_URL_429,
    MOCKED_URL_500,
    MOCKED_URL_ALT_HOST,
    get_mock_session,
    mount_mock_adapter,
)
from time import sleep
from unittest.mock import patch

import pickle

import pytest
from pyrate_limiter import Duration, Limiter, RequestRate, SQLiteBucket
from requests import Response, Session
from requests.adapters import HTTPAdapter
from requests_cache import CacheMixin

from requests_ratelimiter import LimiterAdapter, LimiterMixin, LimiterSession
from requests_ratelimiter.requests_ratelimiter import _convert_rate

patch_sleep = patch('pyrate_limiter.limit_context_decorator.sleep', side_effect=sleep)
rate = RequestRate(5, Duration.SECOND)


@patch_sleep
def test_limiter_session(mock_sleep):
    session = LimiterSession(per_second=5)
    session = mount_mock_adapter(session)

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
@patch.object(HTTPAdapter, 'send')
def test_limiter_adapter(mock_send, mock_sleep):
    # To allow mounting a mock:// URL, we need to patch HTTPAdapter.send()
    # so it doesn't validate the protocol
    mock_response = Response()
    mock_response.url = MOCKED_URL
    mock_response.status = 200
    mock_send.return_value = mock_response

    session = Session()
    adapter = LimiterAdapter(per_second=5)
    session.mount('http+mock://', adapter)

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
def test_custom_limiter(mock_sleep):
    limiter = Limiter(RequestRate(5, Duration.SECOND))
    session = get_mock_session(limiter=limiter)

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


class CustomSession(LimiterMixin, Session):
    """Custom Session that adds an extra class attribute"""

    def __init__(self, *args, flag: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.flag = flag


@patch_sleep
def test_custom_session(mock_sleep):
    session = CustomSession(per_second=5, flag=True)
    session = mount_mock_adapter(session)
    assert session.flag is True

    for _ in range(5):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False

    session.get(MOCKED_URL)
    assert mock_sleep.called is True


@patch_sleep
def test_429(mock_sleep):
    """After receiving a 429 response, the bucket should be filled, allowing no more requests"""
    session = get_mock_session(per_second=5)

    session.get(MOCKED_URL_429)
    assert mock_sleep.called is False

    session.get(MOCKED_URL_429)
    assert mock_sleep.called is True


@patch_sleep
def test_429__per_host(mock_sleep):
    """With per_host, after receiving a 429 response, only that bucket should be filled"""
    session = get_mock_session(per_second=5, per_host=True)

    session.get(MOCKED_URL_429)

    # A 429 from one host should not affect requests for a different host
    session.get(MOCKED_URL_ALT_HOST)
    assert mock_sleep.called is False


@patch_sleep
def test_custom_limit_status(mock_sleep):
    """Optionally handle additional status codes that indicate an exceeded rate limit"""
    session = get_mock_session(per_second=5, limit_statuses=[500])

    session.get(MOCKED_URL_500)
    assert mock_sleep.called is False

    session.get(MOCKED_URL_500)
    assert mock_sleep.called is True


@patch_sleep
def test_limit_status_disabled(mock_sleep):
    """Optionally handle additional status codes that indicate an exceeded rate limit"""
    session = get_mock_session(per_second=5, limit_statuses=[])

    session.get(MOCKED_URL_429)
    session.get(MOCKED_URL_429)
    assert mock_sleep.called is False


@pytest.mark.parametrize(
    'limit, interval, expected_limit, expected_interval',
    [
        (5, 1, 5, 1),
        (0.5, 1, 1, 2),
        (1, 0.5, 1, 0.5),
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
        bucket_kwargs={
            'path': tmp_path / 'rate_limit.db',
            'isolation_level': 'EXCLUSIVE',
            'check_same_thread': False,
        },
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
        bucket_kwargs={
            'path': ratelimit_path,
            'isolation_level': 'EXCLUSIVE',
            'check_same_thread': False,
        },
    )
    session_b = get_mock_session(
        per_second=5,
        bucket_name='b',
        bucket_class=SQLiteBucket,
        bucket_kwargs={
            'path': ratelimit_path,
            'isolation_level': 'EXCLUSIVE',
            'check_same_thread': False,
        },
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
        bucket_kwargs={
            'path': str(ratelimit_path),
            'isolation_level': 'EXCLUSIVE',
            'check_same_thread': False,
        },
    )
    session = mount_mock_adapter(session)

    for _ in range(10):
        session.get(MOCKED_URL)
    assert mock_sleep.called is False


def test_inherited_session_attributes():
    # Test that inherited Session attributes are preserved
    session = LimiterSession(per_second=5)
    assert hasattr(session, 'headers')
    assert hasattr(session, 'cookies')
    assert hasattr(session, 'auth')
    assert hasattr(session, 'hooks')


def test_pickling_and_unpickling():
    # Test pickling and unpickling of LimiterSession instance
    session = LimiterSession(per_second=5)
    pickled_session = pickle.dumps(session)
    assert pickled_session is not None
    unpickled_session = pickle.loads(pickled_session)
    assert unpickled_session is not None

    # Check that the unpickled instance has the same attributes
    assert unpickled_session.per_host == session.per_host
    assert unpickled_session.max_delay == session.max_delay
    assert unpickled_session.bucket_name == session.bucket_name
    assert unpickled_session.limit_statuses == session.limit_statuses
    assert unpickled_session._default_bucket == session._default_bucket
