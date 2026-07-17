# Decision and statistical contract

Use this reference when a candidate reaches falsification, Smoke planning, or Experiment Freeze. Treat statistical evidence as support for a bounded claim, not as a substitute for novelty or importance.

## Lock the scientific quantity first

Before looking at Smoke outcomes, record:

- the estimand and its direction;
- the independent experimental unit;
- one primary endpoint and any exploratory endpoints;
- the target population, distribution, budget, and decision context;
- the comparator and compute/tuning budget;
- the smallest effect size of interest (SESOI), expressed on the endpoint's natural or decision scale;
- the uncertainty framework and multiplicity policy.

Derive the SESOI from scientific or operational consequences, an external standard, a cost/utility model, or documented expert judgment. Do not derive it from the observed pilot effect. Use asymmetric lower and upper margins when gains and harms have different consequences.

Random seeds are not automatically independent scientific units. Account for uncertainty from examples, subjects, sites, datasets, time periods, environments, and training randomness at the level relevant to the claim. Preserve pairing and clustering in the interval estimator.

## Choose one confirmatory framework

Always report an effect estimate and uncertainty interval. Preselect either a frequentist equivalence route or a Bayesian ROPE route for a Precision Smoke or full experiment. Do not choose between them after seeing which gives the preferred answer.

### Frequentist route: CI and TOST

Let the equivalence region be [lower_margin, upper_margin], commonly [-delta, +delta].

- Practical equivalence requires both one-sided tests to pass at alpha. Equivalently, the (1 - 2*alpha) confidence interval must lie wholly inside the equivalence region. At alpha=0.05, this is the 90% CI.
- A conventional 95% CI may also be reported for estimation, but do not confuse it with the CI used by TOST.
- A meaningfully positive result requires the relevant interval bound to exceed the positive SESOI, not merely zero.
- A meaningfully harmful or reversed result requires the relevant interval bound to cross the negative meaningful-effect boundary in the harmful direction.
- Every other result is inconclusive. p > 0.05 is not evidence of equivalence.

Use a non-inferiority test, not TOST, when the scientific question is genuinely one-sided. Predeclare alpha, the margin, interval method, clustering/resampling, and any sequential or multiplicity adjustment.

### Bayesian route: ROPE

Set a ROPE from the same externally justified SESOI and lock:

- the likelihood and hierarchical structure;
- prior distributions;
- the posterior probability or interval decision threshold;
- the treatment of multiplicity;
- a prior-sensitivity analysis.

Classify practical equivalence only when the preregistered posterior criterion places sufficient mass inside the ROPE. Classify meaningful benefit or harm only under the corresponding preregistered posterior criterion outside the ROPE. Otherwise report inconclusive evidence. A ROPE conclusion is not interchangeable with a TOST p-value.

## Smoke precision

Separate two purposes:

1. **Technical Smoke** checks that the data path, split, leakage controls, metrics, simple rules, strong baselines, oracle, and resource estimates work. It may estimate variance and projected sample size, but it is not allowed to declare no meaningful effect from a noisy null.
2. **Precision Smoke** may support a candidate decision. It must lock the estimand, SESOI, primary endpoint, independent unit, analysis framework, target power or precision, split, multiplicity, and early-stop rules before execution.

Plan a Precision Smoke from the SESOI and an external or conservative variance estimate. Do not power it from an optimistic observed Technical Smoke effect. If the interval is too wide to distinguish meaningful benefit, equivalence, or harm, return INSUFFICIENT_EVIDENCE with a concrete sample/compute requirement.

Do not reuse the final confirmatory holdout for either Smoke. A post-result change to the claim, SESOI, split, primary endpoint, or analysis framework makes the old Precision conclusion exploratory for the revised claim.

## Candidate decision

Use exactly one terminal decision for the current claim version:

- **GO**: proceed to the frozen full experiment. All evidence gates pass; the test is feasible and discriminating; projected precision is attainable; and the exact claim passed Final Audit. GO does not mean that a positive result or publication is guaranteed.
- **STOP**: end this candidate because it is already covered, decision-inert, non-discriminating, unfair, infeasible, has negligible oracle headroom, or sufficiently precise evidence rules out the target meaningful effect.
- **INSUFFICIENT_EVIDENCE**: pause because critical scientific literature, data validity, variance, or precision evidence is missing. Missing execution authorization is `awaiting_user` (or `blocked` for a concrete external constraint), not a scientific insufficiency verdict.

NARROW is a claim-version transition, not a terminal decision. Record the old and new claim fingerprints and the evidence that justifies the narrower population, distribution, budget, mechanism, or decision context. Re-run every affected gate and use fresh or independent validation when the narrower claim was selected after observing results. Allow at most two NARROW transitions in one run by default; a third request blocks the current undecided run pending a human choice to STOP or start a genuinely new research question.

## Make null and negative outcomes informative

Freeze the outcome-to-claim mapping before the full experiment:

- meaningful positive: state the bounded claim that becomes supportable;
- practically equivalent: state which meaningful effect is ruled out;
- weak/inconclusive: state why no directional conclusion is permitted and what additional precision is needed;
- harmful/reversed: state the boundary, subgroup, robustness, or decision consequence revealed.

A zero or negative result is informative only when the comparison is fair, uncertainty is sufficiently tight, the tested effect is meaningful, and the result changes a scientific claim or practical choice. Do not turn an imprecise null into a negative-result story.

## Multiplicity and adaptive work

Keep one primary endpoint. Label extra metrics, subgroups, datasets, and OOD regimes as confirmatory only when they have a preregistered hierarchy or multiplicity control; otherwise label them exploratory. Predeclare any sequential stopping rule. A subgroup discovered from Smoke may motivate NARROW, but it needs independent evidence before it can support GO for a confirmatory claim.
