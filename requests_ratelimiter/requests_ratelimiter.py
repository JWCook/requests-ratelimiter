from fractions import Fraction
from inspect import signature
from logging import getLogger
from typing import TYPE_CHECKING, Callable, Dict, Iterable, Optional, Type
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate
from pyrate_limiter.abstracts import AbstractBucket, RateItem
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter

from .buckets import HostBucketFactory

if TYPE_CHECKING:
    MIXIN_BASE = Session
else:
    MIXIN_BASE = object
logger = getLogger(__name__)


class LimiterMixin(MIXIN_BASE):
    """Mixin class that adds rate-limiting behavior to requests.

    See :py:class:`.LimiterSession` for parameter details.
    """

    def __init__(
        self,
        per_second: float = 0,
        per_minute: float = 0,
        per_hour: float = 0,
        per_day: float = 0,
        per_month: float = 0,
        burst: float = 1,
        bucket_class: Type[AbstractBucket] = InMemoryBucket,
        bucket_kwargs: Optional[Dict] = None,
        time_function: Optional[Callable[..., float]] = None,
        limiter: Optional[Limiter] = None,
        per_host: bool = True,
        limit_statuses: Iterable[int] = (429,),
        bucket_name: Optional[str] = None,
        **kwargs,
    ):
        # Translate request rate values into Rate objects (using millisecond intervals)
        rates = [
            _convert_rate(limit, interval)
            for interval, limit in {
                int(Duration.SECOND * burst): per_second * burst,
                int(Duration.MINUTE): per_minute,
                int(Duration.HOUR): per_hour,
                int(Duration.DAY): per_day,
                int(Duration.DAY * 30): per_month,
            }.items()
            if limit
        ]

        if rates and not limiter:
            logger.debug(
                'Creating Limiter with rates:\n%s',
                '\n'.join([f'{r.limit}/{r.interval}ms' for r in rates]),
            )

        bucket_kwargs = bucket_kwargs or {}

        if limiter:
            self.limiter = limiter
            self._custom_limiter = True
        else:
            factory = HostBucketFactory(
                rates=rates,
                bucket_class=bucket_class,
                bucket_init_kwargs=bucket_kwargs,
                bucket_name=bucket_name,
            )
            self.limiter = Limiter(factory, buffer_ms=50)
            self._custom_limiter = False

        if kwargs.pop('max_delay', None):
            logger.warning('max_delay is no longer supported')
        self.limit_statuses = limit_statuses
        self.per_host = per_host
        self.bucket_name = bucket_name
        self._default_bucket = str(uuid4())

        # If the superclass is an adapter or custom Session, pass along any valid keyword arguments
        session_kwargs = _get_valid_kwargs(super().__init__, kwargs)
        super().__init__(**session_kwargs)  # type: ignore  # Base Session doesn't take any kwargs

    def __getstate__(self):
        """Get state for pickling, excluding unpicklable lock objects"""
        state = self.__dict__.copy()
        # Handle unpicklable lock from limiter if it exists
        if hasattr(self, 'limiter') and hasattr(self.limiter, 'lock'):
            # Store limiter state as a dictionary, excluding unpicklable attributes
            limiter_dict = self.limiter.__dict__.copy()
            limiter_dict.pop('lock', None)
            limiter_dict.pop('_thread_local', None)
            state['_limiter_state'] = limiter_dict
            # Remove the original limiter from state
            del state['limiter']
        return state

    def __setstate__(self, state):
        """Restore state after unpickling, recreating lock objects"""
        self.__dict__.update(state)
        # Restore limiter from stored state if it was removed for pickling
        if '_limiter_state' in state:
            # Recreate the limiter with a new lock
            from pyrate_limiter import Limiter

            # Get the bucket factory from the stored state
            bucket_factory = state['_limiter_state']['bucket_factory']
            buffer_ms = state['_limiter_state']['buffer_ms']

            # Create a new limiter with the same configuration
            self.limiter = Limiter(bucket_factory, buffer_ms=buffer_ms)

            # Clean up the temporary state
            if hasattr(self, '_limiter_state'):
                delattr(self, '_limiter_state')

    # Conveniently, both Session.send() and HTTPAdapter.send() have a mostly consistent signature
    def send(self, request: PreparedRequest, **kwargs) -> Response:
        """Send a request with rate-limiting."""
        bucket_name = self._bucket_name(request)
        self.limiter.try_acquire(bucket_name, weight=1, blocking=True)

        response = super().send(request, **kwargs)
        if response.status_code in self.limit_statuses:
            self._fill_bucket(request)

        return response

    def _bucket_name(self, request):
        """Get a bucket name for the given request"""
        if self.bucket_name:
            return self.bucket_name
        elif self.per_host:
            return urlparse(request.url).netloc
        else:
            return self._default_bucket

    def _fill_bucket(self, request: PreparedRequest):
        """Partially fill the bucket for the given request, requiring an extra delay until the next
        request. This is essentially an attempt to catch up to the actual (server-side) limit if
        we've gotten out of sync.

        If the server tracks multiple limits, there's no way to know which specific limit was
        exceeded, so the smallest rate will be used.

        For example, if the server allows 60 requests per minute, and we've tracked only 40 requests
        but received a 429 response, 20 additional "filler" requests will be added to the bucket to
        attempt to catch up to the server-side limit.

        If the server also has an hourly limit, we don't have enough information to know if we've
        exceeded that limit or how long to delay, so we'll keep delaying in 1-minute intervals.
        """
        logger.info(f'Rate limit exceeded for {request.url}; filling limiter bucket')
        bucket_name = self._bucket_name(request)

        # Access bucket through factory (supports dict-like access) or single bucket mode
        if hasattr(self.limiter.bucket_factory, '__getitem__'):
            bucket = self.limiter.bucket_factory[bucket_name]
        else:
            buckets = self.limiter.buckets()
            bucket = buckets[0] if buckets else None

        if not bucket:
            logger.warning('No buckets available to fill')
            return

        now = bucket.now()

        # Use smallest rate interval (first after sorting)
        rate = sorted(bucket.rates, key=lambda r: r.interval)[0]

        # Add filler items to saturate the smallest rate limit
        # This ensures we delay before the next request
        for _ in range(rate.limit):
            filler_item = RateItem(bucket_name, now, weight=1)
            bucket.put(filler_item)

    def close(self) -> None:
        """Close the session or adapter and release all rate-limiter resources.

        Calls the parent ``close()`` to tear down connection pools, then stops the
        background ``Leaker`` thread owned by the internal
        :class:`~pyrate_limiter.BucketFactory`.  The thread is only stopped when the
        limiter was created internally (i.e. via the ``per_second`` / ``per_minute`` /
        … parameters); if a custom :class:`~pyrate_limiter.Limiter` was supplied by the
        caller its lifecycle is the caller's responsibility.
        """
        super().close()
        if not self._custom_limiter:
            self.limiter.bucket_factory.close()


