#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import GapError, finalize_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically render validated Freeze JSON.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = finalize_run(args.run_dir, args.expected_revision, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
