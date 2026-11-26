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
from .trace import KINDS, TraceError, summarise, load


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tracesum",
        description="Say who was busy: a Chrome trace, read on the command line.")
    parser.add_argument("trace", nargs="?", help="a trace JSON exported from the Performance panel")
    parser.add_argument("--top", type=int, default=10, metavar="N",
                        help="how many long tasks to list (default 10)")
    parser.add_argument("--kind", action="append", default=[], metavar="BUCKET=NAME[,NAME]",
                        help="add event names to a bucket (script, style, layout, paint)")
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
    if args.serve and not 0 <= args.port <= 65535:
        print("tracesum: --port must be between 0 and 65535 (0 picks a free one)",
              file=sys.stderr)
        return 2
    if args.long_ms <= 0:
        print("tracesum: --long-ms must be a positive number", file=sys.stderr)
        return 2
    kinds: dict[str, tuple[str, ...]] = {}
    for spec in args.kind:
        bucket, _, names = spec.partition("=")
        bucket = bucket.strip()
        wanted = tuple(name.strip() for name in names.split(",") if name.strip())
        if bucket not in KINDS or not wanted:
            print(f"tracesum: --kind wants BUCKET=NAME[,NAME] with BUCKET in "
                  f"{', '.join(KINDS)}, got {spec!r}", file=sys.stderr)
            return 2
        for name in wanted:
            for other, names_there in KINDS.items():
                if other != bucket and name in names_there:
                    # A name in two buckets gets counted twice; the overlap note
                    # then blames nesting, which is not what happened.
                    print(f"note: {name} is already counted in {other}; "
                          f"--kind {bucket}={name} counts it twice", file=sys.stderr)
        kinds[bucket] = kinds.get(bucket, ()) + wanted
    path = Path(args.trace)
    try:
        summary = summarise(load(path), long_ms=args.long_ms, kinds=kinds or None)
    except TraceError as error:
        if args.json:
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
        else:
            print(f"tracesum: {error}", file=sys.stderr)
        return 2
    data = build(summary, args.top, str(path), long_ms=args.long_ms)
    data["long_ms"] = args.long_ms
    # The page polls every few seconds but the trace is read once: say when, so a
    # re-exported file that changes nothing is not mistaken for live data.
    data["read_at"] = datetime.now().strftime("%H:%M:%S")
    if args.serve:
        from .server import serve
        try:
            serve(data, args.host, args.port)
        except (OSError, OverflowError) as error:
            print(f"tracesum: cannot listen on {args.host}:{args.port} — "
                  f"{error.strerror or error}. Pass --port to pick another.", file=sys.stderr)
            return 2
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data))
    return verdict(data)


if __name__ == "__main__":
    raise SystemExit(main())
