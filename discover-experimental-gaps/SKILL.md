---
name: discover-experimental-gaps
description: Evidence-gated workflow for mapping a journal, conference, or Special Issue; falsifying experimental-gap candidates; running authorized Smoke tests; and freezing a defensible experiment plan. Use for AI/ML prediction or decision/policy/VoI research when novelty must survive closest-paper search, strong baselines, OOD/robustness checks, and reproducible state tracking.
---

# Discover Experimental Gaps

Skill version: 1.0.0  
Schema version: 1.0.0  
Fingerprint version: 1.0.0

## Purpose

Turn a target venue and research area into one falsifiable primary experimental
gap, at most one backup, and—only after all gates pass—a bilingual frozen
experiment plan.

This is an evidence and state-management workflow. It cannot prove that a
search was exhaustive, that cited evidence entails a proposition, or that a
novelty claim is scientifically true. Preserve those limits in every report.

## Non-negotiable boundaries

- Deep Research performs evidence acquisition for Venue Map, Falsification,
  and Final Audit.
- Ordinary conversation compares candidates, designs Smoke tests, interprets
  bounded results, and drafts the Freeze.
- No agent, report, or user-supplied JSON may directly mark a gate passed.
- Only validate_gap_run.py with --commit may update gate decisions.
- Only record_gap_result.py performs general state writes.
- gap_run_status.py is strictly read-only.
- Historical artifacts are never deleted when a revision makes them stale.
- A missing public codebase or dataset is a reproducibility or feasibility
  risk; it is not by itself an experimental gap.
- A Freeze is a design artifact, never authorization to execute the full
  experiment.

## First-turn intake

Ask only for information that cannot be safely discovered:

1. Target journal, conference, or Special Issue; include the CFP URL or PDF if
   the target is ambiguous.
2. Research topic, population/data regime, and any known decision context.
3. Whether external Deep Research is available and allowed for this material.
4. Confidentiality, privacy, data-access, compute, deadline, and cost limits.
5. Choose ai-ml or decision-policy adapter. Use decision-policy whenever the
   claim says better prediction should alter an action, allocation, policy, or
   outcome.

Default to a five-year window, narrowing to three years only when the venue or
topic is unusually fast-moving. Record an explicit search cutoff date.

Use current UTC as the time authority. The prepare search cutoff, the
`audit_protocol` cutoff and every ring's `through` date, and every returned
SearchRun `date_window.through` and `executed_at` must be no later than the
validator's current UTC date or time. Reject every future value.

In v1, intake is the conversation before run creation. Once venue, topic,
window, adapter, and applicable constraints are known,
`prepare_gap_run.py` consumes that intake and creates the canonical run at
`venue_map/ready/undecided`; it does not create artificial intake transitions.

Do not ask the user to supply public venue scope, recent paper metadata, or
standard benchmark details that Deep Research can retrieve.

## Create and inspect a run

Use a dedicated run directory outside the installed Skill. Never put run data
inside the Skill package.

Resolve one Python 3.9+ interpreter before any script call: normally `python`
on Windows, `python3` on Linux, or another explicitly verified executable.
Substitute that executable for `<python>` in every command below.

    <python> <skill-root>/scripts/prepare_gap_run.py --run-dir <run-dir> --venue <venue> --topic <topic> --years 5 --adapter ai-ml

Before each write, read the current revision:

    <python> <skill-root>/scripts/gap_run_status.py --run-dir <run-dir> --json

Every write must use the displayed manifest_revision as expected_revision.
A stale writer must refresh and re-evaluate its proposed delta.

## Workflow

### 1. Venue Map — Deep Research evidence gate

Read references/research-contract.md and references/evidence-schema.md.

Search the target venue, adjacent venues, and the citation graph. Use official
scope/CFP pages plus primary paper or repository sources. Cover the recent
three-to-five-year window and preserve:

- main themes;
- common methods and strongest baseline families;
- datasets, versions, splits, metrics, and statistical protocols;
- compute and tuning conventions;
- OOD, robustness, ablation, oracle, and decision-value practices;
- code/data availability as reproducibility metadata;
- limitations and unresolved leads.

The machine sidecar must contain all three rings:

- target_venue;
- cross_venue;
- citation_graph.

Retain the raw Markdown or PDF and its SHA-256. A sidecar field such as
coverage=true or verified=true has no authority; the validator derives
coverage, foreign-key validity, identifiers, locators, unresolved leads,
versions, dates, and hashes. `validate_gap_run.py` places the derived checks
for every current report under `report_qa` in its validation/QA artifact.

