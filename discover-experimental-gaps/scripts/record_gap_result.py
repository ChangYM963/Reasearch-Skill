#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import GapError, RECORD_KINDS, read_json, record_result


def main() -> int:
    parser = argparse.ArgumentParser(description="CAS-ingest one immutable run artifact.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=sorted(RECORD_KINDS))
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True, type=int)
    args = parser.parse_args()
    try:
        result = record_result(
            args.run_dir, args.kind, read_json(args.input), args.expected_revision
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
