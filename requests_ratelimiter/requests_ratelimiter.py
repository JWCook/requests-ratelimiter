from typing import TYPE_CHECKING, Dict, Type
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Limiter
from pyrate_limiter.bucket import AbstractBucket, MemoryQueueBucket
from pyrate_limiter.request_rate import RequestRate
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

    Args:
        rates: One or more request rates
        bucket_class: Bucket backend class; either ``MemoryQueueBucket`` (default) or ``RedisBucket``
        bucket_kwargs: Bucket backend keyword arguments
        per_host: Track request rate limits separately for each host
    """

    def __init__(
        self,
        *rates: RequestRate,
        bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
        bucket_kwargs: Dict = None,
        per_host: bool = False,
        **kwargs,
    ):
        self.limiter = Limiter(*rates, bucket_class=bucket_class, bucket_kwargs=bucket_kwargs)
        self.per_host = per_host
        self._default_bucket = str(uuid4())
        super().__init__(**kwargs)

    def bucket_name(self, request):
        return urlparse(request.url).netloc if self.per_host else self._default_bucket

    # Conveniently, both Session.send() and HTTPAdapter.send() have a consistent signature
    def send(self, request, **kwargs):
        """Send a request with rate-limiting"""
        with self.limiter.ratelimit(self.bucket_name(request), delay=True):
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
