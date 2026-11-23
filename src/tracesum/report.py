"""One shape for the terminal, the JSON and the page."""
from __future__ import annotations

from .trace import Summary


def build(summary: Summary, top: int = 10, source: str = "", long_ms: float = 50.0) -> dict:
    main = summary.main
    names = {thread.tid: thread.name for thread in summary.threads if thread.name}
    main = summary.main
    return {
        "source": source,
        "span_s": round(summary.total_us / 1_000_000, 3),
        "main_tid": main.tid,
        "main_name": main.name,
        "busy_ms": round(main.busy / 1000, 1),
        "busy_share": round(summary.busy_share * 100, 1),
        "layout_ms": round(summary.layout_us / 1000, 1),
        "layout_count": summary.layout_count,
        "script_ms": round(summary.script_us / 1000, 1),
        "style_ms": round(summary.style_us / 1000, 1),
        "paint_ms": round(summary.paint_us / 1000, 1),
        "threads": [{"tid": thread.tid, "name": thread.name,
                     "busy_ms": round(thread.busy / 1000, 1),
                     "tasks": len(thread.tasks)} for thread in summary.threads[:5]],
        "long_count": len(summary.long_tasks),
        "long_ms": long_ms,
        "main_long_count": sum(1 for task in summary.long_tasks if task.tid == main.tid),
        "long_tasks": [{"name": task.name, "ms": round(task.ms, 1), "tid": task.tid,
                        # relative to the trace's first event, like the DevTools
                        # timeline: an absolute ts from process start is thousands
                        # of seconds and matches nothing on screen
                        "start_s": round((task.start - summary.origin_us) / 1_000_000, 3),
                        "ts_us": int(task.start),
                        "thread": names.get(task.tid, f"tid {task.tid}")}
                       for task in summary.long_tasks[:top]],
    }


def render(data: dict) -> str:
    lines = [
        f"{data['span_s']:.3f}s of trace, main thread {data['main_tid']}"
        f"{' (' + data['main_name'] + ')' if data.get('main_name') else ''} busy "
        f"{data['busy_ms']:.1f}ms ({data['busy_share']:.1f}%)",
        f"  script {data['script_ms']:.1f}ms · style {data['style_ms']:.1f}ms · "
        f"layout {data['layout_ms']:.1f}ms in {data['layout_count']} "
        f"{'pass' if data['layout_count'] == 1 else 'passes'} · "
        f"paint {data['paint_ms']:.1f}ms",
    ]
    if data["long_tasks"]:
        # `--top` is a view, not a measurement: say how many there are in total,
        # otherwise "3 long tasks" reads as if that is all the trace has.
        shown = len(data["long_tasks"])
        total = data["long_count"]
        main_count = data["main_long_count"]
        # A long task on the compositor is not a main-thread hitch: say which thread
        # each one was on, and keep the exit code about the main thread.
        if total > shown:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms ({shown} of {total} shown, --top to see more):")
        elif main_count == total:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms ({total}):")
        else:
            lines.append(f"longest tasks ≥{data['long_ms']:g}ms ({total}, "
                         f"{total - main_count} not on the main thread):")
        for task in data["long_tasks"]:
            # Two tasks with the same name are only distinguishable by where they
            # start: without the time they read as one line printed twice.
            thread = f"  ({task['thread']})" if task.get("thread") else ""
            lines.append(f"  {task['ms']:>8.1f}ms  @{task['start_s']:>7.3f}s  {task['name']}{thread}")
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
