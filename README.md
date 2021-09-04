# Requests-Ratelimiter
[![Build status](https://github.com/JWCook/requests-ratelimiter/workflows/Build/badge.svg)](https://github.com/JWCook/requests-ratelimiter/actions)
[![PyPI](https://img.shields.io/pypi/v/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/requests-ratelimiter)](https://pypi.org/project/requests-ratelimiter)
[![PyPI - Format](https://img.shields.io/pypi/format/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)

**Work in progress**

This package is a thin wrapper around [pyrate-limiter](https://github.com/vutran1710/PyrateLimiter)
that adds convenient integration with the [requests](https://github.com/psf/requests) library.


## Features
* `pyrate-limiter` implements the leaky bucket algorithm, supports multiple rate limits, and an
  optional Redis backend
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
from pyrate_limiter import Duration, RequestRate
from requests import Session
from requests_ratelimiter import LimiterSession

# Apply a rate-limit (5 requests per second) to all requests
session = LimiterSession(RequestRate(5, Duration.SECOND))

# Make rate-limited requests that stay within 5 requests per second
for _ in range(10):
    response = session.get('https://httpbin.org/get')
    print(response.json())
```

### Adapters
Example with `LimiterAdapter`:

```python
from pyrate_limiter import Duration, RequestRate
from requests import Session
from requests_ratelimiter import LimiterAdapter

session = Session()

# Apply a rate-limit (5 requests per second) to all requests
adapter = LimiterAdapter(RequestRate(5, Duration.SECOND))
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
adapter_2 = LimiterAdapter(
    RequestRate(2, Duration.SECOND),
    RequestRate(100, Duration.MINUTE),
)
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
session = LimiterSession(RequestRate(5, Duration.SECOND), per_host=True)

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
[requests.Session](https://docs.python-requests.org/en/master/api/#requests.Session).

To use `requests-ratelimiter` with one of these libraries, you have at least two options:
1. Mount a `LimiterAdapter` on an instance of the library's `Session` class
2. Use `LimiterMixin` to create a custom `Session` class with features from both libraries

### Requests-Cache
For example, to combine with [requests-cache](https://github.com/reclosedev/requests-cache), which
also includes a separate mixin class:
```python
from requests_cache import CacheMixin
from requests_ratelimiter import LimiterMixin


class CachedLimiterSession(LimiterMixin, CacheMixin, Session):
    """Session class with caching and rate-limiting behavior. Accepts arguments for both
    LimiterSession and CachedSession.
    """


session = CachedLimiterSession(RequestRate(5, Duration.SECOND), backend='redis')
```

This example has an extra benefit: cache hits won't count against your rate limit!