Ordinary conversation then selects three or four themes. Do not select the gap
yet.

If Deep Research is unavailable, produce a complete research handoff using the
contract, set the run to awaiting_research through the normal artifact path,
and stop at the evidence boundary. Never substitute remembered literature or
ordinary web snippets and never output GO.

For the initial Venue Map, create and record that handoff deterministically:

    <python> <skill-root>/scripts/prepare_gap_run.py --run-dir <run-dir> --venue <venue> --topic <topic> --await-research

The emitted file is run-dir/outputs/venue-map-research-handoff.json. For later
Falsification or Final Audit handoffs, build the same contract for the current
stage and ingest it with record_gap_result.py using kind research_handoff.

### 2. Candidate discovery — ordinary conversation

Before recording a board, create a provisional bilingual claim envelope from
one selected Venue Map theme and record its fingerprint. The board projection
is bound to that current claim; Falsification may later narrow or replace it
only through the versioned revision path.

Generate three to six total proposals. For each potentially viable candidate
state:

- precise population/data regime;
- intervention or method;
- strongest comparator class;
- outcome/estimand and SESOI;
- mechanism or decision consequence;
- smallest experiment that could refute it;
- closest-paper search terms;
- why the result would matter at the target venue.

Also require non-empty `basis_codes` and an explicit boolean
`prediction_claim`. A prediction candidate must name a decision-value test, or
declare a substantive `prediction_only` scope and explain why it is more than
an accuracy-only contribution. A prediction-only exception also needs one of
`calibration`, `robustness`, `mechanism`, or `distribution_boundary` as its
`prediction_only_basis`. Missing classification fields are not evidence that
a veto was checked.

Apply hard vetoes before scoring. Reject a candidate whose contribution is
only:

- one more dataset;
- more samples, parameters, seeds, or compute;
- a model, map, or backbone swap;
- a routine ablation;
- repetition of an author's future-work sentence;
- better accuracy/AUC without a test of changed decisions or outcomes;
- missing code or unavailable data alone.

Record vetoed proposals under `rejected_candidates`, with stable
`rejection_codes` and traceable `rejection_reasons`; do not put them in the
viable `candidates` array. The accepted plus rejected arrays must total three
to six proposals. If every proposal is rejected, persist the board as
`no_viable_candidate`, remain `discovery/active/undecided`, and ask for new
substantive proposals. Do not start Falsification, design Smoke, emit NARROW,
or manufacture scientific STOP from an empty viable set.

### 3. Adversarial falsification — Deep Research evidence gate

Freeze the current claim fingerprint, then search specifically to defeat it:

- exact and synonymous claim formulations;
- newest and closest papers;
- cited and citing papers;
- benchmark/protocol papers;
- public code and data linked from full text;
- papers outside the target venue that use a stronger comparison set.

Full text is required before declaring that a paper covers the gap. A similar
title or abstract is not enough for STOP.

Retain exactly one primary candidate and at most one backup. The scientific
audit may return:

- GO: candidate survives and can enter Smoke design;
- NARROW: a narrower version may survive;
- STOP: prior work or a hard feasibility/decision-value limit defeats it;
- BLOCKED or INSUFFICIENT_EVIDENCE: evidence cannot support a decision.

GO here is a stage outcome, not the run's final GO. The run decision remains
undecided until Freeze validation passes.

### 4. Technical Smoke — ordinary conversation plus explicit authorization

Read references/smoke-freeze-contract.md and
references/decision-statistics.md. Then read the selected domain adapter.

First freeze a Technical Smoke preregistration. Prefer:

- strongest fair baseline;
- a simple rule;
- an oracle or value-of-information upper bound;
- the smallest informative data slice;
- explicit leakage controls;
- a primary endpoint and SESOI;
- an experiment that distinguishes competing explanations.

A Technical Smoke asks whether the experiment is executable and informative.
It cannot justify a null/equivalence STOP. A hard Technical STOP is allowed
only for a preregistered structured kill criterion containing
`criterion_id`, basis, measure, operator, threshold, and unit. Its result must
provide a matching observation and a JSON-pointer evidence reference into
that same Smoke result. Treat a dominant simple rule as
`NON_DISCRIMINATING`, not as an unregistered new basis.

