import json, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracesum.trace import TraceError, load, summarise


def event(name, dur, ts=0, tid=1, ph="X"):
    return {"ph": ph, "name": name, "dur": dur, "ts": ts, "tid": tid}


def write(events) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(events, handle)
    handle.close()
    return Path(handle.name)


class LoadTests(unittest.TestCase):
    def test_a_bare_array_of_events(self):
        path = write([event("Task", 1000)])
        self.assertEqual(len(load(path)), 1)

    def test_the_trace_events_wrapper(self):
        path = write({"traceEvents": [event("Task", 1000)]})
        self.assertEqual(len(load(path)), 1)

    def test_not_json_says_where(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write("{oops")
        handle.close()
        with self.assertRaises(TraceError) as caught:
            load(Path(handle.name))
        self.assertIn("not JSON", str(caught.exception))

    def test_a_file_without_durations(self):
        path = write([{"ph": "i", "name": "Event"}])
        with self.assertRaises(TraceError) as caught:
            load(path)
        self.assertIn("no complete events", str(caught.exception))


class SummariseTests(unittest.TestCase):
    def test_busy_time_follows_the_thread(self):
        events = [event("LongTask", 120_000, ts=0, tid=7), event("Other", 30_000, ts=0, tid=9)]
        summary = summarise(events)
        self.assertEqual(summary.main.tid, 7)
        self.assertEqual(round(summary.main.busy / 1000), 120)

    def test_long_tasks_over_50ms_only(self):
        events = [event("Big", 80_000), event("Small", 10_000)]
        summary = summarise(events)
        self.assertEqual([task.name for task in summary.long_tasks], ["Big"])

    def test_same_named_tasks_keep_their_own_start(self):
        events = [event("Long", 80_000, ts=1_000_000), event("Long", 80_000, ts=5_000_000)]
        summary = summarise(events)
        starts = sorted(round(task.start / 1_000_000, 3) for task in summary.long_tasks)
        self.assertEqual(starts, [1.0, 5.0])

    def test_thread_names_come_from_metadata(self):
        events = [{"ph": "M", "name": "thread_name", "tid": 4, "args": {"name": "Compositor"}},
                  event("Paint", 10_000, tid=4)]
        summary = summarise(events)
        self.assertEqual(summary.threads[0].name, "Compositor")

    def test_the_renderer_main_wins_over_a_busier_thread(self):
        # a compositor thread can out-busy the main thread on a real profile
        events = [{"ph": "M", "name": "thread_name", "tid": 1, "args": {"name": "CrRendererMain"}},
                  event("Quick", 20_000, tid=1),
                  event("Busy", 500_000, tid=2)]
        summary = summarise(events)
        self.assertEqual(summary.main.tid, 1)

    def test_layout_and_style_are_bucketed(self):
        events = [event("Layout", 20_000), event("UpdateLayoutTree", 10_000), event("Paint", 5_000)]
        summary = summarise(events)
        self.assertEqual(round(summary.layout_us / 1000), 30)
        self.assertEqual(summary.layout_count, 1)
        self.assertEqual(round(summary.paint_us / 1000), 5)

    def test_span_is_the_whole_trace(self):
        events = [event("A", 1000, ts=0), event("B", 2000, ts=9_000_000)]
        summary = summarise(events)
        self.assertEqual(round(summary.total_us / 1_000_000, 3), 9.002)
