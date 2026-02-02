from fractions import Fraction
from inspect import signature
from logging import getLogger
from time import sleep, time
from typing import TYPE_CHECKING, Callable, Dict, Iterable, Optional, Type, Union
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate, SQLiteBucket
from pyrate_limiter.abstracts import AbstractBucket, BucketFactory, RateItem
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter

if TYPE_CHECKING:
    MIXIN_BASE = Session
else:
    MIXIN_BASE = object
logger = getLogger(__name__)


class HostBucketFactory(BucketFactory):
    """Creates separate buckets for per-host rate limiting"""

    def __init__(
        self,
        rates: list[Rate],
        bucket_class: Type[AbstractBucket] = InMemoryBucket,
        bucket_init_kwargs: Optional[Dict] = None,
    ):
        self.rates = rates
        self.bucket_class = bucket_class
        self.bucket_init_kwargs = bucket_init_kwargs or {}
        self.buckets: Dict[str, AbstractBucket] = {}
        self.leak_interval = 300  # 300ms leak interval

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        """Create a RateItem with current timestamp from the appropriate bucket's clock"""
        # Get or create bucket to access its time source
        temp_item = RateItem(name, 0, weight)
        bucket = self.get(temp_item)
        now = bucket.now()
        return RateItem(name, now, weight=weight)

    def get(self, item: RateItem) -> AbstractBucket:
        """Get or create a bucket for the given item name"""
        if item.name not in self.buckets:
            # Create new bucket for this name
            bucket = self._create_bucket()
            self.schedule_leak(bucket)
            self.buckets[item.name] = bucket

        return self.buckets[item.name]

    def _create_bucket(self) -> AbstractBucket:
        """Create a new bucket instance with the configured bucket class"""
        if self.bucket_class == InMemoryBucket:
            return InMemoryBucket(self.rates)
        elif self.bucket_class == SQLiteBucket:
            kwargs = _prepare_sqlite_kwargs(self.bucket_init_kwargs)
            return SQLiteBucket.init_from_file(rates=self.rates, **kwargs)
        else:
            # Generic bucket creation - pass rates as first arg
            return self.bucket_class(self.rates, **self.bucket_init_kwargs)

    def __getitem__(self, name: str) -> AbstractBucket:
        """Dict-like access for backward compatibility with _fill_bucket() method"""
        if name not in self.buckets:
            # Create bucket on access
            temp_item = RateItem(name, 0, 1)
            return self.get(temp_item)
        return self.buckets[name]


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
        max_delay: Union[int, float, None] = None,
        per_host: bool = True,
        limit_statuses: Iterable[int] = (429,),
        bucket_name: Optional[str] = None,
        **kwargs,
    ):
        # Translate request rate values into Rate objects
        # Duration values are in milliseconds in v4
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

        # Compatibility for v2 bucket class names
        if hasattr(bucket_class, '__name__'):
            if bucket_class.__name__ in ('MemoryQueueBucket', 'MemoryListBucket'):
                bucket_class = InMemoryBucket

        bucket_init_kwargs = bucket_kwargs or {}

        if limiter:
            self.limiter = limiter
            self._custom_limiter = True
        # Per-host mode: need multiple buckets
        elif per_host and bucket_name is None:
            factory = HostBucketFactory(
                rates=rates,
                bucket_class=bucket_class,
                bucket_init_kwargs=bucket_init_kwargs,
            )
            self.limiter = Limiter(factory, buffer_ms=50)
            self._custom_limiter = False
        # Single bucket mode: all requests share one bucket
        else:
            if bucket_class == InMemoryBucket:
                bucket = InMemoryBucket(rates)
            elif bucket_class == SQLiteBucket:
                kwargs = _prepare_sqlite_kwargs(bucket_init_kwargs, bucket_name)
                bucket = SQLiteBucket.init_from_file(rates=rates, **kwargs)
            else:
                bucket = bucket_class(rates, **bucket_init_kwargs)

            self.limiter = Limiter(bucket, buffer_ms=50)
            self._custom_limiter = False

        self.limit_statuses = limit_statuses
        self.max_delay = max_delay
        self.per_host = per_host
        self.bucket_name = bucket_name
        self._default_bucket = str(uuid4())

        # If the superclass is an adapter or custom Session, pass along any valid keyword arguments
        session_kwargs = _get_valid_kwargs(super().__init__, kwargs)
        super().__init__(**session_kwargs)  # type: ignore  # Base Session doesn't take any kwargs

    # Conveniently, both Session.send() and HTTPAdapter.send() have a mostly consistent signature
    def send(self, request: PreparedRequest, **kwargs) -> Response:
        """Send a request with rate-limiting.

        Raises:
            :py:exc:`.RuntimeError` if this request would result in a delay longer than ``max_delay``
        """
        bucket_name = self._bucket_name(request)

        # pyrate-limiter v4 no longer supports max_delay; implement by retrying with timeout tracking
        if self.max_delay is not None:
            start_time = time()

            while True:
                acquired = self.limiter.try_acquire(bucket_name, weight=1, blocking=False)
                if acquired:
                    break

                # Not acquired - check if we've exceeded max_delay
                elapsed = time() - start_time
                if elapsed >= self.max_delay:
                    raise RuntimeError(
                        f'Rate limit exceeded. Unable to acquire permit within '
                        f'max_delay ({self.max_delay}s)'
                    )
                sleep(0.05)
        else:
            # No max_delay - simple blocking acquire
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
            :py:class:`~pyrate_limiter.bucket.MemoryQueueBucket` (default),
            :py:class:`~pyrate_limiter.sqlite_bucket.SQLiteBucket`, or
            :py:class:`~pyrate_limiter.bucket.RedisBucket`
        bucket_kwargs: Bucket backend keyword arguments
        limiter: An existing Limiter object to use instead of the above params
        max_delay: The maximum allowed delay time (in seconds); anything over this will abort the
            request and raise a :py:exc:`.BucketFullException`
        per_host: Track request rate limits separately for each host
        limit_statuses: Alternative HTTP status codes that indicate a rate limit was exceeded
    """

    __attrs__ = Session.__attrs__ + [
        'limiter',
        'limit_statuses',
        'max_delay',
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


def _prepare_sqlite_kwargs(bucket_kwargs: Dict, bucket_name: Optional[str] = None) -> Dict:
    """Prepare SQLiteBucket kwargs for v4 compatibility"""
    kwargs = bucket_kwargs.copy()
    if 'path' in kwargs:
        kwargs['db_path'] = str(kwargs.pop('path'))

    # If bucket_name is specified, use it as the table name to ensure separation
    # This allows multiple sessions with different bucket_names to share a db file
    if bucket_name and 'table' not in kwargs:
        kwargs['table'] = f'bucket_{bucket_name}'

    # Filter to only supported parameters for SQLiteBucket.init_from_file
    supported_params = {'table', 'db_path', 'create_new_table', 'use_file_lock'}
    return {k: v for k, v in kwargs.items() if k in supported_params}
