from urllib.parse import urlparse
from uuid import uuid4

from pyrate_limiter import Limiter
from requests.adapters import HTTPAdapter


# TODO: Take a Limiter object, or the same args as Limiter.__init__()?
class LimiterAdapter(HTTPAdapter):
    """Transport adapter that adds rate-limiting"""

    def __init__(self, limiter: Limiter = None, per_host: bool = False, **kwargs):
        self.limiter = limiter
        self.per_host = per_host
        self._default_bucket = str(uuid4())
        super().__init__(**kwargs)

    # def __init__(
    #     self,
    #     *rates: RequestRate,
    #     bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
    #     bucket_kwargs=None,
    #     **kwargs,
    # ):
    #     self.limiter = Limiter(*rates, bucket_class, bucket_kwargs)

    def bucket_name(self, request):
        return urlparse(request.url).netloc if self.per_host else self._default_bucket

    def send(self, request, **kwargs):
        """Send a request with rate-limiting"""
        with self.limiter.ratelimit(self.bucket_name(request), delay=True):
            return super().send(request, **kwargs)
