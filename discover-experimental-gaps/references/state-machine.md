# State machine contract

This document is normative for `discover-experimental-gaps` v1.0.0. Scripts
MUST reject mutations not permitted here. Reports and agents may propose
evidence or verdicts, but cannot directly advance a phase, pass a gate, or set
the final decision.

## Orthogonal state

The canonical state is a projection of append-only event and artifact history.
Its axes have distinct meanings:

- `phase`: workflow location: `intake | venue_map | discovery |
  falsification | smoke | final_audit | freeze | closed`.
- `run_status`: current ability to proceed: `ready | active | awaiting_user |
  awaiting_research | insufficient_evidence | blocked | complete`.
- `decision`: terminal scientific decision: `undecided | GO | STOP`.

`NARROW` is a versioned revision operation, not a phase, status, or terminal
decision. `stale` and `review_required` belong to gate/artifact lifecycle,
not run status.

`manifest_revision` is the compare-and-swap revision for atomic state writes.
`ledger_version` binds scientific validation to the current evidence ledger.
Gate `valid_for.ledger_version` must equal the current root `ledger_version`
when the gate is eligible. A transaction may update both counters, but they are
not interchangeable.

Global invariants:

1. A non-closed run has `decision: undecided` and is not `complete`.
2. `closed` implies `complete` and `decision: GO` or `STOP`.
3. GO requires a passed Freeze gate bound to all current fingerprints. STOP
   requires a traceable scientific-audit verdict; schema, permission, tool, or
   validator failure is never scientific STOP.
4. `insufficient_evidence` is non-terminal. It means reviewed evidence cannot
   distinguish predeclared meaningful alternatives.
5. `blocked` is non-terminal and names a concrete external or authorization
   blocker. Difficulty, uncertainty, or a wide interval alone is not BLOCKED.
6. A gate/artifact that is `review_required` or `stale` cannot support
   Freeze.
7. `governance.narrow_count` never exceeds
   `governance.narrow_limit`.

## Five-gate map

`gap-run.json` contains exactly these keys under `gates`:

| Gate | Subject | Required current binding when passed |
|---|---|---|
| `venue_map` | Venue, field, and closest-work map | Scope and current ledger |
| `falsification` | Adversarial test of selected gap | `fingerprints.claim` |
| `smoke` | Authorized preregistered feasibility/precision Smoke | claim and `fingerprints.protocol` |
| `final_audit` | Latest exact-claim search and scientific audit | claim and `fingerprints.audit` |
| `freeze_validation` | Deterministic consistency only | all three fingerprints and current ledger |

Every GateRecord has:

```json
{
  "status": "pending",
  "outcome": null,
  "subject_refs": [],
  "artifact_ids": [],
  "valid_for": {
    "claim_fingerprint": null,
    "protocol_fingerprint": null,
    "audit_fingerprint": null,
    "ledger_version": 0
  },
  "validated_at": null,
  "validator_version": null,
  "reason_codes": [],
  "unresolved_lead_ids": [],
  "invalidated_by_event_id": null
}
```

Root short names map exactly as follows:

- `fingerprints.claim == valid_for.claim_fingerprint`
- `fingerprints.protocol == valid_for.protocol_fingerprint`
- `fingerprints.audit == valid_for.audit_fingerprint`

JSON Schema checks shapes; the semantic validator checks these equalities.
`outcome: PASS` or `outcome: GO` at a gate means only "the evidence process
passed and may proceed"; it does not assert a positive effect or prove
publication novelty. PASS is used for audit-style gates; GO is used where a
candidate/protocol continuation decision is explicit.

A scientific gate passes only when current mutually consistent artifacts cover:

1. the subject report/result;
2. source verification of identity and locators; and
3. a scientific audit with reasons and evidence references.

`validate_gap_run.py` without `--commit` is state-read-only. With `--commit`
it emits and transactionally applies a current validation artifact to `gates`.
Structurally ready never means scientifically passed.

### Gate lifecycle