class LimiterSession(LimiterMixin, Session):
    """`Session <https://requests.readthedocs.io/en/latest/user/advanced/#session-objects>`_
    that adds rate-limiting behavior to requests.

    The following parameters also apply to :py:class:`.LimiterMixin` and
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
        bucket_class: Bucket backend class; may be one of
            :py:class:`~pyrate_limiter.buckets.in_memory_bucket.InMemoryBucket` (default),
            :py:class:`~pyrate_limiter.buckets.sqlite_bucket.SQLiteBucket`, or
            :py:class:`~pyrate_limiter.buckets.redis_bucket.RedisBucket`
        bucket_kwargs: Bucket backend keyword arguments
        limiter: An existing Limiter object to use instead of the above params
        per_host: Track request rate limits separately for each host
        limit_statuses: Alternative HTTP status codes that indicate a rate limit was exceeded
    """

    __attrs__ = Session.__attrs__ + [
        'limiter',
        'limit_statuses',
        'per_host',
        'bucket_name',
        '_default_bucket',
    ]


class LimiterAdapter(LimiterMixin, HTTPAdapter):  # type: ignore  # send signature accepts **kwargs
    """`Transport adapter
    <https://requests.readthedocs.io/en/latest/user/advanced/#transport-adapters>`_
    that adds rate-limiting behavior to requests.

    See :py:class:`.LimiterSession` for parameter details.
    """


def _convert_rate(limit: float, interval: float) -> Rate:
    """Handle fractional rate limits by converting to a whole number of requests per interval

    Args:
        limit: Number of requests allowed
        interval: Time interval in milliseconds (from Duration enum values)
    """
    limit_fraction = Fraction(limit).limit_denominator(1000)
    converted_limit = limit_fraction.numerator
    converted_interval = interval * limit_fraction.denominator

    # Handle fractional intervals (Rate requires integer interval): e.g., 1 req/0.5ms -> 2 req/1ms
    if converted_interval < 1:
        interval_fraction = Fraction(converted_interval).limit_denominator(1000)
        converted_limit = converted_limit * interval_fraction.denominator
        converted_interval = converted_interval * interval_fraction.denominator

    # Ensure interval is at least 1ms (Rate requires interval > 0)
    return Rate(converted_limit, max(1, int(converted_interval)))


def _get_valid_kwargs(func: Callable, kwargs: Dict) -> Dict:
    """Get the subset of non-None ``kwargs`` that are valid params for ``func``"""
    sig_params = list(signature(func).parameters)
    return {k: v for k, v in kwargs.items() if k in sig_params and v is not None}
