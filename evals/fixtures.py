from __future__ import annotations

import copy
import datetime as dt
import sys
from pathlib import Path
from typing import Any

EVAL_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = EVAL_ROOT.parent / "discover-experimental-gaps"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import gaplib


NOW = "2026-07-16T12:00:00+00:00"
CUTOFF = "2026-07-16"
AXES = [
    "problem",
    "population_or_data",
    "method_or_intervention",
    "comparator",
    "outcome_or_estimand",
    "decision_consequence",
    "mechanism",
    "recency",
]


def bilingual(zh: str, en: str) -> dict[str, str]:
    return {"zh": zh, "en": en}


def claim(gap_id: str, suffix: str = "") -> dict[str, Any]:
    return {
        "gap_id": gap_id,
        "title": bilingual("分布外决策价值检验", "OOD decision-value validation"),
        "research_question": bilingual(
            "稳健预测是否改善实际决策？" + suffix,
            "Does robust prediction improve downstream decisions?" + suffix,
        ),
        "novelty_claim": bilingual(
            "在预设分布偏移下，尚缺少相对强基线的决策价值验证。" + suffix,
            "Decision value against strong baselines remains unvalidated under prespecified shift."
            + suffix,
        ),
        "population": "Public benchmark cases",
        "data_regime": "Temporal OOD split",
        "method": "Uncertainty-aware predictor",
        "intervention": "Use uncertainty in the decision rule",
        "comparator_class": ["recent_strong", "simple_rule"],
        "outcome": "Decision utility",
        "estimand": "Paired mean utility difference",
        "quantifier": "At least the prespecified SESOI",
        "mechanism": "Selective action under uncertainty",
        "decision_consequence": "Lower regret at fixed action budget",
        "excluded_claims": ["universal superiority", "clinical benefit"],
        "sesoi": {"value": "0.02", "unit": "utility"},
    }


def candidate(
    candidate_id: str,
    basis_codes: list[str],
    prediction_claim: bool = False,
) -> dict[str, Any]:
    item = {
        "candidate_id": candidate_id,
        "basis_codes": basis_codes,
        "population": "Public benchmark cases",
        "data_regime": "Prespecified temporal OOD split",
        "method_or_intervention": "Uncertainty-aware decision rule",
        "strongest_comparator": "Recent strong model plus simple rule",
        "outcome_or_estimand": "Paired mean decision-utility difference",
        "sesoi": {"value": "0.02", "unit": "utility"},
        "mechanism_or_decision_consequence": "Selective action lowers regret",
        "refutation_experiment": "Oracle and strongest-baseline paired smoke",
        "closest_paper_search_terms": ["OOD decision utility", "value of information"],
        "venue_relevance": "Tests a decision-relevant robustness claim",
        "prediction_claim": prediction_claim,
    }
    if prediction_claim:
        item["decision_value_test"] = "Paired downstream utility comparison"
    return item


def protocol() -> dict[str, Any]:
    return {
        "data_version": "benchmark-v1",
        "split": "temporal-ood-v1",
        "baselines": ["simple-rule-v1", "strong-model-v2"],
        "strongest_baseline": "strong-model-v2",
        "metrics": ["utility", "regret"],
        "primary_endpoint": "paired utility difference",
        "statistical_route": "paired bootstrap CI",
        "budget": {"wall_time": {"value": "10", "unit": "minute"}},
        "code_version": "fixture-commit-1",
        "decision_rule": "GO if technical checks pass; no null STOP",
    }


def _attestation(prefix: str) -> dict[str, Any]:
    return {
        "status": "verified",
        "artifact_id": f"att-{prefix}",
        "method": "full-text identity and content check",
        "attested_at": NOW,
    }


