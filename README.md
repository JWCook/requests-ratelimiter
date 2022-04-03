# Requests-Ratelimiter
[![Build
status](https://github.com/JWCook/requests-ratelimiter/workflows/Build/badge.svg)](https://github.com/JWCook/requests-ratelimiter/actions)
[![Documentation Status](https://img.shields.io/readthedocs/requests-ratelimiter/stable?label=docs)](https://requests-ratelimiter.readthedocs.io)
[![PyPI](https://img.shields.io/pypi/v/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)
[![Conda](https://img.shields.io/conda/vn/conda-forge/requests-ratelimiter?color=blue)](https://anaconda.org/conda-forge/requests-ratelimiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/requests-ratelimiter)](https://pypi.org/project/requests-ratelimiter)
[![PyPI - Format](https://img.shields.io/pypi/format/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)

This package is a thin wrapper around [pyrate-limiter](https://github.com/vutran1710/PyrateLimiter)
that adds convenient integration with the [requests](https://github.com/psf/requests) library.

Project documentation can be found at [requests-ratelimiter.readthedocs.io](https://requests-ratelimiter.readthedocs.io).


## Features
* `pyrate-limiter` implements the leaky bucket algorithm, supports multiple rate limits, and optional persistence with SQLite and Redis backends
* `requests-ratelimiter` can be used as a
  [transport adapter](https://docs.python-requests.org/en/master/user/advanced/#transport-adapters),
  [session](https://docs.python-requests.org/en/master/user/advanced/#session-objects),
  or session mixin for compatibility with other `requests`-based libraries.
* Rate limits can be automatically tracked separately per host, and different rate limits can be
  manually applied to different hosts

## Installation
```
pip install requests-ratelimiter
```

## Usage

### Sessions
Example with `LimiterSession`:

```python
from requests import Session
from requests_ratelimiter import LimiterSession

# Apply a rate-limit (5 requests per second) to all requests
session = LimiterSession(per_second=5)

# Make rate-limited requests that stay within 5 requests per second
for _ in range(10):
    response = session.get('https://httpbin.org/get')
    print(response.json())
```

### Adapters
Example with `LimiterAdapter`:

```python
from requests import Session
from requests_ratelimiter import LimiterAdapter

session = Session()

# Apply a rate-limit (5 requests per second) to all requests
adapter = LimiterAdapter(per_second=5)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Make rate-limited requests
for user_id in range(100):
    response = session.get(f'https://api.some_site.com/v1/users/{user_id}')
    print(response.json())
```

### Per-Host Rate Limits
With `LimiterAdapter`, you can apply different rate limits to different hosts or URLs:
```python
# Apply different rate limits (2/second and 100/minute) to a specific host
adapter_2 = LimiterAdapter(per_second=2, per_minute=100)
session.mount('https://api.some_site.com', adapter_2)
```

Behavior for matching requests is the same as other transport adapters: `requests` will use the
adapter with the most specific (i.e., longest) URL prefix for a given request. For example:
```python
session.mount('https://api.some_site.com/v1', adapter_3)
session.mount('https://api.some_site.com/v1/users', adapter_4)

# This request will use adapter_3
session.get('https://api.some_site.com/v1/')

# This request will use adapter_4
session.get('https://api.some_site.com/v1/users/1234')
```

### Per-Host Rate Limit Tracking
With either `LimiterSession` or `LimiterAdapter`, you can automatically track rate limits separately
for each host; in other words, requests sent to one host will not count against the rate limit for
any other hosts. This can be enabled with the `per_host` option:

```python
session = LimiterSession(per_second=5, per_host=True)

# Make requests for two different hosts
for _ in range(10):
    response = session.get(f'https://httpbin.org/get')
    print(response.json())
    session.get(f'https://httpbingo.org/get')
    print(response.json())
```

## Compatibility
There are many other useful libraries out there that add features to `requests`, most commonly by
extending or modifying
[requests.Session](https://docs.python-requests.org/en/master/api/#requests.Session) or
[requests.HTTPAdapter](https://docs.python-requests.org/en/master/api/#requests.adapters.HTTPAdapter).

To use `requests-ratelimiter` with one of these libraries, you have a few different options:
1. If the library provides a custom `Session` class, mount a `LimiterAdapter` on it
2. Or use `LimiterMixin` to create a custom `Session` class with features from both libraries
3. If the library provides a custom `Adapter` class, use `LimiterMixin` to create a custom `Adapter`
   class with features from both libraries

### Custom Session Example: Requests-Cache
For example, to combine with [requests-cache](https://github.com/reclosedev/requests-cache), which
also includes a separate mixin class:
```python
from pyrate_limiter import RedisBucket
from requests import Session
from requests_cache import CacheMixin, RedisCache
from requests_ratelimiter import LimiterMixin


class CachedLimiterSession(CacheMixin, LimiterMixin, Session):
    """Session class with caching and rate-limiting behavior. Accepts arguments for both
    LimiterSession and CachedSession.
    """


# Optionally use Redis as both the bucket backend and the cache backend
session = CachedLimiterSession(
    per_second=5,
    bucket_class=RedisBucket,
    backend=RedisCache(),
)
```

This example has an extra benefit: cache hits won't count against your rate limit!
