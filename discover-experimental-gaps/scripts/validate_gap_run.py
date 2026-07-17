#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import (
    GapError, atomic_write_json, commit_validation, derive_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive or transactionally commit gate QA.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()
    try:
        if args.commit:
            if args.expected_revision is None:
                raise GapError(
                    "EXPECTED_REVISION_REQUIRED",
                    "--commit requires --expected-revision.",
                )
            result = commit_validation(args.run_dir, args.expected_revision)
        else:
            result = derive_validation(args.run_dir)
            if args.output:
                atomic_write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
