#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaplib import (
    GapError, atomic_write_json, build_research_handoff, load_state,
    prepare_run, record_result, status_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an experimental-gap run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--search-cutoff")
    parser.add_argument("--adapter", choices=("ai-ml", "decision-policy"), default="ai-ml")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--await-research",
        action="store_true",
        help="Record and emit a standardized Venue Map Deep Research handoff.",
    )
    parser.add_argument("--handoff-output", type=Path)
    args = parser.parse_args()
    try:
        prepare_run(
            args.run_dir, args.venue, args.topic, args.years,
            args.search_cutoff, args.adapter, args.run_id,
        )
        if args.await_research:
            handoff = build_research_handoff(load_state(args.run_dir), "venue_map")
            record_result(args.run_dir, "research_handoff", handoff, 0)
            output = (
                args.handoff_output
                or args.run_dir / "outputs" / "venue-map-research-handoff.json"
            )
            atomic_write_json(output, handoff)
        print(json.dumps(status_summary(args.run_dir), ensure_ascii=False, indent=2))
        return 0
    except GapError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
