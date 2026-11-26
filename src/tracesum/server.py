"""A local page showing the same summary the terminal prints."""
from __future__ import annotations

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources


def make_handler(data: dict) -> type[BaseHTTPRequestHandler]:
    # Whatever builds the payload, the page must be able to say when the trace
    # was read: it polls every 5s but never re-reads the file.
    data = {**data}
    data.setdefault("read_at", datetime.now().strftime("%H:%M:%S"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's spelling)
            if self.path.split("?")[0] in ("/", "/index.html"):
                try:
                    body = resources.files("tracesum").joinpath("static/index.html").read_bytes()
                except (FileNotFoundError, OSError):
                    # A broken install should say so like everything else here does,
                    # not drop the connection with a traceback in the server log.
                    body = json.dumps({"error": "the installed package has no page "
                                                "(tracesum/static/index.html) — reinstall tracesum"}).encode()
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                kind = "text/html; charset=utf-8"
            elif self.path.split("?")[0] == "/api/report":
                body = json.dumps(data, ensure_ascii=False).encode()
                kind = "application/json; charset=utf-8"
            else:
                body = json.dumps({"error": "not found"}).encode()
                kind = "application/json; charset=utf-8"
                self.send_response(404)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    return Handler


def serve(data: dict, host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(data))
    print(f"tracesum  http://{host}:{httpd.server_address[1]}/  (ctrl-c to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
