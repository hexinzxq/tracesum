"""One shape for the terminal, the JSON and the page."""
from __future__ import annotations

from .trace import Summary


NEAR_US = 200_000


def nearby(task, tasks, long_ms: float = 50.0) -> list[dict]:
    """What else ran on this thread right around a long task.

    A 300ms `RunTask` alone does not say what it was doing; the tasks around it do,
    and they are already in the trace the page is showing.
    """
    start, end = task.start - NEAR_US, task.start + task.dur + NEAR_US
    around = [other for other in tasks
              if other is not task and (other.pid, other.tid) == (task.pid, task.tid)
              and other.start + other.dur >= start and other.start <= end]
    around.sort(key=lambda other: other.start)
    return [{"name": other.name, "ms": round(other.ms, 1),
             "start_s": round((other.start - task.start) / 1_000_000, 3),
             "long": other.dur >= long_ms * 1000} for other in around]


def build(summary: Summary, top: int = 10, source: str = "", long_ms: float = 50.0) -> dict:
    main = summary.main
    names = {(thread.pid, thread.tid): thread.name for thread in summary.threads if thread.name}
    tids = [thread.tid for thread in summary.threads]
    every_task = [task for thread in summary.threads for task in thread.tasks]

    def _long_task(task) -> dict:
        around = nearby(task, every_task, long_ms)
        return {"name": task.name, "ms": round(task.ms, 1), "tid": task.tid,
                "pid": task.pid,
                "nested": bool(parent_of(task)),
                "parent": parent_of(task).name if parent_of(task) else "",
                # relative to the trace's first event, like the DevTools timeline:
                # an absolute ts from process start is thousands of seconds
                "start_s": round((task.start - summary.origin_us) / 1_000_000, 3),
                "ts_us": int(task.start),
                "thread": names.get((task.pid, task.tid), f"tid {task.tid}"),
                # Capped at 12 for the page; say how many there were, the same way
                # the thread list and the long-task list say it.
                "nearby": around[:12],
                "nearby_total": len(around)}

    summary_long_ms = long_ms

    def parent_of(task):
        # A 60ms child inside a 300ms parent is part of one hitch, not a second one.
        for other in summary.long_tasks:
            if (other is not task and (other.pid, other.tid) == (task.pid, task.tid)
                    and other.dur > task.dur
                    and other.start <= task.start
                    and other.start + other.dur >= task.start + task.dur):
                return other
        return None
    return {
        "source": source,
        "span_s": round(summary.total_us / 1_000_000, 3),
        "main_tid": main.tid,
        "main_pid": main.pid,
        "main_name": main.name,
        # With no thread names in the trace, "main" is just the busiest thread: the
        # report must say so instead of presenting a guess as a fact.
        "main_guessed": not any(thread.name == "CrRendererMain" for thread in summary.threads),
        # A trace can hold more than one renderer process, so more than one thread
        # is called CrRendererMain; the headline must say it picked one of them.
        "main_candidates": sum(1 for thread in summary.threads
                               if thread.name == "CrRendererMain"),
        "busy_ms": round(main.busy / 1000, 1),
        "busy_share": round(summary.busy_share * 100, 1),
        "layout_ms": round(summary.layout_us / 1000, 1),
        "layout_count": summary.layout_count,
        "script_ms": round(summary.script_us / 1000, 1),
        "style_ms": round(summary.style_us / 1000, 1),
        "paint_ms": round(summary.paint_us / 1000, 1),
        "other_ms": round(summary.other_us / 1000, 1),
        "other_count": summary.other_count,
        "overlap_ms": round(max(0.0, (summary.script_us + summary.style_us
                                      + summary.layout_us + summary.paint_us
                                      + summary.other_us) / 1000 - summary.main.busy / 1000), 1),
        "thread_total": len(summary.threads),
        "threads": [{"tid": thread.tid, "name": thread.name, "pid": thread.pid,
                     # two processes can both have a tid 1: show which one
                     "ambiguous_tid": tids.count(thread.tid) > 1,
                     "busy_ms": round(thread.busy / 1000, 1),
                     "tasks": len(thread.tasks)} for thread in summary.threads[:5]],
        "long_count": len(summary.long_tasks),
        "long_ms": long_ms,
        "main_long_count": sum(1 for task in summary.long_tasks if task.tid == main.tid),
        "long_nested_count": sum(1 for task in summary.long_tasks if parent_of(task)),
        "long_tasks": [_long_task(task) for task in summary.long_tasks[:top]],
    }


