from typing import Dict, Optional, Type

from pyrate_limiter import InMemoryBucket, Rate, SQLiteBucket
from pyrate_limiter.abstracts import AbstractBucket, BucketFactory, RateItem


class HostBucketFactory(BucketFactory):
    """Creates buckets for rate limiting, optionally with one per host"""

    def __init__(
        self,
        rates: list[Rate],
        bucket_class: Type[AbstractBucket] = InMemoryBucket,
        bucket_init_kwargs: Optional[Dict] = None,
        bucket_name: Optional[str] = None,
    ):
        self.rates = rates
        self.bucket_class = bucket_class
        self.bucket_init_kwargs = bucket_init_kwargs or {}
        self.bucket_name = bucket_name
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
            kwargs = prepare_sqlite_kwargs(self.bucket_init_kwargs, self.bucket_name)
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


def prepare_sqlite_kwargs(bucket_kwargs: Dict, bucket_name: Optional[str] = None) -> Dict:
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
