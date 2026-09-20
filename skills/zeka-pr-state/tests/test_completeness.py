"""Collection completeness and fixture contract regressions."""
import copy
import unittest
from unittest.mock import patch
from test_pr_state import SCRIPTS, github_state, snapshot, v


class CompletenessTests(unittest.TestCase):
    def test_check_total_mismatch(self):
        api = github_state.GitHub()
        with patch.object(api, "get", return_value={"total_count": 2, "check_runs": [{"id": 1}]}):
            with self.assertRaises(v.StateError) as exc:
                api.collect("synthetic", "check_runs")
        self.assertEqual(exc.exception.reason, "pagination_changed")

    def test_changed_total_between_pages(self):
        api = github_state.GitHub()
        pages = [{"total_count": 101, "check_runs": [{"id": n} for n in range(100)]},
                 {"total_count": 100, "check_runs": []}]
        with patch.object(api, "get", side_effect=pages), self.assertRaises(v.StateError):
            api.collect("synthetic", "check_runs")

    def test_exact_full_page_with_total_is_complete(self):
        api = github_state.GitHub(max_pages=1)
        with patch.object(api, "get", return_value={"total_count": 100, "check_runs": [{"id": n} for n in range(100)]}):
            result, pages = api.collect("synthetic", "check_runs")
        self.assertEqual((len(result), pages), (100, 1))

    def test_missing_total_is_api_failure(self):
        api = github_state.GitHub()
        with patch.object(api, "get", return_value={"check_runs": []}), self.assertRaises(v.StateError) as exc:
            api.collect("synthetic", "check_runs")
        self.assertEqual(exc.exception.category, "api_failure")

    def test_mixed_synthetic_live_rejected(self):
        synthetic = snapshot()
        live = copy.deepcopy(synthetic)
        live["capture_mode"] = "github_workspace"
        for source in live["sources"]:
            source["kind"] = "git_command" if source["operation"] == "workspace" else "github_rest"
        with self.assertRaises(v.StateError) as exc:
            v.compare(synthetic, live)
        self.assertEqual(exc.exception.reason, "mixed_synthetic_live_comparison")

    def test_incoherent_previous_cannot_satisfy_freshness(self):
        from test_pr_state import expectation
        previous, current = snapshot(), snapshot()
        previous["consistency"].update(status="changed", reason_codes=["capture_changed"])
        result = v.verify(current, expectation(previous={"capture_id": previous["capture_id"],
                                                         "unchanged": ["head_moved"]}), previous)
        self.assertEqual(result["failure_categories"], ["stale_snapshot"])

    def test_shipped_fixture(self):
        root = SCRIPTS.parent / "tests" / "fixtures"
        s = v.load(root / "fork-snapshot.json")
        e = v.load(root / "expectations.json")
        result = v.verify(s, e)
        self.assertEqual(result["overall"], "passed")
        self.assertEqual(result["proof_scope"], "synthetic")


if __name__ == "__main__":
    unittest.main()
