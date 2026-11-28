import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tracesum import server
from tracesum.server import make_handler, url_for


def get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.status, response.headers, response.read()


class ServerTests(unittest.TestCase):
    """The page is the half of tracesum that has no terminal: it needs its own tests."""

    def setUp(self):
        # `read_at` is added by the handler, not by build(); a payload without it
        # still has to render, so the fixture is the bare minimum.
        self.data = {"span_s": 0.4, "main_tid": 1, "main_name": "CrRendererMain",
                     "main_guessed": False, "busy_ms": 100.0, "busy_share": 25.0,
                     "layout_ms": 0.0, "layout_count": 0, "script_ms": 100.0,
                     "style_ms": 0.0, "paint_ms": 0.0, "other_ms": 0.0, "other_count": 0,
                     "overlap_ms": 0.0, "thread_total": 1,
                     "threads": [{"tid": 1, "name": "CrRendererMain", "busy_ms": 100.0,
                                  "tasks": 1}],
                     "long_count": 1, "long_ms": 50.0, "main_long_count": 1,
                     "long_nested_count": 0,
                     "long_tasks": [{"name": "RunTask", "ms": 100.0, "tid": 1,
                                     "nested": False, "parent": "", "start_s": 0.0,
                                     "ts_us": 0, "thread": "CrRendererMain"}],
                     "source": "small.json"}
        handler = make_handler(self.data)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_a_wildcard_host_gets_a_url_a_browser_can_open(self):
        self.assertEqual(url_for("0.0.0.0", 8765), "http://127.0.0.1:8765/")
        self.assertEqual(url_for("::", 8765), "http://127.0.0.1:8765/")
        self.assertEqual(url_for("192.168.1.5", 9000), "http://192.168.1.5:9000/")

    def test_the_api_returns_the_payload_verbatim(self):
        status, headers, body = get(self.port, "/api/report")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        payload = json.loads(body)
        self.assertEqual(payload["busy_ms"], 100.0)
        self.assertEqual(payload["long_tasks"][0]["name"], "RunTask")

    def test_the_handler_stamps_a_read_time_when_build_did_not(self):
        _, _, body = get(self.port, "/api/report")
        self.assertRegex(json.loads(body)["read_at"], r"^\d\d:\d\d:\d\d$")

    def test_the_page_is_the_installed_html(self):
        status, headers, body = get(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b'id="chips"', body)
        self.assertIn(b"/api/report", body)
        self.assertIn(b"nearby", body)

    def test_a_package_without_the_page_says_so(self):
        original = server.resources.files

        class Empty:
            def joinpath(self, _name):
                raise FileNotFoundError("static/index.html")

        server.resources.files = lambda _package: Empty()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                get(self.port, "/")
            self.assertEqual(caught.exception.code, 500)
            self.assertIn("reinstall tracesum", json.loads(caught.exception.read())["error"])
        finally:
            server.resources.files = original

    def test_an_unknown_path_is_json_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            get(self.port, "/nope")
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(json.loads(caught.exception.read())["error"], "not found")

    def test_a_query_string_still_serves_the_page(self):
        status, _, body = get(self.port, "/?x=1")
        self.assertEqual(status, 200)
        self.assertIn(b'id="chips"', body)
