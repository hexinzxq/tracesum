"""`tracesum` — read a Chrome performance trace without opening DevTools.

Exit codes: 0 nothing long on the main thread, 1 a long task (jank), 2 unreadable.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .report import build, render, verdict
from .trace import TraceError, summarise, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tracesum",
        description="Say who was busy: a Chrome trace, read on the command line.")
    parser.add_argument("trace", nargs="?", help="a trace JSON exported from the Performance panel")
    parser.add_argument("--top", type=int, default=10, metavar="N",
                        help="how many long tasks to list (default 10)")
    parser.add_argument("--long-ms", type=float, default=50.0, metavar="MS",
                        help="what counts as a long task (default 50, the Web Vitals line)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--serve", action="store_true",
                        help="serve the same summary as a local page")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if not args.trace:
        print("tracesum: give me a trace file — export one from DevTools → Performance → Save profile",
              file=sys.stderr)
        return 2
    if args.top <= 0:
        print("tracesum: --top must be a positive number", file=sys.stderr)
        return 2
    if args.long_ms <= 0:
        print("tracesum: --long-ms must be a positive number", file=sys.stderr)
        return 2
    path = Path(args.trace)
    try:
        summary = summarise(load(path), long_ms=args.long_ms)
    except TraceError as error:
        if args.json:
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
        else:
            print(f"tracesum: {error}", file=sys.stderr)
        return 2
    data = build(summary, args.top, str(path))
    data["long_ms"] = args.long_ms
    # The page polls every few seconds but the trace is read once: say when, so a
    # re-exported file that changes nothing is not mistaken for live data.
    data["read_at"] = datetime.now().strftime("%H:%M:%S")
    if args.serve:
        from .server import serve
        try:
            serve(data, args.host, args.port)
        except OSError as error:
            print(f"tracesum: cannot listen on {args.host}:{args.port} — "
                  f"{error.strerror or error}. Pass --port to pick another.", file=sys.stderr)
            return 2
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))
    return verdict(data)


if __name__ == "__main__":
    raise SystemExit(main())
