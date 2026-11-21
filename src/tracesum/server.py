"""A local page showing the same summary the terminal prints."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources


def make_handler(data: dict) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's spelling)
            if self.path.split("?")[0] in ("/", "/index.html"):
                body = resources.files("tracesum").joinpath("static/index.html").read_bytes()
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
