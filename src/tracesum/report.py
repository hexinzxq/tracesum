"""One shape for the terminal, the JSON and the page."""
from __future__ import annotations

from .trace import Summary


def build(summary: Summary, top: int = 10, source: str = "") -> dict:
    main = summary.main
    return {
        "source": source,
        "span_s": round(summary.total_us / 1_000_000, 3),
        "main_tid": main.tid,
        "busy_ms": round(main.busy / 1000, 1),
        "busy_share": round(summary.busy_share * 100, 1),
        "layout_ms": round(summary.layout_us / 1000, 1),
        "layout_count": summary.layout_count,
        "script_ms": round(summary.script_us / 1000, 1),
        "style_ms": round(summary.style_us / 1000, 1),
        "paint_ms": round(summary.paint_us / 1000, 1),
        "threads": [{"tid": thread.tid, "busy_ms": round(thread.busy / 1000, 1),
                     "tasks": len(thread.tasks)} for thread in summary.threads[:5]],
        "long_tasks": [{"name": task.name, "ms": round(task.ms, 1), "tid": task.tid}
                       for task in summary.long_tasks[:top]],
    }


def render(data: dict) -> str:
    lines = [
        f"{data['span_s']:.3f}s of trace, main thread {data['main_tid']} busy "
        f"{data['busy_ms']:.1f}ms ({data['busy_share']:.1f}%)",
        f"  script {data['script_ms']:.1f}ms · style {data['style_ms']:.1f}ms · "
        f"layout {data['layout_ms']:.1f}ms in {data['layout_count']} passes · "
        f"paint {data['paint_ms']:.1f}ms",
    ]
    if data["long_tasks"]:
        lines.append("longest tasks:")
        for task in data["long_tasks"]:
            lines.append(f"  {task['ms']:>8.1f}ms  {task['name']}")
    else:
        lines.append("no task over 50ms — the main thread was never blocked for long")
    return "\n".join(lines)


def verdict(data: dict) -> int:
    """0 when nothing on the main thread ran long, 1 when a long task exists.

    The exit code is for a script: "did this trace block the main thread" is a
    yes/no, and 50ms is the number a person feels as jank.
    """
    return 1 if data["long_tasks"] else 0
