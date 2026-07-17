# AI/ML empirical adapter

Apply this adapter to predictive, representation-learning, generative, retrieval, ranking, and benchmark-centered AI/ML candidates. It adds constraints to the core workflow and never weakens novelty, evidence, fairness, or information-value gates.

## Required claim fields

Specify:

- task, target population, deployment or evaluation distribution, and unit of analysis;
- model input and information available at inference time;
- comparator class and compute/tuning budget;
- primary estimand and metric, including direction and SESOI;
- training, validation, test, temporal, site, group, and OOD partitions;
- expected mechanism or failure mode;
- whether the claim concerns prediction, calibration, robustness, efficiency, mechanism, or a downstream decision.

Do not infer a decision benefit from predictive improvement. Add the decision/policy adapter whenever actions, utility, resource allocation, or intervention outcomes appear in the claim.

## Baseline ladder

Use the smallest ladder that can falsify the candidate:

1. constant/random or majority control where meaningful;
2. simple heuristic or linear/tree baseline;
3. a maintained classical or domain-standard method;
4. at least one recent strong baseline appropriate to the exact data and budget;
5. oracle/upper bound or error-information probe.

Match data access, preprocessing, hyperparameter-search opportunity, early stopping, external pretraining, retrieval corpus, and compute budget. Report parameter count, training/inference cost, and tuning trials when material. If a simple baseline matches the proposed advantage within a sufficiently precise SESOI, stop or narrow the complexity claim.

A paper's missing code or data is a reproducibility and feasibility fact, not a novelty gap by itself. Record repository links, licenses, versions, commits, checkpoints, and missing artifacts. A reproducibility study is a candidate only when it tests a precise consequential claim.

## Split and leakage audit

Check for:

- subject, user, patient, site, document, scene, graph-neighbor, or time overlap;
- duplicate or near-duplicate examples across splits;
- preprocessing, normalization, vocabulary, feature, prompt, or retrieval-index leakage;
- test-set model selection or repeated leaderboard tuning;
- pretraining or synthetic-data contamination;
- label availability that would not exist at deployment;
- OOD sets that differ only cosmetically or encode a trivial shortcut.

Freeze the split before Precision Smoke. A split change invalidates all compared arms and interval estimates. Preserve a final confirmatory holdout that neither Technical nor Precision Smoke touches.

## Uncertainty and replication

Do not treat seed-to-seed variance as the only uncertainty when the claim generalizes across examples, subjects, datasets, sites, or environments. Prefer paired estimates and resampling or hierarchical models at the appropriate independent unit. Report all authorized seeds and failed runs; do not select favorable seeds.

Lock one primary metric. Calibration, subgroup, efficiency, robustness, and auxiliary predictive metrics should be hierarchical or exploratory unless multiplicity is controlled. For tiny benchmark differences, define the SESOI before execution and report an interval, not only a leaderboard rank or p-value.

## OOD and robustness

Tie each test to a named shift or threat model:

- temporal, geographic, institutional, demographic, sensor, domain, language, prevalence, or policy shift;
- corruptions, missingness, label noise, adversarial perturbation, prompt variation, or retrieval failure;
- subgroup worst-case performance and calibration;
- compute, data, latency, and memory constraints.

Use a shift-matched strong baseline and state whether labels are available for adaptation. Tested on another dataset is not sufficient unless the new dataset isolates a transport or robustness claim.

## AI/ML Smoke gates

Technical Smoke must check metric direction, label shuffling, leakage, simple rules, one strong baseline, oracle headroom, and projected compute. Precision Smoke must use a frozen split, compute-matched comparisons, appropriate paired/clustered uncertainty, and a preregistered SESOI.

Return:

- GO only if the exact claim survives closest-paper audit, the strong baseline does not trivialize it, the experiment is discriminating, and full-study precision is feasible;
- STOP for covered work, leakage-dependent gains, negligible oracle headroom, decision-inert accuracy gains, unfair compute comparisons, or a precise absence of meaningful effect;
- INSUFFICIENT_EVIDENCE for missing full text, unknown contamination, underpowered intervals, inaccessible critical data, or unresolved baseline implementation.

If the broad claim fails only under particular distributions, budgets, or information regimes, NARROW to an externally motivated boundary and validate it on fresh data. Do not mine a favorable dataset, seed, subgroup, or metric and call it a new gap.
