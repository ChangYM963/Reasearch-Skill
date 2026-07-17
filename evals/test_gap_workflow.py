from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import fixtures

gaplib = fixtures.gaplib


class GapWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gap-eval-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def harness(self, name: str = "run") -> fixtures.Harness:
        return fixtures.Harness(self.root / name)

    def seed_venue_passed(
        self, harness: fixtures.Harness, prefix: str = "venue-seed"
    ) -> None:
        if harness.state["gates"]["venue_map"]["status"] == "passed":
            return
        harness.ingest_research_stage("venue_map", prefix, "PASS")
        harness.commit()

    def seed_narrowable_run(self, harness: fixtures.Harness) -> None:
        self.seed_venue_passed(harness, "venue-narrow")
        harness.record("claim", fixtures.claim(harness.state["run_id"]))
        harness.record("candidate_board", {
            "stage": "discovery",
            "candidates": [
                fixtures.candidate("gap-primary", ["missing_ood"]),
                fixtures.candidate("gap-backup", ["boundary_unknown"]),
                fixtures.candidate("gap-third", ["protocol_nonidentifying"]),
            ],
            "primary_candidate_id": "gap-primary",
            "backup_candidate_id": "gap-backup",
        })

    def commit_current_narrow(
        self, harness: fixtures.Harness, prefix: str
    ) -> None:
        harness.ingest_research_stage("falsification", prefix, "NARROW")
        validation = harness.commit()
        self.assertEqual(
            validation["gate_results"]["falsification"]["outcome"], "NARROW"
        )

    def test_prepare_has_five_independent_gates(self):
        harness = self.harness()
        state = harness.state
        self.assertEqual(set(state["gates"]), set(gaplib.GATE_NAMES))
        self.assertEqual(
            {record["status"] for record in state["gates"].values()},
            {"pending"},
        )
        self.assertEqual(state["decision"], "undecided")

    def test_committed_gate_sequence_projects_the_legal_phase_and_status(self):
        harness = self.harness()
        harness.ingest_research_stage("venue_map", "phase-venue", "PASS")
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("venue_map", "active"),
        )
        harness.commit()
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("discovery", "active"),
        )
        harness.record("claim", fixtures.claim(harness.state["run_id"]))
        harness.record("candidate_board", {
            "stage": "discovery",
            "candidates": [
                fixtures.candidate("phase-primary", ["missing_ood"]),
                fixtures.candidate("phase-backup", ["boundary_unknown"]),
                fixtures.candidate("phase-third", ["protocol_nonidentifying"]),
            ],
            "primary_candidate_id": "phase-primary",
            "backup_candidate_id": "phase-backup",
        })
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("falsification", "awaiting_research"),
        )
        harness.ingest_research_stage("falsification", "phase-fals", "GO")
        harness.record("candidate_board", {
            "stage": "falsification",
            "candidates": [
                fixtures.candidate("phase-primary", ["missing_ood"]),
                fixtures.candidate("phase-backup", ["boundary_unknown"]),
            ],
            "primary_candidate_id": "phase-primary",
            "backup_candidate_id": "phase-backup",
        })
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("falsification", "active"),
        )
        harness.commit()
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("smoke", "active"),
        )

        prereg_record = harness.record(
            "smoke_preregistration", fixtures.smoke_preregistration(harness.state)
        )
        self.assertEqual(harness.state["run_status"], "awaiting_user")
        auth = fixtures.smoke_authorization(
            harness.state,
            harness.state["artifacts"][prereg_record["artifact_id"]]["sha256"],
        )
        harness.record("smoke_authorization", auth)
        result_record = harness.record(
            "smoke_result", fixtures.smoke_result(harness.state, auth)
        )
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "smoke", [prereg_record["artifact_id"], result_record["artifact_id"]]
            ),
        )
        harness.record(
            "scientific_audit",
            fixtures.scientific_audit(
                harness.state,
                "smoke",
                "GO",
                [fixtures.smoke_result(harness.state, auth)["result_id"]],
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        harness.commit()
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("final_audit", "awaiting_research"),
        )
        harness.ingest_research_stage("final_audit", "phase-final", "PASS")
        harness.commit()
        self.assertEqual(
            (harness.state["phase"], harness.state["run_status"]),
            ("freeze", "active"),
        )
        harness.record("experiment_freeze", fixtures.freeze_dossier(harness.state))
        harness.commit()
        self.assertEqual(
            (
                harness.state["phase"], harness.state["run_status"],
                harness.state["decision"],
            ),
            ("closed", "complete", "GO"),
        )

    def test_no_research_connection_emits_handoff_and_never_goes(self):
        harness = self.harness()
        handoff = gaplib.build_research_handoff(harness.state, "venue_map")
        harness.record("research_handoff", handoff)
        state = harness.state
        self.assertEqual(state["run_status"], "awaiting_research")
        self.assertEqual(state["gates"]["venue_map"]["status"], "awaiting_report")
        validation = gaplib.derive_validation(harness.run_dir)
        self.assertEqual(
            validation["gate_results"]["venue_map"]["status"],
            "awaiting_report",
        )
        self.assertNotEqual(state["decision"], "GO")

    def test_canonical_fingerprints_equivalence_and_change(self):
        base = fixtures.claim("fixture-run")
        reordered = copy.deepcopy(base)
        reordered["excluded_claims"] = list(reversed(base["excluded_claims"]))
        reordered["title"]["en"] = "  " + reordered["title"]["en"] + "  "
        self.assertEqual(
            gaplib.claim_fingerprint(base),
            gaplib.claim_fingerprint(reordered),
        )
        changed = copy.deepcopy(base)
        changed["outcome"] = "Accuracy only"
        self.assertNotEqual(
            gaplib.claim_fingerprint(base),
            gaplib.claim_fingerprint(changed),
        )
        p1 = gaplib.protocol_fingerprint(
            gaplib.claim_fingerprint(base), fixtures.protocol()
        )
        modified = fixtures.protocol()
        modified["strongest_baseline"] = "future-model-v3"
        self.assertNotEqual(
            p1,
            gaplib.protocol_fingerprint(
                gaplib.claim_fingerprint(base), modified
            ),
        )

    def test_pseudo_gaps_are_recorded_without_advancing_or_stopping(self):
        harness = self.harness()
        self.seed_venue_passed(harness, "venue-pseudo")
        harness.record("claim", fixtures.claim(harness.state["run_id"]))
        board = {
            "stage": "discovery",
            "candidates": [],
            "rejected_candidates": [
                {
                    "candidate_id": f"candidate-{index}",
                    "rejection_codes": [code],
                    "rejection_reasons": [f"Hard veto: {code}"],
                }
                for index, code in enumerate((
                    "add_dataset", "model_swap", "routine_ablation",
                    "accuracy_without_decision",
                ))
            ],
            "primary_candidate_id": None,
            "backup_candidate_id": None,
        }
        harness.record("candidate_board", board)
        self.assertEqual(harness.state["phase"], "discovery")
        self.assertEqual(harness.state["run_status"], "active")
        self.assertEqual(harness.state["decision"], "undecided")
        stored = gaplib.read_json(gaplib.run_paths(harness.run_dir)["candidates"])
        self.assertEqual(stored["board_status"], "no_viable_candidate")
        self.assertEqual(len(stored["rejected_candidates"]), 4)

    def test_pseudo_gap_omission_and_missing_decision_cannot_bypass_validation(self):
        pseudo = fixtures.candidate("candidate-pseudo", ["add_dataset"])
        board = {
            "stage": "discovery",
            "candidates": [
                pseudo,
                fixtures.candidate("candidate-good-1", ["missing_ood"]),
                fixtures.candidate("candidate-good-2", ["boundary_unknown"]),
            ],
        }
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.validate_candidate_board(board)
        self.assertEqual(caught.exception.code, "PSEUDO_GAP_MISCLASSIFIED")

        missing_basis = fixtures.candidate("candidate-missing", ["missing_ood"])
        del missing_basis["basis_codes"]
        board["candidates"][0] = missing_basis
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.validate_candidate_board(board)
        self.assertEqual(caught.exception.code, "CANDIDATE_BASIS_REQUIRED")

        missing_decision = fixtures.candidate(
            "candidate-prediction", ["missing_ood"], prediction_claim=True
        )
        del missing_decision["decision_value_test"]
        board["candidates"][0] = missing_decision
        with self.assertRaisesRegex(gaplib.GapError, "decision-value"):
            gaplib.validate_candidate_board(board)

    def test_every_pseudo_gap_code_requires_the_rejected_array(self):
        for code in sorted(gaplib.PSEUDO_GAP_CODES):
            with self.subTest(code=code):
                misclassified = {
                    "stage": "discovery",
                    "candidates": [
                        fixtures.candidate("pseudo", [code]),
                        fixtures.candidate("good-1", ["missing_ood"]),
                        fixtures.candidate("good-2", ["boundary_unknown"]),
                    ],
                }
                with self.assertRaises(gaplib.GapError) as caught:
                    gaplib.validate_candidate_board(misclassified)
                self.assertEqual(caught.exception.code, "PSEUDO_GAP_MISCLASSIFIED")
                recorded = {
                    "stage": "discovery",
                    "candidates": [
                        fixtures.candidate("good-1", ["missing_ood"]),
                        fixtures.candidate("good-2", ["boundary_unknown"]),
                    ],
                    "rejected_candidates": [{
                        "candidate_id": "pseudo",
                        "rejection_codes": [code],
                        "rejection_reasons": [f"Hard veto: {code}"],
                    }],
                }
                gaplib.validate_candidate_board(recorded)

    def test_research_report_derived_checks_ignore_self_claims(self):
        harness = self.harness()
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "valid"
        )
        checks = gaplib.research_report_checks(report, harness.state, harness.run_dir)
        self.assertTrue(checks["structurally_ready"])
        self.assertEqual(
            set(checks["rings_present"]),
            {"target_venue", "cross_venue", "citation_graph"},
        )
        report["coverage"] = True
        report["verified"] = True
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.research_report_checks(report, harness.state, harness.run_dir)
        self.assertEqual(caught.exception.code, "SCHEMA_VALIDATION_FAILED")

    def test_research_report_rejects_ring_identifier_fk_locator_and_query_gaps(self):
        cases = []
        harness = self.harness()
        cases.append(fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "ring", missing_ring=True
        ))
        locator = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "locator", missing_locator=True
        )
        cases.append(locator)
        no_query = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "query"
        )
        no_query["search_runs"][0]["queries"] = []
        cases.append(no_query)
        bad_fk = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "fk"
        )
        bad_fk["evidence"][0]["source_id"] = "missing-source"
        cases.append(bad_fk)
        no_identifier = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "identifier"
        )
        no_identifier["sources"][0]["identifiers"] = {}
        cases.append(no_identifier)
        outside = self.root / "outside-raw.md"
        outside.write_text("outside run root", encoding="utf-8")
        absolute_raw = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "absolute-raw"
        )
        absolute_raw["search_runs"][0]["raw_report"]["path"] = str(outside)
        absolute_raw["search_runs"][0]["raw_report"]["sha256"] = (
            gaplib.sha256_file(outside)
        )
        cases.append(absolute_raw)
        for report in cases:
            with self.subTest(report=report["report_id"]):
                with self.assertRaises(gaplib.GapError):
                    gaplib.record_result(
                        harness.run_dir,
                        "research_report",
                        report,
                        harness.state["manifest_revision"],
                    )

    def test_critical_unresolved_lead_blocks_structural_readiness(self):
        harness = self.harness()
        report = fixtures.make_report(
            harness.run_dir,
            harness.state,
            "venue_map",
            "critical",
            critical_open=True,
        )
        checks = gaplib.research_report_checks(report, harness.state, harness.run_dir)
        self.assertFalse(checks["structurally_ready"])
        self.assertEqual(checks["critical_open"], ["lead-critical"])

    def test_source_verification_cannot_false_pass(self):
        harness = self.harness()
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "verification-false"
        )
        recorded = harness.record("research_report", report)
        payload = fixtures.source_verification(
            "venue_map", [recorded["artifact_id"]]
        )
        payload["checks"]["locators_verified"] = False
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("source_verification", payload)
        self.assertEqual(caught.exception.code, "VERIFICATION_FALSE_PASS")

    def test_identical_ingest_is_idempotent_but_stale_writer_loses(self):
        harness = self.harness()
        self.seed_venue_passed(harness, "venue-idempotent")
        payload = fixtures.claim(harness.state["run_id"])
        first = harness.record("claim", payload)
        second = gaplib.record_result(
            harness.run_dir,
            "claim",
            payload,
            harness.state["manifest_revision"],
        )
        self.assertEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(second["status"], "idempotent")

        other = self.harness("concurrent")
        self.seed_venue_passed(other, "venue-concurrent")
        payload = fixtures.claim(other.state["run_id"])
        base_revision = other.state["manifest_revision"]

        def write():
            try:
                return gaplib.record_result(
                    other.run_dir, "claim", payload, base_revision
                )
            except gaplib.GapError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: write(), range(2)))
        self.assertEqual(
            sum(isinstance(item, dict) for item in outcomes), 1
        )
        self.assertEqual(outcomes.count("STALE_REVISION"), 1)

    def test_status_is_strictly_read_only(self):
        harness = self.harness()
        before = gaplib.recursive_hashes(harness.run_dir)
        first = gaplib.status_summary(harness.run_dir)
        second = gaplib.status_summary(harness.run_dir)
        after = gaplib.recursive_hashes(harness.run_dir)
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_unknown_schema_major_is_rejected(self):
        harness = self.harness()
        path = gaplib.run_paths(harness.run_dir)["state"]
        state = gaplib.read_json(path)
        state["schema_version"] = "2.0.0"
        gaplib.atomic_write_json(path, state)
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.status_summary(harness.run_dir)
        self.assertEqual(caught.exception.code, "SCHEMA_INCOMPATIBLE")

    def test_atomic_write_failure_preserves_previous_file(self):
        path = self.root / "atomic.json"
        gaplib.atomic_write_json(path, {"version": 1})
        original = path.read_bytes()
        with mock.patch.object(gaplib.os, "replace", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                gaplib.atomic_write_json(path, {"version": 2})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_every_dependency_matrix_row_and_history_preservation(self):
        for change_type, row in gaplib.DEPENDENCY_MATRIX.items():
            with self.subTest(change_type=change_type):
                harness = self.harness(f"matrix-{change_type}")
                state_path = gaplib.run_paths(harness.run_dir)["state"]
                state = harness.state
                artifact_path = harness.run_dir / "artifacts" / "fixture-artifact.json"
                gaplib.atomic_write_json(artifact_path, {"fixture": change_type})
                digest = gaplib.sha256_data({"fixture": change_type})
                for index, gate_name in enumerate(gaplib.GATE_NAMES):
                    artifact_id = f"artifact-{index}"
                    state["artifacts"][artifact_id] = {
                        "artifact_id": artifact_id,
                        "kind": "fixture",
                        "path": "artifacts/fixture-artifact.json",
                        "sha256": digest,
                        "input_hashes": {
                            "claim": None,
                            "protocol": None,
                            "audit": None,
                        },
                        "subject_refs": [f"gate:{gate_name}"],
                        "status": "current",
                        "sequence": index + 1,
                        "recorded_at": fixtures.NOW,
                    }
                    state["gates"][gate_name]["artifact_ids"] = [artifact_id]
                gaplib.atomic_write_json(state_path, state)
                revision_inputs = {}
                if change_type == "venue_scope":
                    new_scope = copy.deepcopy(state["scope"])
                    new_scope["topic"] = f"{new_scope['topic']} revised"
                    revision_inputs["new_scope"] = new_scope
                elif change_type in ("claim_semantics", "target_distribution"):
                    revision_inputs["new_claim"] = fixtures.claim(
                        state["run_id"], suffix=f" {change_type}"
                    )
                result = gaplib.queue_revision(
                    harness.run_dir,
                    change_type,
                    "matrix fixture",
                    0,
                    **revision_inputs,
                )
                after = harness.state
                for gate_name, action in zip(gaplib.GATE_NAMES, row):
                    expected = {
                        "P": "pending",
                        "R": "review_required",
                        "I": "stale",
                    }[action]
                    self.assertEqual(after["gates"][gate_name]["status"], expected)
                self.assertTrue(artifact_path.exists())
                self.assertTrue(result["preserved"] or result["invalidated"])

    def test_baseline_change_stales_smoke_and_final_but_not_venue(self):
        harness = self.harness()
        harness.reach_science_gates()
        before_ids = set(harness.state["artifacts"])
        result = gaplib.queue_revision(
            harness.run_dir,
            "baseline",
            "New full-text paper changes strongest baseline.",
            harness.state["manifest_revision"],
        )
        state = harness.state
        self.assertEqual(state["gates"]["venue_map"]["status"], "passed")
        self.assertEqual(state["gates"]["falsification"]["status"], "review_required")
        self.assertEqual(state["gates"]["smoke"]["status"], "stale")
        self.assertEqual(state["gates"]["final_audit"]["status"], "stale")
        self.assertIsNone(state["fingerprints"]["protocol"])
        self.assertTrue(before_ids.issubset(state["artifacts"]))
        self.assertIn("smoke", result["invalidated"])

    def test_narrow_is_bounded_and_never_a_terminal_decision(self):
        harness = self.harness()
        self.seed_narrowable_run(harness)
        for index in range(2):
            self.commit_current_narrow(harness, f"narrow-verdict-{index}")
            narrowed_claim = fixtures.claim(
                harness.state["run_id"], suffix=f" narrow {index}"
            )
            narrowed_claim["population"] = f"Public benchmark cases narrow {index}"
            result = gaplib.queue_revision(
                harness.run_dir,
                "claim_semantics",
                f"narrow {index}",
                harness.state["manifest_revision"],
                new_claim=narrowed_claim,
                narrow=True,
            )
            self.assertEqual(result["status"], "queued")
            self.assertEqual(harness.state["decision"], "undecided")
        self.commit_current_narrow(harness, "narrow-verdict-2")
        blocked = gaplib.queue_revision(
            harness.run_dir,
            "claim_semantics",
            "third narrow",
            harness.state["manifest_revision"],
            new_claim=fixtures.claim(
                harness.state["run_id"], suffix=" narrow 3"
            ),
            narrow=True,
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(harness.state["run_status"], "blocked")

    def test_wording_only_change_cannot_impersonate_semantic_narrow(self):
        harness = self.harness()
        self.seed_narrowable_run(harness)
        self.commit_current_narrow(harness, "wording-verdict")
        wording_only = fixtures.claim(harness.state["run_id"], suffix=" reworded")
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.queue_revision(
                harness.run_dir,
                "claim_semantics",
                "wording-only change",
                harness.state["manifest_revision"],
                new_claim=wording_only,
                narrow=True,
            )
        self.assertEqual(caught.exception.code, "CHANGE_CLASS_MISMATCH")

    def test_narrow_requires_a_current_committed_verdict(self):
        harness = self.harness()
        self.seed_venue_passed(harness, "venue-no-narrow")
        harness.record("claim", fixtures.claim(harness.state["run_id"]))
        new_claim = fixtures.claim(harness.state["run_id"], suffix=" narrow")
        new_claim["population"] = "Narrow population"
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.queue_revision(
                harness.run_dir,
                "claim_semantics",
                "unreviewed narrow",
                harness.state["manifest_revision"],
                new_claim=new_claim,
                narrow=True,
            )
        self.assertEqual(caught.exception.code, "NARROW_VERDICT_REQUIRED")

    def test_smoke_execution_requires_permission_and_matching_kind(self):
        harness = self.harness()
        harness.reach_smoke_design()
        prereg_record = harness.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(harness.state),
        )
        prereg_hash = harness.state["artifacts"][prereg_record["artifact_id"]]["sha256"]
        denied = fixtures.smoke_authorization(
            harness.state, prereg_hash, execute=False
        )
        harness.record("smoke_authorization", denied)
        result = fixtures.smoke_result(harness.state, denied)
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("smoke_result", result)
        self.assertEqual(caught.exception.code, "EXECUTION_NOT_AUTHORIZED")

        allowed = self.harness("kind")
        allowed.reach_smoke_design()
        prereg_record = allowed.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(allowed.state),
        )
        auth = fixtures.smoke_authorization(
            allowed.state,
            allowed.state["artifacts"][prereg_record["artifact_id"]]["sha256"],
        )
        allowed.record("smoke_authorization", auth)
        result = fixtures.smoke_result(allowed.state, auth, kind="precision")
        with self.assertRaises(gaplib.GapError) as caught:
            allowed.record("smoke_result", result)
        self.assertEqual(caught.exception.code, "SMOKE_KIND_ESCALATION")

    def test_gate_pass_cannot_be_ingested_or_self_declared(self):
        harness = self.harness()
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.record_result(
                harness.run_dir,
                "gate_validation",
                {"gates": {"venue_map": {"status": "passed"}}},
                0,
            )
        self.assertEqual(caught.exception.code, "GATE_WRITE_FORBIDDEN")

    def test_authorization_rejects_hash_scope_units_and_unauthorized_operations(self):
        harness = self.harness()
        harness.reach_smoke_design()
        prereg_record = harness.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(harness.state),
        )
        prereg_hash = harness.state["artifacts"][prereg_record["artifact_id"]]["sha256"]
        valid = fixtures.smoke_authorization(harness.state, prereg_hash)
        mutations = []
        stale = copy.deepcopy(valid)
        stale["claim_fingerprint"] = "0" * 64
        mutations.append((stale, "AUTH_HASH_MISMATCH"))
        no_scope = copy.deepcopy(valid)
        no_scope["data_scope"] = []
        mutations.append((no_scope, "SCHEMA_VALIDATION_FAILED"))
        no_unit = copy.deepcopy(valid)
        del no_unit["compute_limits"]["wall_time"]["unit"]
        mutations.append((no_unit, "SCHEMA_VALIDATION_FAILED"))
        holdout_permission = copy.deepcopy(valid)
        holdout_permission["permissions"]["access_final_holdout"] = True
        mutations.append((holdout_permission, "FINAL_HOLDOUT_FORBIDDEN"))
        holdout_scope = copy.deepcopy(valid)
        holdout_scope["data_scope"][0]["final_holdout"] = True
        mutations.append((holdout_scope, "FINAL_HOLDOUT_FORBIDDEN"))
        upload_without_destination = copy.deepcopy(valid)
        upload_without_destination["permissions"]["external_upload"] = True
        mutations.append((upload_without_destination, "AUTH_NETWORK_SCOPE_MISSING"))
        for payload, code in mutations:
            with self.subTest(code=code):
                with self.assertRaises(gaplib.GapError) as caught:
                    gaplib.validate_smoke_authorization(
                        harness.run_dir, harness.state, payload
                    )
                self.assertEqual(caught.exception.code, code)

        harness.record("smoke_authorization", valid)
        result = fixtures.smoke_result(harness.state, valid)
        result["operations"]["trained_models"] = True
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("smoke_result", result)
        self.assertEqual(caught.exception.code, "OPERATION_NOT_AUTHORIZED")
        result = fixtures.smoke_result(harness.state, valid)
        result["operations"]["accessed_final_holdout"] = True
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("smoke_result", result)
        self.assertEqual(caught.exception.code, "OPERATION_NOT_AUTHORIZED")

    def test_freeze_rejects_stale_hash_even_after_prior_science_pass(self):
        harness = self.harness()
        harness.reach_science_gates()
        dossier = fixtures.freeze_dossier(harness.state)
        gaplib.queue_revision(
            harness.run_dir,
            "baseline",
            "New strongest baseline.",
            harness.state["manifest_revision"],
        )
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("experiment_freeze", dossier)
        self.assertEqual(caught.exception.code, "ILLEGAL_TRANSITION")

    def test_technical_or_imprecise_null_cannot_stop(self):
        harness = self.harness()
        harness.reach_smoke_design()
        precision_prereg = fixtures.smoke_preregistration(
            harness.state, kind="precision"
        )
        technical = {
            "smoke_kind": "technical",
            "confidence_class": "adequate",
            "stop_basis": "TOST",
            "precision_adequate": True,
            "p_value_only": False,
        }
        self.assertFalse(gaplib._precision_stop_valid(precision_prereg, technical))
        valid = {
            "smoke_kind": "precision",
            "confidence_class": "adequate",
            "stop_basis": "TOST",
            "precision_adequate": True,
            "p_value_only": False,
            "precision_evidence": {
                "estimate": "0",
                "interval_lower": "-0.01",
                "interval_upper": "0.01",
                "interval_level": "0.90",
                "criterion_details": "paired TOST",
            },
        }
        self.assertTrue(gaplib._precision_stop_valid(precision_prereg, valid))
        for mutation in (
            {"precision_adequate": False},
            {"p_value_only": True},
            {"confidence_class": "wide"},
        ):
            result = copy.deepcopy(valid)
            result.update(mutation)
            self.assertFalse(gaplib._precision_stop_valid(precision_prereg, result))

    def test_precision_stop_requires_strict_sesoi_bound_interval(self):
        harness = self.harness()
        harness.reach_smoke_design()
        prereg = fixtures.smoke_preregistration(harness.state, kind="precision")
        gaplib._validate_precision_plan(harness.state, prereg)
        base = {
            "smoke_kind": "precision",
            "confidence_class": "adequate",
            "stop_basis": "TOST",
            "precision_adequate": True,
            "p_value_only": False,
            "precision_evidence": {
                "estimate": "0",
                "interval_lower": "-0.01",
                "interval_upper": "0.01",
                "interval_level": "0.90",
                "criterion_details": "paired TOST",
            },
        }
        self.assertTrue(gaplib._precision_stop_valid(prereg, base))
        for lower, upper in (
            ("-0.02", "0.01"),
            ("-0.01", "0.02"),
            ("-0.03", "0.01"),
        ):
            result = copy.deepcopy(base)
            result["precision_evidence"]["interval_lower"] = lower
            result["precision_evidence"]["interval_upper"] = upper
            self.assertFalse(gaplib._precision_stop_valid(prereg, result))
        outside = copy.deepcopy(base)
        outside["precision_evidence"]["estimate"] = "0.5"
        self.assertFalse(gaplib._precision_stop_valid(prereg, outside))

    def test_precision_plan_rejects_unbound_margins_and_tiny_interval(self):
        harness = self.harness()
        harness.reach_smoke_design()
        for field, value, code in (
            ("upper_margin", "999", "PRECISION_MARGIN_SESOI_MISMATCH"),
            ("interval_level", "0.01", "PRECISION_LEVEL_INVALID"),
        ):
            prereg = fixtures.smoke_preregistration(harness.state, kind="precision")
            prereg["precision_plan"][field] = value
            with self.subTest(field=field):
                with self.assertRaises(gaplib.GapError) as caught:
                    gaplib._validate_precision_plan(harness.state, prereg)
                self.assertEqual(caught.exception.code, code)

    def test_technical_stop_uses_structured_bound_criterion(self):
        harness = self.harness()
        harness.reach_smoke_design()
        criterion = {
            "criterion_id": "no-headroom",
            "basis": "NO_ORACLE_HEADROOM",
            "measure": "oracle_headroom",
            "operator": "<=",
            "threshold": "0",
            "unit": "utility",
        }
        prereg = fixtures.smoke_preregistration(
            harness.state,
            technical_kill_criteria=[criterion],
        )
        result = {
            "result_id": "result-technical-1",
            "smoke_kind": "technical",
            "stop_basis": "NO_ORACLE_HEADROOM",
            "p_value_only": False,
            "results": {"oracle_headroom": "0"},
            "hard_stop_evidence": {
                "criterion_id": "no-headroom",
                "basis": "NO_ORACLE_HEADROOM",
                "observation": {"value": "0", "unit": "utility"},
                "evidence_refs": [
                    "result:result-technical-1#/results/oracle_headroom"
                ],
            },
        }
        self.assertTrue(gaplib._technical_hard_stop_valid(prereg, result))
        forged = copy.deepcopy(result)
        forged["hard_stop_evidence"]["evidence_refs"] = ["fabricated"]
        self.assertFalse(gaplib._technical_hard_stop_valid(prereg, forged))
        not_met = copy.deepcopy(result)
        not_met["results"]["oracle_headroom"] = "0.1"
        not_met["hard_stop_evidence"]["observation"]["value"] = "0.1"
        self.assertFalse(gaplib._technical_hard_stop_valid(prereg, not_met))

    def test_duplicate_technical_criterion_ids_are_rejected(self):
        harness = self.harness()
        harness.reach_smoke_design()
        first = {
            "criterion_id": "duplicate",
            "basis": "LEAKAGE",
            "measure": "leakage_rate",
            "operator": ">",
            "threshold": "0",
            "unit": "fraction",
        }
        second = copy.deepcopy(first)
        second["threshold"] = "0.01"
        prereg = fixtures.smoke_preregistration(
            harness.state,
            technical_kill_criteria=[first, second],
        )
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("smoke_preregistration", prereg)
        self.assertEqual(caught.exception.code, "TECHNICAL_CRITERION_ID_DUPLICATE")

    def test_incomplete_run_cannot_finalize(self):
        harness = self.harness()
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.finalize_run(
                harness.run_dir, harness.state["manifest_revision"]
            )
        self.assertEqual(caught.exception.code, "RUN_NOT_FREEZABLE")

    def test_falsification_stop_closes_without_freeze(self):
        harness = self.harness()
        harness.ingest_research_stage("venue_map", "venue-stop", "PASS")
        harness.commit()
        harness.record("claim", fixtures.claim(harness.state["run_id"]))
        harness.record("candidate_board", {
            "stage": "discovery",
            "candidates": [
                fixtures.candidate("stop-primary", ["missing_ood"]),
                fixtures.candidate("stop-backup", ["boundary_unknown"]),
                fixtures.candidate("stop-third", ["protocol_nonidentifying"]),
            ],
            "primary_candidate_id": "stop-primary",
            "backup_candidate_id": "stop-backup",
        })
        harness.ingest_research_stage("falsification", "fals-stop", "STOP")
        validation = harness.commit()
        self.assertEqual(
            validation["gate_results"]["falsification"]["outcome"], "STOP"
        )
        state = harness.state
        self.assertEqual(state["decision"], "STOP")
        self.assertEqual(state["run_status"], "complete")
        self.assertEqual(state["phase"], "closed")
        revised = fixtures.claim(state["run_id"], suffix=" reopen")
        revised["population"] = "Attempted reopened population"
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.queue_revision(
                harness.run_dir,
                "claim_semantics",
                "attempt to reopen STOP",
                state["manifest_revision"],
                new_claim=revised,
            )
        self.assertEqual(caught.exception.code, "STOP_RUN_CLOSED")
        self.assertNotEqual(
            state["gates"]["freeze_validation"]["status"], "passed"
        )

    def test_complete_go_freeze_and_markdown_are_deterministic(self):
        harness = self.harness()
        harness.reach_science_gates()
        science = harness.state
        for gate in gaplib.GATE_NAMES[:-1]:
            self.assertEqual(science["gates"][gate]["status"], "passed")
        harness.freeze()
        state = harness.state
        self.assertEqual(state["decision"], "GO")
        self.assertEqual(state["run_status"], "complete")
        first = gaplib.finalize_run(
            harness.run_dir, harness.state["manifest_revision"]
        )
        first_bytes = Path(first["output"]).read_bytes()
        second = gaplib.finalize_run(
            harness.run_dir, harness.state["manifest_revision"]
        )
        second_bytes = Path(second["output"]).read_bytes()
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first_bytes, second_bytes)
        self.assertIn("OOD Decision-Value Experiment", first_bytes.decode("utf-8"))

    def test_artifact_tampering_is_detected_before_gate_validation(self):
        harness = self.harness()
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "tamper"
        )
        recorded = harness.record("research_report", report)
        record = harness.state["artifacts"][recorded["artifact_id"]]
        artifact_path = harness.run_dir / record["path"]
        tampered = gaplib.read_json(artifact_path)
        tampered["search_runs"][0]["queries"].append("post-ingest mutation")
        gaplib.atomic_write_json(artifact_path, tampered)
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.derive_validation(harness.run_dir)
        self.assertEqual(caught.exception.code, "ARTIFACT_HASH_MISMATCH")

    def test_bundle_write_failure_rolls_back_manifest_and_ledger(self):
        harness = self.harness()
        paths = gaplib.run_paths(harness.run_dir)
        before = {
            key: paths[key].read_bytes()
            for key in ("state", "ledger", "candidates")
        }
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "rollback"
        )
        real_write = gaplib.atomic_write_json
        injected = {"raised": False}

        def flaky_write(path, value):
            if Path(path).name == "gap-run.json" and not injected["raised"]:
                injected["raised"] = True
                raise OSError("injected state-write failure")
            return real_write(path, value)

        with mock.patch.object(
            gaplib, "atomic_write_json", side_effect=flaky_write
        ):
            with self.assertRaises(OSError):
                harness.record("research_report", report)
        after = {
            key: paths[key].read_bytes()
            for key in ("state", "ledger", "candidates")
        }
        self.assertEqual(before, after)
        self.assertEqual(gaplib.load_state(harness.run_dir)["manifest_revision"], 0)

    def test_out_of_order_artifacts_and_future_verification_ids_are_rejected(self):
        harness = self.harness()
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("claim", fixtures.claim(harness.state["run_id"]))
        self.assertEqual(caught.exception.code, "ILLEGAL_TRANSITION")
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record(
                "source_verification",
                fixtures.source_verification("venue_map", ["future-artifact"]),
            )
        self.assertEqual(caught.exception.code, "VERIFICATION_ARTIFACT_FK")

    def test_preregistration_cannot_silently_replace_protocol(self):
        harness = self.harness()
        harness.reach_smoke_design()
        harness.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(harness.state),
        )
        replacement = fixtures.smoke_preregistration(harness.state)
        replacement["preregistration_id"] = "prereg-replacement"
        replacement["protocol"]["strongest_baseline"] = "new-strongest-v3"
        replacement["protocol"]["baselines"].append("new-strongest-v3")
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("smoke_preregistration", replacement)
        self.assertEqual(caught.exception.code, "USE_QUEUE_REVISION")

    def test_latest_smoke_preregistration_requires_its_own_result_chain(self):
        harness = self.harness()
        harness.reach_smoke_design()
        technical_prereg = fixtures.smoke_preregistration(harness.state)
        technical_record = harness.record(
            "smoke_preregistration", technical_prereg
        )
        technical_auth = fixtures.smoke_authorization(
            harness.state,
            harness.state["artifacts"][technical_record["artifact_id"]]["sha256"],
        )
        harness.record("smoke_authorization", technical_auth)
        technical_result = fixtures.smoke_result(harness.state, technical_auth)
        result_record = harness.record("smoke_result", technical_result)
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "smoke", [technical_record["artifact_id"], result_record["artifact_id"]]
            ),
        )
        harness.record(
            "scientific_audit",
            fixtures.scientific_audit(
                harness.state,
                "smoke",
                "GO",
                [technical_result["result_id"]],
                [technical_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        precision_prereg = fixtures.smoke_preregistration(
            harness.state, kind="precision"
        )
        precision_record = harness.record(
            "smoke_preregistration", precision_prereg
        )
        precision_auth = fixtures.smoke_authorization(
            harness.state,
            harness.state["artifacts"][precision_record["artifact_id"]]["sha256"],
            kind="precision",
        )
        harness.record("smoke_authorization", precision_auth)
        validation = gaplib.derive_validation(harness.run_dir)
        smoke = validation["gate_results"]["smoke"]
        self.assertEqual(smoke["status"], "awaiting_report")
        self.assertIn("SMOKE_RESULT_MISSING", smoke["reason_codes"])

    def test_go_reopen_needs_resolved_evidence_and_emits_revision_artifact(self):
        harness = self.harness()
        harness.reach_science_gates()
        harness.freeze()
        frozen_state = harness.state
        freeze_id = next(
            artifact_id
            for artifact_id, record in frozen_state["artifacts"].items()
            if record["kind"] == "experiment_freeze"
            and record["status"] == "current"
        )
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.finalize_run(
                harness.run_dir, frozen_state["manifest_revision"] - 1
            )
        self.assertEqual(caught.exception.code, "STALE_REVISION")
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.queue_revision(
                harness.run_dir,
                "formatting",
                "cosmetic reopen is forbidden",
                frozen_state["manifest_revision"],
                evidence_refs=[f"artifact:{freeze_id}"],
            )
        self.assertEqual(caught.exception.code, "GO_REOPEN_EVIDENCE_REQUIRED")
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.queue_revision(
                harness.run_dir,
                "baseline",
                "unresolved evidence must not reopen GO",
                frozen_state["manifest_revision"],
                evidence_refs=["fabricated"],
            )
        self.assertEqual(caught.exception.code, "REVISION_EVIDENCE_UNRESOLVED")
        queued = gaplib.queue_revision(
            harness.run_dir,
            "baseline",
            "A verified stronger baseline changes the comparison set.",
            frozen_state["manifest_revision"],
            evidence_refs=[f"artifact:{freeze_id}"],
        )
        state = harness.state
        revision_id = queued["revision_artifact_id"]
        self.assertEqual(state["artifacts"][revision_id]["kind"], "gap_revision")
        payload = gaplib._artifact_payload(
            harness.run_dir, state["artifacts"][revision_id]
        )
        self.assertEqual(payload["change_type"], "baseline")
        self.assertIn(f"artifact:{freeze_id}", payload["evidence_refs"])
        self.assertEqual(state["decision"], "undecided")

    def test_invalid_stop_and_narrow_never_become_terminal(self):
        missing_verification = self.harness("invalid-narrow")
        missing_verification.reach_smoke_design()
        prereg = fixtures.smoke_preregistration(missing_verification.state)
        prereg_record = missing_verification.record(
            "smoke_preregistration", prereg
        )
        auth = fixtures.smoke_authorization(
            missing_verification.state,
            missing_verification.state["artifacts"][
                prereg_record["artifact_id"]
            ]["sha256"],
        )
        missing_verification.record("smoke_authorization", auth)
        result = fixtures.smoke_result(missing_verification.state, auth)
        result_record = missing_verification.record("smoke_result", result)
        missing_verification.record(
            "scientific_audit",
            fixtures.scientific_audit(
                missing_verification.state,
                "smoke",
                "NARROW",
                [result["result_id"]],
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        validation = missing_verification.commit()
        smoke = validation["gate_results"]["smoke"]
        self.assertFalse(smoke["decision_eligible"])
        self.assertIsNone(smoke["outcome"])
        self.assertEqual(smoke["reported_outcome"], "NARROW")
        self.assertEqual(missing_verification.state["decision"], "undecided")
        self.assertNotEqual(missing_verification.state["phase"], "closed")

        invalid_kill = self.harness("invalid-stop")
        invalid_kill.reach_smoke_design()
        prereg_record = invalid_kill.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(invalid_kill.state),
        )
        auth = fixtures.smoke_authorization(
            invalid_kill.state,
            invalid_kill.state["artifacts"][prereg_record["artifact_id"]][
                "sha256"
            ],
        )
        invalid_kill.record("smoke_authorization", auth)
        result = fixtures.smoke_result(invalid_kill.state, auth)
        result_record = invalid_kill.record("smoke_result", result)
        invalid_kill.record(
            "source_verification",
            fixtures.source_verification(
                "smoke",
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        invalid_kill.record(
            "scientific_audit",
            fixtures.scientific_audit(
                invalid_kill.state,
                "smoke",
                "STOP",
                [result["result_id"]],
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        validation = invalid_kill.commit()
        smoke = validation["gate_results"]["smoke"]
        self.assertFalse(smoke["decision_eligible"])
        self.assertIn(
            "STOP_REQUIRES_BOUND_KILL_CRITERION", smoke["reason_codes"]
        )
        self.assertEqual(invalid_kill.state["decision"], "undecided")
        self.assertNotEqual(invalid_kill.state["phase"], "closed")

    def test_baseline_and_narrow_revisions_can_reenter_falsification(self):
        baseline_run = self.harness("baseline-reentry")
        baseline_run.reach_science_gates()
        revised_protocol = fixtures.protocol()
        revised_protocol["strongest_baseline"] = "strong-model-v3"
        revised_protocol["baselines"].append("strong-model-v3")
        gaplib.queue_revision(
            baseline_run.run_dir,
            "baseline",
            "A verified stronger baseline changes the comparison set.",
            baseline_run.state["manifest_revision"],
            new_protocol=revised_protocol,
        )
        self.assertEqual(baseline_run.state["phase"], "falsification")
        baseline_run.ingest_research_stage(
            "falsification", "baseline-refals", "GO"
        )
        baseline_run.commit()
        self.assertEqual(baseline_run.state["phase"], "smoke")
        self.assertEqual(baseline_run.state["decision"], "undecided")

        narrow_run = self.harness("narrow-reentry")
        self.seed_narrowable_run(narrow_run)
        self.commit_current_narrow(narrow_run, "narrow-first")
        state = narrow_run.state
        narrowed_claim = fixtures.claim(
            state["run_id"], suffix=" [narrowed]"
        )
        narrowed_claim["data_regime"] = (
            "Prespecified temporal OOD split with a bounded horizon"
        )
        audit_id = next(
            artifact_id
            for artifact_id in state["gates"]["falsification"]["artifact_ids"]
            if state["artifacts"][artifact_id]["kind"] == "scientific_audit"
        )
        gaplib.queue_revision(
            narrow_run.run_dir,
            "claim_semantics",
            "The audited claim must be narrowed to the specified OOD regime.",
            state["manifest_revision"],
            new_claim=narrowed_claim,
            narrow=True,
            evidence_refs=[f"artifact:{audit_id}"],
        )
        narrow_run.ingest_research_stage(
            "falsification", "narrow-refals", "GO"
        )
        narrow_run.record("candidate_board", {
            "stage": "falsification",
            "candidates": [
                fixtures.candidate("gap-primary", ["missing_ood"]),
                fixtures.candidate("gap-backup", ["boundary_unknown"]),
            ],
            "primary_candidate_id": "gap-primary",
            "backup_candidate_id": "gap-backup",
        })
        narrow_run.commit()
        self.assertEqual(narrow_run.state["phase"], "smoke")
        self.assertEqual(narrow_run.state["decision"], "undecided")

    def test_evidence_subject_and_audit_report_binding_are_enforced(self):
        venue_run = self.harness("venue-scope-fk")
        venue_report = fixtures.make_report(
            venue_run.run_dir,
            venue_run.state,
            "venue_map",
            "bad-scope-subject",
        )
        self.assertTrue(all(
            item["subject"] == {
                "kind": "scope", "ref": venue_run.state["run_id"]
            }
            for item in venue_report["evidence"]
        ))
        venue_report["evidence"][0]["subject"]["ref"] = "not-this-run"
        with self.assertRaises(gaplib.GapError) as caught:
            venue_run.record("research_report", venue_report)
        self.assertEqual(caught.exception.code, "RESEARCH_REPORT_REJECTED")
        self.assertTrue(any(
            error.startswith("EVIDENCE_SCOPE_SUBJECT_FK")
            for error in caught.exception.details["errors"]
        ))

        subject_run = self.harness("subject-fk")
        self.seed_narrowable_run(subject_run)
        invalid = fixtures.make_report(
            subject_run.run_dir,
            subject_run.state,
            "falsification",
            "bad-subject",
        )
        invalid["evidence"][0]["subject"]["ref"] = "nonexistent-claim"
        with self.assertRaises(gaplib.GapError) as caught:
            subject_run.record("research_report", invalid)
        self.assertEqual(caught.exception.code, "RESEARCH_REPORT_REJECTED")
        self.assertTrue(
            any(
                error.startswith("EVIDENCE_CLAIM_SUBJECT_FK")
                for error in caught.exception.details["errors"]
            )
        )

        report_run = self.harness("audit-report-fk")
        self.seed_narrowable_run(report_run)
        first = fixtures.make_report(
            report_run.run_dir,
            report_run.state,
            "falsification",
            "report-one",
        )
        first_record = report_run.record("research_report", first)
        second = fixtures.make_report(
            report_run.run_dir,
            report_run.state,
            "falsification",
            "report-two",
        )
        second_record = report_run.record("research_report", second)
        with self.assertRaises(gaplib.GapError) as caught:
            report_run.record(
                "scientific_audit",
                fixtures.scientific_audit(
                    report_run.state,
                    "falsification",
                    "GO",
                    [first["evidence"][0]["id"]],
                    [second_record["artifact_id"]],
                ),
            )
        self.assertEqual(caught.exception.code, "AUDIT_EVIDENCE_FK")
        self.assertNotEqual(
            first_record["artifact_id"], second_record["artifact_id"]
        )

    def test_smoke_audit_requires_every_evidence_id_to_resolve(self):
        harness = self.harness("smoke-audit-evidence-fk")
        harness.reach_smoke_design()
        prereg_record = harness.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(harness.state),
        )
        authorization = fixtures.smoke_authorization(
            harness.state,
            harness.state["artifacts"][prereg_record["artifact_id"]]["sha256"],
        )
        harness.record("smoke_authorization", authorization)
        result = fixtures.smoke_result(harness.state, authorization)
        result_record = harness.record("smoke_result", result)
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "smoke",
                [prereg_record["artifact_id"], result_record["artifact_id"]],
            ),
        )
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record(
                "scientific_audit",
                fixtures.scientific_audit(
                    harness.state,
                    "smoke",
                    "GO",
                    [result["result_id"], "bogus-evidence-id"],
                    [prereg_record["artifact_id"], result_record["artifact_id"]],
                ),
            )
        self.assertEqual(caught.exception.code, "AUDIT_EVIDENCE_FK")

    def test_final_audit_protocol_is_prefrozen_fresh_and_freeze_bound(self):
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.prepare_run(
                self.root / "future-cutoff",
                "Fixture Conference",
                "future evidence",
                cutoff="2099-01-01",
                run_id="future-cutoff-run",
            )
        self.assertEqual(caught.exception.code, "FUTURE_CUTOFF_FORBIDDEN")

        harness = self.harness("audit-freshness")
        harness.reach_final_audit_design()
        report = fixtures.make_report(
            harness.run_dir, harness.state, "final_audit", "freshness"
        )
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("research_report", report)
        self.assertEqual(caught.exception.code, "ILLEGAL_TRANSITION")

        stale_protocol = fixtures.audit_protocol_for_report(
            harness.state, report, "stale"
        )
        stale_protocol["cutoff_date"] = "2020-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("audit_protocol", stale_protocol)
        self.assertEqual(caught.exception.code, "AUDIT_PROTOCOL_STALE")

        future_protocol = fixtures.audit_protocol_for_report(
            harness.state, report, "future"
        )
        future_protocol["cutoff_date"] = "2099-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("audit_protocol", future_protocol)
        self.assertEqual(caught.exception.code, "AUDIT_PROTOCOL_FUTURE")

        future_ring = fixtures.audit_protocol_for_report(
            harness.state, report, "future-ring"
        )
        future_ring["query_protocol"][0]["date_window"][
            "through"
        ] = "2099-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("audit_protocol", future_ring)
        self.assertEqual(caught.exception.code, "AUDIT_PROTOCOL_FUTURE")

        one_ring_stale = fixtures.audit_protocol_for_report(
            harness.state, report, "one-ring-stale"
        )
        one_ring_stale["query_protocol"][0]["date_window"][
            "through"
        ] = "2020-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("audit_protocol", one_ring_stale)
        self.assertEqual(caught.exception.code, "AUDIT_PROTOCOL_STALE")

        protocol = fixtures.audit_protocol_for_report(
            harness.state, report, "current"
        )
        harness.record("audit_protocol", protocol)
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.build_research_handoff(harness.state, "final_audit")
        self.assertEqual(caught.exception.code, "AUDIT_PROTOCOL_REQUIRED")
        handoff = gaplib.build_research_handoff(
            harness.state, "final_audit", protocol
        )
        self.assertEqual(handoff["audit_protocol"], protocol)
        self.assertEqual(
            gaplib.validate_research_handoff(harness.state, handoff),
            "final_audit",
        )
        for search_run in report["search_runs"]:
            search_run["audit_fingerprint"] = harness.state["fingerprints"][
                "audit"
            ]
        future_report = copy.deepcopy(report)
        for search_run in future_report["search_runs"]:
            search_run["date_window"]["through"] = "2099-01-01"
            search_run["executed_at"] = "2099-01-02T00:00:00+00:00"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("research_report", future_report)
        self.assertEqual(caught.exception.code, "RESEARCH_REPORT_REJECTED")
        self.assertTrue(any(
            error.startswith("SEARCH_CUTOFF_FUTURE")
            for error in caught.exception.details["errors"]
        ))
        self.assertTrue(any(
            error.startswith("SEARCH_EXECUTED_IN_FUTURE")
            for error in caught.exception.details["errors"]
        ))
        report["search_runs"][0]["date_window"]["through"] = "2020-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            harness.record("research_report", report)
        self.assertEqual(caught.exception.code, "RESEARCH_REPORT_REJECTED")

        freeze_run = self.harness("freeze-cutoff")
        freeze_run.reach_science_gates()
        dossier = fixtures.freeze_dossier(freeze_run.state)
        dossier["search_cutoff"] = "2020-01-01"
        with self.assertRaises(gaplib.GapError) as caught:
            freeze_run.record("experiment_freeze", dossier)
        self.assertEqual(caught.exception.code, "FREEZE_CUTOFF_MISMATCH")

    def test_metadata_only_evidence_cannot_support_stop(self):
        harness = self.harness("metadata-stop")
        self.seed_narrowable_run(harness)
        report = fixtures.make_report(
            harness.run_dir,
            harness.state,
            "falsification",
            "metadata",
        )
        for source in report["sources"]:
            source["access_level"] = "metadata"
        report_record = harness.record("research_report", report)
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "falsification", [report_record["artifact_id"]]
            ),
        )
        harness.record(
            "scientific_audit",
            fixtures.scientific_audit(
                harness.state,
                "falsification",
                "STOP",
                [item["id"] for item in report["evidence"]],
                [report_record["artifact_id"]],
            ),
        )
        validation = harness.commit()
        gate = validation["gate_results"]["falsification"]
        self.assertFalse(gate["decision_eligible"])
        self.assertIn(
            "STOP_REQUIRES_VERIFIED_FULL_TEXT", gate["reason_codes"]
        )
        self.assertEqual(harness.state["decision"], "undecided")

    def test_critical_lead_can_be_resolved_with_immutable_history(self):
        harness = self.harness("lead-resolution")
        open_report = fixtures.make_report(
            harness.run_dir,
            harness.state,
            "venue_map",
            "lead-open",
            critical_open=True,
        )
        harness.record("research_report", open_report)
        resolved_report = fixtures.make_report(
            harness.run_dir,
            harness.state,
            "venue_map",
            "lead-resolved",
        )
        resolved_lead = copy.deepcopy(open_report["unresolved_leads"][0])
        resolved_lead["search_run_id"] = resolved_report["search_runs"][0]["id"]
        resolved_lead["status"] = "resolved"
        resolved_lead["next_action"] = None
        resolved_lead["resolution_evidence_ids"] = [
            resolved_report["evidence"][0]["id"]
        ]
        resolved_report["unresolved_leads"] = [resolved_lead]
        resolved_report["search_runs"][0]["unresolved_lead_ids"] = [
            resolved_lead["id"]
        ]
        recorded = harness.record("research_report", resolved_report)
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "venue_map", [recorded["artifact_id"]]
            ),
        )
        harness.record(
            "scientific_audit",
            fixtures.scientific_audit(
                harness.state,
                "venue_map",
                "PASS",
                [item["id"] for item in resolved_report["evidence"]],
                [recorded["artifact_id"]],
            ),
        )
        harness.commit()
        ledger = gaplib.read_json(
            gaplib.run_paths(harness.run_dir)["ledger"]
        )
        self.assertEqual(
            ledger["unresolved_leads"][resolved_lead["id"]]["status"],
            "resolved",
        )
        self.assertEqual(len(ledger["lead_history"]), 1)
        self.assertEqual(harness.state["gates"]["venue_map"]["status"], "passed")

    def test_supplemental_verification_recovers_gate_and_emits_report_qa(self):
        harness = self.harness("supplemental")
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "supplemental"
        )
        recorded = harness.record("research_report", report)
        harness.record(
            "scientific_audit",
            fixtures.scientific_audit(
                harness.state,
                "venue_map",
                "PASS",
                [item["id"] for item in report["evidence"]],
                [recorded["artifact_id"]],
            ),
        )
        validation = harness.commit()
        self.assertEqual(
            validation["gate_results"]["venue_map"]["status"],
            "review_required",
        )
        self.assertIsNone(harness.state["gates"]["venue_map"]["outcome"])
        harness.record(
            "source_verification",
            fixtures.source_verification(
                "venue_map", [recorded["artifact_id"]]
            ),
        )
        validation = harness.commit()
        self.assertEqual(
            validation["gate_results"]["venue_map"]["status"], "passed"
        )
        qa = validation["report_qa"][report["report_id"]]
        self.assertTrue(qa["structurally_ready"])
        self.assertTrue(all(qa["checks"].values()))

    def test_precision_requires_completed_technical_smoke_and_can_reopen(self):
        direct = self.harness("precision-direct")
        direct.reach_smoke_design()
        with self.assertRaises(gaplib.GapError) as caught:
            direct.record(
                "smoke_preregistration",
                fixtures.smoke_preregistration(
                    direct.state, kind="precision"
                ),
            )
        self.assertEqual(caught.exception.code, "TECHNICAL_SMOKE_REQUIRED")

        sequenced = self.harness("precision-sequenced")
        sequenced.reach_final_audit_design()
        self.assertEqual(sequenced.state["phase"], "final_audit")
        precision_record = sequenced.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(
                sequenced.state, kind="precision"
            ),
        )
        self.assertEqual(
            sequenced.state["artifacts"][precision_record["artifact_id"]][
                "kind"
            ],
            "smoke_preregistration",
        )
        self.assertEqual(sequenced.state["phase"], "smoke")
        self.assertEqual(
            sequenced.state["gates"]["smoke"]["status"], "validating"
        )

    def test_asymmetric_sesoi_and_structured_futility_are_computed(self):
        harness = self.harness("precision-contract")
        harness.reach_smoke_design()
        state = copy.deepcopy(harness.state)
        asymmetric = {
            "lower_margin": "-0.01",
            "upper_margin": "0.03",
            "unit": "utility",
        }
        state["claim"]["current"]["sesoi"] = asymmetric
        prereg = fixtures.smoke_preregistration(state, kind="precision")
        prereg["precision_plan"]["sesoi"] = asymmetric
        prereg["precision_plan"]["lower_margin"] = "-0.01"
        prereg["precision_plan"]["upper_margin"] = "0.03"
        gaplib.validate_schema(prereg, "smoke.schema.json")
        gaplib._validate_precision_plan(state, prereg)

        futility = copy.deepcopy(prereg)
        plan = futility["precision_plan"]
        plan["framework"] = "FUTILITY"
        plan.pop("alpha", None)
        plan.pop("interval_level", None)
        plan["futility_rule"] = {
            "measure": "conditional_power",
            "operator": "<=",
            "threshold": "0.2",
            "unit": "probability",
        }
        result = {
            "result_id": "precision-futility",
            "smoke_kind": "precision",
            "precision_adequate": True,
            "p_value_only": False,
            "confidence_class": "adequate",
            "stop_basis": "FUTILITY",
            "results": {"conditional_power": "0.1"},
            "precision_evidence": {
                "estimate": "0",
                "criterion_details": "Preregistered conditional-power rule.",
                "futility_observation": {
                    "value": "0.1",
                    "unit": "probability",
                    "evidence_refs": [
                        "result:precision-futility#/results/conditional_power"
                    ],
                },
            },
        }
        self.assertTrue(gaplib._precision_stop_valid(futility, result))
        tampered = copy.deepcopy(result)
        tampered["precision_evidence"]["futility_observation"][
            "value"
        ] = "0.9"
        self.assertFalse(gaplib._precision_stop_valid(futility, tampered))

    def test_prediction_only_requires_substantive_non_accuracy_basis(self):
        prediction = fixtures.candidate(
            "prediction-only", ["missing_ood"], prediction_claim=True
        )
        prediction.pop("decision_value_test")
        prediction["claim_scope"] = "prediction_only"
        prediction["prediction_only_justification"] = (
            "The claim concerns a preregistered robustness boundary."
        )
        board = {
            "stage": "discovery",
            "candidates": [
                prediction,
                fixtures.candidate("other-one", ["boundary_unknown"]),
                fixtures.candidate("other-two", ["protocol_nonidentifying"]),
            ],
            "primary_candidate_id": "prediction-only",
            "backup_candidate_id": "other-one",
        }
        with self.assertRaises(gaplib.GapError) as caught:
            gaplib.validate_candidate_board(board)
        self.assertEqual(caught.exception.code, "DECISION_VALUE_MISSING")
        prediction["prediction_only_basis"] = "robustness"
        gaplib.validate_candidate_board(board)

    def test_report_duplicate_excluded_fk_mechanism_and_dates_are_rejected(self):
        harness = self.harness("report-extra-checks")
        report = fixtures.make_report(
            harness.run_dir, harness.state, "venue_map", "extra-checks"
        )
        duplicate = copy.deepcopy(report)
        duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
        checks = gaplib.research_report_checks(
            duplicate, harness.state, harness.run_dir
        )
        self.assertIn("ENTITY_ID_DUPLICATE", checks["errors"])

        excluded = copy.deepcopy(report)
        excluded["search_runs"][0]["excluded_sources"] = [{
            "source_id": "source-not-in-report",
            "reason": "Excluded after screening.",
        }]
        checks = gaplib.research_report_checks(
            excluded, harness.state, harness.run_dir
        )
        self.assertIn(
            f"EXCLUDED_SOURCE_FK:{excluded['search_runs'][0]['id']}",
            checks["errors"],
        )

        mechanism_run = self.harness("mechanism-axis")
        self.seed_narrowable_run(mechanism_run)
        no_mechanism = fixtures.make_report(
            mechanism_run.run_dir,
            mechanism_run.state,
            "falsification",
            "no-mechanism",
        )
        for search_run in no_mechanism["search_runs"]:
            search_run["coverage_axes"].remove("mechanism")
        checks = gaplib.research_report_checks(
            no_mechanism, mechanism_run.state, mechanism_run.run_dir
        )
        self.assertIn("REQUIRED_COVERAGE_AXES_MISSING", checks["errors"])

        reversed_window = copy.deepcopy(report)
        reversed_window["search_runs"][0]["date_window"] = {
            "from": fixtures.CUTOFF,
            "through": "2020-01-01",
        }
        checks = gaplib.research_report_checks(
            reversed_window, harness.state, harness.run_dir
        )
        self.assertIn(
            f"DATE_WINDOW_REVERSED:{reversed_window['search_runs'][0]['id']}",
            checks["errors"],
        )

    def test_committed_missing_smoke_authorization_waits_for_user(self):
        harness = self.harness("smoke-wait")
        harness.reach_smoke_design()
        harness.record(
            "smoke_preregistration",
            fixtures.smoke_preregistration(harness.state),
        )
        validation = harness.commit()
        self.assertIn(
            "SMOKE_AUTHORIZATION_MISSING",
            validation["gate_results"]["smoke"]["reason_codes"],
        )
        self.assertEqual(harness.state["phase"], "smoke")
        self.assertEqual(harness.state["run_status"], "awaiting_user")


if __name__ == "__main__":
    unittest.main(verbosity=2)
