import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracesum.cli import main


def trace(events) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(events, handle)
    handle.close()
    return Path(handle.name)


def event(name, dur, ts=0, tid=1):
    return {"ph": "X", "name": name, "dur": dur, "ts": ts, "tid": tid}


class ExitTests(unittest.TestCase):
    def test_a_long_task_is_exit_one(self):
        path = trace([event("Long", 120_000)])
        self.assertEqual(main([str(path)]), 1)

    def test_a_quick_trace_is_exit_zero(self):
        path = trace([event("Small", 10_000)])
        self.assertEqual(main([str(path)]), 0)

    def test_json_is_still_json_on_error(self):
        code = main(["/no/such/trace.json", "--json"])
        self.assertEqual(code, 2)

    def test_top_must_be_positive(self):
        path = trace([event("Small", 1_000)])
        self.assertEqual(main([str(path), "--top", "0"]), 2)


class ServerTests(unittest.TestCase):
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from tracesum.report import build
        from tracesum.server import make_handler
        from tracesum.trace import summarise

        data = build(summarise([event("Long", 120_000)]), 5, "x")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_the_endpoint_returns_the_summary(self):
        import urllib.request
        body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/report", timeout=5).read()
        data = json.loads(body)
        self.assertEqual(data["long_tasks"][0]["name"], "Long")
        self.assertIn("start_s", data["long_tasks"][0])

    def test_the_page_is_html_with_a_viewport(self):
        import urllib.request
        body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5).read().decode()
        self.assertIn("<meta name=\"viewport\"", body)
        self.assertIn("/api/report", body)

    def test_unknown_path_is_404_json(self):
        import urllib.error, urllib.request
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/nope", timeout=5)
        self.assertEqual(caught.exception.code, 404)
