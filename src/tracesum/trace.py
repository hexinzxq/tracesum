"""Read a Chrome trace and say who was busy.

A performance trace is an array of events: `ph: "X"` events are complete and
carry a `dur` in microseconds on a `tid`. That is enough to answer the question
people actually have — "what took the main thread" — without a browser.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

US = 1000.0


class TraceError(Exception):
    """The file is not a trace we can read."""


@dataclass
class Task:
    name: str
    dur: float            # microseconds
    tid: int
    start: float

    @property
    def ms(self) -> float:
        return self.dur / US


@dataclass
class Thread:
    tid: int
    busy: float = 0.0
    name: str = ""
    tasks: list[Task] = field(default_factory=list)


@dataclass
class Summary:
    total_us: float
    threads: list[Thread]
    long_tasks: list[Task]
    layout_us: float
    layout_count: int
    script_us: float
    style_us: float
    paint_us: float
    other_us: float
    other_count: int
    origin_us: float = 0.0

    @property
    def main(self) -> Thread:
        """The renderer main thread when the trace names it, else the busiest.

        A worker or compositor thread can out-busy the main thread on a real
        profile; calling that one "the main thread" makes the whole report
        describe the wrong thread.
        """
        for thread in self.threads:
            if thread.name == "CrRendererMain":
                return thread
        return max(self.threads, key=lambda thread: thread.busy) if self.threads else Thread(0)

    @property
    def busy_share(self) -> float:
        return self.main.busy / self.total_us if self.total_us else 0.0


def load(path: Path) -> list[dict]:
    """The event list, accepting both a bare array and the `{"traceEvents": …}` wrapper."""
    try:
        # `utf-8-sig` so a trace saved with a BOM loads instead of failing with a
        # JSONDecodeError whose advice ("decode using utf-8-sig") the CLI user
        # cannot act on.
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise TraceError(f"{path} is not JSON: {error.msg} at line {error.lineno}") from error
    except OSError as error:
        raise TraceError(f"cannot read {path}: {error.strerror or error}") from error
    if isinstance(payload, dict):
        payload = payload.get("traceEvents", payload.get("events"))
    if not isinstance(payload, list):
        raise TraceError(f"{path} has no event array — export a Chrome performance trace")
    events = [event for event in payload if isinstance(event, dict)]
    if not any(event.get("dur") for event in events):
        raise TraceError(f"{path} has no complete events with a duration — "
                         "is this a trace exported from the Performance panel?")
    return events


def busy_time(tasks: list[Task]) -> float:
    """How long the thread was busy: the union of its task intervals.

    Nested events must not be counted twice (a RunTask and the FunctionCall
    inside it), and two overlapping-but-not-nested intervals must not be
    dropped: taking only the "outer" task loses the tail of the second one.
    """
    covered = 0.0
    busy = 0.0
    for task in sorted(tasks, key=lambda task: (task.start, -task.dur)):
        end = task.start + task.dur
        if task.start > covered:
            busy += task.dur
        elif end > covered:
            busy += end - covered
        covered = max(covered, end)
    return busy


KINDS: dict[str, tuple[str, ...]] = {
    "script": ("FunctionCall", "EvaluateScript", "v8.run"),
    "style": ("UpdateLayoutTree",),
    "layout": ("Layout",),
    "paint": ("Paint", "PrePaint"),
}


def summarise(events: list[dict], long_ms: float = 50.0,
              kinds: dict[str, tuple[str, ...]] | None = None) -> Summary:
    """Aggregate complete events by thread, and bucket the main-thread work by kind."""
    by_thread: dict[int, Thread] = {}
    starts: list[float] = []
    names: dict[int, str] = {}
    for event in events:
        # `ph: "M"` is metadata: the trace itself says which tid is which thread,
        # and a report that guesses from busy time gets renderer-vs-worker wrong.
        if (event.get("ph") == "M" and event.get("name") == "thread_name"
                and isinstance(event.get("args"), dict)):
            tid = int(event.get("tid") or 0)
            names[tid] = str(event["args"].get("name") or "")
    for event in events:
        dur = event.get("dur")
        if event.get("ph") != "X" or not isinstance(dur, (int, float)) or dur <= 0:
            continue
        tid = int(event.get("tid") or 0)
        start = float(event.get("ts") or 0)
        thread = by_thread.setdefault(tid, Thread(tid, name=names.get(tid, "")))
        task = Task(str(event.get("name") or event.get("cat") or "?"), float(dur), tid, start)
        thread.tasks.append(task)
        starts.append(start)
        starts.append(start + task.dur)
    if not by_thread:
        raise TraceError("no complete events with a duration in this trace")
    for thread in by_thread.values():
        thread.busy = busy_time(thread.tasks)
    total = max(starts) - min(starts)
    threads = sorted(by_thread.values(), key=lambda thread: thread.busy, reverse=True)
    # The headline is about one thread, so the buckets are about that thread too:
    # a worker's Layout in the main-thread layout total is the same mistake as
    # calling the busiest thread "main".
    main = next((thread for thread in threads if thread.name == "CrRendererMain"),
                threads[0] if threads else Thread(0))
    tasks = [task for thread in by_thread.values() for task in thread.tasks]
    long_tasks = sorted((task for task in tasks if task.dur >= long_ms * US),
                        key=lambda task: task.dur, reverse=True)
    # Style recalc and layout are different passes: counting UpdateLayoutTree as
    # layout as well puts the same milliseconds in two buckets.
    # `--kind` lets a caller add names the four defaults do not know (a framework's
    # own markers): the buckets are a mapping, not a closed set of Chrome names.
    mapping = {bucket: set(names) for bucket, names in KINDS.items()}
    for bucket, names in (kinds or {}).items():
        mapping[bucket].update(names)
    named = {name for names in mapping.values() for name in names}
    style = sum(task.dur for task in main.tasks if task.name in mapping["style"])
    layout = [task for task in main.tasks if task.name in mapping["layout"]]
    paint = sum(task.dur for task in main.tasks if task.name in mapping["paint"])
    script_tasks = [task for task in main.tasks if task.name in mapping["script"]]
    script = sum(task.dur for task in script_tasks)
    # Four named buckets used to sum to nothing on a timer-driven trace: the
    # main thread was busy for a second and every bucket said 0.0ms. Keep the
    # leftover explicit instead of letting the reader guess.
    classified = style + sum(task.dur for task in layout) + paint + script
    other = max(0.0, main.busy - classified)
    other_count = sum(1 for task in main.tasks if task.name not in named)
    return Summary(
        total_us=total,
        origin_us=min(starts),
        threads=threads,
        long_tasks=long_tasks,
        layout_us=sum(task.dur for task in layout),
        layout_count=len(layout),
        script_us=script,
        style_us=style,
        paint_us=paint,
        other_us=other,
        other_count=other_count,
    )
