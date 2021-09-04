from typing import TYPE_CHECKING, Type
from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Limiter
from pyrate_limiter.bucket import AbstractBucket, MemoryQueueBucket
from pyrate_limiter.request_rate import RequestRate
from requests import Session

if TYPE_CHECKING:
    MixinBase = Session
else:
    MixinBase = object


class LimiterMixin(MixinBase):
    """Mixin class that adds rate-limiting behavior to requests"""

    def __init__(
        self,
        *rates: RequestRate,
        bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
        bucket_kwargs=None,
        per_host: bool = False,
        **kwargs,
    ):
        self.limiter = Limiter(*rates, bucket_class=bucket_class, bucket_kwargs=bucket_kwargs)
        self.per_host = per_host
        self._default_bucket = str(uuid4())
        super().__init__(**kwargs)

    def bucket_name(self, request):
        return urlparse(request.url).netloc if self.per_host else self._default_bucket

    def send(self, request, **kwargs):
        """Send a request with rate-limiting"""
        with self.limiter.ratelimit(self.bucket_name(request), delay=True):
            return super().send(request, **kwargs)


class LimiterSession(LimiterMixin, Session):
    """Session that adds rate-limiting"""
