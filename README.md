# Requests-Ratelimiter
**Work in progress**

This package is a thin wrapper around [pyrate-limiter](https://github.com/vutran1710/PyrateLimiter)
that adds convenient integration with [requests](https://github.com/psf/requests) sessions.

It works as a
[transport adapter](https://docs.python-requests.org/en/master/user/advanced/#transport-adapters)
that runs requests with rate-limiting delays. Rates can optionally be tracked separately per host.


## Installation
TODO: Not yet published on PyPI

```
pip install requests-ratelimiter
```

## Usage
Example:
```python
from pyrate_limiter import Duration, RequestRate
from requests import Session
from requests_ratelimiter import LimiterAdapter

adapter = LimiterAdapter(RequestRate(10, Duration.SECOND))
session = Session()

# Apply a rate-limit (10 requests per second) to all requests
session.mount('http://', adapter)
session.mount('https://', adapter)

# Apply different rate limits (2/second and 100/minute) to a specific host
adapter_2 = LimiterAdapter(
    RequestRate(2, Duration.SECOND),
    RequestRate(100, Duration.MINUTE),
)
session.mount('https://api.some_site.com', adapter_2)

# Make rate-limited requests that stay within 2 requests per second
for user_id in range(100):
    response = session.get(f'https://api.some_site.com/v1/users/{user_id}')
```