| Current | Allowed next | Cause |
|---|---|---|
| `pending` | `awaiting_report` | A research/Smoke handoff was frozen |
| `pending` | `validating` | Required artifacts already exist; chiefly Freeze |
| `awaiting_report` | `validating` | Subject, verification, and audit artifacts ingested |
| `validating` | `passed` | Structural validation plus scientific `PASS` or `GO` |
| `validating` | `failed` | Scientific `STOP`, `BLOCKED`, `FAIL`, or `INSUFFICIENT_EVIDENCE` |
| `validating` | `review_required` | Scientific `NARROW` or dependency review |
| `passed` | `review_required` | Matrix action R |
| `passed` | `stale` | Matrix action I |
| `review_required` | `validating` | Review artifact recorded |
| `review_required` | `stale` | Later event fully invalidates gate |
| `stale` | `awaiting_report` | Replacement evidence must be obtained |
| `stale` | `validating` | Replacement artifacts already exist |
| `failed` | `awaiting_report` | New evidence explicitly queued before terminal close |

No other transition is legal. External ingest cannot set `passed`; passed
cannot silently become pending; every R/I records
`invalidated_by_event_id`.

Outcome consistency:

- `passed` requires `PASS` or `GO`.
- `failed` requires `STOP`, `BLOCKED`, `FAIL`, or `INSUFFICIENT_EVIDENCE`.
- `review_required` permits `NARROW` or null.
- pending, awaiting-report, validating, and stale carry null outcome.

## Legal workflow transitions

All writes use `expected_revision == manifest_revision`. "Validation applied"
means the writer applied a current validation artifact, not that a report
self-declared success.

| Current | Action and hard precondition | Next | Gate effect |
|---|---|---|---|
| none | Complete conversational intake, then prepare venue/topic/window/adapter | `venue_map/ready/undecided` | Create five pending gates |
| `venue_map/ready` | Deep Research handoff recorded | `venue_map/awaiting_research` | Venue Map awaits report |
| `venue_map/ready` or `venue_map/awaiting_research` | Report plus sidecar ingested | `venue_map/active` | Venue Map validates |
| `venue_map/active` | Current PASS/GO validation applied | `discovery/active` | Venue Map passed |
| `discovery/active` | 3-6 total proposals recorded, with at least one viable candidate and all pseudo-gap hard rejects separated | `falsification/awaiting_research` | Falsification awaits report |
| `falsification/awaiting_research` | Adversarial report plus sidecar ingested | `falsification/active` | Falsification validates |
| `falsification/active` | PASS/GO; one primary and at most one backup remain | `smoke/active` | Falsification passed |
| `smoke/active` | Technical preregistration frozen for current claim/protocol | `smoke/awaiting_user` | Smoke awaits authorized result |
| `smoke/awaiting_user` | Matching execution authorization active | `smoke/active` | no scientific gate change |
| `smoke/active` | Authorized result plus verification/audit ingested | `smoke/active` | Smoke validates |
| `smoke/active` | Current PASS/GO validation applied | `final_audit/active` | Smoke passed; Final Audit protocol must be frozen |
| `final_audit/active` | Current `audit_protocol` recorded, then handoff | `final_audit/awaiting_research` | Exact claim/cutoff/query fingerprint frozen |
| `final_audit/awaiting_research` | Matching exact-claim report plus sidecar ingested | `final_audit/active` | Final Audit validates |
| `final_audit/active` | Current PASS/GO validation applied | `freeze/active` | Final Audit passed; Freeze validates |
| `freeze/active` | Deterministic validator confirms gates, hashes, authorization, and artifacts | `closed/complete/GO` | Freeze passed |

Design authorization does not authorize code execution. Research authorization
never bypasses Codex sandbox, network, credential, or external-write approval.

### Negative and non-terminal branches

| Current | Validated outcome/event | Next |
|---|---|---|
| `discovery/active` | All 3-6 proposals hard-vetoed and recorded under `rejected_candidates` | `discovery/active/undecided` | Persist `no_viable_candidate`; request new substantive proposals |
| Venue Map, Falsification, Smoke, or Final Audit active | Scientific STOP with `decision_eligible: true` | `closed/complete/STOP` |
| Same scientific phases active | INSUFFICIENT_EVIDENCE | Same phase, `insufficient_evidence/undecided` |
| Any non-closed phase | Concrete blocker recorded | Same phase, `blocked/undecided` |
| Same phase blocked | Resolution artifact recorded | Prior admissible status stored in blocker/event |
| Same phase insufficient | More evidence queued | Same phase, `awaiting_research` or `active` |

