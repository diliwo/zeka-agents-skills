"""Offline contract, transport and real temporary Git regression tests."""
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import git_state
import github_state
import pr_state
import validation as v

A, B, C = "a" * 40, "b" * 40, "c" * 40
TIME = "2026-09-20T10:00:00+00:00"


def raw_pr():
    return {"id": 100, "number": 7, "html_url": "https://github.com/example/base/pull/7",
            "state": "open", "merged": False, "draft": False, "body": "Synthetic description",
            "user": {"id": 9, "type": "User"}, "created_at": TIME, "updated_at": TIME,
            "base": {"repo": {"full_name": "example/base"}, "ref": "main", "sha": B},
            "head": {"repo": {"full_name": "example/fork"}, "ref": "feature", "sha": A},
            "mergeable": None, "mergeable_state": "unknown"}


def raw_check(identifier=1, head=A, status="completed", conclusion="success"):
    return {"id": identifier, "name": "ci", "app": {"id": 11, "slug": "example-ci"},
            "head_sha": head, "status": status, "conclusion": conclusion,
            "created_at": TIME, "output": {"title": "Synthetic", "summary": "Passed", "text": None}}


class FakeAPI:
    def __init__(self):
        self.pr = raw_pr()
        self.runs = [raw_check()]
        self.statuses = []
        self.comments = []
        self.calls = []
        self.failure = None
        self.final_pr = None
        self.pr_reads = 0
    def get(self, endpoint):
        self.calls.append(endpoint)
        if self.failure == "pr":
            raise v.StateError("api_failure", "api_failed")
        if "/git/ref/" in endpoint:
            return {"ref": "refs/heads/feature", "object": {"type": "commit", "sha": A}}
        self.pr_reads += 1
        return copy.deepcopy(self.final_pr if self.final_pr and self.pr_reads > 1 else self.pr)
    def collect(self, endpoint, field=None):
        self.calls.append(endpoint)
        if self.failure and self.failure in endpoint:
            raise v.StateError("api_failure", "api_failed")
        data = self.runs if field else self.statuses if endpoint.endswith("/statuses") else self.comments if "/issues/" in endpoint else []
        return copy.deepcopy(data), 1


def workspace():
    return {"workspace_id": "synthetic-checkout", "branch": "feature", "detached": False,
            "head_sha": A, "remote": {"name": "origin", "repository": "example/fork",
            "identity_status": "available", "reason_code": None},
            "remote_tracking": {"ref": "refs/remotes/origin/feature", "sha": A, "availability": "available"},
            "worktree": git_state.worktree(b""), "shallow": False, "observed_at": TIME}


def snapshot(api=None):
    with patch.object(git_state, "capture", return_value=workspace()):
        result = pr_state.capture("example/base", 7, api=api or FakeAPI(), workspace="unused",
                                  workspace_id="synthetic-checkout", clock=lambda: TIME)
    result["capture_mode"] = "synthetic"
    result["capture_id"] = "synthetic-capture"
    for source in result["sources"]:
        source["kind"] = "synthetic"
    return result


def coherent(s):
    for source in s["sources"]:
        if source["id"] in s["consistency"]["boundary_source_ids"]:
            source["metadata"]["fingerprint"] = v.digest(v.without_observed_at(s[source["operation"]]["data"]))
    return s


def expectation(**kwargs):
    return {"schema_version": 1, "expectation_id": "synthetic-expectation", **kwargs}


