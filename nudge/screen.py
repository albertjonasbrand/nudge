"""The touchscreen: a local web page shown in Chromium kiosk mode.

Plain stdlib HTTP server. Server -> screen is Server-Sent Events; screen ->
server is small POSTs. Also serves the family page (lexicon editor, log
download) on the same port, reachable from a phone on the home Wi-Fi.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class ScreenServer:
    def __init__(self, app, port: int = 8765, host: str = "0.0.0.0"):
        self.app = app
        self.port = port
        self.host = host
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._state = {"status": "starting", "words": [], "more": 0}
        self._httpd: ThreadingHTTPServer | None = None

    # ---- what the service calls ------------------------------------------

    def show_words(self, words: list[str]) -> None:
        self._state["words"] = words
        self._state["more"] = self.app.more_count
        self._broadcast({"type": "words", "words": words, "more": self.app.more_count})

    def set_status(self, status: str) -> None:
        self._state["status"] = status
        self._broadcast({"type": "status", "status": status})

    def _broadcast(self, msg: dict) -> None:
        data = json.dumps(msg)
        with self._lock:
            for q in list(self._clients):
                q.put(data)

    # ---- server ------------------------------------------------------------

    def start(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):      # quiet
                pass

            def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?")[0]
                if path in ("/", "/index.html"):
                    self._send(200, (STATIC / "index.html").read_bytes())
                elif path == "/family":
                    self._send(200, (STATIC / "family.html").read_bytes())
                elif path == "/events":
                    self._sse()
                elif path == "/state":
                    self._send(200, json.dumps(server._state).encode(), "application/json")
                elif path == "/lexicon":
                    self._send(200, yaml.safe_dump(server.app.lexicon.data, sort_keys=False,
                                                   allow_unicode=True).encode(), "text/plain; charset=utf-8")
                elif path == "/log.csv":
                    p = server.app.stall_log.path
                    body = p.read_bytes() if p.exists() else b"time,tail,cand1,cand2,cand3,used,ms,more\n"
                    self._send(200, body, "text/csv")
                else:
                    self._send(404, b"not found", "text/plain")

            def _sse(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                with server._lock:
                    server._clients.append(q)
                try:
                    self.wfile.write(f"data: {json.dumps({'type': 'state', **server._state})}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            data = q.get(timeout=15)
                            self.wfile.write(f"data: {data}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with server._lock:
                        if q in server._clients:
                            server._clients.remove(q)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {}
                path = self.path.split("?")[0]
                app = server.app
                if path == "/click":
                    threading.Thread(target=app.nudge, args=(False,), daemon=True).start()
                elif path == "/more":
                    threading.Thread(target=app.nudge, args=(True,), daemon=True).start()
                elif path == "/repeat":
                    app.repeat()
                elif path == "/tap":
                    app.tap(int(body.get("index", 0)))
                elif path == "/lexicon":
                    try:
                        data = yaml.safe_load(raw.decode()) or {}
                        for k in ("people", "places", "life", "confirmed"):
                            app.lexicon.data[k] = list(data.get(k) or [])
                        app.lexicon.save()
                        app.resolver.refresh_lexicon()
                    except yaml.YAMLError as e:
                        self._send(400, str(e).encode(), "text/plain")
                        return
                elif path == "/log/enable":
                    app.stall_log.enabled = bool(body.get("enabled", False))
                elif path == "/log/wipe":
                    app.stall_log.wipe()
                else:
                    self._send(404, b"not found", "text/plain")
                    return
                self._send(200, b"ok", "text/plain")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True, name="screen-http").start()
        log.info("screen server on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
