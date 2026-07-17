#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import GapError, status_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Read run status without mutation.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = status_summary(args.run_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(
                f"{result['run_id']} r{result['manifest_revision']} | "
                f"{result['phase']} | {result['run_status']} | {result['decision']}"
            )
            for name, gate in result["gates"].items():
                print(f"- {name}: {gate['status']} ({gate['outcome'] or '-'})")
            for action in result["next_actions"]:
                print(f"next: {action}")
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
