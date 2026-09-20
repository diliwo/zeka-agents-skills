"""Additional fail-closed and consumer projection checks, without changing consumers."""
import copy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_pr_state import (A, B, FakeAPI, SCRIPTS, check_expect,
                           coherent, expectation, git_state, pr_state, raw_pr, snapshot, v)



class EdgeTests(unittest.TestCase):
    def test_unknown_provider(self):
        s = snapshot()
        s["checks"]["data"][0]["source"]["id"] = None
        self.assertEqual(v.verify(s, check_expect())["failure_categories"], ["unavailable"])
    def test_unbound_attempt_does_not_hide_behind_green(self):
        s = snapshot()
        c = copy.deepcopy(s["checks"]["data"][0])
        c.update(id=2, key="check_run:example/base:2", head_sha=None)
        c["binding"]["method"] = "unavailable"
        s["checks"]["data"].append(c)
        self.assertEqual(v.verify(s, check_expect(selection="latest_id"))["failure_categories"], ["unavailable"])
    def test_foreign_cached_ref(self):
        s = snapshot()
        s["workspace"]["data"]["remote"]["repository"] = "example/other"
        self.assertEqual(v.verify(coherent(s), expectation(agreement={"remote_tracking_equals_pr_head": True}))["overall"], "failed")
    def test_cached_wrong_ref_name(self):
        s = snapshot()
        s["workspace"]["data"]["remote_tracking"]["ref"] = "refs/remotes/origin/other"
        self.assertEqual(v.verify(coherent(s), expectation(agreement={"remote_tracking_equals_pr_head": True}))["overall"], "failed")
    def test_cross_repository_check(self):
        s = snapshot()
        s["checks"]["data"][0]["repository"] = "example/other"
        with self.assertRaises(v.StateError):
            v.verify(s, check_expect())
    def test_unknown_status_not_completed(self):
        api = FakeAPI()
        api.statuses = [{"id": 10, "context": "legacy", "state": "unexpected", "creator": {"id": 9}}]
        s = snapshot(api)
        item = next(c for c in s["checks"]["data"] if c["kind"] == "commit_status")
        self.assertEqual(item["status"], "unknown")
    def test_workspace_capture_race(self):
        from test_pr_state import workspace, TIME
        before, after = workspace(), workspace()
        after["head_sha"] = B
        with patch.object(git_state, "capture", side_effect=[before, after]):
            s = pr_state.capture("example/base", 7, api=FakeAPI(), workspace="unused",
                                 workspace_id="synthetic", clock=lambda: TIME)
        self.assertEqual(s["consistency"]["status"], "changed")
    def test_unavailable_workspace(self):
        from test_pr_state import TIME
        with patch.object(git_state, "capture", side_effect=v.StateError("unavailable", "workspace_unavailable")):
            s = pr_state.capture("example/base", 7, api=FakeAPI(), workspace="unused",
                                 workspace_id="synthetic", clock=lambda: TIME)
        self.assertEqual(s["consistency"]["status"], "unknown")
        self.assertNotEqual(pr_state.capture_exit(s), 0)
    def test_ancestry_source_cannot_be_failed(self):
        s = snapshot()
        source = copy.deepcopy(s["sources"][0])
        source.update(id="graph", operation="ancestry", status="unavailable")
        s["sources"].append(source)
        s["ancestry"] = [{"ancestor_sha": B, "descendant_sha": A, "method": "git_merge_base",
                         "availability": "available", "source_id": "graph", "is_ancestor": True,
                         "merge_bases": [B], "reason_code": None}]
        with self.assertRaises(v.StateError):
            v.validate(s, "snapshot")
    def test_missing_previous(self):
        r = v.verify(snapshot(), expectation(previous={"capture_id": "prior", "unchanged": ["head_moved"]}))
        self.assertEqual(r["failure_categories"], ["unavailable"])


class ConsumerProjectionTests(unittest.TestCase):
    def test_review_loop_identity_projection(self):
        # Run legacy imports in a separate interpreter to avoid its validation/common module names.
        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import github
raw = json.loads(sys.stdin.read())
print(json.dumps(github.identity(raw, {"repository": "example/base", "pr": 7})))
"""
        legacy_scripts = SCRIPTS.parents[1] / "zeka-review-loop" / "scripts"
        if not legacy_scripts.exists():
            self.skipTest("consumer repository not installed alongside standalone skill")
        result = subprocess.run([sys.executable, "-c", script, str(legacy_scripts)],
                                input=json.dumps(raw_pr()), text=True, capture_output=True, check=True)
        old = json.loads(result.stdout)
        state = snapshot()["pr"]["data"]
        projected = {"repository": state["repository"], "pr": state["number"],
                     "branch": state["head"]["branch"], "head_sha": state["head"]["sha"],
                     "base_sha": state["base"]["sha"], "head_repository": state["head"]["repository"]}
        self.assertEqual(old, projected)
    def test_review_body_hash_parity_and_check_output_difference(self):
        import hashlib
        s = snapshot()
        body = next(r for r in s["review_sources"]["data"] if r["source_type"] == "pr_body")
        self.assertEqual(body["content_sha256"], hashlib.sha256(b"Synthetic description").hexdigest())
        output = next(r for r in s["review_sources"]["data"] if r["source_type"] == "check_output")
        self.assertNotEqual(output["content_sha256"], hashlib.sha256(b"Synthetic\nPassed\n").hexdigest())


if __name__ == "__main__":
    unittest.main()
