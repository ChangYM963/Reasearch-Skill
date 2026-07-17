#!/usr/bin/env python3
"""Deterministic state and evidence utilities for discover-experimental-gaps."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import time
import unicodedata
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

SKILL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
FINGERPRINT_VERSION = "1.0.0"
VALIDATOR_VERSION = "1.0.0"

PHASES = ("intake", "venue_map", "discovery", "falsification", "smoke",
          "final_audit", "freeze", "closed")
RUN_STATUSES = ("ready", "active", "awaiting_user", "awaiting_research",
                "insufficient_evidence", "blocked", "complete")
DECISIONS = ("undecided", "GO", "STOP")
GATE_NAMES = ("venue_map", "falsification", "smoke",
              "final_audit", "freeze_validation")
GATE_STATUSES = ("pending", "awaiting_report", "validating",
                 "review_required", "passed", "failed", "stale")
ARTIFACT_STATUSES = ("current", "review_required", "stale", "superseded")

DEPENDENCY_MATRIX = {
    "venue_scope":         ("I", "I", "I", "I", "I"),
    "claim_semantics":     ("P", "I", "I", "I", "I"),
    "baseline":            ("P", "R", "I", "I", "I"),
    "endpoint_sesoi":      ("P", "R", "I", "I", "I"),
    "implementation":      ("P", "P", "I", "R", "I"),
    "target_distribution": ("P", "I", "I", "I", "I"),
    "final_audit_cutoff":  ("P", "P", "P", "I", "I"),
    "global_cutoff":       ("P", "R", "P", "I", "I"),
    "closest_nonmaterial": ("P", "R", "P", "I", "I"),
    "formatting":          ("P", "P", "P", "P", "I"),
}
MATRIX_GATES = GATE_NAMES
SET_LIKE_KEYS = {
    "excluded_claims", "coverage_axes", "channels", "included_source_ids",
    "unresolved_lead_ids", "synonyms", "comparison_set", "slices",
    "data_scope", "network_allowlist", "filesystem_write_roots",
    "comparator_class", "baselines", "metrics", "rings", "queries",
    "query_protocol",
}
IDENTIFIER_KEYS = ("doi", "arxiv", "url", "repository")


class GapError(RuntimeError):
    """Stable, user-facing error with a machine code."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _decimal_string(value: Decimal) -> str:
    if not value.is_finite():
        raise GapError("NON_FINITE_NUMBER", "NaN and infinity are forbidden.")
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in ("", "-0") else rendered


def _normalise(value: Any, parent_key: str | None = None) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GapError("NON_FINITE_NUMBER", "NaN and infinity are forbidden.")
        rendered = _decimal_string(Decimal(str(value)))
        return int(rendered) if "." not in rendered else float(rendered)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _normalise(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        items = [_normalise(item) for item in value]
        if parent_key in SET_LIKE_KEYS:
            items.sort(key=canonical_json)
        return items
    raise GapError("NON_JSON_VALUE", f"Unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalise(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_data(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise GapError("MISSING_FILE", f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GapError("INVALID_JSON", f"Invalid JSON in {path}: {exc}") from exc


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, canonical_json(value) + "\n")


def _commit_run_files(
    paths: dict[str, Path],
    previous_state: dict[str, Any],
    previous_ledger: dict[str, Any],
    previous_candidates: dict[str, Any],
    next_state: dict[str, Any],
    next_ledger: dict[str, Any],
    next_candidates: dict[str, Any],
) -> None:
    """Best-effort rollback keeps the last manifest bundle valid on write failure.

    This protects against synchronous exceptions during a multi-file commit. It is
    deliberately not advertised as power-loss atomicity; crash-consistent journals
    remain a post-v1 concern.
    """
    writes: list[tuple[Path, Any, Any]] = []
    if next_ledger != previous_ledger:
        writes.append((paths["ledger"], next_ledger, previous_ledger))
    if next_candidates != previous_candidates:
        writes.append((paths["candidates"], next_candidates, previous_candidates))
    writes.append((paths["state"], next_state, previous_state))
    attempted: list[tuple[Path, Any]] = []
    try:
        for path, value, previous in writes:
            attempted.append((path, previous))
            atomic_write_json(path, value)
    except Exception as exc:
        rollback_errors: list[str] = []
        for path, previous in reversed(attempted):
            try:
                atomic_write_json(path, previous)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic I/O
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            raise GapError(
                "TRANSACTION_ROLLBACK_FAILED",
                "A write failed and the previous run bundle could not be fully restored.",
                rollback_errors,
            ) from exc
        raise


@contextmanager
def exclusive_lock(lock_path: Path, timeout: float = 8.0):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {utc_now()}".encode("utf-8"))
            os.fsync(descriptor)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise GapError("LOCK_TIMEOUT", f"Could not acquire {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def ensure_schema_major(version: str) -> None:
    try:
        major = int(str(version).split(".", 1)[0])
    except (ValueError, TypeError) as exc:
        raise GapError("SCHEMA_INCOMPATIBLE", f"Invalid schema version: {version}") from exc
    if major != int(SCHEMA_VERSION.split(".", 1)[0]):
        raise GapError(
            "SCHEMA_INCOMPATIBLE",
            f"Unsupported schema major {major}; runtime supports {SCHEMA_VERSION}.",
        )


def _json_type_ok(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise GapError("SCHEMA_UNSUPPORTED", f"Only local schema refs are supported: {ref}")
    node: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[token]
    if not isinstance(node, dict):
        raise GapError("SCHEMA_UNSUPPORTED", f"Schema ref is not an object: {ref}")
    return node


def _schema_errors(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$"
) -> list[str]:
    if "$ref" in schema:
        return _schema_errors(value, _resolve_ref(root, schema["$ref"]), root, path)
    errors: list[str] = []
    if "if" in schema:
        condition_matches = not _schema_errors(value, schema["if"], root, path)
        if condition_matches and "then" in schema:
            errors.extend(_schema_errors(value, schema["then"], root, path))
        if not condition_matches and "else" in schema:
            errors.extend(_schema_errors(value, schema["else"], root, path))
    for branch in schema.get("allOf", []):
        errors.extend(_schema_errors(value, branch, root, path))
    if "anyOf" in schema:
        branch_errors = [
            _schema_errors(value, branch, root, path) for branch in schema["anyOf"]
        ]
        if all(branch for branch in branch_errors):
            errors.append(f"{path}: does not match anyOf")
    if "oneOf" in schema:
        matches = sum(
            not _schema_errors(value, branch, root, path)
            for branch in schema["oneOf"]
        )
        if matches != 1:
            errors.append(f"{path}: must match exactly one oneOf branch")
    if "not" in schema and not _schema_errors(value, schema["not"], root, path):
        errors.append(f"{path}: matches forbidden not schema")
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_json_type_ok(value, item) for item in expected):
            return [f"{path}: expected one of {expected}"]
    elif isinstance(expected, str) and not _json_type_ok(value, expected):
        return [f"{path}: expected {expected}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not in enum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_schema_errors(item, properties[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: additional property forbidden")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    _schema_errors(item, schema["additionalProperties"], root, f"{path}.{key}")
                )
        if isinstance(schema.get("propertyNames"), dict):
            for key in value:
                errors.extend(
                    _schema_errors(key, schema["propertyNames"], root, f"{path}.<key>")
                )
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: fewer than minProperties")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems")
        if schema.get("uniqueItems"):
            serialised = [canonical_json(item) for item in value]
            if len(serialised) != len(set(serialised)):
                errors.append(f"{path}: items must be unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, schema["items"], root, f"{path}[{index}]"))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: does not match pattern")
        if schema.get("format") == "date":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                errors.append(f"{path}: invalid date")
        if schema.get("format") == "date-time":
            try:
                dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: invalid date-time")
        if schema.get("format") == "uri" and not re.match(
            r"^[A-Za-z][A-Za-z0-9+.-]*:", value
        ):
            errors.append(f"{path}: invalid URI")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: not below exclusiveMaximum")
    return errors


def schema_path(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / "schemas" / name


def validate_schema(value: Any, name: str) -> None:
    schema = read_json(schema_path(name))
    errors = _schema_errors(value, schema, schema)
    if errors:
        raise GapError("SCHEMA_VALIDATION_FAILED", f"{name} validation failed.", errors)


def _gate_record() -> dict[str, Any]:
    return {
        "status": "pending",
        "outcome": None,
        "subject_refs": [],
        "artifact_ids": [],
        "valid_for": {
            "claim_fingerprint": None,
            "protocol_fingerprint": None,
            "audit_fingerprint": None,
            "ledger_version": 0,
        },
        "validated_at": None,
        "validator_version": None,
        "reason_codes": [],
        "unresolved_lead_ids": [],
        "invalidated_by_event_id": None,
    }


def _safe_window_start(cutoff: dt.date, years: int) -> dt.date:
    try:
        return cutoff.replace(year=cutoff.year - years)
    except ValueError:
        return cutoff.replace(year=cutoff.year - years, day=28)


def new_run_state(
    run_id: str, venue: str, topic: str, years: int, cutoff: str, adapter: str
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "run_id": run_id,
        "created_at": now,
        "updated_at": now,
        "manifest_revision": 0,
        "ledger_version": 0,
        "phase": "venue_map",
        "run_status": "ready",
        "decision": "undecided",
        "independence_level": "sequential_unblinded",
        "scope": {
            "venue": venue,
            "topic": topic,
            "adapter": adapter,
            "date_window": {
                "from": _safe_window_start(
                    dt.date.fromisoformat(cutoff), years
                ).isoformat(),
                "to": cutoff,
            },
        },
        "governance": {"narrow_limit": 2, "narrow_count": 0},
        "claim": {"current_version": 0, "current": None, "history": []},
        "fingerprints": {"claim": None, "protocol": None, "audit": None},
        "gates": {name: _gate_record() for name in GATE_NAMES},
        "artifacts": {},
        "verdict_history": [],
        "blockers": [],
        "events": [],
    }


def default_ledger(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "ledger_version": 0,
        "search_runs": {},
        "sources": {},
        "evidence": {},
        "unresolved_leads": {},
        "lead_history": [],
    }


def default_candidates(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "stage": None,
        "candidates": [],
        "rejected_candidates": [],
        "primary_candidate_id": None,
        "backup_candidate_id": None,
        "board_status": "empty",
    }


def run_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "state": run_dir / "gap-run.json",
        "ledger": run_dir / "evidence-ledger.json",
        "candidates": run_dir / "candidates.json",
        "lock": run_dir / ".locks" / "gap-run.lock",
        "artifacts": run_dir / "artifacts",
        "qa": run_dir / "qa",
        "outputs": run_dir / "outputs",
    }


def prepare_run(
    run_dir: Path,
    venue: str,
    topic: str,
    years: int = 5,
    cutoff: str | None = None,
    adapter: str = "ai-ml",
    run_id: str | None = None,
) -> dict[str, Any]:
    if years < 3 or years > 5:
        raise GapError("INVALID_WINDOW", "The venue map window must be 3–5 years.")
    if adapter not in ("ai-ml", "decision-policy"):
        raise GapError("INVALID_ADAPTER", "adapter must be ai-ml or decision-policy.")
    cutoff = cutoff or utc_today().isoformat()
    try:
        parsed_cutoff = dt.date.fromisoformat(cutoff)
    except ValueError as exc:
        raise GapError("INVALID_DATE", "cutoff must use YYYY-MM-DD.") from exc
    if parsed_cutoff > utc_today():
        raise GapError(
            "FUTURE_CUTOFF_FORBIDDEN",
            "Search cutoff cannot be later than the current UTC date.",
        )
    paths = run_paths(run_dir)
    if paths["state"].exists():
        raise GapError("RUN_EXISTS", f"Run already exists: {run_dir}")
    run_id = run_id or f"gap-{dt.datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8]}"
    state = new_run_state(run_id, venue, topic, years, cutoff, adapter)
    validate_schema(state, "run-state.schema.json")
    for name in ("artifacts", "qa", "outputs"):
        paths[name].mkdir(parents=True, exist_ok=True)
    paths["lock"].parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["ledger"], default_ledger(run_id))
    atomic_write_json(paths["candidates"], default_candidates(run_id))
    atomic_write_json(paths["state"], state)
    return state


def load_state(run_dir: Path) -> dict[str, Any]:
    state = read_json(run_paths(run_dir)["state"])
    ensure_schema_major(state.get("schema_version"))
    return state


CLAIM_KEYS = (
    "population", "data_regime", "method", "intervention",
    "comparator_class", "outcome", "estimand", "quantifier",
    "mechanism", "decision_consequence", "excluded_claims", "sesoi",
)
PROTOCOL_KEYS = (
    "data_version", "split", "baselines", "strongest_baseline",
    "metrics", "primary_endpoint", "statistical_route", "budget",
    "code_version", "decision_rule",
)
AUDIT_KEYS = ("cutoff_date", "rings", "synonyms", "query_protocol")


def claim_fingerprint(claim: dict[str, Any]) -> str:
    missing = [key for key in CLAIM_KEYS if key not in claim]
    if missing:
        raise GapError("CLAIM_INCOMPLETE", "Claim fingerprint fields are missing.", missing)
    return sha256_data({
        "fingerprint_version": FINGERPRINT_VERSION,
        "kind": "claim",
        "payload": {key: claim[key] for key in CLAIM_KEYS},
    })


def protocol_fingerprint(claim_fingerprint_value: str, protocol: dict[str, Any]) -> str:
    missing = [key for key in PROTOCOL_KEYS if key not in protocol]
    if missing:
        raise GapError(
            "PROTOCOL_INCOMPLETE", "Protocol fingerprint fields are missing.", missing
        )
    return sha256_data({
        "fingerprint_version": FINGERPRINT_VERSION,
        "kind": "protocol",
        "claim_fingerprint": claim_fingerprint_value,
        "payload": {key: protocol[key] for key in PROTOCOL_KEYS},
    })


def audit_fingerprint(claim_fingerprint_value: str, audit: dict[str, Any]) -> str:
    missing = [key for key in AUDIT_KEYS if key not in audit]
    if missing:
        raise GapError("AUDIT_INCOMPLETE", "Audit fingerprint fields are missing.", missing)
    return sha256_data({
        "fingerprint_version": FINGERPRINT_VERSION,
        "kind": "audit",
        "claim_fingerprint": claim_fingerprint_value,
        "payload": {key: audit[key] for key in AUDIT_KEYS},
    })


def _event(state: dict[str, Any], kind: str, payload: dict[str, Any]) -> str:
    event_id = f"evt-{state['manifest_revision'] + 1}-{uuid.uuid4().hex[:8]}"
    state["events"].append({
        "event_id": event_id,
        "kind": kind,
        "recorded_at": utc_now(),
        "base_revision": state["manifest_revision"],
        "payload": payload,
    })
    return event_id


def _current_artifacts(
    state: dict[str, Any], kind: str | None = None
) -> list[dict[str, Any]]:
    records = [
        record for record in state["artifacts"].values()
        if record["status"] == "current" and (kind is None or record["kind"] == kind)
    ]
    return sorted(records, key=lambda item: item["sequence"])