def make_report(
    run_dir: Path,
    state: dict[str, Any],
    stage: str,
    prefix: str,
    *,
    critical_open: bool = False,
    missing_locator: bool = False,
    missing_ring: bool = False,
) -> dict[str, Any]:
    source_id = f"src-{prefix}"
    runs: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    rings = ["target_venue", "cross_venue", "citation_graph"]
    if missing_ring:
        rings = rings[:-1]
    for index, ring in enumerate(rings):
        run_id = f"search-{prefix}-{index}"
        raw_path = Path("raw") / f"{run_id}.md"
        absolute = run_dir / raw_path
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_text(
            f"# {stage} {ring}\nPrimary-source fixture.\n",
            encoding="utf-8",
        )
        runs.append({
            "id": run_id,
            "stage": stage,
            "ring": ring,
            "target_ref": state["scope"]["venue"],
            "claim_fingerprint": (
                None if stage == "venue_map" else state["fingerprints"]["claim"]
            ),
            "audit_fingerprint": None,
            "research_mode": "deep_research",
            "executed_at": NOW,
            "date_window": {"from": "2021-07-16", "through": CUTOFF},
            "queries": [f"{state['scope']['topic']} {ring}"],
            "channels": ["publisher", "scholarly_index"],
            "inclusion_criteria": ["primary source with experimental details"],
            "exclusion_criteria": ["metadata-only duplicate"],
            "coverage_axes": list(AXES),
            "included_source_ids": [source_id],
            "excluded_sources": [],
            "unresolved_lead_ids": [f"lead-{prefix}"] if critical_open and index == 0 else [],
            "raw_report": {
                "path": raw_path.as_posix(),
                "media_type": "text/markdown",
                "sha256": gaplib.sha256_file(absolute),
            },
            "base_ledger_version": state["ledger_version"],
        })
        evidence.append({
            "id": f"ev-{prefix}-{index}",
            "search_run_id": run_id,
            "source_id": source_id,
            "subject": {
                "kind": "claim" if stage != "venue_map" else "scope",
                "ref": (
                    state["fingerprints"]["claim"]
                    if stage != "venue_map"
                    else state["run_id"]
                ),
            },
            "proposition": f"Primary evidence for {stage} in {ring}.",
            "stance": "qualifies",
            "materiality": "material",
            "locator": None if missing_locator and index == 0 else {
                "kind": "pdf",
                "page": str(index + 1),
            },
            "content_attestation": _attestation(f"content-{prefix}-{index}"),
        })
    unresolved = []
    if critical_open:
        unresolved.append({
            "id": f"lead-{prefix}",
            "search_run_id": runs[0]["id"],
            "description": "Potential closest paper still needs full text.",
            "severity": "critical",
            "status": "open",
            "next_action": "Obtain and verify full text.",
            "resolution_evidence_ids": [],
        })
    report = {
        "schema_version": gaplib.SCHEMA_VERSION,
        "report_id": f"report-{prefix}",
        "created_at": NOW,
        "search_runs": runs,
        "sources": [{
            "id": source_id,
            "title": f"Primary source {prefix}",
            "identifiers": {"doi": f"10.1000/{prefix}"},
            "source_type": "conference_paper",
            "version": "published",
            "accessed_at": NOW,
            "access_level": "full_text",
            "identity_attestation": _attestation(f"identity-{prefix}"),
        }],
        "evidence": evidence,
        "unresolved_leads": unresolved,
    }
    if stage == "final_audit" and state["fingerprints"]["audit"] is not None:
        audit_hash = state["fingerprints"]["audit"]
        for search_run in report["search_runs"]:
            search_run["audit_fingerprint"] = audit_hash
    return report


def audit_protocol_for_report(
    state: dict[str, Any], report: dict[str, Any], prefix: str
) -> dict[str, Any]:
    synonyms = [
        "experimental gap",
        "out-of-distribution robustness",
        "decision value",
    ]
    spec = copy.deepcopy(gaplib.audit_spec_from_report(report, synonyms))
    return {
        "schema_version": gaplib.SCHEMA_VERSION,
        "audit_protocol_id": f"audit-protocol-{prefix}",
        "claim_fingerprint": state["fingerprints"]["claim"],
        **spec,
    }


def source_verification(
    gate: str, artifact_ids: list[str]
) -> dict[str, Any]:
    return {
        "gate": gate,
        "outcome": "PASS",
        "reviewer": "fixture-source-verifier",
        "artifact_ids_verified": artifact_ids,
        "checks": {
            "identity_verified": True,
            "locators_verified": True,
            "raw_hashes_verified": True,
            "full_text_verified": True,
        },
    }


