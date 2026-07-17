# Smoke and Experiment Freeze contract

Use this contract to keep minimal experiments bounded, authorized, reproducible, and separate from the final confirmatory study. The machine-readable records are ../schemas/smoke.schema.json and ../schemas/experiment-freeze.schema.json.

## Phase contract

Run the phases in this order:

1. Complete early Gap Falsification and retain one primary plus at most one backup candidate.
2. Freeze the current claim fingerprint and prepare a Technical Smoke protocol.
3. Obtain Technical Smoke authorization. Run only the authorized data, code, models, compute, network, and write scope.
4. Use Technical Smoke to test implementation, leakage, baseline strength, oracle headroom, measurement sensitivity, and projected resources.
5. If a candidate needs inferential evidence for its decision, prepare a separate Precision Smoke protocol and obtain new authorization.
6. Map the Smoke result to GO, STOP, or INSUFFICIENT_EVIDENCE without changing the SESOI or endpoint after seeing the result.
7. Run the exact-claim Final Audit. If the claim is narrowed, version it and repeat only the affected gates and Smoke components.
8. Emit the bilingual Experiment Freeze dossier. Do not start the full experiment until its protocol fingerprint and authorization are separately confirmed.

Technical authorization never implies Precision authorization, complex-model training, remote compute, paid API use, external data transfer, or final-holdout access.

## Authorization

Bind every authorization to one `gap_id`, claim fingerprint, protocol
fingerprint, preregistration hash, Smoke kind, and expiry. Record every
permission boolean explicitly; absence means denied.

The machine-required scope is:

- `authorization_id`, `authorized_by: user`, and a non-empty
  `authorization_event_id` audit label;
- versioned `data_scope` entries with slices, read/read-write access, and
  `final_holdout: false`;
- `permissions` for design, local execution, model training, dependency
  installation, external API, remote compute, upload, and final-holdout access;
- compute ceilings for wall time, CPU cores, memory, runs, trials, seeds, and
  cost, each with a value and unit; extra quantified limits may be added;
- network allowlist, filesystem write roots, privacy constraints, expiry, and
  prior consumption.

External API, remote compute, or upload permission also requires a non-empty
network allowlist. `permissions.access_final_holdout` and every
`data_scope[].final_holdout` must remain false for both Smoke kinds.

Use a new authorization when a bound hash, Smoke kind, data scope, resource
ceiling, or external side effect changes. Credentials and tool/sandbox
approval are not represented by this research object and remain separately
controlled by Codex.

The offline validator cannot authenticate a conversation identity or resolve
`authorization_event_id` to a real user message. The parent agent may create
or ingest this object only after explicit user authorization; the event ID is
an audit label, not proof of identity. Result records declare operations and
consumption, but the validator cannot independently observe every process,
dataset read, or network destination.

## Technical Smoke

Technical Smoke should be the smallest implementation that can expose a fatal flaw. Include:

- a constant/random control when meaningful;
- a simple rule or heuristic;
- at least one credible strong baseline;
- an oracle, upper bound, or value-of-information probe;
- a representative development slice while the final holdout remains excluded;
- sanity, leakage, label-shuffle, and metric-direction checks as applicable;
- measured runtime/memory and projected full-study cost.

Its output is feasibility evidence, not a publishable effect estimate. A noisy
benefit does not by itself justify GO; a noisy null cannot justify STOP.

A hard Technical STOP must be preregistered as a structured
`technical_kill_criteria` item:

- unique `criterion_id`;
- basis: `LEAKAGE`, `INFEASIBLE_COST`, `NO_ORACLE_HEADROOM`,
  `NON_DISCRIMINATING`, or `DATA_INVALID`;
- result measure, comparison operator, threshold, and unit.

The result must repeat the criterion ID and basis, record the observed value
and unit, and point to that value with
`result:<result_id>#/results/<measure>`. The runtime resolves the pointer and
evaluates the preregistered comparison. A dominant simple rule is represented
as `NON_DISCRIMINATING`; it is not a free-form post-result kill label.

