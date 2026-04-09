from unittest.mock import MagicMock, patch

import pytest
from pyrate_limiter import InMemoryBucket, PostgresBucket, Rate, RedisBucket

from requests_ratelimiter.buckets import HostBucketFactory, prepare_sqlite_kwargs


def test_in_memory_bucket_creation():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    item = factory.wrap_item('test_host')
    factory.get(item)
    assert 'test_host' in factory.buckets


def test_getitem_creates_bucket_on_demand():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    factory['new_host']
    assert 'new_host' in factory.buckets


def test_getitem_returns_existing_bucket():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    item = factory.wrap_item('existing_host')
    bucket1 = factory.get(item)
    bucket2 = factory['existing_host']
    assert bucket1 is bucket2


def test_wrap_item_uses_bucket_clock():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    item = factory.wrap_item('test_host')
    assert item.name == 'test_host'
    assert item.weight == 1
    assert item.timestamp > 0


def test_wrap_item_custom_weight():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    item = factory.wrap_item('test_host', weight=3)
    assert item.weight == 3


def test_separate_buckets_per_name():
    factory = HostBucketFactory(rates=[Rate(5, 1000)])
    item_a = factory.wrap_item('host_a')
    item_b = factory.wrap_item('host_b')
    bucket_a = factory.get(item_a)
    bucket_b = factory.get(item_b)
    assert bucket_a is not bucket_b
    assert len(factory.buckets) == 2


@pytest.mark.parametrize(
    'extra_init_kwargs, identity, expected_key',
    [
        ({}, 'api.example.com', 'api_example_com'),
        ({'bucket_key': 'override'}, 'api.example.com', 'override'),
        ({}, 'myapp:api.example.com', 'myapp_api_example_com'),
    ],
)
def test_redis_bucket(extra_init_kwargs, identity, expected_key):
    mock_redis = MagicMock()
    mock_redis.script_load.return_value = 'fake_sha1'
    factory = HostBucketFactory(
        rates=[Rate(5, 1000)],
        bucket_class=RedisBucket,
        bucket_init_kwargs={'redis': mock_redis, **extra_init_kwargs},
    )

    with patch.object(RedisBucket, 'init', wraps=RedisBucket.init) as mock_init:
        factory._create_bucket(identity)

    mock_init.assert_called_once_with(
        rates=factory.rates, redis=mock_redis, bucket_key=expected_key
    )


def _postgres_init_stub(self, pool, table, rates):
    self.rates = rates
    self.failing_rate = None


@pytest.mark.parametrize(
    'extra_init_kwargs, identity, expected_table',
    [
        ({}, 'api.example.com', 'api_example_com'),
        ({'table': 'override'}, 'api.example.com', 'override'),
        ({}, 'myapp:api.example.com', 'myapp_api_example_com'),
    ],
)
def test_postgres_bucket(extra_init_kwargs, identity, expected_table):
    mock_pool = MagicMock()
    factory = HostBucketFactory(
        rates=[Rate(5, 1000)],
        bucket_class=PostgresBucket,
        bucket_init_kwargs={'pool': mock_pool, **extra_init_kwargs},
    )

    with patch.object(
        PostgresBucket,
        '__init__',
        autospec=True,
        return_value=None,
        side_effect=_postgres_init_stub,
    ) as mock_init:
        factory._create_bucket(identity)

    _, kwargs = mock_init.call_args
    assert kwargs == {'pool': mock_pool, 'table': expected_table, 'rates': factory.rates}


def test_generic_bucket_creation():
    class CustomBucket(InMemoryBucket):
        pass

    factory = HostBucketFactory(
        rates=[Rate(5, 1000)],
        bucket_class=CustomBucket,
    )
    bucket = factory._create_bucket('test_host')
    assert isinstance(bucket, CustomBucket)


@pytest.mark.parametrize(
    'kwargs, bucket_name, expected',
    [
        ({'path': '/tmp/x.db'}, None, {'db_path': '/tmp/x.db'}),
        ({}, 'mybucket', {'table': 'bucket_mybucket'}),
        ({'path': '/tmp/x.db', 'unknown_key': 'val'}, None, {'db_path': '/tmp/x.db'}),
        ({'table': 'custom'}, 'mybucket', {'table': 'custom'}),
    ],
)
def test_prepare_sqlite_kwargs(kwargs, bucket_name, expected):
    result = prepare_sqlite_kwargs(kwargs, bucket_name)
    assert result == expected
