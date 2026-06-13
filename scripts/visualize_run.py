#!/usr/bin/env python
"""Export a chaos-librarian run directory to a self-contained HTML timeline.

Usage:
    uv run python scripts/visualize_run.py <run-dir> [-o OUTPUT]

The logic lives in ``chaos_librarian.visualize``; this is a thin entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.visualize import build_payload, render_html


def main(argv: list[str] | None = None) -> int:
    """Parse args, build the payload, render HTML. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="scenario run directory")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output HTML path (default: <run-dir>/visualize.html)",
    )
    args = parser.parse_args(argv)

    if not args.run_dir.is_dir():
        print(f"error: not a directory: {args.run_dir}", file=sys.stderr)
        return 1

    output = args.output or args.run_dir / "visualize.html"
    try:
        payload = build_payload(args.run_dir)
        html = render_html(payload)
    except ChaosLibrarianError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output.write_text(html, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