def scientific_audit(
    state: dict[str, Any],
    gate: str,
    outcome: str,
    evidence_ids: list[str],
    subject_artifact_ids: list[str],
) -> dict[str, Any]:
    return {
        "gate": gate,
        "outcome": outcome,
        "claim_fingerprint": state["fingerprints"]["claim"],
        "protocol_fingerprint": state["fingerprints"]["protocol"],
        "audit_fingerprint": state["fingerprints"]["audit"],
        "evidence_ids": evidence_ids,
        "subject_artifact_ids": subject_artifact_ids,
        "reasoning": f"Fixture audit for {gate}: {outcome}.",
        "independence_level": "sequential_unblinded",
    }


def smoke_preregistration(
    state: dict[str, Any],
    *,
    kind: str = "technical",
    technical_kill_criteria: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": gaplib.SCHEMA_VERSION,
        "record_type": "smoke_preregistration",
        "preregistration_id": f"prereg-{kind}-1",
        "gap_id": state["run_id"],
        "claim_fingerprint": state["fingerprints"]["claim"],
        "smoke_kind": kind,
        "protocol": protocol(),
        "created_at": NOW,
        "rationale": bilingual("先验证可执行性。", "Test feasibility first."),
        "expected_discrimination": bilingual(
            "区分无余量和协议可行。", "Distinguish no headroom from a viable protocol."
        ),
    }
    if kind == "precision":
        current_claim = state["claim"]["current"]
        payload["precision_plan"] = {
            "estimand": current_claim["estimand"],
            "independent_unit": "paired benchmark case",
            "primary_endpoint": payload["protocol"]["primary_endpoint"],
            "sesoi": current_claim["sesoi"],
            "framework": "TOST",
            "lower_margin": "-0.02",
            "upper_margin": "0.02",
            "alpha": "0.05",
            "interval_level": "0.90",
            "split": payload["protocol"]["split"],
            "multiplicity_policy": "single primary endpoint",
        }
    if technical_kill_criteria is not None:
        payload["technical_kill_criteria"] = technical_kill_criteria
    return payload


def quantity(value: str, unit: str) -> dict[str, str]:
    return {"value": value, "unit": unit}


def smoke_authorization(
    state: dict[str, Any],
    prereg_hash: str,
    *,
    execute: bool = True,
    kind: str = "technical",
) -> dict[str, Any]:
    return {
        "schema_version": gaplib.SCHEMA_VERSION,
        "record_type": "smoke_authorization",
        "authorization_id": f"auth-{kind}-1",
        "status": "active",
        "authorized_by": "user",
        "authorization_event_id": "user-event-1",
        "granted_at": NOW,
        "expires_at": None,
        "smoke_kind": kind,
        "gap_id": state["run_id"],
        "claim_fingerprint": state["fingerprints"]["claim"],
        "protocol_fingerprint": state["fingerprints"]["protocol"],
        "preregistration_hash": prereg_hash,
        "permissions": {
            "design": True,
            "execute_local": execute,
            "train_models": False,
            "access_final_holdout": False,
            "install_dependencies": False,
            "use_external_api": False,
            "use_remote_compute": False,
            "external_upload": False,
        },
        "data_scope": [{
            "dataset_id": "benchmark",
            "version": "v1",
            "slices": ["smoke-train", "smoke-test"],
            "access": "read",
            "final_holdout": False,
        }],
        "compute_limits": {
            "wall_time": quantity("10", "minute"),
            "cpu_cores": quantity("2", "core"),
            "memory": quantity("4", "GiB"),
            "runs": quantity("2", "run"),
            "trials": quantity("2", "trial"),
            "seeds": quantity("2", "seed"),
            "cost": quantity("0", "USD"),
        },
        "network_allowlist": [],
        "filesystem_write_roots": ["fixture-output"],
        "privacy_constraints": [],
        "consumption": {},
    }


