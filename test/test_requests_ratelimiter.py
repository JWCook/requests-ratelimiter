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

from pyrate_limiter import Duration, Limiter, RequestRate
from requests import Session

from requests_ratelimiter import LimiterAdapter, LimiterMixin, LimiterSession

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
def test_limiter_adapter(mock_sleep):
    session = Session()
    adapter = LimiterAdapter(per_second=5)
    session.mount('https://', adapter)

    for _ in range(5):
        session.get('https://httpbin.org/get')
    assert mock_sleep.called is False

    session.get('https://httpbin.org/get')
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
