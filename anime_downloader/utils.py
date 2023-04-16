from urllib.parse import urlencode, urlunparse

from .constants import PROTOCOL, WORKER


def set_worker(url: str) -> str:
    params = urlencode({"url": url})
    url = urlunparse([PROTOCOL, WORKER, "/", "", params, ""])
    return url
