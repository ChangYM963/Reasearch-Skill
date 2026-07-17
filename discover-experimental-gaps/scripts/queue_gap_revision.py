#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import DEPENDENCY_MATRIX, GapError, queue_revision, read_json


def _optional(path: Path | None):
    return read_json(path) if path else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue a revision and apply fixed invalidation.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--change-type", required=True, choices=sorted(DEPENDENCY_MATRIX))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--claim", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--audit-spec", type=Path)
    parser.add_argument("--scope", type=Path)
    parser.add_argument(
        "--evidence-ref",
        action="append",
        default=[],
        help="Traceable evidence reference; repeat for multiple refs.",
    )
    parser.add_argument("--narrow", action="store_true")
    args = parser.parse_args()
    try:
        result = queue_revision(
            run_dir=args.run_dir,
            change_type=args.change_type,
            reason=args.reason,
            expected_revision=args.expected_revision,
            new_claim=_optional(args.claim),
            new_protocol=_optional(args.protocol),
            new_audit_spec=_optional(args.audit_spec),
            narrow=args.narrow,
            new_scope=_optional(args.scope),
            evidence_refs=args.evidence_ref,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
