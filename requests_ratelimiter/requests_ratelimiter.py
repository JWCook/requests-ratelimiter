from typing import TYPE_CHECKING, Dict, Type, Union
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Duration, Limiter, RequestRate
from pyrate_limiter.bucket import AbstractBucket, MemoryQueueBucket
from requests import Session
from requests.adapters import HTTPAdapter

if TYPE_CHECKING:
    MixinBase = HTTPAdapter
else:
    MixinBase = object


class LimiterMixin(MixinBase):
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
        bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
        bucket_kwargs: Dict = None,
        limiter: Limiter = None,
        max_delay: Union[int, float] = None,
        per_host: bool = False,
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
        self.max_delay = max_delay
        self.per_host = per_host
        super().__init__(**kwargs)

    def bucket_name(self, request):
        return urlparse(request.url).netloc if self.per_host else self._default_bucket

    # Conveniently, both Session.send() and HTTPAdapter.send() have a consistent signature
    def send(self, request, **kwargs):
        """Send a request with rate-limiting"""
        with self.limiter.ratelimit(
            self.bucket_name(request),
            delay=True,
            max_delay=self.max_delay,
        ):
            return super().send(request, **kwargs)


class LimiterSession(LimiterMixin, Session):  # type: ignore  # false positive due to MixinBase
    """`Session <https://docs.python-requests.org/en/master/user/advanced/#session-objects>`_
    that adds rate-limiting behavior to requests.
    """


class LimiterAdapter(LimiterMixin, HTTPAdapter):
    """`Transport adapter
    <https://docs.python-requests.org/en/master/user/advanced/#transport-adapters>`_
    that adds rate-limiting behavior to requests.
    """