def render(data: dict) -> str:
    lines = [
        f"{data['span_s']:.3f}s of trace, "
        f"{'main thread ' + str(data['main_tid']) + ' (' + str(data['main_name']) + ')' if data.get('main_name') and not data.get('main_guessed') else 'busiest thread ' + str(data['main_tid'])}"
        f" busy {data['busy_ms']:.1f}ms ({data['busy_share']:.1f}%)"
        # a guess must not read like a measurement
        + ("" if data.get("main_name") and not data.get("main_guessed")
           else " — this trace names no threads, so \"main\" is a guess"),
        f"  script {data['script_ms']:.1f}ms · style {data['style_ms']:.1f}ms · "
        f"layout {data['layout_ms']:.1f}ms in {data['layout_count']} "
        f"{'pass' if data['layout_count'] == 1 else 'passes'} · "
        f"paint {data['paint_ms']:.1f}ms · other {data['other_ms']:.1f}ms",
    ]
    if data.get("overlap_ms"):
        # Summing by name counts a nested task once per name; say so instead of
        # printing a total larger than the thread's busy time with no comment.
        lines.append(f"  note: bucket totals overlap by {data['overlap_ms']:.1f}ms "
                     f"— nested tasks count once per name, so they can exceed busy time")
    if data.get("other_ms"):
        # A bucket called "other" is only honest if it says what is in it.
        count = data["other_count"]
        lines.append(f"  other: {count} {'task' if count == 1 else 'tasks'} "
                     f"the four buckets do not name (timers, event dispatch, compositing, …)")
    threads = data.get("threads") or []
    if len(threads) > 1:
        # The report is titled after "who is blocking the main thread"; the other
        # threads were computed and shipped in the payload but never printed.
        cut = threads[:3]
        total = data.get("thread_total", len(threads))
        # Both the payload and this line truncate the thread list; say by how much.
        label = (f"threads ({len(cut)} of {total} shown, busiest first):"
                 if total > len(cut) else "threads:")
        # `2 ? 60.0ms` reads like a missing value; an unnamed thread is still a tid.
        # Two processes can both own a tid 1: printing "tid 1" twice reads as
        # one thread listed twice, so name the process when tids repeat.
        def owner(thread: dict) -> str:
            base = f"tid {thread['tid']} {thread['name']}" if thread["name"] else f"tid {thread['tid']}"
            return (f"pid {thread['pid']} {base}"
                    if thread.get("ambiguous_tid") and thread.get("pid") else base)

        shown = " · ".join(
            owner(thread)
            + f" {thread['busy_ms']:.1f}ms / {thread['tasks']} "
              f"{'task' if thread['tasks'] == 1 else 'tasks'}"
            for thread in cut)
        lines.append(f"{label} {shown}")
    if data.get("main_candidates", 0) > 1:
        lines.append(f"  note: {data['main_candidates']} threads are named CrRendererMain "
                     f"(one per renderer process); reporting the busiest, pid {data.get('main_pid')}")
    if data["long_tasks"]:
        # `--top` is a view, not a measurement: say how many there are in total,
        # otherwise "3 long tasks" reads as if that is all the trace has.
        shown = len(data["long_tasks"])
        total = data["long_count"]
        main_count = data["main_long_count"]
        # A long task on the compositor is not a main-thread hitch: say which thread
        # each one was on, and keep the exit code about the main thread.
        nested = data.get("long_nested_count") or 0
        # A 60ms child of a 300ms task is the same hitch, not a second one: counting
        # both as "long tasks" turns one freeze into four.
        extra = f", {nested} nested inside a longer task" if nested else ""
        if total > shown:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms "
                         f"({shown} of {total} shown{extra}, --top to see more):")
        elif main_count == total:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms ({total}{extra}):")
        else:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms ({total}, "
                         f"{total - main_count} not on the main thread{extra}):")
        for task in data["long_tasks"]:
            # Two tasks with the same name are only distinguishable by where they
            # start: without the time they read as one line printed twice.
            thread = f"  ({task['thread']})" if task.get("thread") else ""
            inside = f", in {task['parent']}" if task.get("nested") else ""
            lines.append(f"  {task['ms']:>8.1f}ms  @{task['start_s']:>7.3f}s  "
                         f"{task['name']}{thread}{inside}")
        # (the threshold is printed in the heading, so a --long-ms run is readable)
    else:
        lines.append(f"no task over {data['long_ms']:g}ms — the main thread was never "
                     f"blocked for long")
    return "\n".join(lines)


def verdict(data: dict) -> int:
    """0 when nothing on the main thread ran long, 1 when a long task exists.

    The exit code is for a script: "did this trace block the main thread" is a
    yes/no, and 50ms is the number a person feels as jank.
    """
    # A slow compositor task does not make the page janky: the exit code is about
    # the main thread, and `long_tasks` may hold other threads' work.
    return 1 if data.get("main_long_count") else 0
