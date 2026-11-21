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

    @property
    def main(self) -> Thread:
        return max(self.threads, key=lambda thread: thread.busy) if self.threads else Thread(0)

    @property
    def busy_share(self) -> float:
        return self.main.busy / self.total_us if self.total_us else 0.0


def load(path: Path) -> list[dict]:
    """The event list, accepting both a bare array and the `{"traceEvents": …}` wrapper."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
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


def summarise(events: list[dict], long_ms: float = 50.0) -> Summary:
    """Aggregate complete events by thread, and bucket the main-thread work by kind."""
    by_thread: dict[int, Thread] = {}
    starts: list[float] = []
    for event in events:
        dur = event.get("dur")
        if event.get("ph") != "X" or not isinstance(dur, (int, float)) or dur <= 0:
            continue
        tid = int(event.get("tid") or 0)
        start = float(event.get("ts") or 0)
        thread = by_thread.setdefault(tid, Thread(tid))
        task = Task(str(event.get("name") or event.get("cat") or "?"), float(dur), tid, start)
        thread.tasks.append(task)
        thread.busy += task.dur
        starts.append(start)
        starts.append(start + task.dur)
    if not by_thread:
        raise TraceError("no complete events with a duration in this trace")
    total = max(starts) - min(starts)
    tasks = [task for thread in by_thread.values() for task in thread.tasks]
    long_tasks = sorted((task for task in tasks if task.dur >= long_ms * US),
                        key=lambda task: task.dur, reverse=True)
    kinds = {"Layout": 0.0, "UpdateLayoutTree": 0.0, "Paint": 0.0, "PrePaint": 0.0}
    counts = {"Layout": 0}
    for task in tasks:
        for kind in kinds:
            if task.name == kind:
                kinds[kind] += task.dur
                if kind in counts:
                    counts[kind] += 1
    return Summary(
        total_us=total,
        threads=sorted(by_thread.values(), key=lambda thread: thread.busy, reverse=True),
        long_tasks=long_tasks,
        layout_us=kinds["Layout"] + kinds["UpdateLayoutTree"],
        layout_count=counts["Layout"],
        script_us=sum(task.dur for task in tasks if task.name in ("FunctionCall", "EvaluateScript", "v8.run")),
        style_us=kinds["UpdateLayoutTree"],
        paint_us=kinds["Paint"] + kinds["PrePaint"],
    )
