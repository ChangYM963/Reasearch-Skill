# Fingerprints and dependency invalidation

This document is normative for `discover-experimental-gaps` v1.0.0. Matrix
rules are constants; an agent cannot weaken them for an individual run.

## Action codes

- **P - Preserve:** keep the gate and artifacts eligible if all existing
  bindings remain current.
- **R - Review required:** retain all artifacts, set the gate and relevant
  artifact projections to `review_required`, and prohibit Freeze until a new
  traceable review is validated.
- **I - Invalidate:** retain all artifacts as history, set the gate to `stale`
  and relevant artifacts to `stale` or `superseded`, and prohibit their use
  in the current decision.

P/R/I changes decision eligibility, never artifact bytes. Every R or I records
the causal event ID.

## Canonical fingerprints

Each fingerprint is:

```text
SHA-256(UTF-8(canonical_json(fingerprint_input)))
```

Canonical JSON uses Unicode NFC strings, lexicographically sorted object keys,
compact separators, no trailing newline, UTF-8 without BOM, and lowercase
SHA-256. It trims leading/trailing string whitespace, preserves internal
whitespace, case, and mathematical symbols, normalizes finite JSON numbers,
and rejects NaN and infinities. Exact scientific quantities should be encoded
as normalized decimal strings plus explicit units; ordinary finite JSON
numbers remain accepted for counters and non-measurement values.

Arrays representing sets are sorted by canonical JSON value. Set arrays are
claim `comparator_class` and `excluded_claims`; protocol `baselines` and
`metrics`; and audit `rings` and `synonyms`. The same canonicalizer also sorts
the explicitly set-like evidence and authorization fields named in
`gaplib.SET_LIKE_KEYS`. Other arrays preserve order. Display translations,
timestamps, ledger versions, and claim revision numbers are not hash inputs.

The runtime stores short current keys in `fingerprints`: `claim`,
`protocol`, and `audit`. They map respectively to GateRecord
`valid_for.claim_fingerprint`, `protocol_fingerprint`, and
`audit_fingerprint`. The semantic validator must compare exact values.

### Claim input

The claim fingerprint covers:

```json
{
  "population": "...",
  "data_regime": "...",
  "method": "...",
  "intervention": "...",
  "comparator_class": [],
  "outcome": "...",
  "estimand": "...",
  "quantifier": "...",
  "mechanism": "...",
  "decision_consequence": "...",
  "excluded_claims": [],
  "sesoi": {"value": "...", "unit": "..."}
}
```

Translation-only changes do not alter this object. Scientific meaning changes
do. SESOI entries use exact decimal strings and units.

### Protocol input

The protocol fingerprint includes the current claim fingerprint plus exactly:
`data_version`, `split`, `baselines`, `strongest_baseline`, `metrics`,
`primary_endpoint`, `statistical_route`, `budget`, `code_version`, and
`decision_rule`. A concrete comparison-set or strongest-baseline change always
changes this fingerprint, even when claim prose is unchanged.

### Audit input

The audit fingerprint includes the current claim fingerprint plus exactly:
`cutoff_date`, `rings`, `synonyms`, and `query_protocol`. The query protocol
must carry any required date window, query families, and channels. Moving only
the cutoff changes audit, not claim or protocol.

Structured fingerprint inputs may live in immutable artifacts referenced by
`artifact.input_hashes`; they need not be duplicated in the run manifest.

## Fixed P/R/I matrix

The first column contains stable machine identifiers. Scripts dispatch on the
identifier, not on free prose.

| `change_type` | Material change | Venue Map | Falsification | Smoke | Final Audit | Freeze |
|---|---|---:|---:|---:|---:|---:|
| `venue_scope` | Venue, topic, or venue-year window | I | I | I | I | I |
| `claim_semantics` | Claim semantics, population, OOD regime, or decision objective | P | I | I | I | I |
| `baseline` | Concrete comparison set or strongest baseline | P | R | I | I | I |
| `endpoint_sesoi` | Primary endpoint, SESOI, equivalence margin, or statistical decision rule | P | R | I | I | I |
| `implementation` | Implementation split, seed, budget, or code version without target-distribution change | P | P | I | R | I |
| `target_distribution` | Split/data change that changes the target distribution | P | I | I | I | I |
| `final_audit_cutoff` | Advance only the Final Audit cutoff | P | P | P | I | I |
| `global_cutoff` | Advance the run-wide search cutoff | P | R | P | I | I |
| `closest_nonmaterial` | New closest paper, full text verified, no claim/baseline effect | P | R | P | I | I |
| `formatting` | Pure formatting; every fingerprint input unchanged | P | P | P | P | I |

