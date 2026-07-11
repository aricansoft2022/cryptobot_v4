"""A tiny stdlib HTTP server that exposes the bot's status snapshot as JSON.

Serves the value of an injected ``provider()`` (a dict) at ``/status`` and a
liveness probe at ``/health``. Runs in a background daemon thread; bind to
``127.0.0.1`` for local monitoring. Read-only — it never mutates bot state.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional

StatusProvider = Callable[[], Dict[str, Any]]


def _make_handler(provider: StatusProvider, status_path: str):
    class _StatusHandler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silence default stderr logging
            pass

        def _json(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.rstrip("/") or "/"
            if path == status_path.rstrip("/") or self.path == status_path:
                self._json(200, provider())
            elif path == "/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})

    return _StatusHandler


class StatusServer:
    """Serves an injected status dict over HTTP in a background thread."""

    def __init__(
        self,
        provider: StatusProvider,
        host: str = "127.0.0.1",
        port: int = 0,
        path: str = "/status",
    ) -> None:
        self._path = path
        self._httpd = ThreadingHTTPServer((host, port), _make_handler(provider, path))
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}{self._path}"

    def start(self) -> "StatusServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
