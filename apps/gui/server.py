"""StrategyBench GUI: a local server for playing and inspecting the project's games.

    uv run python apps/gui/server.py [--port 8765] [--runs-dir runs]

Serves a single page and a small JSON API on 127.0.0.1 only. Standard library HTTP server;
game logic from OpenSpiel and the strategybench package. See apps/gui/README.md.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from sbgui.app import ApiError, App  # noqa: E402

STATIC = HERE / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
MAX_BODY = 64 * 1024
CSP = "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'"
_SESSION = re.compile(r"^/api/sessions/([A-Za-z0-9_-]{1,64})(/[a-z]+)?$")


class Handler(BaseHTTPRequestHandler):
    server_version = "StrategyBenchGUI/1"
    app: App  # set by make_server
    verbose = False

    # Plumbing

    def log_message(self, format: str, *args: Any) -> None:
        if self.verbose:
            super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        try:
            text = json.dumps(payload, allow_nan=False, default=_json_default)
        except ValueError:  # NaN or infinity somewhere: JSON has no such numbers, send null
            text = json.dumps(_finite(payload), allow_nan=False, default=_json_default)
        self._send(status, text.encode(), "application/json", extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _allowed_origin(self) -> bool:
        """Only this server's own pages may call it (guards against DNS rebinding and CSRF)."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlsplit(origin).netloc in allowed

    def _body(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ApiError(415, "send JSON (Content-Type: application/json)")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if length > MAX_BODY:
            raise ApiError(413, "request body too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "request body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        return body

    def _dispatch(self, method: str) -> None:
        if not self._allowed_origin():
            return self._error(HTTPStatus.FORBIDDEN, "requests must come from this app's own page")
        url = urlsplit(self.path)
        path = url.path
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if method in ("GET", "HEAD") and path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), content_type)
            result = self._api(method, path, query)
            if result is None:
                return self._error(HTTPStatus.NOT_FOUND, f"no route for {method} {path}")
            status, payload, extra = result
            self._json(status, payload, extra)
        except ApiError as e:
            self._error(e.status, e.message)
        except Exception as e:  # keep serving; report the failure to the page
            self.log_error("unhandled error on %s %s: %r", method, path, e)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__}: {e}")

    def _api(self, method: str, path: str, query: dict[str, str]):
        app = self.app
        get = method in ("GET", "HEAD")
        if get and path == "/api/games":
            return 200, app.games(), None
        if method == "POST" and path == "/api/inspect":
            return 200, app.inspect(self._body()), None
        if get and path == "/api/profile":
            return 200, app.profile(query.get("game")), None
        if method == "POST" and path == "/api/profile/start":
            return 200, app.profile_start(self._body()), None
        if method == "POST" and path == "/api/profile/cancel":
            return 200, app.profile_cancel(self._body()), None
        if method == "POST" and path == "/api/sessions":
            return 201, app.create_session(self._body()), None
        if get and path == "/api/explore":
            return 200, app.explore(query), None
        m = _SESSION.match(path)
        if m is None:
            return None
        sid, action = m.group(1), m.group(2)
        reveal = query.get("reveal") in ("1", "true")
        if get and action is None:
            return 200, app.view(sid, reveal), None
        if get and action == "/export":
            filename = f"strategybench-hands-{sid}.json"
            return 200, app.export(sid), {"Content-Disposition": f'attachment; filename="{filename}"'}
        if get and action == "/hint":
            return 200, app.hint(sid, query.get("ply")), None
        if method == "POST" and action in ("/act", "/step", "/next"):
            handler = {"/act": app.act, "/step": app.step, "/next": app.next_hand}[action]
            return 200, handler(sid, self._body()), None
        return None

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def _finite(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    return value


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    raise TypeError(f"cannot serialise {type(value).__name__}")


def make_server(app: App, port: int = 8765, verbose: bool = False) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 (``port=0`` picks a free port)."""
    handler = type("BoundHandler", (Handler,), {"app": app, "verbose": verbose})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    parser.add_argument("--runs-dir", default=str(REPO / "runs"), help="results directory to read runs from")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)

    app = App(args.runs_dir)
    try:
        server = make_server(app, port=args.port, verbose=args.verbose)
    except OSError as e:
        print(f"could not listen on 127.0.0.1:{args.port}: {e}. Try --port.", file=sys.stderr)
        return 1
    print(f"StrategyBench GUI: http://127.0.0.1:{server.server_address[1]}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