def check_expect(**kwargs):
    return expectation(required_checks=[{"kind": "check_run", "name": "ci",
                                        "must_be_completed": True, "must_be_successful": True, **kwargs}])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()
    def verify(self, e):
        return v.verify(coherent(self.s), e)
    def test_exact_agreement(self):
        r = self.verify(expectation(identity={"repository": "example/base", "head": {"sha": A}},
                    agreement={k: True for k in ("local_head_equals_pr_head", "local_branch_equals_head_branch",
                               "live_remote_equals_pr_head", "remote_tracking_equals_pr_head")}))
        self.assertEqual(r["overall"], "passed")
        self.assertEqual(r["proof_scope"], "synthetic")
    def test_local_head_mismatch(self):
        self.s["workspace"]["data"]["head_sha"] = B
        self.assertEqual(self.verify(expectation(agreement={"local_head_equals_pr_head": True}))["overall"], "failed")
    def test_live_branch_mismatch(self):
        self.s["remote_branch"]["data"]["sha"] = B
        self.assertEqual(self.verify(expectation(agreement={"live_remote_equals_pr_head": True}))["failure_categories"], ["mismatch"])
    def test_cached_branch_distinct(self):
        self.s["workspace"]["data"]["remote_tracking"]["sha"] = B
        self.assertEqual(self.verify(expectation(agreement={"live_remote_equals_pr_head": True}))["overall"], "passed")
        self.assertEqual(self.verify(expectation(agreement={"remote_tracking_equals_pr_head": True}))["overall"], "failed")
    def test_dirty_worktree(self):
        self.s["workspace"]["data"]["worktree"] = git_state.worktree(b" M private.txt\0?? new.txt\0")
        self.assertEqual(self.verify(expectation(workspace={"must_be_clean": True}))["overall"], "failed")
        self.assertNotIn("private.txt", v.canonical(self.s))
    def test_detached_head(self):
        self.s["workspace"]["data"].update(branch=None, detached=True)
        self.assertEqual(self.verify(expectation(workspace={"branch": None}))["overall"], "passed")
        self.assertEqual(self.verify(expectation(agreement={"local_branch_equals_head_branch": True}))["overall"], "failed")
    def test_fork_roles(self):
        self.assertEqual(self.verify(expectation(identity={"head": {"repository": "example/fork"},
                     "base": {"repository": "example/base"}}, workspace={"remote_repository": "example/fork"}))["overall"], "passed")
    def test_wrong_head_repository(self):
        self.assertEqual(self.verify(expectation(identity={"head": {"repository": "example/base"}}))["overall"], "failed")
    def add_ancestor(self, answer=True, status="available"):
        source = copy.deepcopy(self.s["sources"][0])
        source.update(id="graph", operation="ancestry", status=status)
        self.s["sources"].append(source)
        self.s["ancestry"] = [{"ancestor_sha": B, "descendant_sha": A, "method": "git_merge_base",
            "availability": status, "source_id": "graph", "is_ancestor": answer, "merge_bases": [B] if answer else [],
            "reason_code": None if status == "available" else "missing_object"}]
    def test_ancestor_present(self):
        self.add_ancestor()
        self.assertEqual(self.verify(expectation(ancestors=[B]))["overall"], "passed")
    def test_ancestor_absent(self):
        self.add_ancestor(False)
        self.assertEqual(self.verify(expectation(ancestors=[B]))["failure_categories"], ["mismatch"])
    def test_ancestor_unavailable(self):
        self.add_ancestor(None, "unavailable")
        self.assertEqual(self.verify(expectation(ancestors=[B]))["failure_categories"], ["unavailable"])
    def test_missing_ancestry(self):
        self.assertEqual(self.verify(expectation(ancestors=[B]))["failure_categories"], ["unavailable"])
    def test_bound_check(self):
        self.assertEqual(self.verify(check_expect())["overall"], "passed")
    def test_wrong_sha_check(self):
        self.s["checks"]["data"][0]["head_sha"] = B
        self.assertEqual(self.verify(check_expect())["failure_categories"], ["mismatch"])
    def test_missing_check(self):
        self.s["checks"]["data"] = []
        self.assertEqual(self.verify(check_expect())["failure_categories"], ["mismatch"])
    def test_pending_check(self):
        self.s["checks"]["data"][0].update(status="in_progress", conclusion=None)
        self.assertEqual(self.verify(check_expect())["overall"], "failed")
    def test_failed_check(self):
        self.s["checks"]["data"][0]["conclusion"] = "failure"
        self.assertEqual(self.verify(check_expect())["overall"], "failed")
    def test_unbound_check(self):
        self.s["checks"]["data"][0].update(head_sha=None)
        self.s["checks"]["data"][0]["binding"]["method"] = "unavailable"
        self.assertEqual(self.verify(check_expect())["failure_categories"], ["unavailable"])
    def test_duplicate_attempt_default(self):
        c = copy.deepcopy(self.s["checks"]["data"][0])
        c.update(id=2, key="check_run:example/base:2")
        self.s["checks"]["data"].append(c)
        self.assertEqual(self.verify(check_expect())["failure_categories"], ["unavailable"])
    def test_latest_pending_never_older_green(self):
        c = copy.deepcopy(self.s["checks"]["data"][0])
        c.update(id=2, key="check_run:example/base:2", status="in_progress", conclusion=None)
        self.s["checks"]["data"].append(c)
        result = self.verify(check_expect(selection="latest_id"))
        self.assertEqual(result["overall"], "failed")
        self.assertEqual(result["assertions"][-1]["selected_check_id"], 2)
        self.assertEqual(result["assertions"][-1]["superseded_check_ids"], [1])
    def test_provider_ambiguity(self):
        c = copy.deepcopy(self.s["checks"]["data"][0])
        c.update(id=2, key="check_run:example/base:2", source={"kind": "app", "id": 22, "slug": "other"})
        self.s["checks"]["data"].append(c)
        self.assertEqual(self.verify(check_expect(selection="latest_id"))["failure_categories"], ["unavailable"])
        self.assertEqual(self.verify(check_expect(source={"id": 11}))["overall"], "passed")
    def test_required_policy_not_inferred(self):
        self.assertEqual(self.s["required_check_contract"]["availability"], "not_requested")
    def test_unknown_fields(self):
        self.s["governance"] = "approved"
        with self.assertRaises(v.StateError):
            v.validate(self.s, "snapshot")
    def test_duplicate_json_and_nonfinite(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(v.StateError):
                v.parse(raw)
    def test_consistency_fingerprint_tampering(self):
        self.s["pr"]["data"]["head"]["sha"] = B
        with self.assertRaises(v.StateError):
            v.validate(self.s, "snapshot")
    def test_synthetic_cannot_masquerade_as_live(self):
        self.s["capture_mode"] = "github_workspace"
        with self.assertRaises(v.StateError):
            v.validate(self.s, "snapshot")
    def test_empty_expectations(self):
        for e in (expectation(), expectation(agreement={"local_head_equals_pr_head": False})):
            with self.subTest(e=e), self.assertRaises(v.StateError):
                self.verify(e)
    def test_partial_collection_rejected(self):
        self.s["sources"][2]["metadata"]["complete"] = False
        with self.assertRaises(v.StateError):
            v.validate(self.s, "snapshot")
    def test_failure_precedence(self):
        self.assertEqual(v.exit_code(["mismatch", "stale_snapshot", "api_failure"]), 5)
        self.assertEqual(v.exit_code(["invalid_input", "api_failure"]), 7)
    def test_immutable_serialization(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "snapshot.json"
            v.write_new(path, self.s)
            self.assertEqual(path.read_text().strip(), v.canonical(self.s))
            with self.assertRaises(v.StateError):
                v.write_new(path, self.s)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.before = snapshot()
        self.after = copy.deepcopy(self.before)
        self.after["capture_id"] = "synthetic-next"
    def changes(self):
        return v.compare(coherent(self.before), coherent(self.after))
    def test_head_moved(self):
        self.after["pr"]["data"]["head"]["sha"] = C
        self.assertIn("head_moved", self.changes()["changed"])
    def test_base_only_does_not_invalidate_head(self):
        self.after["pr"]["data"]["base"]["sha"] = C
        self.assertEqual(self.changes()["changed"], ["base_moved"])
        e = expectation(identity={"head": {"sha": A}}, previous={"capture_id": "synthetic-capture", "unchanged": ["head_moved"]})
        self.assertEqual(v.verify(self.after, e, self.before)["overall"], "passed")
        e["previous"]["unchanged"].append("base_moved")
        self.assertIn("stale_snapshot", v.verify(self.after, e, self.before)["failure_categories"])
    def test_branch_changed(self):
        self.after["pr"]["data"]["head"]["branch"] = "other"
        self.assertIn("branch_changed", self.changes()["changed"])
    def test_head_repository_changed(self):
        self.after["pr"]["data"]["head"]["repository"] = "example/other"
        self.assertIn("head_repository_changed", self.changes()["changed"])
    def test_closed_and_reopened(self):
        self.after["pr"]["data"]["state"] = "closed"
        self.assertIn("pr_state_changed", self.changes()["changed"])
        self.before, self.after = self.after, self.before
        self.assertIn("pr_state_changed", self.changes()["changed"])
    def test_check_changed(self):
        self.after["checks"]["data"][0]["conclusion"] = "failure"
        self.assertIn("checks_changed", self.changes()["changed"])
    def test_body_edit_same_id(self):
        self.after["review_sources"]["data"][0]["content_sha256"] = v.body_hash("Changed")
        row = next(r for r in self.changes()["changes"] if r["change"] == "review_sources_changed")
        self.assertEqual(len(row["items"]["changed"]), 1)
    def test_new_review(self):
        c = copy.deepcopy(self.after["review_sources"]["data"][0])
        c.update(id=99, key="check_output:example/base:99")
        self.after["review_sources"]["data"].append(c)
        row = next(r for r in self.changes()["changes"] if r["change"] == "review_sources_changed")
        self.assertEqual(row["items"]["added"], ["check_output:example/base:99"])
    def test_unavailable_is_not_empty_inventory(self):
        self.after["checks"] = v.envelope(status="unavailable", reason="limit_reached")
        row = next(r for r in self.changes()["changes"] if r["change"] == "checks_changed")
        self.assertEqual(row["status"], "unavailable")
        self.assertNotIn("items", row)
    def test_deterministic_order(self):
        self.after["review_sources"]["data"].reverse()
        self.assertEqual(self.changes()["changed"], [])
        self.assertEqual(v.canonical(self.changes()), v.canonical(self.changes()))
    def test_mergeability_only(self):
        self.after["mergeability"]["data"]["mergeable"] = True
        self.assertEqual(self.changes()["changed"], ["mergeability_changed"])


class CaptureTests(unittest.TestCase):
    def test_capture_moves_midflight(self):
        api = FakeAPI()
        api.final_pr = raw_pr()
        api.final_pr["head"]["sha"] = B
        s = snapshot(api)
        self.assertEqual(s["consistency"]["status"], "changed")
        self.assertEqual(v.verify(s, expectation(identity={"head": {"sha": A}}))["failure_categories"], ["stale_snapshot"])
    def test_api_failure_is_diagnostic(self):
        api = FakeAPI()
        api.failure = "pr"
        s = snapshot(api)
        self.assertEqual(s["pr"]["availability"], "api_failure")
        self.assertEqual(pr_state.capture_exit(s), 5)
    def test_partial_api_failure_no_partial_checks(self):
        api = FakeAPI()
        api.failure = "/statuses"
        s = snapshot(api)
        self.assertEqual(s["checks"]["availability"], "api_failure")
        self.assertIsNone(s["checks"]["data"])
        self.assertEqual(v.verify(s, check_expect())["failure_categories"], ["api_failure"])
    def test_legacy_status_exact_endpoint(self):
        api = FakeAPI()
        api.statuses = [{"id": 10, "context": "legacy", "state": "success", "creator": {"id": 9}}]
        s = snapshot(api)
        e = expectation(required_checks=[{"kind": "commit_status", "name": "legacy", "must_be_completed": True, "must_be_successful": True}])
        self.assertEqual(v.verify(s, e)["overall"], "passed")
        item = next(c for c in s["checks"]["data"] if c["kind"] == "commit_status")
        item["head_sha"] = B
        with self.assertRaises(v.StateError):
            v.validate(s, "snapshot")
    def test_body_redaction(self):
        api = FakeAPI()
        secret = "ghp_" + "a" * 36
        api.pr["body"] = secret
        api.comments = [{"id": 9, "body": secret, "user": {"id": 9}}]
        s = snapshot(api)
        self.assertNotIn(secret, v.canonical(s))
        comment = next(r for r in s["review_sources"]["data"] if r["source_type"] == "issue_comment")
        self.assertIsNone(comment["associated_sha"])
        self.assertEqual(comment["content_sha256"], v.body_hash(secret))
    def test_no_workspace_capture(self):
        s = pr_state.capture("example/base", 7, api=FakeAPI(), clock=lambda: TIME)
        self.assertEqual(s["workspace"]["availability"], "not_requested")
        self.assertEqual(s["consistency"]["status"], "stable")
    def test_skip_collections(self):
        api = FakeAPI()
        s = pr_state.capture("example/base", 7, api=api, checks=False, reviews=False, clock=lambda: TIME)
        self.assertEqual(s["checks"]["availability"], "not_requested")
        self.assertEqual(len(api.calls), 3)
    def test_missing_head_repository(self):
        api = FakeAPI()
        api.pr["head"]["repo"] = None
        s = snapshot(api)
        self.assertEqual(s["remote_branch"]["availability"], "unavailable")
        self.assertEqual(pr_state.capture_exit(s), 3)


class TransportTests(unittest.TestCase):
    def test_pagination(self):
        api = github_state.GitHub()
        with patch.object(api, "get", side_effect=[[{"id": n} for n in range(100)], [{"id": 100}]]) as get:
            result, pages = api.collect("repos/example/base/issues/7/comments")
        self.assertEqual((len(result), pages), (101, 2))
        self.assertIn("page=2", get.call_args.args[0])
    def test_pagination_cap(self):
        api = github_state.GitHub(max_pages=1)
        with patch.object(api, "get", return_value=[{"id": n} for n in range(100)]), self.assertRaises(v.StateError) as exc:
            api.collect("synthetic")
        self.assertEqual(exc.exception.reason, "limit_reached")
    def test_pagination_duplicate(self):
        api = github_state.GitHub()
        with patch.object(api, "get", side_effect=[[{"id": n} for n in range(100)], [{"id": 1}]]), self.assertRaises(v.StateError) as exc:
            api.collect("synthetic")
        self.assertEqual(exc.exception.reason, "pagination_changed")
    def test_read_only_transport(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, b"[]", b"")
        github_state.GitHub(runner=runner).get("repos/example/base/statuses/" + A)
        self.assertEqual(calls[0][calls[0].index("--method") + 1], "GET")
    def test_stderr_never_emitted(self):
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, b"", b"secret private path")
        with self.assertRaises(v.StateError) as exc:
            github_state.GitHub(runner=runner).get("synthetic")
        self.assertEqual(str(exc.exception), "api_failed")
    def test_branch_url_encoding(self):
        self.assertTrue(github_state.ref_endpoint("example/fork", "feature/a#b").endswith("feature%2Fa%23b"))
    def test_remote_forms(self):
        for remote in ("https://github.com/Example/Repo.git", "git@github.com:Example/Repo.git", "ssh://git@github.com/Example/Repo.git"):
            self.assertEqual(git_state.normalize_remote(remote), "example/repo")
    def test_unsupported_remote_no_leak(self):
        for remote in ("git@internal-alias:private/repo", "https://token:secret@github.com/example/repo.git"):
            with self.subTest(remote=remote), self.assertRaises(v.StateError) as exc:
                git_state.normalize_remote(remote)
            self.assertNotIn(remote, str(exc.exception))
            self.assertNotIn("secret", str(exc.exception))
    def test_sensitive_output_blocked(self):
        with self.assertRaises(v.StateError):
            v.scan({"body": "ghp_" + "a" * 36})


class LocalGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-b", "feature")
        self.git("config", "user.email", "synthetic@example.invalid")
        self.git("config", "user.name", "Synthetic")
        (self.root / "tracked").write_text("one")
        self.git("add", "tracked")
        self.git("commit", "-m", "synthetic first")
        self.first = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", "https://github.com/example/fork.git")
        self.git("update-ref", "refs/remotes/origin/feature", self.first)
    def tearDown(self):
        self.temp.cleanup()
    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True).stdout.decode().strip()
    def capture(self):
        return git_state.capture(self.root, "temporary", "origin", "feature", lambda: TIME)
    def test_clean_real_repository(self):
        s = self.capture()
        self.assertTrue(s["worktree"]["clean"])
        self.assertEqual(s["head_sha"], s["remote_tracking"]["sha"])
        self.assertNotIn(str(self.root), v.canonical(s))
    def test_staged_only(self):
        (self.root / "tracked").write_text("two")
        self.git("add", "tracked")
        flags = self.capture()["worktree"]
        self.assertTrue(flags["staged"])
        self.assertFalse(flags["unstaged"])
    def test_unstaged_only(self):
        (self.root / "tracked").write_text("two")
        flags = self.capture()["worktree"]
        self.assertTrue(flags["unstaged"])
        self.assertFalse(flags["staged"])
    def test_untracked_only(self):
        (self.root / "untracked").write_text("two")
        flags = self.capture()["worktree"]
        self.assertTrue(flags["untracked"])
        self.assertFalse(flags["staged"])
    def test_detached(self):
        self.git("checkout", "--detach")
        self.assertTrue(self.capture()["detached"])
    def test_graph(self):
        (self.root / "tracked").write_text("two")
        self.git("commit", "-am", "synthetic second")
        second = self.git("rev-parse", "HEAD")
        self.assertTrue(git_state.ancestry(self.root, self.first, second)[0])
        self.assertFalse(git_state.ancestry(self.root, second, self.first)[0])
    def test_missing_graph_object(self):
        with self.assertRaises(v.StateError) as exc:
            git_state.ancestry(self.root, A, self.first)
        self.assertEqual(exc.exception.reason, "missing_object")
    def test_grafts_fail_closed(self):
        (self.root / ".git" / "info" / "grafts").write_text(self.first)
        with self.assertRaises(v.StateError):
            git_state.ancestry(self.root, self.first, self.first)
    def test_capture_is_read_only(self):
        (self.root / "tracked").write_text("two")
        before = self.git("status", "--porcelain")
        self.capture()
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.first)


class CLITests(unittest.TestCase):
    def test_verify_and_compare(self):
        with tempfile.TemporaryDirectory() as root:
            s, e = Path(root) / "s.json", Path(root) / "e.json"
            v.write_new(s, snapshot())
            v.write_new(e, check_expect())
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(pr_state.main(["verify", "--snapshot", str(s), "--expectations", str(e)]), 0)
            self.assertEqual(json.loads(out.getvalue())["proof_scope"], "synthetic")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pr_state.main(["compare", "--previous", str(s), "--current", str(s)]), 0)
    def test_invalid_input_no_path_leak(self):
        with redirect_stdout(io.StringIO()) as out:
            code = pr_state.main(["verify", "--snapshot", "private-missing-file", "--expectations", "absent"])
        self.assertEqual(code, 7)
        self.assertNotIn("private-missing-file", out.getvalue())


if __name__ == "__main__":
    unittest.main()