def smoke_result(
    state: dict[str, Any],
    authorization: dict[str, Any],
    *,
    kind: str = "technical",
    stop_basis: str = "none",
    interval_lower: str = "-0.01",
    interval_upper: str = "0.01",
) -> dict[str, Any]:
    payload = {
        "schema_version": gaplib.SCHEMA_VERSION,
        "record_type": "smoke_result",
        "result_id": f"result-{kind}-1",
        "gap_id": state["run_id"],
        "authorization_id": authorization["authorization_id"],
        "smoke_kind": kind,
        "claim_fingerprint": state["fingerprints"]["claim"],
        "protocol_fingerprint": state["fingerprints"]["protocol"],
        "preregistration_hash": authorization["preregistration_hash"],
        "operations": {
            "trained_models": False,
            "accessed_final_holdout": False,
            "installed_dependencies": False,
            "used_external_api": False,
            "used_remote_compute": False,
            "uploaded_external": False,
        },
        "resource_consumption": {
            "wall_time": quantity("1", "minute"),
            "runs": quantity("1", "run"),
        },
        "confidence_class": "adequate",
        "p_value_only": False,
        "precision_adequate": True,
        "stop_basis": stop_basis,
        "results": {
            "strong_baseline_executable": True,
            "oracle_executable": True,
            "primary_endpoint_measurable": True,
        },
        "completed_at": NOW,
    }
    if kind == "precision":
        payload["precision_evidence"] = {
            "estimate": "0",
            "interval_lower": interval_lower,
            "interval_upper": interval_upper,
            "interval_level": "0.90",
            "criterion_details": "Preregistered paired TOST interval.",
        }
    return payload


def gate_dossier() -> dict[str, Any]:
    rationale = bilingual("证据门已通过。", "Evidence gate passed.")
    return {
        "status": "PASS",
        "rationale": rationale,
        "evidence_refs": ["artifact:evidence"],
    }


def result_route(label: str) -> dict[str, Any]:
    return {
        "trigger": bilingual(f"{label}触发条件", f"{label} trigger"),
        "claim_that_survives": bilingual(f"{label}后保留的主张", f"Claim surviving {label}"),
        "interpretation": bilingual(f"{label}解释", f"{label} interpretation"),
        "next_action": bilingual(f"{label}下一步", f"Next action for {label}"),
    }


