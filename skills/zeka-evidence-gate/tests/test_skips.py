"""Declared skip accountability without pretending native tests prove requirements."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_evidence_gate import (Invalid, OTHER, REF, add_ci, artifact_bytes,
                                export_review_loop, main, real_sample, render,
                                sample, summarize, validate_manifest, verify, write_bundle)


def complete_manifest():
    """Synthetic in-memory stand-in for an independently passing three-level bundle."""
    m = real_sample()
    m["scope"] = "Synthetic verification of platform-aware regression obligations."
    m["caveats"] = ["All observations here are fabricated test input."]
    regression = copy.deepcopy(m["records"][0])
    target = m["required_targets"][1]
    target["requirement"] = "Required regression scenarios for the recorded environment pass."
    regression.update(id="E-002", target_id=target["id"], requirement=target["requirement"],
                      requirement_ref=target["requirement_ref"], level="regression", phase="standalone",
                      artifact_ids=["A-regression"])
    regression["details"].update(suite="PortableRegression", filter=None, passed=573)
    regression.update(expected_result={"required_scenarios_pass": True}, observed_result={"required_scenarios_pass": True},
                      preconditions=["Synthetic test inputs loaded."], caveats=[],
                      output_excerpt="Synthetic regression observations satisfied the declared scenarios.")
    regression["procedure"]["argv"] = ["dotnet", "test", "tests/Backend.IntegrationTests",
                                       "--configuration", "Release", "--logger", "trx"]
    regression["provenance"]["metadata"]["argv"] = copy.deepcopy(regression["procedure"]["argv"])
    m["records"][1] = regression
    artifact = copy.deepcopy(m["artifacts"][0])
    artifact.update(id="A-regression", path="regression.json", provenance=copy.deepcopy(regression["provenance"]))
    m["artifacts"].append(artifact)
    add_ci(m)
    m["records"][2].pop("reason", None)
    return m


def platform_skip(test="Backend.Tests::WindowsVolumeTests.Read", target_ids=None):
    return {"test": test, "reason": "Requires Windows volume APIs; unavailable on Linux.",
            "expected_for_environment": True, "target_ids": target_ids or [],
            "condition": {"kind": "platform", "supported_os": ["Windows"]}}


def with_skips():
    m = complete_manifest()
    m["records"][1]["details"].update(skipped=2, skips=[platform_skip(),
        platform_skip("Backend.Tests::WindowsVolumeTests.Write")])
    return m


def mark_target_unexecuted(m, status):
    r = m["records"][0]
    r.update(status=status, reason="Required scenario skipped: the environment prerequisite is absent.",
             exit_code=None, observed_result=None, details=None, artifact_ids=[])
    m["artifacts"] = [a for a in m["artifacts"] if a["id"] != "A-001"]
    m["records"][1]["details"]["skips"][0]["target_ids"] = [r["target_id"]]


class SkipTests(unittest.TestCase):
    def test_zero_skips_remains_backward_compatible(self):
        m = complete_manifest()
        self.assertTrue(summarize(m)["complete"])
        m["records"][1]["details"]["skips"] = []
        self.assertTrue(summarize(m)["complete"])
        self.assertNotIn("## Skipped tests", render(sample()))

    def test_accounted_platform_skips_outside_targets_may_pass(self):
        for kind in ("unit", "integration"):
            with self.subTest(kind=kind):
                m = with_skips()
                m["required_targets"][1]["class"] = kind
                m["records"][1]["class"] = kind
                result = summarize(m)
                self.assertTrue(result["complete"])
                self.assertEqual(result["passed_targets"], 3)
                self.assertEqual(result["levels"]["regression"], "passed")

    def test_failures_still_prevent_pass_with_or_without_inventory(self):
        for m in (complete_manifest(), with_skips()):
            m["records"][1]["details"]["failed"] = 1
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_positive_skip_count_requires_inventory_not_prose(self):
        m = with_skips()
        del m["records"][1]["details"]["skips"]
        m["records"][1]["caveats"] = ["Two Windows tests were skipped."]
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_reported_skip_count_must_equal_inventory_length(self):
        for count in (0, 1, 3):
            m = with_skips()
            m["records"][1]["details"]["skipped"] = count
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_skip_identity_reason_and_relationship_are_required_and_typed(self):
        for key in ("test", "reason", "expected_for_environment", "target_ids", "condition"):
            m = with_skips()
            del m["records"][1]["details"]["skips"][0][key]
            with self.subTest(missing=key), self.assertRaises(Invalid):
                validate_manifest(m)
        for key, value in (("test", ""), ("test", "  "), ("test", 42), ("reason", None),
                           ("reason", " "), ("reason", "TBD"), ("expected_for_environment", "true"),
                           ("target_ids", None)):
            m = with_skips()
            m["records"][1]["details"]["skips"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(Invalid):
                validate_manifest(m)

    def test_duplicate_test_identities_cannot_pad_inventory(self):
        m = with_skips()
        m["records"][1]["details"]["skips"][1] = copy.deepcopy(m["records"][1]["details"]["skips"][0])
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_unknown_and_duplicate_target_ids_rejected(self):
        for ids in (["unknown"], ["T-001", "T-001"]):
            m = with_skips()
            m["records"][1]["details"]["skips"][0]["target_ids"] = ids
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_skip_cannot_satisfy_own_or_other_passing_target(self):
        for ids in (["T-001"], ["T-002"], ["T-003"], ["T-001", "T-002"]):
            m = with_skips()
            m["records"][1]["details"]["skips"][0]["target_ids"] = ids
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_explicit_untested_target_is_valid_but_incomplete(self):
        m = with_skips()
        mark_target_unexecuted(m, "untested")
        summary = summarize(m)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["passed_targets"], 2)
        self.assertEqual(summary["levels"]["focused"], "untested")
        self.assertEqual(summary["levels"]["regression"], "passed")

    def test_explicit_blocked_target_is_valid_but_incomplete(self):
        m = with_skips()
        mark_target_unexecuted(m, "blocked")
        r = m["records"][1]
        r["environment"]["prerequisites"] = [{"id": "disposable-database", "available": False}]
        skip = r["details"]["skips"][0]
        skip.update(reason="Disposable database is unavailable.",
                    condition={"kind": "prerequisite", "id": "disposable-database"})
        summary = summarize(m)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["levels"]["focused"], "blocked")

    def test_platform_condition_must_agree_with_recorded_environment(self):
        m = with_skips()
        m["records"][1]["environment"]["os"] = "Windows"
        with self.assertRaises(Invalid):
            validate_manifest(m)
        # Unknown/free-form OS descriptions cannot be treated as definitely non-Windows.
        m["records"][1]["environment"]["os"] = "Windows 11"
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_unknown_conditions_or_unexplained_expected_skips_rejected(self):
        for condition in (None, {"kind": "other"}, {"kind": "platform", "supported_os": []},
                          {"kind": "platform", "supported_os": ["AnyOS"]}):
            m = with_skips()
            m["records"][1]["details"]["skips"][0]["condition"] = condition
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_unexpected_skip_cannot_pass_but_can_be_explicitly_blocked(self):
        m = with_skips()
        r = m["records"][1]
        r["details"]["skips"][0].update(expected_for_environment=False, condition=None,
                                       reason="Runner did not report an understood skip condition.")
        with self.assertRaises(Invalid):
            validate_manifest(m)
        r.update(status="blocked", exit_code=None, reason="Unexpected skip needs investigation.")
        self.assertFalse(summarize(m)["complete"])

    def test_prerequisite_skip_cannot_contradict_availability_or_hide_unknown_id(self):
        for prerequisites in ([], [{"id": "fixture", "available": True}],
                              [{"id": "fixture", "available": False}, {"id": "fixture", "available": False}]):
            m = with_skips()
            r = m["records"][1]
            r["environment"]["prerequisites"] = prerequisites
            r["details"]["skips"][0]["condition"] = {"kind": "prerequisite", "id": "fixture"}
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_intentional_exclusion_needs_structured_authoritative_reference(self):
        m = with_skips()
        entry = m["records"][1]["details"]["skips"][0]
        entry.update(reason="Optional stress test excluded by the execution contract.",
                     condition={"kind": "explicit_exclusion", "ref": REF})
        self.assertTrue(summarize(m)["complete"])
        del entry["condition"]["ref"]
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_skips_do_not_replace_at_least_one_executed_test_or_exit_zero(self):
        for mutate in (lambda r: r["details"].update(passed=0), lambda r: r.update(exit_code=1),
                       lambda r: r.update(exit_code=None)):
            m = with_skips()
            mutate(m["records"][1])
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_skip_accounting_also_applies_to_unexecuted_records_with_counts(self):
        m = with_skips()
        r = m["records"][1]
        r.update(status="untested", exit_code=None, reason="Suite obligation was not executed.")
        del r["details"]["skips"]
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_report_shows_skip_details_and_completeness_effect(self):
        m = with_skips()
        report = render(m)
        self.assertEqual(report, render(copy.deepcopy(m)))
        for value in ("## Skipped tests", "573 passed / 0 failed / 2 skipped",
                      "WindowsVolumeTests.Read", "WindowsVolumeTests.Write", "Requires Windows volume APIs",
                      "Expected for environment: true", "Windows", "Linux", "outside declared targets",
                      r"No effect on required\-target completeness"):
            self.assertIn(value, report)
        mark_target_unexecuted(m, "untested")
        report = render(m)
        self.assertIn("required target remains untested", report)

    def test_skip_metadata_is_bound_to_structured_source_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            m = with_skips()
            write_bundle(root, m)
            verify(root, offline=True)
            m["records"][1]["details"]["skips"][0]["reason"] = "A different explanation."
            with self.assertRaisesRegex(Invalid, "does not match"):
                artifact_bytes(m, root)

    def test_adapter_keeps_passing_unrelated_skips_and_maps_required_gaps(self):
        for status in ("passed", "untested", "blocked"):
            m = with_skips()
            if status != "passed":
                mark_target_unexecuted(m, status)
            summary = summarize(m, freshness_checked=True)
            result = export_review_loop(m, summary, 123, "report.md")
            self.assertEqual(result["regression"]["status"], "passed")
            self.assertEqual(result["protected_ci"]["status"], "passed")
            self.assertEqual(result["focused"]["status"], {"passed": "passed", "untested": "missing",
                                                          "blocked": "unavailable"}[status])

    def test_complete_cli_cannot_accept_required_skips(self):
        # Git identity itself is covered by GitTests; isolate completeness here.
        for status, code in (("passed", 0), ("untested", 2), ("blocked", 2)):
            with tempfile.TemporaryDirectory() as tmp:
                m = with_skips()
                if status != "passed":
                    mark_target_unexecuted(m, status)
                write_bundle(Path(tmp), m)
                with patch("validation.check_repository"), contextlib.redirect_stdout(io.StringIO()) as out:
                    result = main(["verify", tmp, "--repo", tmp, "--require-complete"])
                self.assertEqual(result, code)
                self.assertEqual(json.loads(out.getvalue())["complete"], status == "passed")

    def test_historical_skips_do_not_disqualify_current_passing_target(self):
        m = with_skips()
        before = copy.deepcopy(m["records"][1])
        before.update(id="E-before", phase="before", commit_sha=OTHER, target_id="T-001",
                      level="focused", requirement=m["records"][0]["requirement"],
                      requirement_ref=m["records"][0]["requirement_ref"], status="blocked", exit_code=None,
                      reason="Historical prerequisite prevented execution.", artifact_ids=[])
        before["details"]["skips"][0]["target_ids"] = ["T-001"]
        before["provenance"]["metadata"].update(start_sha=OTHER, end_sha=OTHER)
        m["records"].append(before)
        m["comparisons"][0]["before_id"] = before["id"]
        self.assertTrue(summarize(m)["complete"])
        self.assertIn("Historical skips do not affect current completeness", render(m))


if __name__ == "__main__":
    unittest.main()
