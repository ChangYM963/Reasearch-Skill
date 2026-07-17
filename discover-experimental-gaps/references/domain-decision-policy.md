# Decision, policy, and value-of-information adapter

Apply this adapter whenever a candidate claims that predictions, representations, uncertainty, or additional information improve an action, policy, allocation, intervention, or operational outcome. Predictive accuracy alone cannot pass this adapter.

## Define the decision problem

Record:

- decision maker, action space, decision time, and information set;
- target population and deployment distribution;
- utility, cost, harm, constraint, or regret function with units;
- current policy and simple feasible rules;
- outcome horizon and delayed or censored feedback;
- oracle information and whether it is attainable at decision time;
- primary policy estimand and SESOI on a decision-relevant scale;
- causal or off-policy assumptions needed to estimate policy value.

Separate three claims: the model predicts better, predictions change actions, and changed actions improve outcomes. Each arrow needs evidence. If only the first is tested, narrow the claim to prediction or stop the decision claim.

## Baseline and oracle ladder

Compare, as applicable:

1. current practice or status-quo policy;
2. constant allocation and a simple threshold/rule;
3. a calibrated score with an optimized but frozen threshold;
4. a strong policy or optimization baseline under the same information and constraints;
5. perfect-prediction, perfect-information, or constrained oracle;
6. error-informed and value-of-information probes that reveal where better information could alter actions.

Give every method the same feasible action set, resource constraint, information timing, and tuning budget. An oracle that uses unavailable future information is an upper bound, not a deployable comparator.

## Decision outcomes

Choose a primary endpoint such as expected utility, regret, net benefit, welfare, cost at fixed safety, or constraint violation. Also report action-change rate and the distribution of benefits/harms when they explain mechanism. Accuracy, AUC, likelihood, or calibration may support the analysis but cannot replace policy value.

Set the SESOI from the smallest operationally worthwhile gain after implementation cost and harm, not from a convenient predictive delta. Use asymmetric margins when harm is more consequential than benefit.

## Identification and evaluation audit

For observational or logged-policy evaluation, document:

- consistency, exchangeability/no-unmeasured-confounding assumptions;
- positivity/overlap and support diagnostics;
- propensity and outcome-model specification;
- direct, inverse-propensity, doubly robust, or other estimator choice;
- clustering, repeated decisions, interference, censoring, and missingness;
- sensitivity analysis and negative controls where appropriate.

Do not label an association or simulator result as causal deployment benefit. If identification is not credible, restrict the claim to retrospective policy value under stated assumptions or require a prospective/randomized design.

For simulation, validate the simulator on policy-relevant outcomes and test misspecification. For human-in-the-loop systems, measure adherence, overrides, automation bias, workload, and heterogeneous harm; model outputs do not imply that users act on them.

## Decision Smoke

Technical Smoke should answer:

- Does a prediction difference change any action under realistic thresholds and constraints?
- How much headroom exists between current/simple policies and the constrained oracle?
- Does an error-information probe improve policy value?
- Are policy-value estimates supported by overlap and stable weights?
- Are utility conclusions robust to plausible cost and harm ranges?

Precision Smoke must lock the policy estimand, SESOI/ROPE, information set, action constraints, evaluation estimator, independent unit, split, and uncertainty method. Protect the final policy-evaluation holdout.

Use the result as follows:

- GO: the decision problem is identifiable or prospectively testable, oracle headroom is meaningful, a realistic policy can change actions, and full-study precision is feasible.
- STOP: predictions do not change actions, constrained oracle headroom is negligible, implementation cost erases benefit, overlap/identification makes the claim impossible, or precise evidence rules out meaningful decision value.
- INSUFFICIENT_EVIDENCE: utility is unspecified, uncertainty is too wide, overlap is unresolved, or key scientific cost evidence is missing. Missing authorization is awaiting_user; an external ethics or access prohibition is a concrete blocker.

NARROW may target a prespecified budget, risk range, subgroup, information regime, or operating threshold only when it remains important and has independent support. Validate a post-result boundary on fresh data and re-audit the exact decision claim.

## Informative negative routes

A negative result can show that better predictions do not alter decisions, simple policies capture nearly all attainable value, benefits disappear after realistic costs, or gains occur only under a bounded information regime. Freeze these interpretations before the full experiment and require intervals tight enough to rule out the decision-relevant SESOI. Do not convert an imprecise policy-value estimate into AI does not help.
