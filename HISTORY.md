# History

## 0.9.1 (2026-02-12)
* Fix re-exported pyrate-limiter imports

## 0.9.0 (2026-02-09)
* Migrate to pyrate-limiter v4
* ⚠️ If you are using pyrate-limiter features directly (via `Limiter` class or custom bucket classes), see its [release notes](https://github.com/vutran1710/PyrateLimiter/blob/master/CHANGELOG.md) for info on breaking changes.
* ⚠️ Drop support for python 3.8 and 3.9 (required upstream)
* ⚠️ Remove `max_delay`

## 0.8.0 (2026-01-03)
* ⚠️ Drop support for python 3.7
* Add tests for python 3.13 and 3.14
* Convert packaging and project config to uv. This only affects development tasks, and does not library usage.

## 0.7.0 (2024-07-02)
* Add pickling support for `LimiterSession`

## 0.6.0 (2024-02-29)
* Add `bucket` param to specify bucket name when not using per-host rate limiting

## 0.5.1 (2023-01-29)
* Fix simplifying fractional rate below specified interval

## 0.5.0 (2023-01-29)
* Add support for floating point values for rate limits

## 0.4.2 (2023-09-27)
* Update conda-forge package to restrict pyrate-limiter to <3.0

## 0.4.1 (2023-07-24)
* Add support for python 3.12

## 0.4.0 (2022-09-27)
* Drop support for python 3.6
* Add support for python 3.11
* Remove upper version constraint for `requests`

## 0.3.2 (2022-05-09)
* Default to not using monotonic time if using a persistent backend (SQLite or Redis)

## 0.3.1 (2022-04-06)
* Fix 429 response handling: if multiple rate limits are defined, fill bucket according to smallest rate limit
* Default to not passing `bucket_name` argument to backend
* Import main `pyrate_limiter` classes into top-level package

## 0.3.0 (2022-04-06)
* Add handling for 429 responses
* Add `limit_statuses` argument to define additional status codes that indicate a rate limit has been exceeded
* Forward any valid superclass keyword args for `LimiterAdapter`, or if `LimiterMixin` is used to create a custom class

## 0.2.1 (2021-09-05)
* Add shortcut arguments for most common rate limit intervals (`per_second`, etc.)
* Add `max_delay` option to specify maximum delay time before raising an error

## 0.2.0 (2021-09-04)
* Make `rates` a non-variable argument so it can work with a mixin superclass
* Add API docs, Readme intro + examples, and Sphinx config for readthedocs.io

## 0.1.0 (2021-09-04)
Initial PyPI release