After preregistration, request structured user authorization. Design permission
does not imply execution permission. Technical permission does not imply
Precision permission. Paid APIs, dependency installation, remote compute,
credentials, uploads, external writes, and model training are denied unless
explicitly granted. The final confirmatory holdout is prohibited in both
Technical and Precision Smoke; an authorization payload cannot override this.

The authorization must bind:

- authorization ID and an authorization-event audit label;
- Smoke kind, gap ID, claim fingerprint, protocol fingerprint, and
  preregistration hash;
- versioned datasets, slices, read/write scope, and final-holdout protection;
- CPU/GPU, memory, wall time, runs, trials, seeds, and cost with units;
- network allowlist, write roots, privacy constraints, expiry, and consumption.

This research authorization never bypasses Codex sandbox, network, credential,
or external-write approval.

The offline validator cannot authenticate a conversation identity or prove
that `authorization_event_id` names a real user message; it checks only the
structured record and bindings. The parent agent may create or ingest an
authorization object only after explicit user authorization. The event ID is
traceability metadata, not an identity credential.

### 5. Precision Smoke — only when needed

Create a separately preregistered and separately authorized Precision Smoke
when STOP would rely on equivalence, futility, or exclusion of a meaningful
effect. Runtime admission requires a complete validated Technical Smoke chain.
If Technical Smoke was already committed, Precision may reopen Smoke only
before any Final Audit report has been ingested.

Do not treat p greater than 0.05 as evidence of no effect. A wide interval that
contains meaningful benefit, zero, or meaningful harm is
INSUFFICIENT_EVIDENCE. Valid precision routes include:

- TOST with a predeclared equivalence margin;
- a confidence interval wholly within the equivalence region;
- Bayesian ROPE with predeclared thresholds;
- a defensible futility rule.

The machine contract binds estimand, independent unit, endpoint, current
SESOI, its exact scalar-derived or asymmetric margins, split, framework,
multiplicity policy, and the framework-specific alpha/interval, ROPE threshold,
or structured futility rule. Futility must bind measure, operator, threshold,
unit, observed value, and a JSON pointer into the same result. The runtime then
checks structured result evidence against that plan. Comparator fairness,
preprocessing, power, priors/sensitivity, missing-data handling, and external
SESOI rationale remain required scientific-audit judgments where applicable;
the v1 schema does not pretend to prove them.

Smoke GO does not require a positive result. It requires a fair, executable,
discriminating, adequately precise main experiment.

### 6. Final Audit — Deep Research evidence gate

Before creating the handoff or ingesting a report, record an immutable
`audit_protocol` artifact. It freezes the current claim fingerprint, cutoff,
all three rings, non-empty synonyms, and one complete query-protocol block per
ring; its canonical hash becomes the current audit fingerprint. Every ring
must search through that cutoff, and execution cannot predate the declared
window. The returned report may only reproduce and match this fingerprint; it
cannot define or overwrite it after the search.

The Final Audit handoff must carry the complete frozen `audit_protocol` payload
and the same `audit_fingerprint`. Reject a handoff when either is missing or
does not reproduce the current frozen fingerprint.

Then search the exact current claim again. Recheck closest papers, comparison
set, strongest baseline, and unresolved leads. Freeze `search_cutoff` must
equal the current audit-protocol cutoff.

If a new paper changes the comparison set or strongest baseline, emit a
baseline-change revision. This changes the protocol fingerprint and makes the
old Smoke stale. If a fully verified paper defeats the claim, STOP. If only a
narrower claim survives, return NARROW.

### 7. NARROW — local versioned loop

Read references/dependency-matrix.md before revising.

NARROW is not a terminal state. It:

1. records a verdict;
2. creates a new claim version;
3. applies the fixed P/R/I dependency row;
4. preserves all historical files and hashes;
5. reruns only affected research and Smoke work.

Use queue_gap_revision.py. Never hand-edit gap-run.json.

    <python> <skill-root>/scripts/queue_gap_revision.py --run-dir <run-dir> --change-type claim_semantics --reason <reason> --claim <new-claim.json> --narrow --evidence-ref <artifact-or-evidence-ref> --expected-revision <revision>

The command returns `revision_artifact_id`. That immutable `gap_revision`
artifact stores before/after claim, scope, fingerprints, protocol/audit inputs,
reason, and resolved evidence references. A frozen GO may reopen only for a
material non-formatting revision with a reference resolving to a current
artifact, ledger evidence item, DOI, arXiv ID, URL, or repository URL.

