import contextlib, io, json, tempfile, unittest
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

    def test_the_total_number_of_long_tasks_is_in_the_json(self):
        path = trace([event("A", 80_000, ts=0), event("B", 90_000, ts=200_000),
                      event("C", 70_000, ts=400_000)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path), "--json", "--top", "1"])
        data = json.loads(out.getvalue())
        self.assertEqual(len(data["long_tasks"]), 1)
        self.assertEqual(data["long_count"], 3)

    def test_long_task_times_are_relative_to_the_trace(self):
        path = trace([event("A", 80_000, ts=5_000_000), event("B", 90_000, ts=5_100_000)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path), "--json"])
        data = json.loads(out.getvalue())
        starts = {task["name"]: (task["start_s"], task["ts_us"]) for task in data["long_tasks"]}
        self.assertEqual(starts["A"], (0.0, 5_000_000))
        self.assertEqual(starts["B"], (0.1, 5_100_000))

    def test_a_long_compositor_task_is_not_a_failing_main_thread(self):
        path = trace([{"ph": "M", "name": "thread_name", "tid": 1, "args": {"name": "CrRendererMain"}},
                      event("Quick", 20_000, tid=1), event("Paint", 500_000, tid=2)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([str(path)])
        self.assertEqual(code, 0)
        self.assertIn("1 not on the main thread", out.getvalue())

    def test_a_long_main_thread_task_still_fails(self):
        path = trace([event("Long", 500_000, tid=1)])
        self.assertEqual(main([str(path)]), 1)

    def test_long_ms_moves_the_line_and_the_exit_code(self):
        path = trace([event("Middle", 80_000)])
        self.assertEqual(main([str(path)]), 1)  # 80ms is a long task by default
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([str(path), "--long-ms", "100"]), 0)
        self.assertIn("no task over 100ms", out.getvalue())

    def test_long_ms_must_be_positive(self):
        path = trace([event("Middle", 80_000)])
        self.assertEqual(main([str(path), "--long-ms", "0"]), 2)

    def test_a_trace_without_thread_names_says_main_is_a_guess(self):
        path = trace([event("Paint", 300_000, tid=2)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertIn("busiest thread 2", out.getvalue())
        self.assertIn("no threads", out.getvalue())

    def test_a_named_main_thread_is_not_called_a_guess(self):
        path = trace([{"ph": "M", "name": "thread_name", "tid": 1,
                       "args": {"name": "CrRendererMain"}}, event("Long", 120_000, tid=1)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertIn("main thread 1 (CrRendererMain)", out.getvalue())
        self.assertNotIn("guess", out.getvalue())

    def test_the_other_threads_are_printed(self):
        path = trace([{"ph": "M", "name": "thread_name", "tid": 1, "args": {"name": "CrRendererMain"}},
                      {"ph": "M", "name": "thread_name", "tid": 2, "args": {"name": "Compositor"}},
                      event("Quick", 20_000, tid=1), event("Paint", 500_000, tid=2)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertIn("threads: tid 2 Compositor 500.0ms / 1 task", out.getvalue())

    def test_a_single_thread_trace_has_no_threads_line(self):
        path = trace([event("Quick", 20_000, tid=1)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertNotIn("threads:", out.getvalue())

    def test_a_truncated_thread_list_says_how_many_there_are(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}}]
        for tid in range(2, 8):
            events.append(event("Work", 60_000, tid=tid))  # 6 threads with work
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertIn("threads (3 of 6 shown", out.getvalue())

    def test_an_unnamed_thread_is_a_tid_not_a_question_mark(self):
        path = trace([event("A", 60_000, tid=2), event("B", 60_000, tid=3)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        line = [row for row in out.getvalue().splitlines() if row.startswith("threads")][0]
        self.assertIn("tid 2", line)
        self.assertNotIn("?", line)

    def test_an_out_of_range_port_is_a_sentence(self):
        path = trace([event("Quick", 10_000)])
        for port in ("70000", "-1"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main([str(path), "--serve", "--port", port]), 2)
            self.assertIn("--port must be between 0 and 65535", err.getvalue())

    def test_buckets_that_overlap_say_so(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  event("Paint", 100_000, ts=0),
                  event("Layout", 50_000, ts=20_000)]
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        self.assertIn("bucket totals overlap by 50.0ms", out.getvalue())

    def test_kind_moves_an_event_name_into_a_bucket(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  event("TimerFire", 100_000)]
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path), "--kind", "script=TimerFire"])
        line = [row for row in out.getvalue().splitlines() if "script" in row][0]
        self.assertIn("script 100.0ms", line)
        self.assertIn("other 0.0ms", line)

    def test_a_bad_kind_spec_is_a_sentence(self):
        path = trace([event("A", 1_000)])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main([str(path), "--kind", "bogus=X"]), 2)
        self.assertIn("--kind wants BUCKET=NAME", err.getvalue())

    def test_a_nested_long_task_says_what_it_is_inside(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  event("RunTask", 300_000, ts=0),
                  event("FunctionCall", 60_000, ts=20_000)]
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path)])
        text = out.getvalue()
        self.assertIn("1 nested inside a longer task", text)
        self.assertIn("in RunTask", text)

    def test_kind_on_a_name_another_bucket_owns_says_so(self):
        path = trace([event("Paint", 100_000)])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main([str(path), "--kind", "script=Paint"])
        self.assertIn("note: Paint is already counted in paint", err.getvalue())

    def test_long_ms_reaches_the_neighbour_flags(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  event("Big", 200_000, ts=0), event("Small", 60_000, ts=210_000)]
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path), "--long-ms", "100", "--json"])
        data = json.loads(out.getvalue())
        flags = {item["name"]: item["long"] for item in data["long_tasks"][0]["nearby"]}
        self.assertFalse(flags["Small"], "60ms is not long when --long-ms is 100")

    def test_a_crowded_neighbourhood_says_how_many_there_were(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  event("Big", 100_000, ts=0)]
        events += [event(f"Small{i}", 1_000, ts=100_000 + i * 2_000) for i in range(20)]
        path = trace(events)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(path), "--json"])
        task = json.loads(out.getvalue())["long_tasks"][0]
        self.assertEqual(len(task["nearby"]), 12)
        self.assertEqual(task["nearby_total"], 20)

    def test_json_and_serve_cannot_be_asked_for_at_once(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["/tmp/sv.json", "--json", "--serve"])
        self.assertEqual(code, 2)
        self.assertIn("pick one", err.getvalue())

    def test_a_kind_name_the_trace_lacks_says_so(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main([str(trace([event("Paint", 10_000)])), "--kind", "script=TimerFire"])
        self.assertEqual(code, 0)  # nothing long, and an empty bucket is not an error
        self.assertIn("note: --kind script=TimerFire matched no event", err.getvalue())

    def test_two_renderer_mains_say_which_one_was_reported(self):
        events = [{"ph": "M", "name": "thread_name", "pid": 1, "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  {"ph": "M", "name": "thread_name", "pid": 2, "tid": 1,
                   "args": {"name": "CrRendererMain"}},
                  {"ph": "X", "name": "Paint", "dur": 100_000, "ts": 0, "pid": 1, "tid": 1},
                  {"ph": "X", "name": "Paint", "dur": 300_000, "ts": 0, "pid": 2, "tid": 1}]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main([str(trace(events))])
        text = out.getvalue()
        self.assertIn("2 threads are named CrRendererMain", text)
        self.assertIn("reporting the busiest, pid 2", text)

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

    def test_the_page_is_told_when_the_trace_was_read(self):
        import urllib.request
        body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5).read().decode()
        self.assertIn("read_at", body)
        data = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/report", timeout=5).read())
        self.assertRegex(data["read_at"], r"^\d{2}:\d{2}:\d{2}$")
        self.assertTrue(data["source"])

    def test_the_page_counts_long_tasks_like_the_terminal(self):
        import urllib.request
        body = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5).read().decode()
        self.assertIn("main_long_count", body)
        self.assertIn("task.thread", body)

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
