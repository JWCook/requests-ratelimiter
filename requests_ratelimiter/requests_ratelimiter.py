from inspect import signature
from logging import getLogger
from typing import TYPE_CHECKING, Callable, Dict, Iterable, Type, Union
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Duration, Limiter, RequestRate
from pyrate_limiter.bucket import AbstractBucket, MemoryListBucket
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter

if TYPE_CHECKING:
    MIXIN_BASE = Session
else:
    MIXIN_BASE = object
logger = getLogger(__name__)


class LimiterMixin(MIXIN_BASE):
    """Mixin class that adds rate-limiting behavior to requests.

    The following parameters also apply to :py:class:`.LimiterSession` and
    :py:class:`.LimiterAdapter`.

    .. note::
        The ``per_*`` params are aliases for the most common rate limit
        intervals; for more complex rate limits, you can provide a
        :py:class:`~pyrate_limiter.limiter.Limiter` object instead.

    Args:
        per_second: Max requests per second
        per_minute: Max requests per minute
        per_hour: Max requests per hour
        per_day: Max requests per day
        per_month: Max requests per month
        burst: Max number of consecutive requests allowed before applying per-second rate-limiting
        bucket_class: Bucket backend class; either ``MemoryQueueBucket`` (default) or ``RedisBucket``
        bucket_kwargs: Bucket backend keyword arguments
        limiter: An existing Limiter object to use instead of the above params
        max_delay: The maximum allowed delay time (in seconds); anything over this will abort the
            request
        per_host: Track request rate limits separately for each host
    """

    def __init__(
        self,
        per_second: float = 0,
        per_minute: float = 0,
        per_hour: float = 0,
        per_day: float = 0,
        per_month: float = 0,
        burst: float = 1,
        bucket_class: Type[AbstractBucket] = MemoryListBucket,
        bucket_kwargs: Dict = None,
        limiter: Limiter = None,
        max_delay: Union[int, float] = None,
        per_host: bool = False,
        limit_statuses: Iterable[int] = (429,),
        **kwargs,
    ):
        self._default_bucket = str(uuid4())
        bucket_kwargs = bucket_kwargs or {}
        bucket_kwargs.setdefault('bucket_name', self._default_bucket)

        # Translate request rate values into RequestRate objects
        rates = [
            RequestRate(limit, interval)
            for interval, limit in {
                Duration.SECOND * burst: per_second * burst,
                Duration.MINUTE: per_minute,
                Duration.HOUR: per_hour,
                Duration.DAY: per_day,
                Duration.MONTH: per_month,
            }.items()
            if limit
        ]

        self.limiter = limiter or Limiter(
            *rates, bucket_class=bucket_class, bucket_kwargs=bucket_kwargs
        )
        self.limit_statuses = limit_statuses
        self.max_delay = max_delay
        self.per_host = per_host

        # If the superclass is an adapter or custom Session, pass along any valid keyword arguments
        session_kwargs = get_valid_kwargs(super().__init__, kwargs)
        super().__init__(**session_kwargs)  # type: ignore  # Base Session doesn't take any kwargs

    # Conveniently, both Session.send() and HTTPAdapter.send() have a mostly consistent signature
    def send(self, request: PreparedRequest, **kwargs) -> Response:
        """Send a request with rate-limiting"""
        with self.limiter.ratelimit(
            self._bucket_name(request),
            delay=True,
            max_delay=self.max_delay,
        ):
            response = super().send(request, **kwargs)
            if response.status_code in self.limit_statuses:
                self._fill_bucket(request)
            return response

    def _bucket_name(self, request):
        """Get a bucket name for the given request"""
        return urlparse(request.url).netloc if self.per_host else self._default_bucket

    def _fill_bucket(self, request: PreparedRequest):
        """Fill the bucket for the given request, indicating no more requests are avaliable"""
        logger.info(f'Rate limit exceeded for {request.url}; filling limiter bucket')
        bucket = self.limiter.bucket_group[self._bucket_name(request)]
        now = self.limiter.time_function()

        # Bucket.put() will return 1 until full
        while True:
            if bucket.put(now) != 1:
                break


class LimiterSession(LimiterMixin, Session):
    """`Session <https://docs.python-requests.org/en/master/user/advanced/#session-objects>`_
    that adds rate-limiting behavior to requests.
    """


class LimiterAdapter(LimiterMixin, HTTPAdapter):  # type: ignore  # send signature accepts **kwargs
    """`Transport adapter
    <https://docs.python-requests.org/en/master/user/advanced/#transport-adapters>`_
    that adds rate-limiting behavior to requests.
    """


def get_valid_kwargs(func: Callable, kwargs: Dict) -> Dict:
    """Get the subset of non-None ``kwargs`` that are valid params for ``func``"""
    sig_params = list(signature(func).parameters)
    return {k: v for k, v in kwargs.items() if k in sig_params and v is not None}