def freeze_dossier(state: dict[str, Any]) -> dict[str, Any]:
    gate_names = (
        "venue_fit",
        "evidence_sufficiency",
        "novelty",
        "importance",
        "discrimination",
        "baseline_fairness",
        "feasibility",
        "information_value",
        "smoke",
        "final_audit",
    )
    return {
        "schema_version": gaplib.SCHEMA_VERSION,
        "freeze_id": "freeze-1",
        "run_id": state["run_id"],
        "gap_id": state["run_id"],
        "claim_version": state["claim"]["current_version"],
        "claim_fingerprint": state["fingerprints"]["claim"],
        "protocol_fingerprint": state["fingerprints"]["protocol"],
        "audit_fingerprint": state["fingerprints"]["audit"],
        "artifact_status": "FROZEN_FOR_EXPERIMENT",
        "generated_at": NOW,
        "search_cutoff": CUTOFF,
        "venue": {
            "name": state["scope"]["venue"],
            "kind": "CONFERENCE",
            "scope_source": "https://example.org/scope",
            "target_window": "2027",
            "fit_rationale": bilingual("符合实验研究范围。", "Fits experimental scope."),
        },
        "domain_adapters": ["AI_ML"],
        "title": bilingual("分布外决策价值实验", "OOD Decision-Value Experiment"),
        "research_question": bilingual(
            "不确定性是否提高分布外决策效用？",
            "Does uncertainty improve OOD decision utility?",
        ),
        "safe_novelty_claim": bilingual(
            "截至检索截止日，特定协议下的决策价值尚未被充分验证。",
            "As of the cutoff, decision value under the specified protocol remains insufficiently validated.",
        ),
        "decision": {
            "status": "GO",
            "reason_codes": ["ALL_GATES_CURRENT"],
            "rationale": bilingual("五门与指纹一致。", "All gates and fingerprints agree."),
            "evidence_refs": ["artifact:gate-validation"],
            "unblock_requirements": [],
            "full_experiment_authorized": False,
        },
        "gates": {name: gate_dossier() for name in gate_names},
        "claim_history": [],
        "closest_papers": [{
            "paper_id": "paper-closest",
            "citation": "Closest et al. (2026)",
            "source_url": "https://example.org/paper",
            "doi": "10.1000/closest",
            "published_at": "2026-01-01",
            "verified_full_text": True,
            "relation": "PARTIALLY_COVERS",
            "differentiator": bilingual(
                "未检验预设决策效用。", "Does not test prespecified decision utility."
            ),
            "code_availability": "PUBLIC_VERIFIED",
            "data_availability": "PUBLIC_VERIFIED",
            "evidence_refs": ["artifact:closest-fulltext"],
        }],
        "data": [{
            "data_id": "benchmark",
            "version": "v1",
            "role": "OOD",
            "access": "PUBLIC",
            "license_or_basis": "Research license",
            "split_id": "temporal-ood-v1",
            "split_protocol": bilingual("按时间切分。", "Temporal split."),
            "independent_unit": "case",
            "distribution": bilingual("未来时间段。", "Future period."),
            "final_holdout": False,
        }],
        "baselines": [{
            "baseline_id": "strong-model-v2",
            "version": "v2",
            "category": "RECENT_STRONG",
            "source_ref": "https://example.org/baseline",
            "strength_rationale": bilingual("近期强基线。", "Recent strong baseline."),
            "data_access_parity": True,
            "compute_matching": "Matched wall time and tuning trials",
            "tuning_budget": "Two trials",
        }],
        "experiment_design": {
            "primary_experiment": bilingual(
                "比较配对决策效用。", "Compare paired decision utility."
            ),
            "comparison": bilingual(
                "同数据同预算比较。", "Same-data, same-budget comparison."
            ),
            "smoke_record_refs": ["artifact:result-technical-1"],
            "mechanism_ablations": [{
                "id": "ablation-uncertainty",
                "description": bilingual("移除不确定性。", "Remove uncertainty."),
            }],
            "oracle_or_voi_tests": [{
                "id": "oracle-perfect",
                "description": bilingual("完美信息上界。", "Perfect-information upper bound."),
            }],
            "compute_budget": "10 CPU-hours, 5 seeds",
            "stopping_rules": [
                bilingual("达到预设精度或预算。", "Stop at target precision or budget.")
            ],
        },
        "statistics": {
            "estimand": bilingual("配对平均效用差。", "Paired mean utility difference."),
            "independent_unit": "case",
            "primary_endpoint": "utility difference",
            "sesoi": {
                "scale": "utility",
                "lower_margin": -0.02,
                "upper_margin": 0.02,
                "rationale": bilingual("决策上最小有意义差异。", "Minimum decision-relevant effect."),
                "source": "https://example.org/sesoi",
                "locked_before_results": True,
            },
            "framework": {
                "type": "FREQUENTIST_ESTIMATION",
                "alpha": 0.05,
                "estimation_ci_level": 0.95,
                "interval_method": "paired bootstrap",
                "primary_test": "two-sided estimation",
            },
            "sample_size": 100,
            "target_precision": "95% CI half-width <= 0.02",
            "multiplicity_policy": "One primary endpoint",
            "missing_data_rule": "Report and sensitivity-analyze missing cases",
        },
        "robustness": {
            "ood_tests": [{
                "id": "ood-temporal",
                "description": bilingual("时间分布外。", "Temporal OOD."),
            }],
            "robustness_tests": [],
            "subgroup_tests": [],
            "threat_model": bilingual("时间漂移和校准误差。", "Temporal drift and miscalibration."),
        },
        "reproducibility": {
            "code_availability": "PLANNED_PUBLIC",
            "code_plan": bilingual("接收后公开。", "Release after acceptance."),
            "data_availability": "PUBLIC_VERIFIED",
            "data_plan": bilingual("记录版本与切分。", "Publish versions and splits."),
            "environment_ref": "artifact:environment-lock",
            "seed_policy": "Five prespecified seeds",
            "artifact_refs": ["artifact:protocol"],
        },
        "result_routes": {
            "positive": result_route("positive"),
            "weak_or_inconclusive": result_route("weak"),
            "negative_equivalent_or_harmful": result_route("negative"),
        },
        "final_audit": {
            "exact_claim_fingerprint": state["fingerprints"]["claim"],
            "status": "PASS",
            "searched_at": NOW,
            "search_cutoff": CUTOFF,
            "query_log_ref": "artifact:final-query-log",
            "new_closest_paper_ids": [],
            "evidence_refs": ["artifact:final-audit"],
        },
        "provenance": {
            "evidence_ledger_ref": "artifact:evidence-ledger",
            "venue_map_ref": "artifact:venue-map",
            "falsification_report_refs": ["artifact:falsification"],
            "smoke_record_refs": ["artifact:result-technical-1"],
            "final_audit_ref": "artifact:final-audit",
            "generated_by": "discover-experimental-gaps v1.0.0",
        },
    }