def _artifact_payload(run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    root = run_dir.resolve()
    path = (run_dir / record["path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GapError(
            "ARTIFACT_PATH_ESCAPE",
            f"Artifact path escapes the run directory: {record['path']}",
        ) from exc
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except FileNotFoundError as exc:
        raise GapError("MISSING_FILE", f"Required artifact is missing: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GapError("INVALID_ARTIFACT_JSON", f"Artifact is not canonical UTF-8 JSON: {path}") from exc
    canonical_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    if raw != canonical_bytes:
        raise GapError(
            "ARTIFACT_BYTES_CHANGED",
            f"Artifact bytes are not the canonical bytes originally written: {record['artifact_id']}",
        )
    if sha256_data(payload) != record.get("sha256"):
        raise GapError(
            "ARTIFACT_HASH_MISMATCH",
            f"Artifact content no longer matches its manifest hash: {record['artifact_id']}",
        )
    if not isinstance(payload, dict):
        raise GapError("ARTIFACT_TYPE_INVALID", "Runtime artifacts must contain JSON objects.")
    return payload


def _latest_payload(
    run_dir: Path, state: dict[str, Any], kind: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    records = _current_artifacts(state, kind)
    if not records:
        return None
    record = records[-1]
    return record, _artifact_payload(run_dir, record)


def _write_artifact(
    run_dir: Path,
    state: dict[str, Any],
    kind: str,
    payload: dict[str, Any],
    subject_refs: Iterable[str] = (),
) -> tuple[dict[str, Any], bool]:
    digest = sha256_data(payload)
    for record in state["artifacts"].values():
        if record["kind"] == kind and record["sha256"] == digest:
            return record, False
    artifact_id = str(payload.get("artifact_id") or f"{kind}-{digest[:16]}")
    if artifact_id in state["artifacts"]:
        raise GapError("ARTIFACT_ID_CONFLICT", f"Artifact ID already exists: {artifact_id}")
    relative = Path("artifacts") / f"{artifact_id}.json"
    atomic_write_json(run_dir / relative, payload)
    record = {
        "artifact_id": artifact_id,
        "kind": kind,
        "path": relative.as_posix(),
        "sha256": digest,
        "input_hashes": {
            "claim": state["fingerprints"]["claim"],
            "protocol": state["fingerprints"]["protocol"],
            "audit": state["fingerprints"]["audit"],
        },
        "subject_refs": sorted(set(subject_refs)),
        "status": "current",
        "sequence": len(state["artifacts"]) + 1,
        "recorded_at": utc_now(),
    }
    state["artifacts"][artifact_id] = record
    return record, True


def _source_has_identifier(source: dict[str, Any]) -> bool:
    identifiers = source.get("identifiers", {})
    if not isinstance(identifiers, dict):
        return False
    doi = str(identifiers.get("doi", "")).strip()
    arxiv = str(identifiers.get("arxiv", "")).strip()
    url = str(identifiers.get("url", "")).strip()
    repository = str(identifiers.get("repository", "")).strip()
    return any((
        bool(re.match(r"^10\.\d{4,9}/\S+$", doi, re.IGNORECASE)),
        bool(re.match(r"^(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?$", arxiv)),
        bool(re.match(r"^https?://[^/\s]+(?:/.*)?$", url, re.IGNORECASE)),
        bool(re.match(r"^https?://[^/\s]+/.+", repository, re.IGNORECASE)),
    ))


def report_stage(report: dict[str, Any]) -> str:
    stages = {item.get("stage") for item in report.get("search_runs", [])}
    if len(stages) != 1:
        raise GapError("REPORT_STAGE_MIXED", "One sidecar must contain exactly one stage.")
    return str(next(iter(stages)))


def audit_spec_from_report(
    report: dict[str, Any], synonyms: Iterable[str] = ()
) -> dict[str, Any]:
    runs = report["search_runs"]
    cutoff = max(str(item["date_window"]["through"]) for item in runs)
    return {
        "cutoff_date": cutoff,
        "rings": sorted({item["ring"] for item in runs}),
        "synonyms": sorted(set(synonyms)),
        "query_protocol": [
            {
                "ring": item["ring"],
                "target_ref": item["target_ref"],
                "queries": item["queries"],
                "channels": item["channels"],
                "inclusion_criteria": item["inclusion_criteria"],
                "exclusion_criteria": item["exclusion_criteria"],
                "coverage_axes": item["coverage_axes"],
                "date_window": item["date_window"],
            }
            for item in sorted(runs, key=lambda entry: entry["id"])
        ],
    }


def _audit_spec_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in AUDIT_KEYS}


def _validate_audit_protocol(
    state: dict[str, Any], payload: dict[str, Any]
) -> str:
    required = {
        "schema_version", "audit_protocol_id", "claim_fingerprint",
        "cutoff_date", "rings", "synonyms", "query_protocol",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise GapError(
            "AUDIT_PROTOCOL_INCOMPLETE",
            "Final Audit protocol is missing required fields.",
            missing,
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise GapError("SCHEMA_INCOMPATIBLE", "Audit protocol schema is incompatible.")
    if payload.get("claim_fingerprint") != state["fingerprints"]["claim"]:
        raise GapError(
            "AUDIT_PROTOCOL_CLAIM_STALE",
            "Final Audit protocol is not bound to the current claim.",
        )
    rings = payload.get("rings")
    required_rings = {"target_venue", "cross_venue", "citation_graph"}
    if not isinstance(rings, list) or set(rings) != required_rings:
        raise GapError(
            "AUDIT_PROTOCOL_RINGS",
            "Final Audit protocol must freeze all three search rings.",
        )
    synonyms = payload.get("synonyms")
    if (
        not isinstance(synonyms, list)
        or not synonyms
        or any(not isinstance(term, str) or not term.strip() for term in synonyms)
    ):
        raise GapError(
            "AUDIT_PROTOCOL_SYNONYMS",
            "Final Audit protocol must explicitly freeze non-empty synonyms.",
        )
    try:
        cutoff = dt.date.fromisoformat(str(payload.get("cutoff_date")))
        scope_cutoff = dt.date.fromisoformat(state["scope"]["date_window"]["to"])
    except (TypeError, ValueError) as exc:
        raise GapError(
            "AUDIT_PROTOCOL_DATE",
            "Final Audit cutoff must be a valid YYYY-MM-DD date.",
        ) from exc
    if cutoff < scope_cutoff:
        raise GapError(
            "AUDIT_PROTOCOL_STALE",
            "Final Audit cutoff cannot precede the current run cutoff.",
        )
    if cutoff > utc_today():
        raise GapError(
            "AUDIT_PROTOCOL_FUTURE",
            "Final Audit cutoff cannot be later than the current UTC date.",
        )
    query_protocol = payload.get("query_protocol")
    if not isinstance(query_protocol, list) or len(query_protocol) != 3:
        raise GapError(
            "AUDIT_PROTOCOL_QUERY",
            "Final Audit protocol must freeze one query block per search ring.",
        )
    seen: set[str] = set()
    required_fields = {
        "ring", "target_ref", "queries", "channels", "inclusion_criteria",
        "exclusion_criteria", "coverage_axes", "date_window",
    }
    for entry in query_protocol:
        if not isinstance(entry, dict) or required_fields - set(entry):
            raise GapError(
                "AUDIT_PROTOCOL_QUERY",
                "Each Final Audit query block is structurally incomplete.",
            )
        ring = entry.get("ring")
        if ring not in required_rings or ring in seen:
            raise GapError(
                "AUDIT_PROTOCOL_QUERY",
                "Final Audit query blocks must name each ring exactly once.",
            )
        seen.add(str(ring))
        for key in (
            "queries", "channels", "inclusion_criteria",
            "exclusion_criteria", "coverage_axes",
        ):
            value = entry.get(key)
            if not isinstance(value, list) or not value:
                raise GapError(
                    "AUDIT_PROTOCOL_QUERY",
                    f"Final Audit query block has empty {key}.",
                )
        if not str(entry.get("target_ref", "")).strip():
            raise GapError("AUDIT_PROTOCOL_QUERY", "Final Audit target_ref is empty.")
        window = entry.get("date_window")
        try:
            start = dt.date.fromisoformat(str(window["from"]))
            through = dt.date.fromisoformat(str(window["through"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GapError(
                "AUDIT_PROTOCOL_DATE",
                "Final Audit query windows must contain valid from/through dates.",
            ) from exc
        if start > through or through < cutoff:
            raise GapError(
                "AUDIT_PROTOCOL_STALE",
                "Every Final Audit ring must search through the frozen cutoff.",
            )
        if through > utc_today():
            raise GapError(
                "AUDIT_PROTOCOL_FUTURE",
                "Final Audit query windows cannot extend beyond the current UTC date.",
            )
    return audit_fingerprint(state["fingerprints"]["claim"], _audit_spec_payload(payload))


def _current_audit_protocol(
    run_dir: Path, state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    return _latest_payload(run_dir, state, "audit_protocol")


def research_report_checks(
    report: dict[str, Any], state: dict[str, Any], run_dir: Path | None = None
) -> dict[str, Any]:
    validate_schema(report, "research-report.schema.json")
    errors: list[str] = []
    stage = report_stage(report)
    candidate_ids: set[str] = set()
    if run_dir is not None and run_paths(run_dir)["candidates"].is_file():
        candidate_state = read_json(run_paths(run_dir)["candidates"])
        candidate_ids = {
            str(item["candidate_id"])
            for item in candidate_state.get("candidates", [])
            if item.get("candidate_id")
        }
    entity_ids = [
        str(item.get("id"))
        for key in ("search_runs", "sources", "evidence", "unresolved_leads")
        for item in report.get(key, [])
    ]
    if len(entity_ids) != len(set(entity_ids)):
        errors.append("ENTITY_ID_DUPLICATE")
    source_ids = {source.get("id") for source in report.get("sources", [])}
    run_ids = {item.get("id") for item in report.get("search_runs", [])}
    evidence_ids = {item.get("id") for item in report.get("evidence", [])}
    lead_ids = {lead.get("id") for lead in report.get("unresolved_leads", [])}
    for source in report.get("sources", []):
        if not _source_has_identifier(source):
            errors.append(f"SOURCE_IDENTIFIER_INVALID:{source.get('id')}")
        if not source.get("identity_attestation"):
            errors.append(f"IDENTITY_ATTESTATION_MISSING:{source.get('id')}")
    material_without_locator: list[str] = []
    for evidence in report.get("evidence", []):
        if evidence.get("search_run_id") not in run_ids:
            errors.append(f"EVIDENCE_SEARCH_FK:{evidence.get('id')}")
        if evidence.get("source_id") not in source_ids:
            errors.append(f"EVIDENCE_SOURCE_FK:{evidence.get('id')}")
        if evidence.get("materiality") == "material" and not evidence.get("locator"):
            material_without_locator.append(str(evidence.get("id")))
        if not evidence.get("content_attestation"):
            errors.append(f"CONTENT_ATTESTATION_MISSING:{evidence.get('id')}")
        subject = evidence.get("subject", {})
        subject_kind = subject.get("kind")
        subject_ref = subject.get("ref")
        if stage == "venue_map":
            if subject_kind != "scope":
                errors.append(f"EVIDENCE_SCOPE_SUBJECT_KIND:{evidence.get('id')}")
            elif subject_ref != state["run_id"]:
                errors.append(f"EVIDENCE_SCOPE_SUBJECT_FK:{evidence.get('id')}")
        else:
            if (
                subject_kind == "claim"
                and subject_ref != state["fingerprints"]["claim"]
            ):
                errors.append(f"EVIDENCE_CLAIM_SUBJECT_FK:{evidence.get('id')}")
            elif subject_kind == "candidate" and subject_ref not in candidate_ids:
                errors.append(f"EVIDENCE_CANDIDATE_SUBJECT_FK:{evidence.get('id')}")
            elif subject_kind not in ("claim", "candidate"):
                errors.append(f"EVIDENCE_SUBJECT_KIND:{evidence.get('id')}")
    if material_without_locator:
        errors.append("MATERIAL_LOCATOR_MISSING:" + ",".join(material_without_locator))
    rings = {run.get("ring") for run in report.get("search_runs", [])}
    required_rings = {"target_venue", "cross_venue", "citation_graph"}
    if not required_rings.issubset(rings):
        errors.append("REQUIRED_RINGS_MISSING")
    axes = {
        axis for run in report.get("search_runs", [])
        for axis in run.get("coverage_axes", [])
    }
    required_axes = {
        "problem", "population_or_data", "method_or_intervention",
        "comparator", "outcome_or_estimand", "recency",
    }
    if state["scope"].get("adapter") == "decision-policy":
        required_axes.add("decision_consequence")
    claim = state["claim"].get("current") or {}
    if str(claim.get("mechanism", "")).strip().lower() not in (
        "", "none", "not applicable", "n/a"
    ):
        required_axes.add("mechanism")
    if not required_axes.issubset(axes):
        errors.append("REQUIRED_COVERAGE_AXES_MISSING")
    audit_protocol_item = (
        _current_audit_protocol(run_dir, state)
        if stage == "final_audit" and run_dir is not None
        else None
    )
    audit_protocol = audit_protocol_item[1] if audit_protocol_item else None
    if stage == "final_audit" and audit_protocol is None:
        errors.append("AUDIT_PROTOCOL_MISSING")
    allowed_targets = {
        str(state["scope"]["venue"]),
        str(state["fingerprints"]["claim"] or ""),
        *candidate_ids,
    }
    try:
        scope_start = dt.date.fromisoformat(state["scope"]["date_window"]["from"])
        scope_cutoff = dt.date.fromisoformat(state["scope"]["date_window"]["to"])
    except (KeyError, TypeError, ValueError):
        scope_start = dt.date.min
        scope_cutoff = dt.date.max
    current_utc_date = utc_today()
    for run in report.get("search_runs", []):
        if run.get("base_ledger_version") != state["ledger_version"]:
            errors.append(f"STALE_LEDGER_VERSION:{run.get('id')}")
        if run.get("research_mode") != "deep_research":
            errors.append(f"DEEP_RESEARCH_MODE_REQUIRED:{run.get('id')}")
        if stage != "venue_map" and run.get("claim_fingerprint") != state["fingerprints"]["claim"]:
            errors.append(f"STALE_CLAIM_FINGERPRINT:{run.get('id')}")
        if not run.get("queries"):
            errors.append(f"EMPTY_QUERIES:{run.get('id')}")
        if run.get("target_ref") not in allowed_targets:
            errors.append(f"SEARCH_TARGET_FK:{run.get('id')}")
        included = set(run.get("included_source_ids", []))
        if not included.issubset(source_ids):
            errors.append(f"SEARCH_SOURCE_FK:{run.get('id')}")
        excluded = {
            item.get("source_id") for item in run.get("excluded_sources", [])
        }
        if not excluded.issubset(source_ids):
            errors.append(f"EXCLUDED_SOURCE_FK:{run.get('id')}")
        if included.intersection(excluded):
            errors.append(f"SEARCH_SOURCE_INCLUDED_AND_EXCLUDED:{run.get('id')}")
        if not set(run.get("unresolved_lead_ids", [])).issubset(lead_ids):
            errors.append(f"SEARCH_LEAD_FK:{run.get('id')}")
        window = run.get("date_window", {})
        try:
            window_start = dt.date.fromisoformat(str(window["from"]))
            window_through = dt.date.fromisoformat(str(window["through"]))
            executed_at = dt.datetime.fromisoformat(
                str(run.get("executed_at")).replace("Z", "+00:00")
            )
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=dt.timezone.utc)
            executed = executed_at.astimezone(dt.timezone.utc).date()
            if window_start > window_through:
                errors.append(f"DATE_WINDOW_REVERSED:{run.get('id')}")
            if window_through < scope_cutoff:
                errors.append(f"SEARCH_CUTOFF_STALE:{run.get('id')}")
            if window_through > current_utc_date:
                errors.append(f"SEARCH_CUTOFF_FUTURE:{run.get('id')}")
            if stage == "venue_map" and window_start > scope_start:
                errors.append(f"VENUE_WINDOW_INCOMPLETE:{run.get('id')}")
            if executed < window_through:
                errors.append(f"SEARCH_EXECUTED_BEFORE_CUTOFF:{run.get('id')}")
            if executed > current_utc_date:
                errors.append(f"SEARCH_EXECUTED_IN_FUTURE:{run.get('id')}")
            if audit_protocol is not None:
                audit_cutoff = dt.date.fromisoformat(audit_protocol["cutoff_date"])
                if window_through < audit_cutoff:
                    errors.append(f"FINAL_AUDIT_RING_STALE:{run.get('id')}")
        except (KeyError, TypeError, ValueError):
            errors.append(f"SEARCH_DATE_INVALID:{run.get('id')}")
        raw_path = run.get("raw_report", {}).get("path")
        raw_hash = run.get("raw_report", {}).get("sha256")
        if not raw_path or not raw_hash:
            errors.append(f"RAW_REPORT_REFERENCE_MISSING:{run.get('id')}")
        elif run_dir is not None:
            raw_file = Path(raw_path)
            if raw_file.is_absolute():
                errors.append(f"RAW_REPORT_PATH_ABSOLUTE:{run.get('id')}")
                continue
            raw_file = (run_dir / raw_file).resolve()
            try:
                raw_file.relative_to(run_dir.resolve())
            except ValueError:
                errors.append(f"RAW_REPORT_PATH_ESCAPE:{run.get('id')}")
                continue
            if not raw_file.is_file():
                errors.append(f"RAW_REPORT_MISSING:{run.get('id')}")
            elif sha256_file(raw_file) != raw_hash:
                errors.append(f"RAW_REPORT_HASH_MISMATCH:{run.get('id')}")
    for lead in report.get("unresolved_leads", []):
        if lead.get("search_run_id") not in run_ids:
            errors.append(f"LEAD_SEARCH_FK:{lead.get('id')}")
        if not set(lead.get("resolution_evidence_ids", [])).issubset(evidence_ids):
            errors.append(f"LEAD_EVIDENCE_FK:{lead.get('id')}")
        if lead.get("status") in ("resolved", "dismissed") and not lead.get(
            "resolution_evidence_ids"
        ):
            errors.append(f"LEAD_RESOLUTION_EVIDENCE_MISSING:{lead.get('id')}")
    if stage == "final_audit" and audit_protocol is not None:
        expected = state["fingerprints"]["audit"]
        supplied = {item.get("audit_fingerprint") for item in report["search_runs"]}
        derived = audit_fingerprint(
            state["fingerprints"]["claim"],
            audit_spec_from_report(report, audit_protocol["synonyms"]),
        )
        if expected is None or supplied != {expected} or derived != expected:
            errors.append("AUDIT_FINGERPRINT_STALE")
    critical_open = [
        lead["id"] for lead in report.get("unresolved_leads", [])
        if lead.get("severity") == "critical" and lead.get("status") == "open"
    ]
    error_set = set(errors)
    def clear_of(*prefixes: str) -> bool:
        return not any(
            any(error.startswith(prefix) for prefix in prefixes)
            for error in error_set
        )
    return {
        "report_id": report.get("report_id"),
        "stage": stage,
        "errors": sorted(set(errors)),
        "rings_present": sorted(rings),
        "coverage_axes_present": sorted(axes),
        "source_ids": sorted(source_ids),
        "evidence_ids": sorted(evidence_ids),
        "critical_open": critical_open,
        "structurally_ready": not errors and not critical_open,
        "qa_checks": {
            "required_rings_complete": required_rings.issubset(rings),
            "required_axes_complete": required_axes.issubset(axes),
            "foreign_keys_valid": clear_of(
                "EVIDENCE_", "SEARCH_SOURCE_FK", "EXCLUDED_SOURCE_FK",
                "SEARCH_LEAD_FK", "LEAD_", "SEARCH_TARGET_FK",
            ),
            "identifiers_valid": clear_of("SOURCE_IDENTIFIER_INVALID"),
            "material_locators_valid": clear_of("MATERIAL_LOCATOR_MISSING"),
            "critical_leads_closed": not critical_open,
            "claim_hash_current": clear_of("STALE_CLAIM_FINGERPRINT"),
            "audit_hash_current": clear_of(
                "AUDIT_PROTOCOL_MISSING", "AUDIT_FINGERPRINT_STALE"
            ),
            "raw_reports_verified": clear_of("RAW_REPORT_"),
            "date_windows_current": clear_of(
                "DATE_WINDOW_", "SEARCH_CUTOFF_", "VENUE_WINDOW_",
                "SEARCH_EXECUTED_", "FINAL_AUDIT_RING_", "SEARCH_DATE_",
            ),
            "research_mode_satisfied": clear_of("DEEP_RESEARCH_MODE_REQUIRED"),
            "entity_ids_unique": clear_of("ENTITY_ID_DUPLICATE"),
        },
    }


PSEUDO_GAP_CODES = {
    "add_dataset", "scale_only", "model_swap", "map_swap",
    "routine_ablation", "future_work_only", "accuracy_without_decision",
    "reproducibility_only",
}
CANDIDATE_TEXT_FIELDS = (
    "population", "data_regime", "method_or_intervention",
    "strongest_comparator", "outcome_or_estimand",
    "mechanism_or_decision_consequence", "refutation_experiment",
    "venue_relevance",
)


def validate_candidate_board(board: dict[str, Any]) -> None:
    candidates = board.get("candidates")
    rejected = board.get("rejected_candidates", [])
    stage = board.get("stage", "discovery")
    if stage not in ("discovery", "falsification"):
        raise GapError("CANDIDATE_STAGE", "Candidate board stage is invalid.")
    if not isinstance(candidates, list) or not isinstance(rejected, list):
        raise GapError(
            "CANDIDATES_INVALID",
            "candidates and rejected_candidates must be arrays.",
        )
    if stage == "discovery" and not 3 <= len(candidates) + len(rejected) <= 6:
        raise GapError(
            "CANDIDATE_COUNT",
            "Discovery must record 3–6 total proposed candidates, including hard rejects.",
        )
    if stage == "falsification" and not 1 <= len(candidates) <= 2:
        raise GapError("CANDIDATE_COUNT", "Falsification may retain one primary and one backup.")
    ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise GapError("CANDIDATE_INVALID", "Each candidate must be an object.")
        candidate_id = item.get("candidate_id")
        if not candidate_id or candidate_id in ids:
            raise GapError("CANDIDATE_ID", "Candidate IDs must be non-empty and unique.")
        ids.add(candidate_id)
        basis_codes = item.get("basis_codes")
        if (
            not isinstance(basis_codes, list)
            or not basis_codes
            or any(not isinstance(code, str) or not code.strip() for code in basis_codes)
        ):
            raise GapError(
                "CANDIDATE_BASIS_REQUIRED",
                f"{candidate_id} must declare at least one non-empty basis code.",
            )
        basis = set(basis_codes)
        if basis.issubset(PSEUDO_GAP_CODES):
            raise GapError(
                "PSEUDO_GAP_MISCLASSIFIED",
                f"{candidate_id} relies only on a forbidden pseudo-gap; record it in rejected_candidates.",
                sorted(basis),
            )
        missing = [
            field for field in CANDIDATE_TEXT_FIELDS
            if not isinstance(item.get(field), str) or not item[field].strip()
        ]
        if missing:
            raise GapError(
                "CANDIDATE_FIELDS_REQUIRED",
                f"{candidate_id} is missing required scientific fields.",
                missing,
            )
        terms = item.get("closest_paper_search_terms")
        if (
            not isinstance(terms, list)
            or not terms
            or any(not isinstance(term, str) or not term.strip() for term in terms)
        ):
            raise GapError(
                "CANDIDATE_SEARCH_TERMS_REQUIRED",
                f"{candidate_id} needs non-empty closest-paper search terms.",
            )
        sesoi = item.get("sesoi")
        scalar_sesoi = (
            isinstance(sesoi, dict)
            and str(sesoi.get("value", "")).strip()
            and str(sesoi.get("unit", "")).strip()
        )
        asymmetric_sesoi = (
            isinstance(sesoi, dict)
            and str(sesoi.get("lower_margin", "")).strip()
            and str(sesoi.get("upper_margin", "")).strip()
            and str(sesoi.get("unit", "")).strip()
        )
        if not scalar_sesoi and not asymmetric_sesoi:
            raise GapError(
                "CANDIDATE_SESOI_REQUIRED",
                f"{candidate_id} needs a unitful SESOI.",
            )
        if not isinstance(item.get("prediction_claim"), bool):
            raise GapError(
                "PREDICTION_CLASSIFICATION_REQUIRED",
                f"{candidate_id} must explicitly classify prediction_claim.",
            )
        prediction_only = (
            item.get("claim_scope") == "prediction_only"
            and isinstance(item.get("prediction_only_justification"), str)
            and item["prediction_only_justification"].strip()
            and item.get("prediction_only_basis") in (
                "calibration", "robustness", "mechanism", "distribution_boundary"
            )
        )
        if item["prediction_claim"] and not item.get("decision_value_test") and not prediction_only:
            raise GapError(
                "DECISION_VALUE_MISSING",
                f"{candidate_id} needs a decision-value test or an explicit substantive prediction-only scope.",
            )

    rejected_ids: set[str] = set()
    for item in rejected:
        if not isinstance(item, dict):
            raise GapError("CANDIDATE_INVALID", "Each rejected candidate must be an object.")
        candidate_id = item.get("candidate_id")
        if not candidate_id or candidate_id in ids or candidate_id in rejected_ids:
            raise GapError("CANDIDATE_ID", "Candidate IDs must be non-empty and unique.")
        rejected_ids.add(candidate_id)
        codes = item.get("rejection_codes")
        reasons = item.get("rejection_reasons")
        if (
            not isinstance(codes, list)
            or not codes
            or any(code not in PSEUDO_GAP_CODES for code in codes)
        ):
            raise GapError(
                "PSEUDO_GAP_CODE_REQUIRED",
                f"{candidate_id} needs one or more recognized hard-veto codes.",
            )
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(reason, str) or not reason.strip() for reason in reasons)
        ):
            raise GapError(
                "PSEUDO_GAP_REASON_REQUIRED",
                f"{candidate_id} needs traceable hard-veto reasons.",
            )
    primary = board.get("primary_candidate_id")
    backup = board.get("backup_candidate_id")
    if primary is not None and primary not in ids:
        raise GapError("CANDIDATE_FK", "primary_candidate_id is not present.")
    if backup is not None and backup not in ids:
        raise GapError("CANDIDATE_FK", "backup_candidate_id is not present.")
    if primary is not None and primary == backup:
        raise GapError("CANDIDATE_FK", "Primary and backup must differ.")
    if not candidates and (primary is not None or backup is not None):
        raise GapError("CANDIDATE_FK", "An all-rejected board cannot select primary or backup.")
    if stage == "falsification":
        if primary is None:
            raise GapError("PRIMARY_REQUIRED", "Falsification must retain exactly one primary.")
        if len(candidates) == 2 and backup is None:
            raise GapError("BACKUP_REQUIRED", "The second retained candidate must be the backup.")
        if len(candidates) == 1 and backup is not None:
            raise GapError("CANDIDATE_FK", "A one-candidate board cannot select a backup.")


REQUIRED_PERMISSION_KEYS = (
    "design", "execute_local", "train_models", "access_final_holdout",
    "install_dependencies", "use_external_api", "use_remote_compute",
    "external_upload",
)
REQUIRED_LIMIT_KEYS = (
    "wall_time", "cpu_cores", "memory", "runs", "trials", "seeds", "cost",
)


def _quantity(value: Any, path: str) -> tuple[Decimal, str]:
    if not isinstance(value, dict) or set(("value", "unit")) - set(value):
        raise GapError("BUDGET_UNIT_MISSING", f"{path} must have value and unit.")
    try:
        amount = Decimal(str(value["value"]))
    except Exception as exc:
        raise GapError("BUDGET_VALUE_INVALID", f"{path}.value is invalid.") from exc
    if not amount.is_finite() or amount < 0 or not str(value["unit"]).strip():
        raise GapError("BUDGET_VALUE_INVALID", f"{path} must be finite, nonnegative, and unitful.")
    return amount, str(value["unit"])


def _decimal_value(value: Any, path: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise GapError("STATISTIC_INVALID", f"{path} is not a decimal value.") from exc
    if not number.is_finite():
        raise GapError("STATISTIC_INVALID", f"{path} must be finite.")
    return number


def _validate_precision_plan(
    state: dict[str, Any], preregistration: dict[str, Any]
) -> dict[str, Any]:
    plan = preregistration.get("precision_plan")
    if not isinstance(plan, dict):
        raise GapError("PRECISION_PLAN_REQUIRED", "Precision Smoke needs a structured plan.")
    claim = state["claim"]["current"] or {}
    protocol = preregistration["protocol"]
    if plan.get("estimand") != claim.get("estimand"):
        raise GapError("PRECISION_PLAN_MISMATCH", "Precision estimand differs from the current claim.")
    if canonical_json(plan.get("sesoi")) != canonical_json(claim.get("sesoi")):
        raise GapError("PRECISION_PLAN_MISMATCH", "Precision SESOI differs from the current claim.")
    if plan.get("primary_endpoint") != protocol.get("primary_endpoint"):
        raise GapError("PRECISION_PLAN_MISMATCH", "Precision endpoint differs from the protocol.")
    if canonical_json(plan.get("split")) != canonical_json(protocol.get("split")):
        raise GapError("PRECISION_PLAN_MISMATCH", "Precision split differs from the protocol.")
    lower = _decimal_value(plan.get("lower_margin"), "precision_plan.lower_margin")
    upper = _decimal_value(plan.get("upper_margin"), "precision_plan.upper_margin")
    if lower >= upper:
        raise GapError("PRECISION_MARGIN_INVALID", "Precision lower margin must be below upper margin.")
    sesoi = plan.get("sesoi")
    if isinstance(sesoi, dict) and "value" in sesoi:
        sesoi_value, _ = _quantity(sesoi, "precision_plan.sesoi")
        sesoi_value = abs(sesoi_value)
        expected_lower, expected_upper = -sesoi_value, sesoi_value
    elif isinstance(sesoi, dict):
        expected_lower = _decimal_value(
            sesoi.get("lower_margin"), "precision_plan.sesoi.lower_margin"
        )
        expected_upper = _decimal_value(
            sesoi.get("upper_margin"), "precision_plan.sesoi.upper_margin"
        )
        if not str(sesoi.get("unit", "")).strip():
            raise GapError(
                "PRECISION_MARGIN_SESOI_MISMATCH",
                "Asymmetric SESOI requires a non-empty unit.",
            )
    else:
        raise GapError(
            "PRECISION_MARGIN_SESOI_MISMATCH",
            "Precision SESOI must define a scalar or lower/upper margins.",
        )
    if (
        expected_lower >= expected_upper
        or lower != expected_lower
        or upper != expected_upper
    ):
        raise GapError(
            "PRECISION_MARGIN_SESOI_MISMATCH",
            "Precision margins must exactly equal the current claim SESOI bounds.",
        )
    framework = plan.get("framework")
    if framework in ("TOST", "CI_EQUIVALENCE"):
        level = _decimal_value(plan.get("interval_level"), "precision_plan.interval_level")
        if not Decimal("0.8") <= level < Decimal("1"):
            raise GapError(
                "PRECISION_LEVEL_INVALID",
                "Equivalence intervals must use a preregistered level in [0.8, 1).",
            )
        if framework == "TOST":
            alpha = _decimal_value(plan.get("alpha"), "precision_plan.alpha")
            if not Decimal("0") < alpha <= Decimal("0.1"):
                raise GapError(
                    "PRECISION_ALPHA_INVALID",
                    "TOST alpha must be greater than zero and no larger than 0.1.",
                )
            if level != Decimal("1") - Decimal("2") * alpha:
                raise GapError("TOST_CI_LEVEL_INVALID", "TOST interval level must equal 1 - 2*alpha.")
    elif framework == "BAYESIAN_ROPE":
        threshold = _decimal_value(
            plan.get("posterior_threshold"), "precision_plan.posterior_threshold"
        )
        if not Decimal("0") < threshold <= Decimal("1"):
            raise GapError("ROPE_THRESHOLD_INVALID", "ROPE threshold must be in (0, 1].")
    elif framework == "FUTILITY":
        rule = plan.get("futility_rule")
        if not isinstance(rule, dict):
            raise GapError("FUTILITY_RULE_REQUIRED", "Futility rule must be structured.")
        if not str(rule.get("measure", "")).strip() or rule.get("operator") not in (
            "==", "!=", ">", ">=", "<", "<="
        ):
            raise GapError(
                "FUTILITY_RULE_REQUIRED",
                "Futility rule needs measure, operator, threshold, and unit.",
            )
    return plan


def _validate_precision_evidence(
    preregistration: dict[str, Any], result: dict[str, Any]
) -> None:
    plan = preregistration.get("precision_plan")
    evidence = result.get("precision_evidence")
    if not isinstance(plan, dict) or not isinstance(evidence, dict):
        raise GapError("PRECISION_EVIDENCE_REQUIRED", "Precision result needs bound evidence.")
    estimate = _decimal_value(evidence.get("estimate"), "precision_evidence.estimate")
    framework = plan["framework"]
    if framework in ("TOST", "CI_EQUIVALENCE"):
        lower = _decimal_value(evidence.get("interval_lower"), "precision_evidence.interval_lower")
        upper = _decimal_value(evidence.get("interval_upper"), "precision_evidence.interval_upper")
        level = _decimal_value(evidence.get("interval_level"), "precision_evidence.interval_level")
        if lower > upper:
            raise GapError("PRECISION_INTERVAL_INVALID", "Precision interval bounds are reversed.")
        if not lower <= estimate <= upper:
            raise GapError(
                "PRECISION_ESTIMATE_OUTSIDE_INTERVAL",
                "The point estimate must lie inside its reported interval.",
            )
        if level != _decimal_value(plan.get("interval_level"), "precision_plan.interval_level"):
            raise GapError("PRECISION_LEVEL_MISMATCH", "Result interval level differs from preregistration.")
    elif framework == "BAYESIAN_ROPE":
        mass = _decimal_value(
            evidence.get("posterior_mass_in_rope"),
            "precision_evidence.posterior_mass_in_rope",
        )
        if not Decimal("0") <= mass <= Decimal("1"):
            raise GapError("ROPE_MASS_INVALID", "Posterior ROPE mass must be in [0, 1].")
    elif framework == "FUTILITY":
        observation = evidence.get("futility_observation")
        rule = plan.get("futility_rule")
        if not isinstance(observation, dict) or not isinstance(rule, dict):
            raise GapError(
                "FUTILITY_RESULT_REQUIRED",
                "Futility result must contain a structured observation.",
            )
        if observation.get("unit") != rule.get("unit"):
            raise GapError(
                "FUTILITY_UNIT_MISMATCH",
                "Futility observation unit differs from the preregistered rule.",
            )
        references = observation.get("evidence_refs")
        if not isinstance(references, list) or not references:
            raise GapError(
                "FUTILITY_EVIDENCE_REQUIRED",
                "Futility observation needs result-bound evidence references.",
            )
        expected_prefix = (
            f"result:{result.get('result_id')}#/results/{rule.get('measure')}"
        )
        if expected_prefix not in references:
            raise GapError(
                "FUTILITY_EVIDENCE_REQUIRED",
                "Futility evidence must point to its preregistered measure.",
            )
        valid, measured = _result_evidence_ref_value(result, expected_prefix)
        if not valid or canonical_json(measured) != canonical_json(
            observation.get("value")
        ):
            raise GapError(
                "FUTILITY_EVIDENCE_MISMATCH",
                "Futility observation does not match the bound result value.",
            )
        if not all(_result_evidence_ref_valid(result, ref) for ref in references):
            raise GapError(
                "FUTILITY_EVIDENCE_REQUIRED",
                "Futility evidence contains an invalid result pointer.",
            )


def validate_smoke_authorization(
    run_dir: Path, state: dict[str, Any], authorization: dict[str, Any]
) -> None:
    validate_schema(authorization, "smoke.schema.json")
    if authorization.get("status") not in (
        "active", "consumed", "expired", "revoked", "stale"
    ):
        raise GapError("AUTH_STATUS_INVALID", "Unknown authorization status.")
    if authorization.get("smoke_kind") not in ("technical", "precision"):
        raise GapError("SMOKE_KIND_INVALID", "Smoke kind must be technical or precision.")
    if authorization.get("claim_fingerprint") != state["fingerprints"]["claim"]:
        raise GapError("AUTH_HASH_MISMATCH", "Authorization claim hash is stale.")
    if authorization.get("protocol_fingerprint") != state["fingerprints"]["protocol"]:
        raise GapError("AUTH_HASH_MISMATCH", "Authorization protocol hash is stale.")
    prereg = _latest_payload(run_dir, state, "smoke_preregistration")
    if prereg is None or authorization.get("preregistration_hash") != prereg[0]["sha256"]:
        raise GapError("AUTH_PREREG_MISMATCH", "Authorization is not bound to current preregistration.")
    permissions = authorization.get("permissions")
    if not isinstance(permissions, dict):
        raise GapError("AUTH_PERMISSIONS_MISSING", "permissions object is required.")
    missing = [key for key in REQUIRED_PERMISSION_KEYS if not isinstance(permissions.get(key), bool)]
    if missing:
        raise GapError("AUTH_PERMISSIONS_MISSING", "Permission booleans are missing.", missing)
    if not permissions["design"]:
        raise GapError("AUTH_DESIGN_REQUIRED", "Smoke authorization must at least permit design.")
    if permissions["access_final_holdout"]:
        raise GapError(
            "FINAL_HOLDOUT_FORBIDDEN",
            "Neither Technical nor Precision Smoke may access the final confirmatory holdout.",
        )
    data_scope = authorization.get("data_scope")
    if not isinstance(data_scope, list) or not data_scope:
        raise GapError("AUTH_DATA_SCOPE_MISSING", "Versioned data_scope must be non-empty.")
    for index, item in enumerate(data_scope):
        required = {"dataset_id", "version", "slices", "access", "final_holdout"}
        if not isinstance(item, dict) or required - set(item):
            raise GapError("AUTH_DATA_SCOPE_MISSING", f"data_scope[{index}] is incomplete.")
        if item["final_holdout"] is not False:
            raise GapError(
                "FINAL_HOLDOUT_FORBIDDEN",
                f"data_scope[{index}] must exclude the final confirmatory holdout.",
            )
    limits = authorization.get("compute_limits")
    if not isinstance(limits, dict):
        raise GapError("AUTH_BUDGET_MISSING", "compute_limits object is required.")
    missing_limits = [key for key in REQUIRED_LIMIT_KEYS if key not in limits]
    if missing_limits:
        raise GapError("AUTH_BUDGET_MISSING", "Compute limits are missing.", missing_limits)
    for key in REQUIRED_LIMIT_KEYS:
        _quantity(limits[key], f"compute_limits.{key}")
    for key in ("network_allowlist", "filesystem_write_roots", "privacy_constraints"):
        if not isinstance(authorization.get(key), list):
            raise GapError("AUTH_SCOPE_MISSING", f"{key} must be an array.")
    if authorization.get("authorized_by") != "user":
        raise GapError("AUTH_USER_REQUIRED", "Research execution must be authorized by the user.")
    if authorization.get("gap_id") not in (
        state["run_id"],
        (state["claim"]["current"] or {}).get("gap_id"),
    ):
        raise GapError("AUTH_GAP_MISMATCH", "Authorization gap ID is not current.")
    expires = authorization.get("expires_at")
    if expires and authorization.get("status") == "active":
        try:
            parsed = dt.datetime.fromisoformat(expires)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            if parsed < dt.datetime.now(dt.timezone.utc):
                raise GapError("AUTH_EXPIRED", "Authorization has expired.")
        except ValueError as exc:
            raise GapError("AUTH_EXPIRY_INVALID", "expires_at is not ISO-8601.") from exc
    if (
        authorization["permissions"]["use_external_api"]
        or authorization["permissions"]["use_remote_compute"]
        or authorization["permissions"]["external_upload"]
    ) and not authorization["network_allowlist"]:
        raise GapError("AUTH_NETWORK_SCOPE_MISSING", "External use needs a network allowlist.")


def _authorization_by_id(
    run_dir: Path, state: dict[str, Any], authorization_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for record in reversed(_current_artifacts(state, "smoke_authorization")):
        payload = _artifact_payload(run_dir, record)
        if payload.get("authorization_id") == authorization_id:
            return record, payload
    return None


def validate_smoke_result(
    run_dir: Path, state: dict[str, Any], result: dict[str, Any]
) -> None:
    validate_schema(result, "smoke.schema.json")
    found = _authorization_by_id(run_dir, state, str(result.get("authorization_id")))
    if found is None:
        raise GapError("AUTH_NOT_FOUND", "Smoke result has no current authorization.")
    auth_record, auth = found
    if auth_record["status"] != "current" or auth.get("status") != "active":
        raise GapError("AUTH_NOT_ACTIVE", "Smoke authorization is not active.")
    if not auth["permissions"]["execute_local"]:
        raise GapError("EXECUTION_NOT_AUTHORIZED", "Design permission does not allow execution.")
    if result.get("smoke_kind") != auth.get("smoke_kind"):
        raise GapError("SMOKE_KIND_ESCALATION", "Technical authorization cannot run Precision Smoke.")
    if result.get("claim_fingerprint") != state["fingerprints"]["claim"]:
        raise GapError("RESULT_HASH_MISMATCH", "Smoke result claim hash is stale.")
    if result.get("protocol_fingerprint") != state["fingerprints"]["protocol"]:
        raise GapError("RESULT_HASH_MISMATCH", "Smoke result protocol hash is stale.")
    if result.get("preregistration_hash") != auth.get("preregistration_hash"):
        raise GapError("RESULT_PREREG_MISMATCH", "Smoke result preregistration hash is stale.")
    preregistration: dict[str, Any] | None = None
    for prereg_record in reversed(_current_artifacts(state, "smoke_preregistration")):
        if prereg_record["sha256"] == auth.get("preregistration_hash"):
            preregistration = _artifact_payload(run_dir, prereg_record)
            break
    if preregistration is None:
        raise GapError("RESULT_PREREG_MISMATCH", "Bound preregistration is not current.")
    if result.get("smoke_kind") == "precision":
        _validate_precision_evidence(preregistration, result)
    if result.get("gap_id") != auth.get("gap_id"):
        raise GapError("RESULT_GAP_MISMATCH", "Smoke result gap ID differs from authorization.")
    operations = result.get("operations", {})
    permission_map = {
        "trained_models": "train_models",
        "accessed_final_holdout": "access_final_holdout",
        "installed_dependencies": "install_dependencies",
        "used_external_api": "use_external_api",
        "used_remote_compute": "use_remote_compute",
        "uploaded_external": "external_upload",
    }
    for operation, permission in permission_map.items():
        if operations.get(operation) and not auth["permissions"][permission]:
            raise GapError("OPERATION_NOT_AUTHORIZED", f"{operation} was not authorized.")
    consumption = result.get("resource_consumption")
    if not isinstance(consumption, dict):
        raise GapError("CONSUMPTION_MISSING", "Smoke result must record resource consumption.")
    prior_totals: dict[str, tuple[Decimal, str]] = {}
    for key, used in auth.get("consumption", {}).items():
        prior_totals[key] = _quantity(used, f"authorization.consumption.{key}")
    for prior_record in _current_artifacts(state, "smoke_result"):
        prior = _artifact_payload(run_dir, prior_record)
        if prior.get("authorization_id") != auth.get("authorization_id"):
            continue
        if prior.get("result_id") == result.get("result_id"):
            continue
        for key, used in prior.get("resource_consumption", {}).items():
            amount, unit = _quantity(used, f"prior.resource_consumption.{key}")
            previous, previous_unit = prior_totals.get(key, (Decimal("0"), unit))
            if unit != previous_unit:
                raise GapError("CONSUMPTION_UNIT_MISMATCH", f"Inconsistent unit for {key}.")
            prior_totals[key] = (previous + amount, unit)
    for key, used in consumption.items():
        if key not in auth["compute_limits"]:
            raise GapError("BUDGET_SCOPE_EXCEEDED", f"Unbudgeted resource: {key}")
        amount, unit = _quantity(used, f"resource_consumption.{key}")
        limit, limit_unit = _quantity(auth["compute_limits"][key], f"compute_limits.{key}")
        previous, previous_unit = prior_totals.get(key, (Decimal("0"), unit))
        if unit != previous_unit:
            raise GapError("CONSUMPTION_UNIT_MISMATCH", f"Inconsistent unit for {key}.")
        if unit != limit_unit or previous + amount > limit:
            raise GapError("BUDGET_EXCEEDED", f"{key} exceeds the authorized budget.")


def _merge_report_into_ledger(
    ledger: dict[str, Any], report: dict[str, Any]
) -> None:
    mapping = (
        ("search_runs", "search_runs"),
        ("sources", "sources"),
        ("evidence", "evidence"),
    )
    for report_key, ledger_key in mapping:
        for item in report.get(report_key, []):
            item_id = item["id"]
            existing = ledger[ledger_key].get(item_id)
            if existing is not None and sha256_data(existing) != sha256_data(item):
                raise GapError("LEDGER_ID_CONFLICT", f"Conflicting ledger ID: {item_id}")
            ledger[ledger_key][item_id] = item
    ledger.setdefault("lead_history", [])
    for item in report.get("unresolved_leads", []):
        item_id = item["id"]
        existing = ledger["unresolved_leads"].get(item_id)
        if existing is None:
            ledger["unresolved_leads"][item_id] = item
            continue
        if sha256_data(existing) == sha256_data(item):
            continue
        allowed_resolution = (
            existing.get("status") == "open"
            and item.get("status") in ("resolved", "dismissed")
            and item.get("description") == existing.get("description")
            and item.get("severity") == existing.get("severity")
            and bool(item.get("resolution_evidence_ids"))
        )
        if not allowed_resolution:
            raise GapError(
                "LEDGER_ID_CONFLICT",
                f"Lead {item_id} may only transition immutably from open to resolved/dismissed.",
            )
        ledger["lead_history"].append({
            "lead_id": item_id,
            "previous": existing,
            "replacement": item,
            "resolved_by_report_id": report.get("report_id"),
        })
        ledger["unresolved_leads"][item_id] = item


RECORD_KINDS = {
    "claim", "candidate_board", "audit_protocol", "research_handoff",
    "research_report", "smoke_preregistration",
    "smoke_authorization", "smoke_result", "source_verification",
    "scientific_audit", "experiment_freeze",
}


def build_research_handoff(
    state: dict[str, Any],
    stage: str,
    audit_protocol_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in ("venue_map", "falsification", "final_audit"):
        raise GapError("REPORT_STAGE_INVALID", f"Unknown research stage: {stage}")
    if stage != "venue_map" and state["fingerprints"]["claim"] is None:
        raise GapError("CLAIM_REQUIRED", f"{stage} handoff needs a current claim.")
    axes = [
        "problem", "population_or_data", "method_or_intervention",
        "comparator", "outcome_or_estimand", "recency",
    ]
    if state["scope"].get("adapter") == "decision-policy":
        axes.append("decision_consequence")
    handoff = {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": f"handoff-{stage}-r{state['manifest_revision']}",
        "stage": stage,
        "run_id": state["run_id"],
        "target": state["scope"],
        "claim_fingerprint": state["fingerprints"]["claim"],
        "audit_fingerprint": state["fingerprints"]["audit"],
        "base_ledger_version": state["ledger_version"],
        "required_rings": ["target_venue", "cross_venue", "citation_graph"],
        "required_coverage_axes": axes,
        "research_mode_required": "deep_research",
        "source_policy": {
            "primary_sources_required": True,
            "full_text_for_closest_papers": True,
            "raw_report_and_sha256_required": True,
            "material_locator_required": True,
        },
        "return_schema": "schemas/research-report.schema.json",
        "validator_limits": [
            "Structure and hashes do not prove search execution.",
            "A sidecar cannot mark a gate passed.",
        ],
        "requested_at": utc_now(),
    }
    if stage == "final_audit":
        if state["fingerprints"]["audit"] is None:
            raise GapError(
                "AUDIT_PROTOCOL_REQUIRED",
                "Freeze a Final Audit protocol before creating its research handoff.",
            )
        if audit_protocol_payload is None:
            raise GapError(
                "AUDIT_PROTOCOL_REQUIRED",
                "Final Audit handoff must carry the frozen audit protocol payload.",
            )
        computed = _validate_audit_protocol(state, audit_protocol_payload)
        if computed != state["fingerprints"]["audit"]:
            raise GapError(
                "AUDIT_FINGERPRINT_MISMATCH",
                "Final Audit handoff protocol differs from the current audit hash.",
            )
        handoff["audit_protocol_required"] = True
        handoff["audit_protocol"] = audit_protocol_payload
    return handoff


def validate_research_handoff(
    state: dict[str, Any], handoff: dict[str, Any]
) -> str:
    stage = handoff.get("stage")
    if stage not in ("venue_map", "falsification", "final_audit"):
        raise GapError("REPORT_STAGE_INVALID", "Handoff stage is invalid.")
    if handoff.get("run_id") != state["run_id"]:
        raise GapError("HANDOFF_RUN_MISMATCH", "Handoff run_id is not current.")
    if handoff.get("base_ledger_version") != state["ledger_version"]:
        raise GapError("STALE_LEDGER_VERSION", "Handoff ledger version is stale.")
    if handoff.get("claim_fingerprint") != state["fingerprints"]["claim"]:
        raise GapError("STALE_CLAIM_FINGERPRINT", "Handoff claim hash is stale.")
    if stage == "final_audit":
        if state["fingerprints"]["audit"] is None:
            raise GapError(
                "AUDIT_PROTOCOL_REQUIRED",
                "Final Audit handoff has no frozen audit protocol.",
            )
        if handoff.get("audit_fingerprint") != state["fingerprints"]["audit"]:
            raise GapError(
                "AUDIT_FINGERPRINT_MISMATCH",
                "Final Audit handoff is not bound to the frozen audit protocol.",
            )
        protocol_payload = handoff.get("audit_protocol")
        if not isinstance(protocol_payload, dict):
            raise GapError(
                "AUDIT_PROTOCOL_REQUIRED",
                "Final Audit handoff does not carry its frozen query protocol.",
            )
        if _validate_audit_protocol(state, protocol_payload) != state[
            "fingerprints"
        ]["audit"]:
            raise GapError(
                "AUDIT_FINGERPRINT_MISMATCH",
                "Final Audit handoff query protocol is stale.",
            )
    if set(handoff.get("required_rings", [])) != {
        "target_venue", "cross_venue", "citation_graph"
    }:
        raise GapError("HANDOFF_RINGS_INCOMPLETE", "Handoff must request all three rings.")
    if handoff.get("research_mode_required") != "deep_research":
        raise GapError("DEEP_RESEARCH_MODE_REQUIRED", "Handoff must require Deep Research.")
    if not handoff.get("required_coverage_axes"):
        raise GapError("HANDOFF_AXES_INCOMPLETE", "Handoff coverage axes are empty.")
    return str(stage)


def _bilingual(value: Any, name: str) -> None:
    if not isinstance(value, dict) or not all(
        isinstance(value.get(language), str) and value[language].strip()
        for language in ("zh", "en")
    ):
        raise GapError("BILINGUAL_FIELD_REQUIRED", f"{name} must contain non-empty zh and en.")


def _validate_freeze_cross_fields(
    run_dir: Path, state: dict[str, Any], freeze: dict[str, Any]
) -> None:
    if freeze.get("run_id") != state["run_id"]:
        raise GapError("FREEZE_RUN_MISMATCH", "Freeze run_id is not current.")
    if freeze.get("claim_version") != state["claim"]["current_version"]:
        raise GapError("FREEZE_CLAIM_VERSION_STALE", "Freeze claim version is stale.")
    decision = freeze.get("decision", {})
    if decision.get("status") != "GO" or decision.get("full_experiment_authorized") is not False:
        raise GapError("FREEZE_DECISION_INVALID", "Freeze must be GO and must not authorize execution.")
    if freeze.get("artifact_status") != "FROZEN_FOR_EXPERIMENT":
        raise GapError("FREEZE_STATUS_INVALID", "GO Freeze must be FROZEN_FOR_EXPERIMENT.")
    if freeze.get("final_audit", {}).get("status") != "PASS":
        raise GapError("FINAL_AUDIT_NOT_PASS", "Freeze requires a PASS Final Audit.")
    if freeze.get("final_audit", {}).get("exact_claim_fingerprint") != state["fingerprints"]["claim"]:
        raise GapError("FINAL_AUDIT_CLAIM_STALE", "Final Audit exact claim hash is stale.")
    audit_protocol_item = _current_audit_protocol(run_dir, state)
    if audit_protocol_item is None:
        raise GapError(
            "AUDIT_PROTOCOL_MISSING",
            "Freeze has no current pre-registered Final Audit protocol.",
        )
    if freeze.get("search_cutoff") != audit_protocol_item[1].get("cutoff_date"):
        raise GapError(
            "FREEZE_CUTOFF_MISMATCH",
            "Freeze search cutoff differs from the current Final Audit protocol.",
        )
    gate_values = freeze.get("gates", {}).values()
    if not gate_values or any(item.get("status") != "PASS" for item in gate_values):
        raise GapError("FREEZE_SUBGATE_NOT_PASS", "Every Freeze scientific subgate must PASS.")
    sesoi = freeze.get("statistics", {}).get("sesoi", {})
    if sesoi.get("lower_margin") >= sesoi.get("upper_margin"):
        raise GapError("SESOI_ORDER_INVALID", "SESOI lower margin must be below upper margin.")
    framework = freeze.get("statistics", {}).get("framework", {})
    if framework.get("type") == "FREQUENTIST_TOST":
        expected_level = 1 - 2 * framework["alpha"]
        if abs(framework["equivalence_ci_level"] - expected_level) > 1e-9:
            raise GapError("TOST_CI_LEVEL_INVALID", "TOST CI level must equal 1 - 2 alpha.")
    results = _gate_payloads(run_dir, state, "smoke", "smoke_result")
    if not results:
        raise GapError("CURRENT_SMOKE_CHAIN_MISSING", "Freeze has no current Smoke result.")
    operations = results[-1][1].get("operations", {})
    if operations.get("accessed_final_holdout"):
        raise GapError("FINAL_HOLDOUT_TOUCHED", "GO Freeze cannot use a touched final holdout.")


def _validate_claim(claim: dict[str, Any]) -> str:
    for field in ("title", "research_question", "novelty_claim"):
        _bilingual(claim.get(field), field)
    return claim_fingerprint(claim)


def _gate_for_report(report: dict[str, Any]) -> str:
    mapping = {
        "venue_map": "venue_map",
        "falsification": "falsification",
        "final_audit": "final_audit",
    }
    stage = report_stage(report)
    if stage not in mapping:
        raise GapError("REPORT_STAGE_INVALID", f"Unknown research stage: {stage}")
    return mapping[stage]


def _verify_scientific_audit(
    state: dict[str, Any], payload: dict[str, Any]
) -> None:
    gate = payload.get("gate")
    if gate not in GATE_NAMES[:-1]:
        raise GapError("AUDIT_GATE_INVALID", "Scientific audit names an invalid gate.")
    if payload.get("outcome") not in (
        "PASS", "GO", "STOP", "NARROW", "BLOCKED", "INSUFFICIENT_EVIDENCE", "FAIL"
    ):
        raise GapError("AUDIT_OUTCOME_INVALID", "Scientific audit outcome is invalid.")
    for key in ("claim", "protocol", "audit"):
        supplied = payload.get(f"{key}_fingerprint")
        current = state["fingerprints"][key]
        if supplied != current:
            raise GapError("AUDIT_HASH_MISMATCH", f"Scientific audit {key} hash is stale.")
    if not payload.get("evidence_ids"):
        raise GapError("AUDIT_EVIDENCE_MISSING", "Scientific audit needs evidence IDs.")
    if not str(payload.get("reasoning", "")).strip():
        raise GapError("AUDIT_REASONING_MISSING", "Scientific audit needs reasoning.")


def _advance_after_ingest(
    state: dict[str, Any], kind: str, payload: dict[str, Any]
) -> None:
    if kind == "claim":
        state["phase"] = "discovery"
        state["run_status"] = "active"
    elif kind == "candidate_board":
        stage = payload.get("stage", "discovery")
        if stage == "discovery" and not payload.get("candidates"):
            state["phase"] = "discovery"
            state["run_status"] = "active"
        elif stage == "discovery":
            state["phase"] = "falsification"
            state["run_status"] = "awaiting_research"
        else:
            state["phase"] = "falsification"
            state["run_status"] = "active"
    elif kind == "research_handoff":
        stage = payload["stage"]
        state["phase"] = stage
        state["run_status"] = "awaiting_research"
    elif kind == "research_report":
        stage = report_stage(payload)
        state["phase"] = stage
        state["run_status"] = "active"
    elif kind == "audit_protocol":
        state["phase"] = "final_audit"
        state["run_status"] = "active"
    elif kind.startswith("smoke_"):
        state["phase"] = "smoke"
        state["run_status"] = (
            "awaiting_user" if kind == "smoke_preregistration" else "active"
        )
    elif kind == "experiment_freeze":
        state["phase"] = "freeze"
        state["run_status"] = "active"


def _require_record_preconditions(
    run_dir: Path,
    state: dict[str, Any],
    candidates: dict[str, Any],
    kind: str,
    payload: dict[str, Any],
) -> None:
    if state["phase"] == "closed" or state["decision"] != "undecided":
        raise GapError(
            "RUN_CLOSED",
            "Closed runs accept no new research artifacts; use a permitted evidence revision or start a new run.",
        )
    phase = state["phase"]
    gate_passed = lambda name: state["gates"][name]["status"] == "passed"
    if kind == "claim":
        if phase != "discovery" or not gate_passed("venue_map"):
            raise GapError("ILLEGAL_TRANSITION", "A claim requires a passed Venue Map gate.")
    elif kind == "candidate_board":
        stage = payload.get("stage", "discovery")
        if state["claim"]["current"] is None:
            raise GapError("CLAIM_REQUIRED", "Candidate boards require a current claim.")
        if stage == "discovery" and (phase != "discovery" or not gate_passed("venue_map")):
            raise GapError("ILLEGAL_TRANSITION", "Discovery board is not legal in the current phase.")
        if stage == "falsification":
            has_report = bool(_gate_payloads(
                run_dir, state, "falsification", "research_report"
            ))
            has_audit = bool(_gate_payloads(
                run_dir, state, "falsification", "scientific_audit"
            ))
            if phase != "falsification" or not has_report or not has_audit:
                raise GapError(
                    "ILLEGAL_TRANSITION",
                    "Retained candidates require current Falsification report and audit artifacts.",
                )
    elif kind in ("research_handoff", "research_report"):
        stage = payload.get("stage") if kind == "research_handoff" else report_stage(payload)
        if stage == "venue_map" and phase != "venue_map":
            raise GapError("ILLEGAL_TRANSITION", "Venue Map research is not current.")
        falsification_reopened = (
            candidates.get("board_status") == "ready_for_smoke"
            and state["gates"]["falsification"]["status"] in (
                "stale", "review_required", "failed"
            )
        )
        if stage == "falsification" and (
            phase != "falsification"
            or candidates.get("board_status") not in ("ready_for_falsification", "ready_for_smoke")
            or (
                candidates.get("board_status") == "ready_for_smoke"
                and not falsification_reopened
            )
            or state["claim"]["current"] is None
        ):
            raise GapError("ILLEGAL_TRANSITION", "Falsification prerequisites are incomplete.")
        if stage == "final_audit" and (
            phase != "final_audit"
            or not gate_passed("smoke")
            or _current_audit_protocol(run_dir, state) is None
        ):
            raise GapError(
                "ILLEGAL_TRANSITION",
                "Final Audit requires a passed Smoke gate and frozen audit protocol.",
            )
    elif kind == "audit_protocol":
        if (
            phase != "final_audit"
            or not gate_passed("smoke")
            or _gate_payloads(
                run_dir, state, "final_audit", "research_report"
            )
        ):
            raise GapError(
                "ILLEGAL_TRANSITION",
                "Audit protocol must be frozen after Smoke and before Final Audit research.",
            )
        if _current_audit_protocol(run_dir, state) is not None:
            raise GapError(
                "USE_QUEUE_REVISION",
                "A frozen audit protocol may only change through queue_gap_revision.py.",
            )
    elif kind == "smoke_preregistration":
        smoke_kind = payload.get("smoke_kind")
        common_ready = (
            gate_passed("falsification")
            and candidates.get("board_status") == "ready_for_smoke"
        )
        if smoke_kind == "technical" and (phase != "smoke" or not common_ready):
            raise GapError("ILLEGAL_TRANSITION", "Smoke design prerequisites are incomplete.")
        if smoke_kind == "precision":
            if phase not in ("smoke", "final_audit") or not common_ready:
                raise GapError(
                    "ILLEGAL_TRANSITION",
                    "Precision Smoke prerequisites are incomplete.",
                )
            if _gate_payloads(
                run_dir, state, "final_audit", "research_report"
            ):
                raise GapError(
                    "USE_QUEUE_REVISION",
                    "Precision Smoke cannot reopen after Final Audit research has started.",
                )
            latest_prereg = _latest_payload(
                run_dir, state, "smoke_preregistration"
            )
            technical_validation = _smoke_gate_validation(run_dir, state)
            if (
                latest_prereg is None
                or latest_prereg[1].get("smoke_kind") != "technical"
                or technical_validation["status"] != "passed"
                or technical_validation["outcome"] not in ("PASS", "GO")
            ):
                raise GapError(
                    "TECHNICAL_SMOKE_REQUIRED",
                    "Precision Smoke requires a complete, validated Technical Smoke chain.",
                )
    elif kind == "smoke_authorization":
        if phase != "smoke" or _latest_payload(
            run_dir, state, "smoke_preregistration"
        ) is None:
            raise GapError("ILLEGAL_TRANSITION", "Authorization requires a current Smoke preregistration.")
    elif kind == "smoke_result":
        if phase != "smoke":
            raise GapError("ILLEGAL_TRANSITION", "Smoke result is not legal outside Smoke.")
    elif kind in ("source_verification", "scientific_audit"):
        gate_name = payload.get("gate")
        expected_phase = {
            "venue_map": "venue_map",
            "falsification": "falsification",
            "smoke": "smoke",
            "final_audit": "final_audit",
        }.get(gate_name)
        if expected_phase is None or phase != expected_phase:
            raise GapError(
                "ILLEGAL_TRANSITION",
                "Verification or audit does not belong to the current phase.",
            )
    elif kind == "experiment_freeze":
        if phase != "freeze" or any(
            not gate_passed(name) for name in GATE_NAMES[:-1]
        ):
            raise GapError("ILLEGAL_TRANSITION", "Freeze prerequisites are incomplete.")


def record_result(
    run_dir: Path,
    kind: str,
    payload: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    if kind not in RECORD_KINDS:
        if kind == "gate_validation":
            raise GapError(
                "GATE_WRITE_FORBIDDEN",
                "Gate validation cannot be ingested; use validate_gap_run.py --commit.",
            )
        raise GapError("KIND_INVALID", f"Unsupported artifact kind: {kind}")
    paths = run_paths(run_dir)
    with exclusive_lock(paths["lock"]):
        state = load_state(run_dir)
        if state["manifest_revision"] != expected_revision:
            raise GapError(
                "STALE_REVISION",
                f"Expected revision {expected_revision}, current is {state['manifest_revision']}.",
            )
        incoming_digest = sha256_data(payload)
        for existing in state["artifacts"].values():
            if existing["kind"] == kind and existing["sha256"] == incoming_digest:
                return {
                    "status": "idempotent",
                    "artifact_id": existing["artifact_id"],
                    "manifest_revision": state["manifest_revision"],
                }
        ledger = read_json(paths["ledger"])
        candidates = read_json(paths["candidates"])
        _require_record_preconditions(run_dir, state, candidates, kind, payload)
        next_state = copy.deepcopy(state)
        next_ledger = copy.deepcopy(ledger)
        next_candidates = copy.deepcopy(candidates)
        subject_refs: list[str] = []
        target_gate: str | None = None

        if kind == "claim":
            if state["claim"]["current"] is not None:
                raise GapError(
                    "USE_QUEUE_REVISION",
                    "Existing claims must change through queue_gap_revision.py.",
                )
            fingerprint = _validate_claim(payload)
            next_state["claim"] = {
                "current_version": 1,
                "current": payload,
                "history": [{
                    "version": 1,
                    "claim_fingerprint": fingerprint,
                    "recorded_at": utc_now(),
                    "claim": payload,
                }],
            }
            next_state["fingerprints"]["claim"] = fingerprint
            subject_refs = [f"claim:{fingerprint}"]
        elif kind == "candidate_board":
            validate_candidate_board(payload)
            board_stage = payload.get("stage", "discovery")
            board_status = (
                "no_viable_candidate"
                if board_stage == "discovery" and not payload["candidates"]
                else "ready_for_falsification"
                if board_stage == "discovery"
                else "ready_for_smoke"
            )
            next_candidates = {
                "schema_version": SCHEMA_VERSION,
                "run_id": state["run_id"],
                "stage": board_stage,
                "candidates": payload["candidates"],
                "rejected_candidates": payload.get("rejected_candidates", []),
                "primary_candidate_id": payload.get("primary_candidate_id"),
                "backup_candidate_id": payload.get("backup_candidate_id"),
                "board_status": board_status,
                "bound_claim_fingerprint": state["fingerprints"]["claim"],
            }
            subject_refs = [
                f"candidate:{item['candidate_id']}" for item in payload["candidates"]
            ] + [
                f"candidate-reject:{item['candidate_id']}"
                for item in payload.get("rejected_candidates", [])
            ]
        elif kind == "audit_protocol":
            computed_audit = _validate_audit_protocol(state, payload)
            if (
                state["fingerprints"]["audit"] is not None
                and state["fingerprints"]["audit"] != computed_audit
            ):
                raise GapError(
                    "AUDIT_FINGERPRINT_MISMATCH",
                    "Queued audit fingerprint differs from the protocol artifact.",
                )
            next_state["fingerprints"]["audit"] = computed_audit
            target_gate = "final_audit"
            subject_refs = [
                f"claim:{state['fingerprints']['claim']}",
                f"audit:{computed_audit}",
            ]
        elif kind == "research_handoff":
            stage = validate_research_handoff(state, payload)
            target_gate = _gate_for_report({
                "search_runs": [{"stage": stage}]
            })
            subject_refs = [f"gate:{target_gate}"]
        elif kind == "research_report":
            checks = research_report_checks(payload, state, run_dir)
            if checks["errors"]:
                raise GapError(
                    "RESEARCH_REPORT_REJECTED",
                    "Research report failed deterministic checks.",
                    checks,
                )
            stage = report_stage(payload)
            if stage != "venue_map" and state["fingerprints"]["claim"] is None:
                raise GapError("CLAIM_REQUIRED", "This research stage needs a current claim.")
            target_gate = _gate_for_report(payload)
            _merge_report_into_ledger(next_ledger, payload)
            next_ledger["ledger_version"] += 1
            next_state["ledger_version"] = next_ledger["ledger_version"]
            subject_refs = [f"search:{item['id']}" for item in payload["search_runs"]]
        elif kind == "smoke_preregistration":
            validate_schema(payload, "smoke.schema.json")
            if state["fingerprints"]["claim"] is None:
                raise GapError("CLAIM_REQUIRED", "Smoke preregistration needs a current claim.")
            if payload.get("claim_fingerprint") != state["fingerprints"]["claim"]:
                raise GapError("PREREG_HASH_MISMATCH", "Preregistration claim hash is stale.")
            if payload.get("smoke_kind") not in ("technical", "precision"):
                raise GapError("SMOKE_KIND_INVALID", "Unknown Smoke kind.")
            if payload["smoke_kind"] == "precision":
                _validate_precision_plan(state, payload)
            if payload["smoke_kind"] == "technical":
                criteria = payload.get("technical_kill_criteria", [])
                criterion_ids = [item["criterion_id"] for item in criteria]
                if len(criterion_ids) != len(set(criterion_ids)):
                    raise GapError(
                        "TECHNICAL_CRITERION_ID_DUPLICATE",
                        "Technical kill criterion IDs must be unique within a preregistration.",
                    )
            computed_protocol = protocol_fingerprint(
                state["fingerprints"]["claim"], payload["protocol"]
            )
            current_protocol = state["fingerprints"]["protocol"]
            if current_protocol is not None and computed_protocol != current_protocol:
                raise GapError(
                    "USE_QUEUE_REVISION",
                    "A preregistration cannot replace the current protocol; queue the applicable dependency revision first.",
                )
            next_state["fingerprints"]["protocol"] = computed_protocol
            target_gate = "smoke"
            subject_refs = [f"claim:{state['fingerprints']['claim']}"]
        elif kind == "smoke_authorization":
            validate_smoke_authorization(run_dir, state, payload)
            target_gate = "smoke"
            subject_refs = [f"authorization:{payload['authorization_id']}"]
        elif kind == "smoke_result":
            validate_smoke_result(run_dir, state, payload)
            target_gate = "smoke"
            subject_refs = [f"authorization:{payload['authorization_id']}"]
        elif kind == "source_verification":
            target_gate = payload.get("gate")
            if target_gate not in GATE_NAMES[:-1]:
                raise GapError("VERIFICATION_GATE_INVALID", "Invalid verification gate.")
            if payload.get("outcome") not in ("PASS", "FAIL", "REVIEW"):
                raise GapError("VERIFICATION_OUTCOME_INVALID", "Invalid verification outcome.")
            if not payload.get("checks") or not payload.get("reviewer"):
                raise GapError("VERIFICATION_INCOMPLETE", "Verification needs checks and reviewer.")
            if not payload.get("artifact_ids_verified"):
                raise GapError(
                    "VERIFICATION_INCOMPLETE",
                    "Verification must name every artifact it checked.",
                )
            verified_ids = set(payload["artifact_ids_verified"])
            missing_ids = sorted(
                artifact_id for artifact_id in verified_ids
                if artifact_id not in state["artifacts"]
                or state["artifacts"][artifact_id]["status"] != "current"
            )
            if missing_ids:
                raise GapError(
                    "VERIFICATION_ARTIFACT_FK",
                    "Verification references missing or non-current artifacts.",
                    missing_ids,
                )
            gate_ids = set(state["gates"][target_gate]["artifact_ids"])
            if not verified_ids.issubset(gate_ids):
                raise GapError(
                    "VERIFICATION_GATE_MISMATCH",
                    "Verification artifacts are not subjects of the named gate.",
                    sorted(verified_ids - gate_ids),
                )
            required_checks = (
                "identity_verified", "locators_verified", "raw_hashes_verified"
            )
            if any(
                not isinstance(payload["checks"].get(check), bool)
                for check in required_checks
            ):
                raise GapError(
                    "VERIFICATION_INCOMPLETE",
                    "Verification checks need explicit booleans.",
                    list(required_checks),
                )
            if payload["outcome"] == "PASS" and not all(
                payload["checks"][check] for check in required_checks
            ):
                raise GapError(
                    "VERIFICATION_FALSE_PASS",
                    "A PASS verification cannot contain a failed identity, locator, or raw-hash check.",
                )
            subject_refs = [f"gate:{target_gate}"]
        elif kind == "scientific_audit":
            _verify_scientific_audit(state, payload)
            target_gate = payload["gate"]
            subject_ids = payload.get("subject_artifact_ids")
            if not isinstance(subject_ids, list) or not subject_ids:
                raise GapError(
                    "AUDIT_SUBJECT_REQUIRED",
                    "Scientific audit must name the current subject artifacts it judged.",
                )
            subject_set = set(subject_ids)
            missing_subjects = sorted(
                artifact_id for artifact_id in subject_set
                if artifact_id not in state["artifacts"]
                or state["artifacts"][artifact_id]["status"] != "current"
            )
            if missing_subjects:
                raise GapError(
                    "AUDIT_SUBJECT_FK",
                    "Scientific audit references missing or non-current subjects.",
                    missing_subjects,
                )
            gate_ids = set(state["gates"][target_gate]["artifact_ids"])
            if not subject_set.issubset(gate_ids):
                raise GapError(
                    "AUDIT_GATE_MISMATCH",
                    "Scientific audit subjects are not attached to the named gate.",
                    sorted(subject_set - gate_ids),
                )
            if target_gate != "smoke":
                subject_evidence: set[str] = set()
                for artifact_id in subject_set:
                    subject_record = state["artifacts"][artifact_id]
                    if subject_record["kind"] != "research_report":
                        continue
                    subject_report = _artifact_payload(run_dir, subject_record)
                    subject_evidence.update(
                        str(item["id"]) for item in subject_report.get("evidence", [])
                    )
                if (
                    not subject_evidence
                    or not set(payload["evidence_ids"]).issubset(subject_evidence)
                ):
                    raise GapError(
                        "AUDIT_EVIDENCE_FK",
                        "Scientific audit evidence must belong to its current report subjects.",
                    )
            else:
                smoke_subjects = [
                    (artifact_id, state["artifacts"][artifact_id])
                    for artifact_id in subject_set
                    if state["artifacts"][artifact_id]["kind"] == "smoke_result"
                ]
                allowed_evidence = {artifact_id for artifact_id, _ in smoke_subjects}
                for _, record in smoke_subjects:
                    allowed_evidence.add(
                        str(_artifact_payload(run_dir, record).get("result_id", ""))
                    )
                audit_evidence = set(payload["evidence_ids"])
                if (
                    not smoke_subjects
                    or not audit_evidence
                    or not audit_evidence.issubset(allowed_evidence)
                ):
                    raise GapError(
                        "AUDIT_EVIDENCE_FK",
                        "Every Smoke audit evidence ID must reference a current Smoke result or its artifact ID.",
                    )
            if (
                state["scope"].get("adapter") == "decision-policy"
                and payload.get("outcome") in ("PASS", "GO")
                and payload.get("decision_value_verified") is not True
            ):
                raise GapError(
                    "DECISION_VALUE_UNVERIFIED",
                    "Decision/policy GO requires a verified decision-value test.",
                )
            subject_refs = [
                *[f"evidence:{item}" for item in payload["evidence_ids"]],
                *[f"artifact:{item}" for item in sorted(subject_set)],
            ]
        elif kind == "experiment_freeze":
            validate_schema(payload, "experiment-freeze.schema.json")
            if any(state["gates"][gate]["status"] != "passed" for gate in GATE_NAMES[:-1]):
                raise GapError("UPSTREAM_GATES_NOT_PASSED", "Freeze requires four passed science gates.")
            for key in ("claim", "protocol", "audit"):
                if payload.get(f"{key}_fingerprint") != state["fingerprints"][key]:
                    raise GapError("FREEZE_HASH_MISMATCH", f"Freeze {key} hash is stale.")
            _validate_freeze_cross_fields(run_dir, state, payload)
            target_gate = "freeze_validation"
            subject_refs = [f"claim:{state['fingerprints']['claim']}"]

        record, created = _write_artifact(
            run_dir, next_state, kind, payload, subject_refs
        )
        if not created:
            return {
                "status": "idempotent",
                "artifact_id": record["artifact_id"],
                "manifest_revision": state["manifest_revision"],
            }
        if target_gate is not None:
            gate = next_state["gates"][target_gate]
            if record["artifact_id"] not in gate["artifact_ids"]:
                gate["artifact_ids"].append(record["artifact_id"])
            gate["subject_refs"] = sorted(set(gate["subject_refs"] + subject_refs))
            gate["status"] = (
                "awaiting_report" if kind == "research_handoff" else "validating"
            )
            gate["outcome"] = None
            gate["valid_for"] = _gate_record()["valid_for"]
            gate["validated_at"] = None
            gate["validator_version"] = None
            gate["reason_codes"] = []
            gate["unresolved_lead_ids"] = []
            gate["invalidated_by_event_id"] = None
        _advance_after_ingest(next_state, kind, payload)
        event_id = _event(
            next_state, "artifact_recorded",
            {"artifact_id": record["artifact_id"], "kind": kind},
        )
        next_state["manifest_revision"] += 1
        next_state["updated_at"] = utc_now()
        validate_schema(next_state, "run-state.schema.json")
        _commit_run_files(
            paths,
            state,
            ledger,
            candidates,
            next_state,
            next_ledger,
            next_candidates,
        )
        return {
            "status": "recorded",
            "artifact_id": record["artifact_id"],
            "event_id": event_id,
            "manifest_revision": next_state["manifest_revision"],
        }


def _gate_payloads(
    run_dir: Path, state: dict[str, Any], gate_name: str, kind: str
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for artifact_id in state["gates"][gate_name]["artifact_ids"]:
        record = state["artifacts"].get(artifact_id)
        if record and record["status"] == "current" and record["kind"] == kind:
            result.append((record, _artifact_payload(run_dir, record)))
    return result


def _validation_result(
    state: dict[str, Any],
    status: str,
    outcome: str | None,
    artifact_ids: Iterable[str],
    reasons: Iterable[str],
    unresolved: Iterable[str] = (),
    *,
    decision_eligible: bool = False,
    reported_outcome: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "outcome": outcome,
        "reported_outcome": (
            reported_outcome if reported_outcome is not None else outcome
        ),
        "decision_eligible": decision_eligible,
        "artifact_ids": sorted(set(artifact_ids)),
        "valid_for": {
            "claim_fingerprint": state["fingerprints"]["claim"],
            "protocol_fingerprint": state["fingerprints"]["protocol"],
            "audit_fingerprint": state["fingerprints"]["audit"],
            "ledger_version": state["ledger_version"],
        },
        "reason_codes": sorted(set(reasons)),
        "unresolved_lead_ids": sorted(set(unresolved)),
    }


def _verification_and_audit(
    run_dir: Path,
    state: dict[str, Any],
    gate_name: str,
    required_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str], list[str]]:
    reasons: list[str] = []
    used: list[str] = []
    verifications = _gate_payloads(run_dir, state, gate_name, "source_verification")
    audits = _gate_payloads(run_dir, state, gate_name, "scientific_audit")
    verification: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    for record, payload in reversed(verifications):
        covered = set(payload.get("artifact_ids_verified", []))
        if required_ids.issubset(covered):
            verification = payload
            used.append(record["artifact_id"])
            break
    if verification is None:
        reasons.append("SOURCE_VERIFICATION_MISSING")
    elif verification.get("outcome") == "FAIL":
        reasons.append("SOURCE_VERIFICATION_FAILED")
    elif verification.get("outcome") != "PASS":
        reasons.append("SOURCE_VERIFICATION_REVIEW")
    for record, payload in reversed(audits):
        bound_subjects = set(payload.get("subject_artifact_ids", []))
        relevant_hashes = {
            "venue_map": (),
            "falsification": ("claim",),
            "smoke": ("claim", "protocol"),
            "final_audit": ("claim", "protocol", "audit"),
        }[gate_name]
        hashes_current = all(
            payload.get(f"{key}_fingerprint") == state["fingerprints"][key]
            for key in relevant_hashes
        )
        if required_ids.issubset(bound_subjects) and hashes_current:
            audit = payload
            used.append(record["artifact_id"])
            break
    if audit is None:
        reasons.append("SCIENTIFIC_AUDIT_MISSING_OR_STALE")
    return verification, audit, reasons, used


def _critical_open(ledger: dict[str, Any]) -> list[str]:
    return sorted(
        lead_id for lead_id, lead in ledger.get("unresolved_leads", {}).items()
        if lead.get("severity") == "critical" and lead.get("status") == "open"
    )


def _research_stop_full_text_valid(
    report: dict[str, Any],
    audit: dict[str, Any],
    verification: dict[str, Any],
) -> bool:
    if verification.get("checks", {}).get("full_text_verified") is not True:
        return False
    evidence_by_id = {
        str(item["id"]): item for item in report.get("evidence", [])
    }
    sources_by_id = {
        str(item["id"]): item for item in report.get("sources", [])
    }
    cited = [str(item) for item in audit.get("evidence_ids", [])]
    if not cited:
        return False
    for evidence_id in cited:
        evidence = evidence_by_id.get(evidence_id)
        if (
            evidence is None
            or evidence.get("materiality") != "material"
            or not evidence.get("locator")
        ):
            return False
        source = sources_by_id.get(str(evidence.get("source_id")))
        if source is None or source.get("access_level") != "full_text":
            return False
    return True


def _research_gate_validation(
    run_dir: Path,
    state: dict[str, Any],
    ledger: dict[str, Any],
    gate_name: str,
    stage: str,
) -> dict[str, Any]:
    reports = [
        pair for pair in _gate_payloads(run_dir, state, gate_name, "research_report")
        if report_stage(pair[1]) == stage
    ]
    if not reports:
        return _validation_result(
            state, "awaiting_report", None, [], ["RESEARCH_REPORT_MISSING"]
        )
    report_record, report = reports[-1]
    check_state = copy.deepcopy(state)
    check_state["ledger_version"] = report["search_runs"][0]["base_ledger_version"]
    checks = research_report_checks(report, check_state, run_dir)
    required_ids = {report_record["artifact_id"]}
    verification, audit, reasons, used = _verification_and_audit(
        run_dir, state, gate_name, required_ids
    )
    reasons.extend(checks["errors"])
    unresolved = sorted(set(checks["critical_open"] + _critical_open(ledger)))
    if unresolved:
        reasons.append("CRITICAL_UNRESOLVED_LEADS")
    artifact_ids = [report_record["artifact_id"], *used]
    if reasons:
        return _validation_result(
            state,
            "review_required",
            None,
            artifact_ids,
            reasons,
            unresolved,
            reported_outcome=audit.get("outcome") if audit else None,
        )
    assert verification is not None and audit is not None
    outcome = audit.get("outcome")
    if outcome == "NARROW":
        return _validation_result(
            state,
            "review_required",
            outcome,
            artifact_ids,
            ["NARROW_REQUIRED"],
            decision_eligible=True,
        )
    if outcome in ("BLOCKED", "INSUFFICIENT_EVIDENCE", "FAIL"):
        return _validation_result(
            state,
            "failed",
            outcome,
            artifact_ids,
            [outcome],
            decision_eligible=outcome in ("BLOCKED", "INSUFFICIENT_EVIDENCE"),
        )
    allowed = {
        "venue_map": {"PASS", "GO"},
        "falsification": {"PASS", "GO", "STOP"},
        "final_audit": {"PASS", "GO", "STOP"},
    }[gate_name]
    if outcome not in allowed:
        return _validation_result(
            state,
            "failed",
            "FAIL",
            artifact_ids,
            ["AUDIT_OUTCOME_NOT_ALLOWED"],
            reported_outcome=outcome,
        )
    if outcome == "STOP":
        if not _research_stop_full_text_valid(report, audit, verification):
            return _validation_result(
                state,
                "review_required",
                None,
                artifact_ids,
                ["STOP_REQUIRES_VERIFIED_FULL_TEXT"],
                reported_outcome=outcome,
            )
        return _validation_result(
            state,
            "failed",
            outcome,
            artifact_ids,
            ["CLAIM_STOPPED"],
            decision_eligible=True,
        )
    if stage == "final_audit":
        expected = state["fingerprints"]["audit"]
        supplied = {item.get("audit_fingerprint") for item in report["search_runs"]}
        if expected is None or supplied != {expected}:
            return _validation_result(
                state, "failed", outcome, artifact_ids, ["AUDIT_FINGERPRINT_STALE"]
            )
    return _validation_result(
        state, "passed", outcome, artifact_ids, [], decision_eligible=True
    )


HARD_STOP_BASES = {
    "LEAKAGE", "INFEASIBLE_COST", "NO_ORACLE_HEADROOM",
    "NON_DISCRIMINATING", "DATA_INVALID",
}


def _precision_stop_valid(
    preregistration: dict[str, Any], result: dict[str, Any]
) -> bool:
    if (
        result.get("smoke_kind") != "precision"
        or result.get("precision_adequate") is not True
        or result.get("p_value_only") is True
        or result.get("confidence_class") != "adequate"
    ):
        return False
    try:
        _validate_precision_evidence(preregistration, result)
        plan = preregistration["precision_plan"]
        evidence = result["precision_evidence"]
        framework = plan["framework"]
        if result.get("stop_basis") != framework:
            return False
        if framework in ("TOST", "CI_EQUIVALENCE"):
            return (
                _decimal_value(evidence["interval_lower"], "interval_lower")
                > _decimal_value(plan["lower_margin"], "lower_margin")
                and _decimal_value(evidence["interval_upper"], "interval_upper")
                < _decimal_value(plan["upper_margin"], "upper_margin")
            )
        if framework == "BAYESIAN_ROPE":
            return _decimal_value(
                evidence["posterior_mass_in_rope"], "posterior_mass_in_rope"
            ) >= _decimal_value(plan["posterior_threshold"], "posterior_threshold")
        if framework == "FUTILITY":
            rule = plan["futility_rule"]
            observation = evidence["futility_observation"]
            return _criterion_comparison_met(
                observation.get("value"),
                str(rule.get("operator")),
                rule.get("threshold"),
            )
    except (GapError, KeyError, TypeError):
        return False
    return False


def _result_evidence_ref_value(
    result: dict[str, Any], reference: Any
) -> tuple[bool, Any]:
    if not isinstance(reference, str):
        return False, None
    prefix = f"result:{result.get('result_id')}#/results/"
    if not reference.startswith(prefix):
        return False, None
    tokens = reference[len(prefix):].split("/")
    node: Any = result.get("results")
    try:
        for token in tokens:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                node = node[token]
            elif isinstance(node, list):
                node = node[int(token)]
            else:
                return False, None
    except (KeyError, IndexError, TypeError, ValueError):
        return False, None
    return node is not None, node


def _result_evidence_ref_valid(result: dict[str, Any], reference: Any) -> bool:
    return _result_evidence_ref_value(result, reference)[0]


def _criterion_comparison_met(
    observed: Any, operator: str, threshold: Any
) -> bool:
    if operator in ("==", "!="):
        equal = canonical_json(observed) == canonical_json(threshold)
        return equal if operator == "==" else not equal
    try:
        left = _decimal_value(observed, "hard_stop_evidence.observation.value")
        right = _decimal_value(threshold, "technical_kill_criteria.threshold")
    except GapError:
        return False
    return {
        ">": left > right,
        ">=": left >= right,
        "<": left < right,
        "<=": left <= right,
    }.get(operator, False)


def _technical_hard_stop_valid(
    preregistration: dict[str, Any], result: dict[str, Any]
) -> bool:
    basis = result.get("stop_basis")
    evidence = result.get("hard_stop_evidence")
    if not isinstance(evidence, dict):
        return False
    criteria = preregistration.get("technical_kill_criteria", [])
    criterion = next(
        (
            item for item in criteria
            if isinstance(item, dict)
            and item.get("criterion_id") == evidence.get("criterion_id")
        ),
        None,
    )
    if not isinstance(criterion, dict):
        return False
    observation = evidence.get("observation")
    references = evidence.get("evidence_refs", [])
    expected_reference = (
        f"result:{result.get('result_id')}#/results/{criterion.get('measure')}"
    )
    resolved = [
        _result_evidence_ref_value(result, reference)
        for reference in references
        if reference == expected_reference
    ]
    observed_values = [value for valid, value in resolved if valid]
    return (
        result.get("smoke_kind") == "technical"
        and basis in HARD_STOP_BASES
        and criterion.get("basis") == basis
        and evidence.get("basis") == basis
        and isinstance(observation, dict)
        and observation.get("unit") == criterion.get("unit")
        and bool(observed_values)
        and any(
            canonical_json(value) == canonical_json(observation.get("value"))
            for value in observed_values
        )
        and _criterion_comparison_met(
            observation.get("value"),
            str(criterion.get("operator")),
            criterion.get("threshold"),
        )
        and all(
            _result_evidence_ref_valid(result, reference)
            for reference in references
        )
        and result.get("p_value_only") is not True
    )


def _current_smoke_chain(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, tuple[dict[str, Any], dict[str, Any]] | None]:
    preregs = _gate_payloads(run_dir, state, "smoke", "smoke_preregistration")
    chain: dict[str, tuple[dict[str, Any], dict[str, Any]] | None] = {
        "preregistration": preregs[-1] if preregs else None,
        "authorization": None,
        "result": None,
    }
    if not preregs:
        return chain
    prereg_record, prereg = preregs[-1]
    auths = [
        item
        for item in _gate_payloads(run_dir, state, "smoke", "smoke_authorization")
        if item[1].get("preregistration_hash") == prereg_record["sha256"]
        and item[1].get("smoke_kind") == prereg.get("smoke_kind")
    ]
    if not auths:
        return chain
    auth_record, auth = auths[-1]
    chain["authorization"] = (auth_record, auth)
    results = [
        item
        for item in _gate_payloads(run_dir, state, "smoke", "smoke_result")
        if item[1].get("authorization_id") == auth.get("authorization_id")
        and item[1].get("preregistration_hash") == prereg_record["sha256"]
        and item[1].get("smoke_kind") == prereg.get("smoke_kind")
    ]
    if results:
        chain["result"] = results[-1]
    return chain


def _smoke_gate_validation(
    run_dir: Path, state: dict[str, Any]
) -> dict[str, Any]:
    chain = _current_smoke_chain(run_dir, state)
    prereg_item = chain["preregistration"]
    auth_item = chain["authorization"]
    result_item = chain["result"]
    if prereg_item is None:
        return _validation_result(
            state, "awaiting_report", None, [], ["SMOKE_PREREGISTRATION_MISSING"]
        )
    prereg_record, prereg = prereg_item
    if auth_item is None:
        return _validation_result(
            state, "review_required", None, [prereg_record["artifact_id"]],
            ["SMOKE_AUTHORIZATION_MISSING"],
        )
    auth_record, auth = auth_item
    if result_item is None:
        return _validation_result(
            state, "awaiting_report", None,
            [prereg_record["artifact_id"], auth_record["artifact_id"]],
            ["SMOKE_RESULT_MISSING"],
        )
    result_record, result = result_item
    required_ids = {prereg_record["artifact_id"], result_record["artifact_id"]}
    verification, audit, reasons, used = _verification_and_audit(
        run_dir, state, "smoke", required_ids
    )
    artifact_ids = [
        prereg_record["artifact_id"], auth_record["artifact_id"],
        result_record["artifact_id"], *used,
    ]
    try:
        validate_smoke_authorization(run_dir, state, auth)
        validate_smoke_result(run_dir, state, result)
    except GapError as exc:
        reasons.append(exc.code)
    if result.get("confidence_class") == "wide" or result.get("p_value_only") is True:
        reasons.append("INSUFFICIENT_PRECISION")
    if audit is None:
        return _validation_result(
            state, "review_required", None, artifact_ids, reasons
        )
    outcome = audit.get("outcome")
    if outcome == "STOP" and not (
        _precision_stop_valid(prereg, result)
        or _technical_hard_stop_valid(prereg, result)
    ):
        reasons.append("STOP_REQUIRES_BOUND_KILL_CRITERION")
    if outcome == "NARROW":
        eligible = not reasons
        reasons.append("NARROW_REQUIRED")
        return _validation_result(
            state,
            "review_required",
            outcome if eligible else None,
            artifact_ids,
            reasons,
            decision_eligible=eligible,
            reported_outcome=outcome,
        )
    if outcome in ("BLOCKED", "INSUFFICIENT_EVIDENCE", "FAIL"):
        non_scientific_reasons = [
            reason for reason in reasons
            if not (
                outcome == "INSUFFICIENT_EVIDENCE"
                and reason == "INSUFFICIENT_PRECISION"
            )
        ]
        if non_scientific_reasons:
            return _validation_result(
                state,
                "review_required",
                None,
                artifact_ids,
                [*reasons, outcome],
                reported_outcome=outcome,
            )
        return _validation_result(
            state,
            "failed",
            outcome,
            artifact_ids,
            [*reasons, outcome],
            decision_eligible=outcome in ("BLOCKED", "INSUFFICIENT_EVIDENCE"),
        )
    if reasons:
        return _validation_result(
            state,
            "review_required",
            None,
            artifact_ids,
            reasons,
            reported_outcome=outcome,
        )
    if outcome not in ("PASS", "GO", "STOP"):
        return _validation_result(
            state,
            "failed",
            "FAIL",
            artifact_ids,
            ["AUDIT_OUTCOME_NOT_ALLOWED"],
            reported_outcome=outcome,
        )
    if outcome == "STOP":
        return _validation_result(
            state,
            "failed",
            outcome,
            artifact_ids,
            ["CLAIM_STOPPED"],
            decision_eligible=True,
        )
    return _validation_result(
        state, "passed", outcome, artifact_ids, [], decision_eligible=True
    )


def _freeze_gate_validation(
    run_dir: Path, state: dict[str, Any], science: dict[str, Any]
) -> dict[str, Any]:
    upstream = GATE_NAMES[:-1]
    reasons: list[str] = []
    for gate_name in upstream:
        result = science[gate_name]
        if result["status"] != "passed":
            reasons.append(f"UPSTREAM_NOT_PASSED:{gate_name}")
        for key in ("claim", "protocol", "audit"):
            if result["valid_for"][f"{key}_fingerprint"] != state["fingerprints"][key]:
                reasons.append(f"UPSTREAM_HASH_STALE:{gate_name}:{key}")
        if result["valid_for"]["ledger_version"] != state["ledger_version"]:
            reasons.append(f"UPSTREAM_LEDGER_STALE:{gate_name}")
    freezes = _gate_payloads(
        run_dir, state, "freeze_validation", "experiment_freeze"
    )
    if not freezes:
        reasons.append("EXPERIMENT_FREEZE_MISSING")
        return _validation_result(state, "awaiting_report", None, [], reasons)
    freeze_record, freeze = freezes[-1]
    artifact_ids = [freeze_record["artifact_id"]]
    try:
        validate_schema(freeze, "experiment-freeze.schema.json")
    except GapError as exc:
        reasons.append(exc.code)
    for key in ("claim", "protocol", "audit"):
        if freeze.get(f"{key}_fingerprint") != state["fingerprints"][key]:
            reasons.append(f"FREEZE_HASH_STALE:{key}")
    if freeze.get("decision", {}).get("status") != "GO":
        reasons.append("FREEZE_DECISION_MUST_BE_GO")
    chain = _current_smoke_chain(run_dir, state)
    auth_item = chain["authorization"]
    result_item = chain["result"]
    expires: Any = None
    if auth_item is None or result_item is None:
        reasons.append("CURRENT_SMOKE_CHAIN_MISSING")
    else:
        auth = auth_item[1]
        result = result_item[1]
        if result.get("authorization_id") != auth.get("authorization_id"):
            reasons.append("SMOKE_AUTHORIZATION_CHAIN_BROKEN")
        if auth.get("status") != "active":
            reasons.append("SMOKE_AUTHORIZATION_NOT_ACTIVE")
        expires = auth.get("expires_at")
    if expires:
        try:
            parsed_expiry = dt.datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if parsed_expiry.tzinfo is None:
                parsed_expiry = parsed_expiry.replace(tzinfo=dt.timezone.utc)
            if parsed_expiry < dt.datetime.now(dt.timezone.utc):
                reasons.append("SMOKE_AUTHORIZATION_EXPIRED")
        except (AttributeError, TypeError, ValueError):
            reasons.append("SMOKE_AUTHORIZATION_EXPIRY_INVALID")
    status = "passed" if not reasons else "review_required"
    return _validation_result(
        state,
        status,
        "GO" if status == "passed" else None,
        artifact_ids,
        reasons,
        decision_eligible=status == "passed",
    )


def derive_validation(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    validate_schema(state, "run-state.schema.json")
    ledger = read_json(run_paths(run_dir)["ledger"])
    science = {
        "venue_map": _research_gate_validation(
            run_dir, state, ledger, "venue_map", "venue_map"
        ),
        "falsification": _research_gate_validation(
            run_dir, state, ledger, "falsification", "falsification"
        ),
        "smoke": _smoke_gate_validation(run_dir, state),
        "final_audit": _research_gate_validation(
            run_dir, state, ledger, "final_audit", "final_audit"
        ),
    }
    science["freeze_validation"] = _freeze_gate_validation(run_dir, state, science)
    report_qa: dict[str, Any] = {}
    for gate_name in ("venue_map", "falsification", "final_audit"):
        for record, report in _gate_payloads(
            run_dir, state, gate_name, "research_report"
        ):
            check_state = copy.deepcopy(state)
            check_state["ledger_version"] = report["search_runs"][0][
                "base_ledger_version"
            ]
            checks = research_report_checks(report, check_state, run_dir)
            report_qa[str(report["report_id"])] = {
                "artifact_id": record["artifact_id"],
                "gate": gate_name,
                "report_id": report["report_id"],
                "stage": checks["stage"],
                "checks": checks["qa_checks"],
                "errors": checks["errors"],
                "critical_open": checks["critical_open"],
                "structurally_ready": checks["structurally_ready"],
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "run_id": state["run_id"],
        "base_manifest_revision": state["manifest_revision"],
        "input_state_sha256": sha256_data(state),
        "derived_from_updated_at": state["updated_at"],
        "gate_results": science,
        "report_qa": report_qa,
        "limitations": [
            "Validator checks structure, references, locators, versions, and hashes.",
            "Validator does not prove searches ran, evidence entails propositions, completeness, or novelty.",
        ],
    }


def _append_verdict_once(
    state: dict[str, Any], gate_name: str, outcome: str, validation_id: str
) -> None:
    key = (gate_name, outcome, validation_id)
    existing = {
        (item.get("gate"), item.get("outcome"), item.get("validation_artifact_id"))
        for item in state["verdict_history"]
    }
    if key not in existing:
        state["verdict_history"].append({
            "gate": gate_name,
            "outcome": outcome,
            "claim_version": state["claim"]["current_version"],
            "claim_fingerprint": state["fingerprints"]["claim"],
            "validation_artifact_id": validation_id,
            "recorded_at": utc_now(),
        })


def _project_nonterminal_state(
    run_dir: Path,
    state: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    """Project phase/status from the earliest current gate, never future gates."""
    results = validation["gate_results"]
    phase_for_gate = {
        "venue_map": "venue_map",
        "falsification": "falsification",
        "smoke": "smoke",
        "final_audit": "final_audit",
        "freeze_validation": "freeze",
    }
    for outcome, run_status in (
        ("BLOCKED", "blocked"),
        ("INSUFFICIENT_EVIDENCE", "insufficient_evidence"),
        ("NARROW", "awaiting_user"),
    ):
        for gate_name in GATE_NAMES:
            if (
                results[gate_name]["outcome"] == outcome
                and results[gate_name].get("decision_eligible") is True
            ):
                state["phase"] = phase_for_gate[gate_name]
                state["run_status"] = run_status
                return

    venue = results["venue_map"]
    if venue["status"] != "passed":
        state["phase"] = "venue_map"
        state["run_status"] = (
            "awaiting_research" if venue["status"] == "awaiting_report" else "active"
        )
        return

    candidates = read_json(run_paths(run_dir)["candidates"])
    board_status = candidates.get("board_status", "empty")
    if state["claim"]["current"] is None or board_status in (
        "empty", "no_viable_candidate"
    ):
        state["phase"] = "discovery"
        state["run_status"] = "active"
        return

    falsification = results["falsification"]
    if falsification["status"] != "passed":
        state["phase"] = "falsification"
        state["run_status"] = (
            "awaiting_research"
            if falsification["status"] == "awaiting_report"
            else "active"
        )
        return
    if board_status != "ready_for_smoke":
        state["phase"] = "falsification"
        state["run_status"] = "active"
        return

    smoke = results["smoke"]
    if smoke["status"] != "passed":
        state["phase"] = "smoke"
        reasons = set(smoke["reason_codes"])
        state["run_status"] = "active"
        if "SMOKE_AUTHORIZATION_MISSING" in reasons:
            state["run_status"] = "awaiting_user"
        elif "SMOKE_RESULT_MISSING" in reasons:
            latest_auth = _latest_payload(run_dir, state, "smoke_authorization")
            if latest_auth is None or not latest_auth[1]["permissions"]["execute_local"]:
                state["run_status"] = "awaiting_user"
        return

    final_audit = results["final_audit"]
    if final_audit["status"] != "passed":
        state["phase"] = "final_audit"
        state["run_status"] = (
            "awaiting_research"
            if final_audit["status"] == "awaiting_report"
            else "active"
        )
        return

    state["phase"] = "freeze"
    state["run_status"] = "active"


def commit_validation(
    run_dir: Path, expected_revision: int
) -> dict[str, Any]:
    paths = run_paths(run_dir)
    with exclusive_lock(paths["lock"]):
        state = load_state(run_dir)
        if state["manifest_revision"] != expected_revision:
            raise GapError(
                "STALE_REVISION",
                f"Expected revision {expected_revision}, current is {state['manifest_revision']}.",
            )
        validation = derive_validation(run_dir)
        next_state = copy.deepcopy(state)
        record, _ = _write_artifact(
            run_dir, next_state, "gate_validation", validation, ["run:" + state["run_id"]]
        )
        validated_at = utc_now()
        for gate_name, result in validation["gate_results"].items():
            gate = next_state["gates"][gate_name]
            gate["status"] = result["status"]
            gate["outcome"] = result["outcome"]
            gate["artifact_ids"] = sorted(
                set(gate["artifact_ids"] + result["artifact_ids"])
            )
            gate["valid_for"] = result["valid_for"]
            gate["validated_at"] = validated_at
            gate["validator_version"] = VALIDATOR_VERSION
            gate["reason_codes"] = result["reason_codes"]
            gate["unresolved_lead_ids"] = result["unresolved_lead_ids"]
            gate["invalidated_by_event_id"] = None
            if (
                result.get("decision_eligible") is True
                and result["outcome"] in (
                "STOP", "NARROW", "BLOCKED", "INSUFFICIENT_EVIDENCE"
                )
            ):
                _append_verdict_once(
                    next_state, gate_name, result["outcome"], record["artifact_id"]
                )
        outcomes = {
            gate: (
                result["outcome"]
                if result.get("decision_eligible") is True
                else None
            )
            for gate, result in validation["gate_results"].items()
        }
        if validation["gate_results"]["freeze_validation"]["status"] == "passed":
            next_state["decision"] = "GO"
            next_state["phase"] = "closed"
            next_state["run_status"] = "complete"
        elif "STOP" in outcomes.values():
            next_state["decision"] = "STOP"
            next_state["phase"] = "closed"
            next_state["run_status"] = "complete"
        else:
            _project_nonterminal_state(run_dir, next_state, validation)
        event_id = _event(
            next_state, "validation_committed",
            {"validation_artifact_id": record["artifact_id"]},
        )
        next_state["manifest_revision"] += 1
        next_state["updated_at"] = utc_now()
        validate_schema(next_state, "run-state.schema.json")
        qa_path = paths["qa"] / f"{record['artifact_id']}.json"
        atomic_write_json(qa_path, validation)
        atomic_write_json(paths["state"], next_state)
        return {
            "status": "validated",
            "artifact_id": record["artifact_id"],
            "event_id": event_id,
            "manifest_revision": next_state["manifest_revision"],
            "gate_results": validation["gate_results"],
            "report_qa": validation["report_qa"],
        }


def _invalidate_gate_artifacts(
    state: dict[str, Any], gate_name: str, action: str
) -> list[str]:
    changed: list[str] = []
    status = "stale" if action == "I" else "review_required"
    for artifact_id in state["gates"][gate_name]["artifact_ids"]:
        record = state["artifacts"].get(artifact_id)
        if record and record["status"] == "current":
            record["status"] = status
            changed.append(artifact_id)
    return changed


def _earliest_phase(actions: dict[str, str]) -> str:
    mapping = {
        "venue_map": "venue_map",
        "falsification": "falsification",
        "smoke": "smoke",
        "final_audit": "final_audit",
        "freeze_validation": "freeze",
    }
    for gate in GATE_NAMES:
        if actions[gate] in ("I", "R"):
            return mapping[gate]
    return "freeze"


def _revision_evidence_ref_valid(
    state: dict[str, Any], ledger: dict[str, Any], reference: str
) -> bool:
    artifact_id = reference.removeprefix("artifact:")
    artifact = state["artifacts"].get(artifact_id)
    if artifact is not None and artifact.get("status") == "current":
        return True
    if reference.startswith("evidence:"):
        return reference.split(":", 1)[1] in ledger.get("evidence", {})
    if reference.startswith("doi:"):
        return bool(re.match(r"^doi:10\.\d{4,9}/\S+$", reference, re.IGNORECASE))
    if reference.startswith("arxiv:"):
        return bool(reference.split(":", 1)[1].strip())
    if reference.startswith(("url:https://", "url:http://")):
        return True
    if reference.startswith(("repository:https://", "repository:http://")):
        return True
    return False


def queue_revision(
    run_dir: Path,
    change_type: str,
    reason: str,
    expected_revision: int,
    new_claim: dict[str, Any] | None = None,
    new_protocol: dict[str, Any] | None = None,
    new_audit_spec: dict[str, Any] | None = None,
    narrow: bool = False,
    new_scope: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    if change_type not in DEPENDENCY_MATRIX:
        raise GapError("CHANGE_TYPE_INVALID", f"Unknown change type: {change_type}")
    if not reason.strip():
        raise GapError("REVISION_REASON_REQUIRED", "Revision reason cannot be empty.")
    paths = run_paths(run_dir)
    with exclusive_lock(paths["lock"]):
        state = load_state(run_dir)
        ledger = read_json(paths["ledger"])
        if state["manifest_revision"] != expected_revision:
            raise GapError(
                "STALE_REVISION",
                f"Expected revision {expected_revision}, current is {state['manifest_revision']}.",
            )
        next_state = copy.deepcopy(state)
        revision_evidence = sorted(set(evidence_refs or []))
        if any(not isinstance(ref, str) or not ref.strip() for ref in revision_evidence):
            raise GapError("REVISION_EVIDENCE_INVALID", "Revision evidence refs must be non-empty strings.")
        if state["decision"] == "STOP":
            raise GapError(
                "STOP_RUN_CLOSED",
                "A closed STOP run cannot be revised in v1; start a new run.",
            )
        if state["decision"] == "GO":
            if narrow:
                raise GapError(
                    "NARROW_REQUIRES_REOPENED_EVIDENCE",
                    "A frozen GO must first be reopened by a material non-NARROW evidence revision.",
                )
            if change_type == "formatting" or not revision_evidence:
                raise GapError(
                    "GO_REOPEN_EVIDENCE_REQUIRED",
                    "A frozen GO may reopen only for a material revision with traceable evidence refs.",
                )
        narrow_verdict: dict[str, Any] | None = None
        if narrow:
            if new_claim is None:
                raise GapError(
                    "NEW_CLAIM_REQUIRED",
                    "NARROW requires a complete replacement claim.",
                )
            narrow_verdict = next((
                verdict for verdict in reversed(state["verdict_history"])
                if verdict.get("outcome") == "NARROW"
                and verdict.get("claim_version") == state["claim"]["current_version"]
                and verdict.get("claim_fingerprint") == state["fingerprints"]["claim"]
                and state["gates"].get(verdict.get("gate"), {}).get("status")
                == "review_required"
                and state["gates"].get(verdict.get("gate"), {}).get("outcome")
                == "NARROW"
            ), None)
            if narrow_verdict is None or state["run_status"] != "awaiting_user":
                raise GapError(
                    "NARROW_VERDICT_REQUIRED",
                    "NARROW requires a committed scientific verdict for the current claim.",
                )
            revision_evidence = sorted(set([
                *revision_evidence,
                narrow_verdict["validation_artifact_id"],
            ]))
        invalid_evidence = [
            reference for reference in revision_evidence
            if not _revision_evidence_ref_valid(state, ledger, reference)
        ]
        if invalid_evidence:
            raise GapError(
                "REVISION_EVIDENCE_UNRESOLVED",
                "Revision evidence refs must resolve to current artifacts, ledger evidence, or stable external identifiers.",
                invalid_evidence,
            )
        if change_type == "venue_scope" and new_scope is None:
            raise GapError("NEW_SCOPE_REQUIRED", "venue_scope revision requires --scope.")
        if change_type in ("claim_semantics", "target_distribution") and new_claim is None:
            raise GapError(
                "NEW_CLAIM_REQUIRED",
                f"{change_type} revision requires a complete new claim.",
            )
        if new_scope is not None:
            if change_type != "venue_scope":
                raise GapError(
                    "CHANGE_CLASS_MISMATCH",
                    "A scope replacement must use change_type venue_scope.",
                )
            required_scope = {"venue", "topic", "adapter", "date_window"}
            if required_scope - set(new_scope):
                raise GapError(
                    "NEW_SCOPE_INCOMPLETE",
                    "Scope replacement is incomplete.",
                    sorted(required_scope - set(new_scope)),
                )
            if new_scope["adapter"] not in ("ai-ml", "decision-policy"):
                raise GapError("INVALID_ADAPTER", "Scope adapter is invalid.")
            next_state["scope"] = new_scope
        if narrow and next_state["governance"]["narrow_count"] >= next_state["governance"]["narrow_limit"]:
            next_state["run_status"] = "blocked"
            next_state["blockers"].append({
                "code": "NARROW_LIMIT_REACHED",
                "reason": reason,
                "recorded_at": utc_now(),
            })
            event_id = _event(next_state, "narrow_limit_reached", {"reason": reason})
            next_state["manifest_revision"] += 1
            next_state["updated_at"] = utc_now()
            validate_schema(next_state, "run-state.schema.json")
            atomic_write_json(paths["state"], next_state)
            return {
                "status": "blocked",
                "event_id": event_id,
                "manifest_revision": next_state["manifest_revision"],
            }

        old_fingerprints = copy.deepcopy(state["fingerprints"])
        if new_claim is not None:
            new_hash = _validate_claim(new_claim)
            if change_type == "formatting" and new_hash != old_fingerprints["claim"]:
                raise GapError(
                    "FORMAT_CHANGE_NOT_SEMANTICALLY_NEUTRAL",
                    "Formatting revision changed the claim fingerprint.",
                )
            version = next_state["claim"]["current_version"] + 1
            next_state["claim"]["current_version"] = version
            next_state["claim"]["current"] = new_claim
            next_state["claim"]["history"].append({
                "version": version,
                "claim_fingerprint": new_hash,
                "recorded_at": utc_now(),
                "claim": new_claim,
            })
            next_state["fingerprints"]["claim"] = new_hash
            if (
                new_hash != old_fingerprints["claim"]
                and change_type not in (
                    "venue_scope", "claim_semantics", "endpoint_sesoi",
                    "target_distribution",
                )
            ):
                raise GapError(
                    "CHANGE_CLASS_MISMATCH",
                    "Declared change type understates a changed claim fingerprint.",
                )
            if (
                change_type in ("claim_semantics", "target_distribution")
                and new_hash == old_fingerprints["claim"]
            ):
                raise GapError(
                    "CHANGE_CLASS_MISMATCH",
                    f"{change_type} did not change the claim fingerprint.",
                )
            if narrow and new_hash == old_fingerprints["claim"]:
                raise GapError(
                    "NARROW_NOT_SEMANTIC",
                    "NARROW must change the scientific claim fingerprint.",
                )
        if new_protocol is not None:
            next_state["fingerprints"]["protocol"] = protocol_fingerprint(
                next_state["fingerprints"]["claim"], new_protocol
            )
            if (
                next_state["fingerprints"]["protocol"] != old_fingerprints["protocol"]
                and change_type in (
                    "final_audit_cutoff", "global_cutoff",
                    "closest_nonmaterial", "formatting",
                )
            ):
                raise GapError(
                    "CHANGE_CLASS_MISMATCH",
                    "Declared change type understates a changed protocol fingerprint.",
                )
        elif change_type in (
            "venue_scope", "claim_semantics", "baseline", "endpoint_sesoi",
            "implementation", "target_distribution",
        ):
            next_state["fingerprints"]["protocol"] = None
        if new_audit_spec is not None:
            next_state["fingerprints"]["audit"] = audit_fingerprint(
                next_state["fingerprints"]["claim"], new_audit_spec
            )
        elif change_type != "formatting":
            next_state["fingerprints"]["audit"] = None
        if narrow:
            next_state["governance"]["narrow_count"] += 1
        if (
            change_type == "formatting"
            and next_state["fingerprints"] != old_fingerprints
        ):
            raise GapError(
                "FORMAT_CHANGE_NOT_SEMANTICALLY_NEUTRAL",
                "Formatting revision changed a fingerprint.",
            )

        revision_payload = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "gap_revision",
            "revision_id": f"revision-r{state['manifest_revision'] + 1}",
            "base_manifest_revision": state["manifest_revision"],
            "change_type": change_type,
            "reason": reason,
            "narrow": narrow,
            "evidence_refs": revision_evidence,
            "claim": {
                "from_version": state["claim"]["current_version"],
                "to_version": next_state["claim"]["current_version"],
                "before": state["claim"]["current"],
                "after": next_state["claim"]["current"],
            },
            "scope": {"before": state["scope"], "after": next_state["scope"]},
            "fingerprints": {
                "before": old_fingerprints,
                "after": next_state["fingerprints"],
            },
            "protocol_input": new_protocol,
            "audit_spec": new_audit_spec,
            "recorded_at": utc_now(),
        }
        revision_record, _ = _write_artifact(
            run_dir,
            next_state,
            "gap_revision",
            revision_payload,
            [f"claim:{old_fingerprints['claim']}", *revision_evidence],
        )
        actions = dict(zip(MATRIX_GATES, DEPENDENCY_MATRIX[change_type]))
        event_id = _event(
            next_state,
            "revision_queued",
            {
                "change_type": change_type,
                "reason": reason,
                "narrow": narrow,
                "actions": actions,
                "revision_artifact_id": revision_record["artifact_id"],
                "evidence_refs": revision_evidence,
                "old_fingerprints": old_fingerprints,
                "new_fingerprints": next_state["fingerprints"],
            },
        )
        preserved: list[str] = []
        invalidated: list[str] = []
        review: list[str] = []
        for gate_name, action in actions.items():
            gate = next_state["gates"][gate_name]
            if action == "P":
                preserved.append(gate_name)
                continue
            changed = _invalidate_gate_artifacts(next_state, gate_name, action)
            gate["status"] = "stale" if action == "I" else "review_required"
            gate["outcome"] = None
            gate["reason_codes"] = [
                "INVALIDATED_BY_REVISION" if action == "I" else "REVISION_REVIEW_REQUIRED"
            ]
            gate["invalidated_by_event_id"] = event_id
            if action == "I":
                invalidated.extend([gate_name, *changed])
            else:
                review.extend([gate_name, *changed])
        next_state["phase"] = _earliest_phase(actions)
        next_state["run_status"] = "ready"
        next_state["decision"] = "undecided"
        next_state["manifest_revision"] += 1
        next_state["updated_at"] = utc_now()
        validate_schema(next_state, "run-state.schema.json")
        atomic_write_json(paths["state"], next_state)
        return {
            "status": "queued",
            "event_id": event_id,
            "revision_artifact_id": revision_record["artifact_id"],
            "manifest_revision": next_state["manifest_revision"],
            "preserved": sorted(preserved),
            "invalidated": sorted(set(invalidated)),
            "requires_review": sorted(set(review)),
            "fingerprints": next_state["fingerprints"],
        }


def status_summary(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    gates = {
        name: {
            "status": gate["status"],
            "outcome": gate["outcome"],
            "reason_codes": gate["reason_codes"],
            "valid_for": gate["valid_for"],
        }
        for name, gate in state["gates"].items()
    }
    next_actions: list[str] = []
    if state["run_status"] == "complete":
        next_actions.append("No state transition required.")
    elif state["run_status"] == "blocked":
        next_actions.append("Resolve blockers or close the run.")
    elif state["run_status"] == "insufficient_evidence":
        next_actions.append("Design an adequately powered Precision Smoke.")
    elif any(gate["status"] == "review_required" for gate in state["gates"].values()):
        next_actions.append("Review affected artifacts; queue NARROW if claim changes.")
    elif state["phase"] in ("venue_map", "falsification", "final_audit"):
        next_actions.append("Obtain and ingest the required Deep Research sidecar.")
    elif state["phase"] == "smoke":
        next_actions.append("Freeze preregistration, obtain authorization, or ingest Smoke results.")
    elif state["phase"] == "freeze":
        next_actions.append("Ingest Freeze JSON, commit validation, then finalize.")
    else:
        next_actions.append("Compare candidates in ordinary conversation.")
    return {
        "run_id": state["run_id"],
        "manifest_revision": state["manifest_revision"],
        "ledger_version": state["ledger_version"],
        "phase": state["phase"],
        "run_status": state["run_status"],
        "decision": state["decision"],
        "claim_version": state["claim"]["current_version"],
        "fingerprints": state["fingerprints"],
        "gates": gates,
        "next_actions": next_actions,
    }


def _bi(value: dict[str, Any]) -> tuple[str, str]:
    return str(value.get("zh", "")), str(value.get("en", ""))


def _json_block(value: Any) -> str:
    return "~~~json\n" + json.dumps(
        _normalise(value), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n~~~"


def render_freeze_markdown(freeze: dict[str, Any]) -> str:
    """Pure deterministic rendering; never introduces research judgement."""
    title_zh, title_en = _bi(freeze["title"])
    rq_zh, rq_en = _bi(freeze["research_question"])
    claim_zh, claim_en = _bi(freeze["safe_novelty_claim"])
    decision = freeze["decision"]
    lines = [
        f"# {title_en}",
        "",
        f"**中文题目：** {title_zh}",
        "",
        "## Research question / 研究问题",
        "",
        rq_en,
        "",
        rq_zh,
        "",
        "## Safe novelty claim / 安全创新主张",
        "",
        claim_en,
        "",
        claim_zh,
        "",
        "## Frozen identifiers",
        "",
        f"- Freeze ID: {freeze['freeze_id']}",
        f"- Claim version: {freeze['claim_version']}",
        f"- Claim fingerprint: {freeze['claim_fingerprint']}",
        f"- Protocol fingerprint: {freeze['protocol_fingerprint']}",
        f"- Audit fingerprint: {freeze['audit_fingerprint']}",
        f"- Decision: {decision['status']}",
        "",
        "## Closest papers",
        "",
        _json_block(freeze["closest_papers"]),
        "",
        "## Data and baselines",
        "",
        _json_block({"data": freeze["data"], "baselines": freeze["baselines"]}),
        "",
        "## Experiment design",
        "",
        _json_block(freeze["experiment_design"]),
        "",
        "## Statistics",
        "",
        _json_block(freeze["statistics"]),
        "",
        "## OOD and robustness",
        "",
        _json_block(freeze["robustness"]),
        "",
        "## Reproducibility",
        "",
        _json_block(freeze["reproducibility"]),
        "",
        "## Positive, weak, and negative result routes",
        "",
        _json_block(freeze["result_routes"]),
        "",
        "## Final audit and provenance",
        "",
        _json_block({
            "final_audit": freeze["final_audit"],
            "provenance": freeze["provenance"],
        }),
        "",
        "> This Freeze is a design artifact. It does not authorize experiment execution.",
        "",
    ]
    return "\n".join(lines)


def _assert_current_gate_bindings(state: dict[str, Any]) -> None:
    for gate_name, gate in state["gates"].items():
        if gate["status"] != "passed":
            raise GapError("GATE_NOT_PASSED", f"{gate_name} is not passed.")
        for key in ("claim", "protocol", "audit"):
            if gate["valid_for"][f"{key}_fingerprint"] != state["fingerprints"][key]:
                raise GapError("GATE_HASH_STALE", f"{gate_name} has stale {key} binding.")
        if gate["valid_for"]["ledger_version"] != state["ledger_version"]:
            raise GapError("GATE_LEDGER_STALE", f"{gate_name} has stale ledger binding.")


def finalize_run(
    run_dir: Path,
    expected_revision: int,
    output: Path | None = None,
) -> dict[str, Any]:
    paths = run_paths(run_dir)
    with exclusive_lock(paths["lock"]):
        state = load_state(run_dir)
        if state["manifest_revision"] != expected_revision:
            raise GapError(
                "STALE_REVISION",
                f"Expected revision {expected_revision}, current is {state['manifest_revision']}.",
            )
        if state["decision"] != "GO" or state["run_status"] != "complete":
            raise GapError("RUN_NOT_FREEZABLE", "Run is not complete with a GO decision.")
        _assert_current_gate_bindings(state)
        current_validation = derive_validation(run_dir)
        if current_validation["gate_results"]["freeze_validation"]["status"] != "passed":
            raise GapError("FREEZE_REVALIDATION_FAILED", "Current deterministic validation failed.")
        freezes = _gate_payloads(
            run_dir, state, "freeze_validation", "experiment_freeze"
        )
        if not freezes:
            raise GapError("EXPERIMENT_FREEZE_MISSING", "No current Freeze JSON exists.")
        record, freeze = freezes[-1]
        validate_schema(freeze, "experiment-freeze.schema.json")
        for key in ("claim", "protocol", "audit"):
            if freeze[f"{key}_fingerprint"] != state["fingerprints"][key]:
                raise GapError("FREEZE_HASH_MISMATCH", f"Freeze {key} hash is stale.")
        markdown = render_freeze_markdown(freeze)
        output = output or paths["outputs"] / "experiment-freeze.md"
        atomic_write_text(output, markdown)
        return {
            "status": "finalized",
            "manifest_revision": state["manifest_revision"],
            "freeze_artifact_id": record["artifact_id"],
            "output": str(output),
            "sha256": sha256_bytes(markdown.encode("utf-8")),
        }


def recursive_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
