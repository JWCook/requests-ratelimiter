from requests.adapters import HTTPAdapter
from pyrate_limiter import Limiter


class LimiterAdapter(HTTPAdapter):
    """Transport adapter that adds rate-limiting"""
