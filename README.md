# Requests-Ratelimiter
[![Build
status](https://github.com/JWCook/requests-ratelimiter/workflows/Build/badge.svg)](https://github.com/JWCook/requests-ratelimiter/actions)
[![Codecov](https://codecov.io/gh/JWCook/requests-ratelimiter/branch/main/graph/badge.svg)](https://codecov.io/gh/JWCook/requests-ratelimiter)
[![Documentation Status](https://img.shields.io/readthedocs/requests-ratelimiter/stable?label=docs)](https://requests-ratelimiter.readthedocs.io)
[![PyPI](https://img.shields.io/pypi/v/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)
[![Conda](https://img.shields.io/conda/vn/conda-forge/requests-ratelimiter?color=blue)](https://anaconda.org/conda-forge/requests-ratelimiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/requests-ratelimiter)](https://pypi.org/project/requests-ratelimiter)
[![PyPI - Format](https://img.shields.io/pypi/format/requests-ratelimiter?color=blue)](https://pypi.org/project/requests-ratelimiter)

This package is a simple wrapper around [pyrate-limiter v2](https://github.com/vutran1710/PyrateLimiter/tree/v2.10.0)
that adds convenient integration with the [requests](https://requests.readthedocs.io) library.

Full project documentation can be found at [requests-ratelimiter.readthedocs.io](https://requests-ratelimiter.readthedocs.io).


# Features
* `pyrate-limiter` is a general-purpose rate-limiting library that implements the leaky bucket
  algorithm, supports multiple rate limits, and has optional persistence with SQLite and Redis
  backends
* `requests-ratelimiter` adds some conveniences for sending rate-limited HTTP requests with the
  `requests` library
* It can be used as either a
  [session](https://requests.readthedocs.io/en/latest/user/advanced/#session-objects) or a
  [transport adapter](https://requests.readthedocs.io/en/latest/user/advanced/#transport-adapters)
* It can also be used as a mixin, for compatibility with other `requests`-based libraries
* Rate limits are tracked separately per host
* Different rate limits can optionally be applied to different hosts

# Installation
```
pip install requests-ratelimiter
```

# Usage

## Usage Options
There are three ways to use `requests-ratelimiter`:

### Session
The simplest option is
[`LimiterSession`](https://requests-ratelimiter.readthedocs.io/en/stable/reference.html#requests_ratelimiter.LimiterSession),
which can be used as a drop-in replacement for
[`requests.Session`](https://requests.readthedocs.io/en/latest/api/#requests.Session).

Note: By default, each session will perform rate limiting independently. If you are using a multi-threaded environment
or multiple processes, you should use a persistent backend like SQLite or Redis which can persist the rate limit across
threads, processes, and/or application restarts. When using `requests-ratelimiter` as part of a web application, it is
recommended to use a persistent backend to ensure that the rate limit is shared across all requests.

Example:
```python
from requests_ratelimiter import LimiterSession
from time import time

# Apply a rate limit of 5 requests per second to all requests
session = LimiterSession(per_second=5)
start = time()

# Send requests that stay within the defined rate limit
for i in range(20):
    response = session.get('https://httpbin.org/get')
    print(f'[t+{time()-start:.2f}] Sent request {i+1}')
```

Example output:
```bash
[t+0.22] Sent request 1
[t+0.26] Sent request 2
[t+0.30] Sent request 3
[t+0.34] Sent request 4
[t+0.39] Sent request 5
[t+1.24] Sent request 6
[t+1.28] Sent request 7
[t+1.32] Sent request 8
[t+1.37] Sent request 9
[t+1.41] Sent request 10
[t+2.04] Sent request 11
...
```

### Adapter
For more advanced usage,
[`LimiterAdapter`](https://requests-ratelimiter.readthedocs.io/en/stable/reference.html#requests_ratelimiter.LimiterAdapter)
is available to be used as a
[transport adapter](https://requests.readthedocs.io/en/latest/user/advanced/#transport-adapters).

Example:
```python
from requests import Session
from requests_ratelimiter import LimiterAdapter

session = Session()

# Apply a rate-limit (5 requests per second) to all requests
adapter = LimiterAdapter(per_second=5)
session.mount('http://', adapter)
session.mount('https://', adapter)

# Send rate-limited requests
for user_id in range(100):
    response = session.get(f'https://api.some_site.com/v1/users/{user_id}')
    print(response.json())
```

### Mixin
Finally,
[`LimiterMixin`](https://requests-ratelimiter.readthedocs.io/en/stable/reference.html#requests_ratelimiter.LimiterMixin)
is available for advanced use cases in which you want add rate-limiting features to a custom session
or adapter class. See
[Custom Session Example](#custom-session-example-requests-cache) below for an example.

## Rate Limit Settings
### Basic Settings
The following parameters are available for the most common rate limit intervals:
* `per_second`: Max requests per second
* `per_minute`: Max requests per minute
* `per_hour`: Max requests per hour
* `per_day`: Max requests per day
* `per_month`: Max requests per month
* `burst`: Max number of consecutive requests allowed before applying per-second rate-limiting

<!-- TODO: Section explaining burst rate limit -->

### Advanced Settings
If you need to define more complex rate limits, you can create a `Limiter` object instead:
```python
from pyrate_limiter import Duration, RequestRate, Limiter
from requests_ratelimiter import LimiterSession

nanocentury_rate = RequestRate(10, Duration.SECOND * 3.156)
fortnight_rate = RequestRate(1000, Duration.DAY * 14)
trimonthly_rate = RequestRate(10000, Duration.MONTH * 3)
limiter = Limiter(nanocentury_rate, fortnight_rate, trimonthly_rate)

session = LimiterSession(limiter=limiter)
```

See [pyrate-limiter docs](https://pyratelimiter.readthedocs.io/en/latest/#basic-usage) for more `Limiter` usage details.

## Backends
By default, rate limits are tracked in memory and are not persistent. You can optionally use either
SQLite or Redis to persist rate limits across threads, processes, and/or application restarts.
You can specify which backend to use with the `bucket_class` argument. For example, to use SQLite:
```python
from pyrate_limiter import SQLiteBucket
from requests_ratelimiter import LimiterSession

session = LimiterSession(per_second=5, bucket_class=SQLiteBucket)
```

See [pyrate-limiter docs](https://pyratelimiter.readthedocs.io/en/latest/#backends) for more details.

## Other Features
### Per-Host Rate Limit Tracking
With either `LimiterSession` or `LimiterAdapter`, rate limits are tracked separately for each host.
In other words, requests sent to one host will not count against the rate limit for any other hosts:

```python
session = LimiterSession(per_second=5)

# Make requests for two different hosts
for _ in range(10):
    response = session.get(f'https://httpbin.org/get')
    print(response.json())
    session.get(f'https://httpbingo.org/get')
    print(response.json())
```

If you have a case where multiple hosts share the same rate limit, you can disable this behavior
with the `per_host` option:
```python
session = LimiterSession(per_second=5, per_host=False)
```

### Per-Host Rate Limit Definitions
With `LimiterAdapter`, you can apply different rate limits to different hosts or URLs:
```python
# Apply a different set of rate limits (2/second and 100/minute) to a specific host
adapter_2 = LimiterAdapter(per_second=2, per_minute=100)
session.mount('https://api.some_site.com', adapter_2)
```

Behavior for matching requests is the same as other transport adapters: `requests` will use the
adapter with the most specific (i.e., longest) URL prefix that matches a given request. For example:
```python
session.mount('https://api.some_site.com/v1', adapter_3)
session.mount('https://api.some_site.com/v1/users', adapter_4)

# This request will use adapter_3
session.get('https://api.some_site.com/v1/')

# This request will use adapter_4
session.get('https://api.some_site.com/v1/users/1234')
```

### Custom Tracking
For advanced use cases, you can define your own custom tracking behavior with the `bucket` option.
For example, an API that enforces rate limits based on a tenant ID, this feature can be used to track
rate limits per tenant. If `bucket` is specified, host tracking is disabled.

Note: It is advisable to use SQLite or Redis backends when using custom tracking because using the default backend
each session will track rate limits independently, even if both sessions call the same URL.
```python
sessionA = LimiterSession(per_second=5, bucket='tenant1')
sessionB = LimiterSession(per_second=5, bucket='tenant2')
```

### Rate Limit Error Handling
Sometimes, server-side rate limiting may not behave exactly as documented (or may not be documented
at all). Or you might encounter other scenarios where your client-side limit gets out of sync with
the server-side limit. Typically, a server will send a `429: Too Many Requests` response for an
exceeded rate limit.

When this happens, `requests-ratelimiter` will adjust its request log in an attempt to catch up to
the server-side limit. If a server sends a different status code other than 429 to indicate an
exceeded limit, you can set this with `limit_statuses`:
```python
session = LimiterSession(per_second=5, limit_statuses=[429, 500])
```

Or if you would prefer to disable this behavior and handle it yourself:
```python
session = LimiterSession(per_second=5, limit_statuses=[])
```

# Compatibility
There are many other useful libraries out there that add features to `requests`, most commonly by
extending or modifying
[requests.Session](https://requests.readthedocs.io/en/latest/api/#requests.Session) or
[requests.HTTPAdapter](https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter).

To use `requests-ratelimiter` with one of these libraries, you have a few different options:
1. If the library provides a custom `Session` class, mount a `LimiterAdapter` on it
2. Or use `LimiterMixin` to create a custom `Session` class with features from both libraries
3. If the library provides a custom `Adapter` class, use `LimiterMixin` to create a custom `Adapter`
   class with features from both libraries

## Custom Session Example: Requests-Cache
For example, to combine with [requests-cache](https://github.com/requests-cache/requests-cache), which
also includes a separate mixin class:
```python
from requests import Session
from requests_cache import CacheMixin
from requests_ratelimiter import LimiterMixin, SQLiteBucket


class CachedLimiterSession(CacheMixin, LimiterMixin, Session):
    """
    Session class with caching and rate-limiting behavior. Accepts arguments for both
    LimiterSession and CachedSession.
    """


# Optionally use SQLite as both the bucket backend and the cache backend
session = CachedLimiterSession(
    per_second=5,
    cache_name='cache.db',
    bucket_class=SQLiteBucket,
    bucket_kwargs={
        "path": "cache.db",
        'isolation_level': "EXCLUSIVE",
        'check_same_thread': False,
    },
)
```

This example has an extra benefit: cache hits won't count against your rate limit!
