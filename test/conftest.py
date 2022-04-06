from logging import basicConfig, getLogger

from requests_mock import ANY as ANY_METHOD
from requests_mock import Adapter

from requests_ratelimiter import LimiterSession

MOCK_PROTOCOLS = ['mock://', 'http+mock://', 'https+mock://']

MOCKED_URL = 'http+mock://requests-ratelimiter.com/text'
MOCKED_URL_ALT_HOST = 'http+mock://requests-ratelimiter-2.com/text'
MOCKED_URL_429 = 'http+mock://requests-ratelimiter.com/429'
MOCKED_URL_500 = 'http+mock://requests-ratelimiter.com/500'

# Configure logging to show log output when tests fail (or with pytest -s)
basicConfig(level='INFO')
getLogger('requests_ratelimiter').setLevel('DEBUG')


def get_mock_session(**kwargs) -> LimiterSession:
    """Get a LimiterSession with some URLs mocked by default"""
    session = LimiterSession(**kwargs)
    session = mount_mock_adapter(session)
    return session


def mount_mock_adapter(session: LimiterSession) -> LimiterSession:
    adapter = get_mock_adapter()
    for protocol in MOCK_PROTOCOLS:
        session.mount(protocol, adapter)
    session.mock_adapter = adapter  # type: ignore
    return session


def get_mock_adapter() -> Adapter:
    """Get a requests-mock Adapter with some URLs mocked by default"""
    adapter = Adapter()
    adapter.register_uri(
        ANY_METHOD,
        MOCKED_URL,
        headers={'Content-Type': 'text/plain'},
        text='mock response',
        status_code=200,
    )
    adapter.register_uri(
        ANY_METHOD,
        MOCKED_URL_ALT_HOST,
        headers={'Content-Type': 'text/plain'},
        text='mock response',
        status_code=200,
    )
    adapter.register_uri(ANY_METHOD, MOCKED_URL_429, status_code=429)
    adapter.register_uri(ANY_METHOD, MOCKED_URL_500, status_code=500)
    return adapter
