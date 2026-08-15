"""A dummy n8n for the webhook tests: an HTTP server that writes down what it got.

Test-only, and deliberately not a mock of `urllib`. What the brief promises is
that a *real* POST leaves this process with the right headers and the right
body, and that a *real* endpoint which never answers costs the operator
nothing. Patching the transport away would test the code's opinion of itself.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from apps.core import webhooks


class RecordingWebhookServer:
    """Context manager: `with RecordingWebhookServer() as server: ...`.

    `server.url` is what `N8N_WEBHOOK_URL` should be overridden to.
    `server.received` holds one entry per request, with headers and body.
    `delay_seconds` makes the endpoint slow — the "n8n is hanging" case.
    """

    def __init__(
        self, *, delay_seconds: float = 0.0, status: int = 200, redirect_to: str | None = None
    ):
        self.delay_seconds = delay_seconds
        self.status = 302 if redirect_to else status
        self.redirect_to = redirect_to
        self.received: list[dict] = []
        self._server = None
        self._thread = None

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "RecordingWebhookServer":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's contract
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                outer.received.append(
                    {"headers": dict(self.headers.items()), "raw": raw}
                )
                if outer.delay_seconds:
                    time.sleep(outer.delay_seconds)
                self.send_response(outer.status)
                if outer.redirect_to:
                    self.send_header("Location", outer.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                """Silence: the test output is not a web server access log."""

        class QuietHTTPServer(HTTPServer):
            def handle_error(self, request, client_address):
                """Expected, in the timeout test: the client hung up while the
                handler was still sleeping. A traceback on stderr would make a
                passing test look broken."""

        # Port 0: the OS picks a free one, so parallel runs cannot collide.
        self._server = QuietHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
        return False

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/webhook/vectron"

    # --- assertions helpers -------------------------------------------------

    def payloads(self) -> list[dict]:
        return [json.loads(entry["raw"].decode("utf-8")) for entry in self.received]

    def raw_bodies(self) -> list[bytes]:
        return [entry["raw"] for entry in self.received]


def wait_for_delivery(timeout: float = 5.0) -> None:
    """Join every in-flight webhook thread.

    Production never does this — the whole design is that nobody waits — so the
    joining lives here, in the tests, and finds the threads by the name
    `webhooks.send` gives them.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [
            thread
            for thread in threading.enumerate()
            if thread.name == webhooks.THREAD_NAME and thread.is_alive()
        ]
        if not alive:
            return
        for thread in alive:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