Freeze is invalidated for `formatting` so the deterministic finalizer must
regenerate and validate the exact Freeze artifact; scientific gates remain
preserved.

## Fingerprint impact

`same` means recomputation must reproduce the old hash; `new` requires a new
input object and hash.

| `change_type` | Claim | Protocol | Audit |
|---|---:|---:|---:|
| `venue_scope` | new only if a new claim is supplied | reset | reset |
| `claim_semantics` | new | reset or new | reset or new |
| `baseline` | same | reset or new | reset or new |
| `endpoint_sesoi` | new when a new claim is supplied; otherwise same | reset or new | reset or new |
| `implementation` | same | reset or new | reset or new |
| `target_distribution` | new | reset or new | reset or new |
| `final_audit_cutoff` | same | same | new |
| `global_cutoff` | same | same | new |
| `closest_nonmaterial` | same | same | new |
| `formatting` | same | same | same |

`reset` means the runtime sets the fingerprint to null until a complete
replacement input is supplied. For a conditional row, compare normalized
before/after inputs and choose the most conservative applicable change type.
No gate may be preserved as decision-eligible when its `valid_for` value
differs from the current fingerprint.

## Application algorithm

For each accepted revision or new-evidence event:

1. Validate `change_type`, reason, any supplied evidence references, and
   `expected_revision` against `manifest_revision`. Resolved evidence
   references are mandatory for NARROW and reopening a completed GO.
2. Require a complete replacement scope for `venue_scope`, and a complete
   new claim for `claim_semantics` or `target_distribution`.
3. Recompute every supplied fingerprint and reject known understatement:
   a changed claim under an inapplicable row, a changed protocol under a
   cutoff/nonmaterial/formatting row, or any fingerprint change under
   `formatting`.
4. If one event contains several substantive changes, the caller must select
   the most conservative applicable row or queue separate events. v1 does not
   infer or merge arbitrary semantic change classes.
5. Append the causal event with old/new fingerprints; immutable result
   artifacts remain in history.
6. Apply the fixed row's status projections without deleting or editing
   artifact bytes.
7. Stale Freeze for every row, clear current GO eligibility, and retain the
   previous Freeze/verdict in history.
8. Resume at the earliest R/I gate in workflow order: Venue Map,
   Falsification, Smoke, Final Audit, Freeze.

Reject a detected understated declaration with `CHANGE_CLASS_MISMATCH`; do not
silently downgrade it. Because v1 cannot infer every scientific semantic
change, the parent agent remains responsible for conservative classification.

Queueing a revision sets `run_status: ready` at the earliest affected phase.
When the next external research handoff is recorded, that phase becomes
`awaiting_research`; Smoke can rebuild its preregistration before requesting a
new authorization. Freeze-only invalidation resumes `freeze/ready`.
`formatting` is a pre-close scientific no-op that still invalidates a draft
Freeze; it cannot reopen a completed GO.

## New paper, baseline, and local NARROW

A title or abstract match cannot produce STOP or automatically change a claim.
Identity, full text, and a material locator must first be verified.

Initially use `closest_nonmaterial` only after full-text review
finds no claim or baseline effect. If later review changes the comparison set
or strongest baseline, append a separate `baseline` event and
recompute protocol. The old Smoke is stale. Independent model outputs may be
reused as immutable inputs, but Smoke remains stale until the added baseline
and preregistered paired comparison finish.

NARROW creates a new `claim.current_version`, appends the old/current versions
to `claim.history`, increments `governance.narrow_count`, and applies this
matrix. It restarts only at the earliest R/I gate; preserved earlier gates are
not rerun. Old Technical Smoke can remain implementation context but cannot be
current Precision or confirmatory evidence for the revised claim.

When `governance.narrow_count >= governance.narrow_limit`, reject another
revision with `NARROW_LIMIT_REACHED`. The run becomes blocked/undecided pending
a new run or new evidence; the limit never manufactures scientific STOP.
