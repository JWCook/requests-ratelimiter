# TODO: Actual unit tests. For now, this just makes sure the Readme examples don't break.
from pyrate_limiter import Duration, Limiter, RequestRate
from requests import Session

from requests_ratelimiter import LimiterAdapter, LimiterSession

rate = RequestRate(5, Duration.SECOND)


def test_limiter_session():
    session = LimiterSession(per_second=5)

    for _ in range(5):
        session.get('https://httpbin.org/get')


def test_limiter_adapter():
    session = Session()

    adapter = LimiterAdapter(per_second=5)
    session.mount('https://', adapter)

    for _ in range(5):
        session.get('https://httpbin.org/get')


def test_custom_limiter():
    limiter = Limiter(RequestRate(5, Duration.SECOND))
    session = LimiterSession(limiter=limiter)
    for _ in range(5):
        session.get('https://httpbin.org/get')
