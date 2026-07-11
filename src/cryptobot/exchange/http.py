"""A real HTTP transport for :class:`BinanceRestClient`, using only the stdlib.

Injecting this into ``BinanceRestClient`` gives a working production transport
with no third-party dependencies. It honours the standard ``HTTP(S)_PROXY``
environment variables (via :mod:`urllib`). It is deliberately tiny; the client
builds and signs the full URL, so this only performs the call.
"""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def urllib_transport(method: str, url: str, headers: Mapping[str, str], timeout: float = 10.0) -> Any:
    """Perform an HTTP request and return the parsed JSON body.

    Raises :class:`urllib.error.HTTPError` for non-2xx responses, but first reads
    the error body so Binance's ``{"code", "msg"}`` payload is available to the
    caller for diagnostics.
    """
    request = Request(url, method=method, headers=dict(headers))
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        error.msg = f"{error.msg}: {body}" if body else error.msg
        raise
    return json.loads(payload) if payload else None