class Harness:
    def __init__(self, run_dir: Path, adapter: str = "ai-ml"):
        self.run_dir = run_dir
        gaplib.prepare_run(
            run_dir,
            "Fixture Conference",
            "robust decision learning",
            years=5,
            cutoff=CUTOFF,
            adapter=adapter,
            run_id="fixture-run",
        )

    @property
    def state(self) -> dict[str, Any]:
        return gaplib.load_state(self.run_dir)

    def record(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        return gaplib.record_result(
            self.run_dir, kind, payload, self.state["manifest_revision"]
        )

    def commit(self) -> dict[str, Any]:
        return gaplib.commit_validation(
            self.run_dir, self.state["manifest_revision"]
        )

    def ingest_research_stage(
        self,
        stage: str,
        prefix: str,
        audit_outcome: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report = make_report(self.run_dir, self.state, stage, prefix)
        if stage == "final_audit":
            protocol_payload = audit_protocol_for_report(
                self.state, report, prefix
            )
            self.record("audit_protocol", protocol_payload)
            for search_run in report["search_runs"]:
                search_run["audit_fingerprint"] = self.state["fingerprints"][
                    "audit"
                ]
        recorded = self.record("research_report", report)
        gate = {
            "venue_map": "venue_map",
            "falsification": "falsification",
            "final_audit": "final_audit",
        }[stage]
        self.record(
            "source_verification",
            source_verification(gate, [recorded["artifact_id"]]),
        )
        current = self.state
        self.record(
            "scientific_audit",
            scientific_audit(
                current,
                gate,
                audit_outcome,
                [item["id"] for item in report["evidence"]],
                [recorded["artifact_id"]],
            ),
        )
        return report, recorded

    def reach_smoke_design(self) -> None:
        self.ingest_research_stage("venue_map", "venue", "PASS")
        self.commit()
        self.record("claim", claim(self.state["run_id"]))
        self.record("candidate_board", {
            "stage": "discovery",
            "candidates": [
                candidate(
                    "gap-primary", ["missing_ood", "decision_value"], True
                ),
                candidate("gap-backup", ["boundary_unknown"]),
                candidate("gap-third", ["protocol_nonidentifying"]),
            ],
            "primary_candidate_id": "gap-primary",
            "backup_candidate_id": "gap-backup",
        })
        self.ingest_research_stage("falsification", "fals", "GO")
        self.record("candidate_board", {
            "stage": "falsification",
            "candidates": [
                candidate(
                    "gap-primary", ["missing_ood", "decision_value"], True
                ),
                candidate("gap-backup", ["boundary_unknown"]),
            ],
            "primary_candidate_id": "gap-primary",
            "backup_candidate_id": "gap-backup",
        })
        self.commit()

    def reach_final_audit_design(self) -> None:
        self.reach_smoke_design()
        prereg = smoke_preregistration(self.state)
        prereg_record = self.record("smoke_preregistration", prereg)
        auth = smoke_authorization(
            self.state, self.state["artifacts"][prereg_record["artifact_id"]]["sha256"]
        )
        self.record("smoke_authorization", auth)
        result = smoke_result(self.state, auth)
        result_record = self.record("smoke_result", result)
        self.record(
            "source_verification",
            source_verification(
                "smoke", [prereg_record["artifact_id"], result_record["artifact_id"]]
            ),
        )
        self.record(
            "scientific_audit",
            scientific_audit(
                self.state,
                "smoke",
                "GO",
                [result["result_id"]],
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        self.commit()

    def reach_science_gates(self) -> None:
        self.reach_final_audit_design()
        self.ingest_research_stage("final_audit", "final", "PASS")
        self.commit()

    def freeze(self) -> dict[str, Any]:
        dossier = freeze_dossier(self.state)
        self.record("experiment_freeze", dossier)
        return self.commit()