## Precision Smoke

Use Precision Smoke only when a complete Technical Smoke chain validates as
PASS/GO and a candidate decision requires controlled uncertainty. It may
reopen Smoke after Technical commit only before Final Audit research starts.
The v1 machine plan locks:

- current claim estimand and SESOI, independent unit, primary endpoint, and
  exact split;
- lower/upper margins exactly equal to the current claim SESOI: symmetric when
  represented by one absolute value, or explicitly asymmetric;
- `TOST`, `CI_EQUIVALENCE`, `BAYESIAN_ROPE`, or `FUTILITY`;
- multiplicity policy and, as applicable, alpha plus interval level,
  posterior threshold, or a structured futility measure/operator/threshold/unit.

For TOST, the interval level must equal `1 - 2*alpha`. Equivalence intervals
must use a level in `[0.8, 1)`, contain their estimate, and lie strictly inside
the margins before STOP. ROPE posterior mass must meet its threshold; futility
must provide a bound observed value and result JSON pointer that satisfy the
preregistered comparison. `p_value_only`, wide confidence, or
inadequate precision cannot STOP.

Comparator fairness, preprocessing, external SESOI rationale, target
power/sample size, Bayesian prior/sensitivity, missing-data rules, and
compute-matched tuning remain required scientific-audit checks where
applicable; the v1 schema does not claim to machine-prove them.

If target precision is not reached, return INSUFFICIENT_EVIDENCE. Do not
silently add samples, seeds, subgroups, metrics, or tuning trials beyond
authorization.

## Dependency invalidation

`dependency-matrix.md` is the sole normative P/R/I table. Do not maintain a
second matrix here. Preserve never deletes history; Review cannot support
Freeze until resolved; Invalidate makes the old gate/artifacts ineligible for
the current claim. A comparison-set or strongest-baseline change creates a new
protocol fingerprint and invalidates the bound Smoke chain.

## Decision and narrowing

- GO authorizes planning the frozen full experiment, not executing it and not claiming publication-level novelty.
- STOP requires a hard failure or sufficiently precise futility/equivalence result. Nonsignificance alone is not enough.
- INSUFFICIENT_EVIDENCE requires explicit unblock conditions and remains resumable.
- NARROW creates a new claim version. It must retain venue importance, have independent literature support or a prespecified boundary, and pass Final Audit again. Post-result narrowing is exploratory until tested on fresh or held-out data.

Limit NARROW to two transitions per run by default. A third rescue attempt
blocks the current run pending a human choice to STOP or start a new run; it
does not silently close the run or permit arbitrary subgroup mining.

## Experiment Freeze

The draft `Experiment Freeze` JSON is ingested at `freeze/active/undecided`;
only successful Freeze validation moves the run to `closed/complete/GO` and
allows deterministic Markdown finalization. It uses `FROZEN_FOR_EXPERIMENT`.
STOP and INSUFFICIENT_EVIDENCE remain traceable in
gate validation, verdict history, and preserved artifacts, but v1 does not
mislabel them as an Experiment Freeze; a deterministic closure dossier for
those outcomes is P1.

For a GO dossier, provide Chinese and English title, research question, safe
novelty claim, and decision rationale. Freeze closest papers, data and split,
strong baselines and budgets, primary experiment, mechanism ablations,
OOD/robustness tests, statistical protocol, reproducibility plan, and evidence
provenance.

Predeclare bilingual routes for meaningful positive, weak/inconclusive, and negative/equivalent/harmful outcomes. Each route must say exactly what claim survives and what action follows. The routes are interpretations of the same frozen research question, not post-hoc alternative stories.

The full experiment is not authorized by the Freeze artifact. Require a separate execution approval bound to its protocol hash, data scope, compute/cost ceiling, and external side effects.
