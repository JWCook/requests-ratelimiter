# TODO: Actual unit tests. For now, this just makes sure the Readme examples don't break.
from pyrate_limiter import Duration, RequestRate
from requests import Session

from requests_ratelimiter import LimiterAdapter, LimiterSession

rate = RequestRate(5, Duration.SECOND)


def test_limiter_session():
    session = LimiterSession(rate)

    for _ in range(5):
        session.get('https://httpbin.org/get')


def test_limiter_adapter():
    session = Session()

    adapter = LimiterAdapter(rate)
    session.mount('https://', adapter)

    for _ in range(5):
        session.get('https://httpbin.org/get')