At most two NARROW transitions are allowed in v1. A third request becomes
BLOCKED and needs a human decision to STOP or start a new run.

### 8. Experiment Freeze

Read references/smoke-freeze-contract.md and the Freeze schema.

Freeze JSON must include bilingual title, research question, and safe novelty
claim, plus:

- closest papers and differentiators;
- versioned data and exact splits;
- strongest baselines and fairness controls;
- main experiment, mechanism ablations, oracle/VoI tests;
- OOD, robustness, subgroup, and threat-model tests;
- estimand, endpoint, SESOI, sample-size/precision and statistical route;
- code/data release plan and environment/seed policy;
- positive, weak/inconclusive, and negative/equivalent/harmful paper routes.

Commit deterministic validation:

    <python> <skill-root>/scripts/validate_gap_run.py --run-dir <run-dir> --commit --expected-revision <revision>

Only when all five gates are passed and bound to the current three
fingerprints and ledger version may finalization run:

    <python> <skill-root>/scripts/finalize_gap_run.py --run-dir <run-dir> --expected-revision <revision>

The finalizer renders only validated Freeze JSON. It must not invent, improve,
or reinterpret research content.

## Gate evidence rule

Each of the four science gates needs both:

1. a source-verification artifact covering identity and locators; and
2. a scientific-audit artifact with evidence IDs, current
   `subject_artifact_ids`, and a traceable judgment.

The subject list must cover the current report for research gates and the
current preregistration plus result for Smoke. Verification IDs must resolve
to current artifacts attached to that gate. Non-Smoke audit evidence IDs must
belong to the current report named in `subject_artifact_ids`; Smoke audit
evidence must name the current result ID or result artifact ID.

The fifth gate is deterministic Freeze validation. Structural readiness is not
scientific passage. A report cannot pass itself. STOP, NARROW, BLOCKED, or
INSUFFICIENT_EVIDENCE changes run state only when the validation result marks
`decision_eligible: true` after all required verification, bindings, hashes,
lead checks, and any full-text/kill/precision rule have passed.

## Multi-agent execution

Single-agent sequential execution is the required baseline. Record
independence_level as sequential_unblinded.

If subagent spawning is available, parallelize only independent, bounded
roles:

- Venue Mapper;
- Protocol/Baseline Auditor;
- Adversarial Falsifier;
- Smoke Designer;
- Final Auditor.

Give the Falsifier no information about which candidate the user hopes will
survive. Subagents return evidence deltas and artifact drafts only. The parent
agent alone checks conflicts, performs scientific synthesis, and calls the
canonical writer. If subagents are unavailable, execute the same role briefs
sequentially with isolated notes.

## Output language

- Explain evidence, uncertainty, candidate comparison, vetoes, and next steps
  in Chinese.
- Freeze title, research question, safe novelty claim, decision rationale, and
  result routes must contain both Chinese and English.
- Keep citations, identifiers, hashes, code names, dataset names, and metric
  names in their source form.

## Reference routing

- Read references/state-machine.md before any transition or recovery.
- Read references/dependency-matrix.md before any change, NARROW, new closest
  paper, baseline change, cutoff update, or protocol revision.
- Read references/research-contract.md and references/evidence-schema.md before
  preparing or ingesting a Deep Research handoff.
- Read references/decision-statistics.md before interpreting intervals,
  equivalence, futility, null, weak, or negative results.
- Read references/smoke-freeze-contract.md before preregistration,
  authorization, Smoke ingestion, Final Audit, or Freeze.
- Read references/domain-ai-ml.md for predictive/model-evaluation research.
- Read references/domain-decision-policy.md whenever actions, utility, regret,
  allocation, policy, oracle, or value of information appears in the claim.

## Recovery and safety

- On STALE_REVISION, reread status; never overwrite the other writer.
- On SCHEMA_INCOMPATIBLE, stop without migration or silent rewriting.
- On stale hashes, use the dependency matrix; do not manually restore passed.
- On missing Deep Research, emit a handoff and wait.
- On missing execution authorization, design only.
- On critical unresolved leads, BLOCKED or INSUFFICIENT_EVIDENCE; never GO.
- Resolve an open lead only with a later report carrying the same lead ID,
  resolved/dismissed status, and in-report resolution evidence; history is
  preserved.
- On contradictory evidence, preserve both propositions and locators, then
  require scientific audit.