An all-rejected Discovery board cannot begin Falsification, NARROW, or Smoke.
Discovery cannot emit STOP because it is not an evidence gate. Freeze validator
failure returns `freeze/active` (or blocked for a concrete external blocker);
it does not create STOP.

## Local NARROW

`queue_gap_revision.py` is the sole revision entry point and uses the shared
lock/CAS transaction. It atomically:

1. Requires `decision: undecided`, except an explicitly reopened GO after
   material new evidence. Closed STOP is not reopened in v1; start a new run.
2. Requires a committed NARROW verdict for the current claim and gate plus the
   expected manifest revision. The caller supplies the complete replacement
   claim and any replacement protocol/audit inputs; the writer automatically
   binds the NARROW validation artifact as revision evidence.
3. Rejects with `NARROW_LIMIT_REACHED` when
   `governance.narrow_count >= governance.narrow_limit`. This never creates
   STOP; keep the run blocked/undecided pending a new run or evidence.
4. Creates an immutable before/after revision artifact, advances
   `claim.current_version`, appends `claim.history`, increments narrow_count,
   and recomputes affected fingerprints.
5. Applies the fixed P/R/I matrix. Old artifacts remain; only eligibility
   projections and append-only events change.
6. Resets decision to undecided and resumes at the earliest R/I gate. It never
   reruns an earlier preserved gate.

Every queued revision resumes the earliest affected phase with
`run_status: ready`. Recording a research handoff then changes a research
phase to `awaiting_research`; ingesting its report changes it to `active`.
At Smoke, `ready` means create/review the current preregistration before
requesting authorization. Freeze-only invalidation resumes `freeze/ready`.

Old Technical Smoke may be implementation context after NARROW, but is not
current confirmatory or Precision-Smoke evidence for the revised claim.

## Immutable artifacts and authority

Each runtime artifact record contains `artifact_id`, `kind`, `path`,
`sha256`, `input_hashes`, `status`, monotonic `sequence`, and
`recorded_at`. After recording,
artifact bytes and identity fields are immutable:

- ID, kind, path, hash, sequence, and recorded time;
- input-hash bindings at creation;
- content at the referenced path.

Invalidation never edits or deletes those bytes. The manifest may update only
the derived artifact `status` while appending a linked event. Replaced content
gets a new artifact ID; the old record remains historical and changes status
only through an explicit matrix/review event. Every read verifies
canonical bytes and the recorded SHA-256 before using an artifact in a gate.

Mutation authority:

- agents/subagents return deltas based on a manifest revision; no canonical
  writes;
- `validate_gap_run.py` without `--commit` is read-only; with `--commit` it
  uses the locked CAS path to record validation and project gate state;
- `gap_run_status.py` is strictly read-only;
- `record_gap_result.py` is the sole general writer;
- `queue_gap_revision.py` is the sole NARROW writer using the same transaction
  layer;
- `finalize_gap_run.py` requires `--expected-revision`, holds the run lock,
  revalidates current bindings, and renders only validated Freeze JSON without
  research judgment.

Single files use temp-write, flush, file fsync, and replace. Multi-file
manifest/ledger/candidate commits restore the prior bundle after a synchronous
write exception; a newly written but unreferenced artifact may remain orphaned
and has no decision authority. Power-loss journaling is outside v1 and must
not be claimed.

## Semantic checks beyond JSON Schema

The runtime additionally enforces:

- CAS equality for every mutation and monotonic artifact `sequence`;
- canonical artifact bytes, recorded SHA-256, and current artifact/gate
  foreign keys;
- gate valid-for fields equal current root fingerprints and ledger version;
- claim, protocol, and audit fingerprints recompute from normalized inputs;
- revision actions come from the fixed P/R/I matrix;
- NARROW has a committed current verdict, advances claim version/count once,
  and creates an immutable revision artifact;
- the latest Smoke preregistration has its own matching authorization and
  result chain;
- Precision preregistration follows a complete Technical chain and cannot
  reopen after Final Audit research starts;
- Final Audit has a current pre-registered audit protocol, fresh per-ring
  dates, and a Freeze cutoff equal to that protocol;
- terminal scientific outcomes carry `decision_eligible: true`;
- passed Freeze has four current passed science gates and a current Freeze
  artifact.

The runtime does not prove exhaustive search, source entailment, real user
identity behind an authorization label, or scientific novelty.
