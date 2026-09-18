"""Offline behavior tests using synthetic public-safe API data."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import Stop, config, write
from evidence import evaluate
from findings import FLAGS, assess, inventory
from freshness import baseline, freshness, size_limited
from github import api, capture, trigger
from report import build
from review_loop import iteration, main, poll

A, B = "a" * 40, "b" * 40
T0, T1, T2 = ("2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z")
BOT = "review-bot[bot]"


def cfg():
    return config({"repository": "example/project", "pr": 1, "actor": "Codex",
                   "scope_ref": "scope-1", "architecture_source": "decision-source",
                   "bot_logins": [BOT], "check_app_slugs": ["review-app"]})


def snapshot(head=A, time=T2):
    return {"schema_version": 1, "repository": "example/project", "pr": 1,
            "branch": "feature", "head_repository": "example/project",
            "head_sha": head, "base_sha": "c" * 40, "collected_at": time,
            "worktree": {"clean": True, "head_sha": head, "branch": "feature"},
            "pr_body": "", "comments": [], "inline": [], "checks": [], "checks_available": True,
            "reviews": [{"id": 42, "user": {"login": BOT}, "commit_id": head,
                         "body": "Review complete", "state": "COMMENTED", "submitted_at": time}]}


def ticket(s=None):
    s = s or snapshot()
    return {**{k: s[k] for k in ("repository", "pr", "branch", "head_repository", "head_sha", "base_sha")},
            "requested_at": T1, "baseline": {}, "mode": "normal"}


def evidence(head=A):
    return {"repository": "example/project", "pr": 1, "head_sha": head,
            **{k: {"status": "passed", "head_sha": head, "ref": k + "-artifact"}
               for k in ("focused", "regression", "protected_ci")}}


def finding(s=None):
    s = s or snapshot()
    return {"id": "F1", "source_keys": [inventory(s, cfg())[0]["source_key"]],
            "summary": "Display formatter defect", "severity": "low", "component": "formatter",
            "owner": "software", "flags": dict.fromkeys(FLAGS, False), "reproduced": True,
            "disposition": "accepted/actionable", "state": "open", "evidence_refs": ["reproducer"],
            "decision": {"by": "Chief", "ref": "approval-1", "scope_ref": "scope-1",
                         "head_sha": s["head_sha"], "blocking": True, "action": "fix"}}


def run(findings=None, s=None):
    s = s or snapshot()
    i = iteration(s, ticket(s), cfg(), findings)
    i["evidence"] = evidence(s["head_sha"])
    for entry in i["coverage"]:
        entry["rationale"] = "Reviewed entire source against implementation."
        entry["finding_ids"] = [f["id"] for f in i["findings"] if entry["source_key"] in f["source_keys"]]
    return {"schema_version": 1, "config": cfg(), "iterations": [i], "stop_reason": None}


def correction_run():
    result = run([finding()])
    s = snapshot(B, "2026-01-01T00:01:02Z")
    fixed = copy.deepcopy(result["iterations"][0]["findings"][0])
    fixed.update(state="corrected", correction_ref="fix-1", evidence_refs=["focused-artifact"])
    i = run([fixed], s)["iterations"][0]
    i["ticket"]["requested_at"] = "2026-01-01T00:01:01Z"
    i["corrections"] = [{"finding_id": "F1", "from_sha": A, "to_sha": B,
                          "owner": "Codex", "ref": "fix-1", "focused_ref": "focused-artifact"}]
    result["iterations"].append(i)
    return result


class FreshnessTests(unittest.TestCase):
    def test_native_review_exact_sha(self):
        self.assertTrue(freshness(snapshot(), ticket(), cfg())["fresh"])

    def test_wrong_sha_old_time_and_pending_reviews(self):
        for field, value in (("commit_id", B), ("submitted_at", T0), ("submitted_at", T1),
                             ("state", "PENDING"), ("state", "DISMISSED")):
            with self.subTest(field=field, value=value):
                s = snapshot()
                s["reviews"][0][field] = value
                self.assertFalse(freshness(s, ticket(), cfg())["fresh"])

    def test_summary_without_check_requires_explicit_head_binding(self):
        s = snapshot()
        s["reviews"] = []
        s["comments"] = [{"id": 7, "user": {"login": BOT}, "created_at": T0, "updated_at": T2,
                          "body": "Confidence 5/5; commit " + A}]
        self.assertFalse(freshness(s, ticket(), cfg())["fresh"])
        s["comments"][0]["body"] += "\n<!-- zeka-review-complete sha=" + A + " -->"
        self.assertTrue(freshness(s, ticket(), cfg())["fresh"])

    def test_untrusted_bot_cannot_anchor(self):
        s = snapshot()
        s["reviews"][0]["user"]["login"] = "looks-like-review-bot"
        self.assertFalse(freshness(s, ticket(), cfg())["fresh"])

    def test_unchanged_summary_edit_cannot_anchor(self):
        s = snapshot()
        s["reviews"] = []
        s["comments"] = [{"id": 7, "user": {"login": BOT}, "updated_at": T0,
                          "body": "<!-- zeka-review-complete sha=" + A + " -->"}]
        t = ticket()
        t["baseline"] = baseline(s, cfg())
        s["comments"][0]["updated_at"] = T2
        self.assertFalse(freshness(s, t, cfg())["fresh"])

    def test_head_and_base_movement_fail_closed(self):
        for key in ("head_sha", "base_sha", "branch", "head_repository"):
            s = snapshot()
            s[key] = B
            with self.subTest(key=key), self.assertRaises(Stop):
                freshness(s, ticket(), cfg())

    def test_late_review_is_not_fresh(self):
        s = snapshot(time="2026-01-01T00:20:00Z")
        self.assertFalse(freshness(s, ticket(), cfg())["fresh"])

    def test_active_or_failed_check_blocks_even_started_before_trigger(self):
        for state, conclusion in (("in_progress", None), ("completed", "failure"),
                                   ("completed", "cancelled"), ("completed", "skipped")):
            s = snapshot()
            s["checks"] = [{"id": 1, "name": "review", "app": {"slug": "review-app"},
                            "head_sha": A, "status": state, "conclusion": conclusion,
                            "started_at": T0, "completed_at": T0}]
            with self.subTest(state=state, conclusion=conclusion):
                self.assertFalse(freshness(s, ticket(), cfg())["fresh"])

    def test_successful_rerun_supersedes_failed_check(self):
        s = snapshot()
        s["checks"] = [{"id": 1, "name": "review", "app": {"slug": "review-app"},
                        "head_sha": A, "status": "completed", "conclusion": "failure"},
                       {"id": 2, "name": "review", "app": {"slug": "review-app"},
                        "head_sha": A, "status": "completed", "conclusion": "success"}]
        self.assertTrue(freshness(s, ticket(), cfg())["fresh"])
        s["reviews"] = []
        self.assertFalse(freshness(s, ticket(), cfg())["fresh"])

    def test_unavailable_checks_are_explicit(self):
        s = snapshot()
        s["checks_available"] = False
        with self.assertRaises(Stop):
            freshness(s, ticket(), cfg())
        c = cfg()
        c["allow_unavailable_checks"] = True
        self.assertTrue(freshness(s, ticket(), c)["fresh"])

    def test_size_limit_detection(self):
        s = snapshot()
        s["reviews"][0]["body"] = "Too many files changed for review"
        self.assertTrue(size_limited(s, cfg()))


class GovernanceTests(unittest.TestCase):
    def test_approved_software_finding_authorizes_only_codex(self):
        f = finding()
        self.assertTrue(assess(f, cfg(), A)["correction_authorized"])
        c = cfg()
        c["actor"] = "Hephaestus"
        self.assertFalse(assess(f, c, A)["correction_authorized"])

    def test_platform_owner_requires_hephaestus(self):
        f = finding()
        f["owner"] = "platform"
        self.assertFalse(assess(f, cfg(), A)["correction_authorized"])
        c = cfg()
        c["actor"] = "Hephaestus"
        self.assertTrue(assess(f, c, A)["correction_authorized"])

    def test_all_mandatory_risks_block_generic_approval(self):
        for flag in FLAGS:
            f = finding()
            f["flags"][flag] = True
            f["severity"] = "medium"
            with self.subTest(flag=flag):
                outcome = assess(f, cfg(), A)
                self.assertIn(flag, outcome["active_stops"])
                self.assertFalse(outcome["correction_authorized"])

    def test_security_at_every_severity_blocks_generic_approval(self):
        for severity in ("low", "medium", "high", "critical", "unknown"):
            with self.subTest(severity=severity):
                f = finding()
                f["severity"] = severity
                f["flags"]["security"] = True
                outcome = assess(f, cfg(), A)
                self.assertIn("security", outcome["active_stops"])
                self.assertFalse(outcome["correction_authorized"])

    def test_low_security_requires_current_scoped_adjudication(self):
        f = finding()
        f["flags"]["security"] = True
        f["adjudication"] = {"by": "Chief", "ref": "security-review", "scope_ref": "scope-1",
                             "head_sha": A, "cleared_stops": ["security"]}
        self.assertTrue(assess(f, cfg(), A)["correction_authorized"])
        for key, value in (("by", "Greptile"), ("ref", ""), ("scope_ref", "other-scope"),
                           ("head_sha", B), ("cleared_stops", [])):
            with self.subTest(key=key):
                invalid = copy.deepcopy(f)
                invalid["adjudication"][key] = value
                outcome = assess(invalid, cfg(), A)
                self.assertIn("security", outcome["active_stops"])
                self.assertFalse(outcome["correction_authorized"])
        f["flags"]["authorization"] = True
        self.assertFalse(assess(f, cfg(), A)["correction_authorized"])

    def test_low_security_adjudication_does_not_replace_fix_approval(self):
        f = finding()
        f["flags"]["security"] = True
        f["adjudication"] = {"by": "Chief", "ref": "security-review", "scope_ref": "scope-1",
                             "head_sha": A, "cleared_stops": ["security"]}
        f.pop("decision")
        self.assertFalse(assess(f, cfg(), A)["correction_authorized"])

    def test_reproduction_cannot_be_waived(self):
        f = finding()
        f["reproduced"] = False
        f["adjudication"] = {"by": "Chief", "ref": "review", "scope_ref": "scope-1",
                             "head_sha": A, "cleared_stops": ["cannot_reproduce"]}
        self.assertIn("cannot_reproduce", assess(f, cfg(), A)["active_stops"])

    def test_consequential_adjudication_needs_final_authority(self):
        f = finding()
        f["flags"]["architecture_boundary"] = True
        f["adjudication"] = {"by": "Chief", "ref": "review", "scope_ref": "scope-1",
                             "head_sha": A, "cleared_stops": ["architecture_boundary"]}
        self.assertFalse(assess(f, cfg(), A)["correction_authorized"])
        f["adjudication"]["final_authority_approval_ref"] = "verified-final-decision"
        self.assertTrue(assess(f, cfg(), A)["correction_authorized"])
        self.assertFalse(assess(f, cfg(), B)["correction_authorized"])

    def test_missing_flags_and_unapproved_dispositions(self):
        f = finding()
        del f["flags"]["conflict"]
        with self.assertRaises(Stop):
            assess(f, cfg(), A)
        f = finding()
        f.pop("decision")
        self.assertTrue(assess(f, cfg(), A)["requires_chief"])

    def test_reviewer_cannot_approve(self):
        f = finding()
        f["decision"]["by"] = "Greptile"
        self.assertFalse(assess(f, cfg(), A)["correction_authorized"])


class ReportTests(unittest.TestCase):
    def test_clean_review_ready_without_score(self):
        report = build(run())
        self.assertTrue(report["READY_FOR_CHIEF_REVIEW"])
        self.assertNotIn("MERGE_READY", report)

    def test_score_does_not_override_open_blocker(self):
        r = run([finding()])
        self.assertFalse(build(r)["READY_FOR_CHIEF_REVIEW"])
        self.assertEqual(build(r)["remaining_unresolved_findings"], ["F1"])

    def test_full_correction_cycle(self):
        report = build(correction_run())
        self.assertTrue(report["READY_FOR_CHIEF_REVIEW"])
        self.assertEqual(report["starting_sha"], A)
        self.assertEqual(report["final_sha"], B)
        self.assertEqual(len(report["corrections_performed"]), 1)

    def test_disappearing_finding_and_unexplained_head_rejected(self):
        r = correction_run()
        r["iterations"][1]["findings"] = []
        with self.assertRaises(Stop):
            build(r)
        r = correction_run()
        r["iterations"][1]["corrections"] = []
        with self.assertRaises(Stop):
            build(r)

    def test_unauthorized_stale_or_wrong_owner_correction_rejected(self):
        for change in ("approval", "freshness", "owner"):
            r = correction_run()
            if change == "approval":
                r["iterations"][0]["findings"][0].pop("decision")
            elif change == "freshness":
                r["iterations"][0]["ticket"]["requested_at"] = T2
            else:
                r["iterations"][1]["corrections"][0]["owner"] = "Hephaestus"
            with self.subTest(change=change), self.assertRaises(Stop):
                build(r)

    def test_global_adjudication_stops_other_fixes(self):
        r = correction_run()
        risk = finding()
        risk["id"] = "F2"
        risk["flags"]["tenant_isolation"] = True
        for i in r["iterations"]:
            i["findings"].append(copy.deepcopy(risk))
        r["iterations"][0]["coverage"][0]["finding_ids"].append("F2")
        r["iterations"][1]["coverage"][0]["finding_ids"].append("F2")
        with self.assertRaises(Stop):
            build(r)

    def test_complete_coverage_and_nonempty_rationale_required(self):
        for change in ("missing", "rationale", "changed-body"):
            r = run()
            if change == "missing":
                r["iterations"][0]["coverage"] = []
            elif change == "rationale":
                r["iterations"][0]["coverage"][0]["rationale"] = ""
            else:
                r["iterations"][0]["snapshot"]["reviews"][0]["body"] += " new finding"
            with self.subTest(change=change), self.assertRaises(Stop):
                build(r)

    def test_deferred_nonblocking_debt_remains_visible(self):
        f = finding()
        f.update(disposition="pre-existing debt", state="deferred")
        f["decision"].update(action="defer", blocking=False)
        report = build(run([f]))
        self.assertTrue(report["READY_FOR_CHIEF_REVIEW"])
        self.assertEqual(report["findings"][0]["disposition"], "pre-existing debt")
        f["decision"]["blocking"] = True
        self.assertFalse(build(run([f]))["READY_FOR_CHIEF_REVIEW"])

    def test_iteration_cap_and_external_stop(self):
        r = run()
        r["config"]["max_iterations"] = 1
        self.assertTrue(build(r)["READY_FOR_CHIEF_REVIEW"])
        r["iterations"] *= 2
        with self.assertRaises(Stop):
            build(r)
        r = run()
        r["stop_reason"] = "external_review_timeout"
        self.assertFalse(build(r)["READY_FOR_CHIEF_REVIEW"])

    def test_all_evidence_must_pass_for_current_sha(self):
        for key in ("focused", "regression", "protected_ci"):
            for status in ("failed", "pending", "missing", "unavailable"):
                r = run()
                r["iterations"][0]["evidence"][key]["status"] = status
                with self.subTest(key=key, status=status):
                    self.assertFalse(build(r)["READY_FOR_CHIEF_REVIEW"])
            r = run()
            r["iterations"][0]["evidence"][key]["head_sha"] = B
            self.assertFalse(build(r)["READY_FOR_CHIEF_REVIEW"])

    def test_ci_absence_needs_explicit_current_chief_decision(self):
        e = evidence()
        e["protected_ci"] = {"status": "not_required"}
        self.assertFalse(evaluate(e, cfg(), A)["passed"])
        e["protected_ci"]["waiver"] = {"by": "Chief", "ref": "policy", "reason": "No applicable checks", "head_sha": A}
        self.assertTrue(evaluate(e, cfg(), A)["passed"])


class TransportTests(unittest.TestCase):
    def raw_pr(self):
        return {"state": "open", "number": 1, "body": "",
                "base": {"sha": "c" * 40, "repo": {"full_name": "example/project"}},
                "head": {"sha": A, "ref": "feature", "repo": {"full_name": "example/project"}}}

    def test_api_paginates_and_never_uses_shell(self):
        with patch("github.command", return_value='[[{"id":1}],[{"id":2}]]') as command:
            self.assertEqual(len(api("endpoint", pages=True)), 2)
            self.assertEqual(command.call_args.args[0], ["gh", "api", "endpoint", "--paginate", "--slurp"])

    def test_capture_collects_every_page_and_checks_identity_twice(self):
        raw = self.raw_pr()
        responses = [raw, [[{"id": 1}], [{"id": 2}]], [[], []], [snapshot()["reviews"]],
                     [{"check_runs": []}], raw]
        with patch("github.api", side_effect=responses) as remote, patch("github.local_state", return_value=snapshot()["worktree"]):
            result = capture(cfg())
            self.assertEqual([c["id"] for c in result["comments"]], [1, 2])
            self.assertEqual(remote.call_count, 6)

    def test_capture_detects_head_race(self):
        raw = self.raw_pr()
        moved = copy.deepcopy(raw)
        moved["head"]["sha"] = B
        with patch("github.api", side_effect=[raw, [[]], [[]], [[]], [{"check_runs": []}], moved]), patch("github.local_state"):
            with self.assertRaises(Stop):
                capture(cfg())

    def test_trigger_is_explicit_and_apps_requires_configuration(self):
        c = cfg()
        s = snapshot()
        s["reviews"][0]["body"] = "Too many files changed for review"
        with patch("github.api", return_value=self.raw_pr()) as remote, patch("github.local_state"):
            with self.assertRaises(Stop):
                trigger(c, s, "apps")
            self.assertEqual(remote.call_count, 1)

    def test_trigger_ticket_uses_server_timestamp_and_baseline(self):
        response = {"id": 5, "created_at": T1, "html_url": "https://example.invalid/comment/5"}
        with patch("github.api", side_effect=[self.raw_pr(), response]), patch("github.local_state"):
            result = trigger(cfg(), snapshot(), "normal")
            self.assertEqual(result["requested_at"], T1)
            self.assertIn("reviews:42", result["baseline"])

    def test_poll_summary_fallback_and_expired_ticket(self):
        c = cfg()
        s = snapshot()
        s["reviews"][0]["submitted_at"] = T0
        s["reviews"][0]["body"] = "Too many files changed for review"
        with patch("review_loop.now", return_value=T2), patch("review_loop.capture", return_value=s):
            self.assertEqual(poll(c, ticket())["status"], "size_limit_requires_apps")
        with patch("review_loop.now", return_value="2026-01-01T00:20:00Z"), patch("review_loop.capture") as capture_mock:
            with self.assertRaises(Stop):
                poll(c, ticket())
            capture_mock.assert_not_called()

    def test_artifact_collision_and_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "run.json", Path(folder) / "report.json"
            write(source, run())
            self.assertEqual(main(["report", "--run", str(source), "--out", str(target)]), 0)
            self.assertEqual(main(["report", "--run", str(source), "--out", str(target)]), 3)
            source2 = Path(folder) / "blocked.json"
            write(source2, run([finding()]))
            self.assertEqual(main(["report", "--run", str(source2), "--out", str(Path(folder) / "blocked-report.json")]), 2)

    def test_cli_entrypoint_works_from_other_directory(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "review_loop.py"
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(script), "--help"], cwd=folder,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn("capture", result.stdout)


class AdditionalBoundaryTests(unittest.TestCase):
    def test_output_collision_cannot_post_trigger(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.json"
            write(target, {})
            with patch("review_loop.trigger") as post:
                code = main(["trigger", "--config", "unused.json", "--snapshot", "unused.json",
                             "--out", str(target), "--send"])
                self.assertEqual(code, 3)
                post.assert_not_called()

    def test_unknown_owner_cannot_become_platform_by_adjudication(self):
        f = finding()
        f["owner"] = "unknown"
        f["adjudication"] = {"by": "Chief", "ref": "review", "scope_ref": "scope-1",
                             "head_sha": A, "cleared_stops": ["classification_requires_adjudication"]}
        c = cfg()
        c["actor"] = "Hephaestus"
        self.assertFalse(assess(f, c, A)["correction_authorized"])

    def test_review_cannot_postdate_snapshot(self):
        s = snapshot()
        s["reviews"][0]["submitted_at"] = "2026-01-01T00:00:03Z"
        with self.assertRaises(Stop):
            freshness(s, ticket(), cfg())

    def test_invalid_evidence_reference_type_is_rejected(self):
        f = finding()
        f["evidence_refs"] = "not-a-list"
        with self.assertRaises(Stop):
            assess(f, cfg(), A)

    def test_dirty_or_wrong_branch_local_state_stops(self):
        from github import local_state
        for responses in ([" M source.py"], ["", "other-branch"], ["", "feature", B],
                          ["", "feature", A, "https://github.com/other/repository.git"]):
            with self.subTest(responses=responses), patch("github.command", side_effect=responses):
                with self.assertRaises(Stop):
                    local_state(snapshot(), cfg())

    def test_fork_head_remote_is_supported(self):
        from github import local_state
        s = snapshot()
        s["head_repository"] = "fork/project"
        with patch("github.command", side_effect=["", "feature", A, "git@github.com:fork/project.git"]):
            self.assertTrue(local_state(s, cfg())["clean"])

    def test_provenance_covers_inline_summary_checks_and_pr_body(self):
        s = snapshot()
        s["pr_body"] = "Summary"
        s["comments"] = [{"id": 7, "body": "General defect", "user": {"login": BOT}}]
        s["inline"] = [{"id": 8, "body": "Inline defect", "path": "src/display.py",
                        "line": 5, "commit_id": A, "user": {"login": BOT}}]
        s["checks"] = [{"id": 9, "app": {"slug": "review-app"}, "output": {"text": "Check detail"}}]
        items = inventory(s, cfg())
        self.assertEqual({item["surface"] for item in items},
                         {"pr_body", "comments", "inline", "reviews", "checks"})
        self.assertEqual(next(i for i in items if i["surface"] == "inline")["path"], "src/display.py")

    def test_malformed_json_emits_closed_gate(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "run.json", Path(folder) / "report.json"
            write(source, [])
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                code = main(["report", "--run", str(source), "--out", str(output)])
            self.assertEqual(code, 3)
            self.assertFalse(json.loads(captured.getvalue())["READY_FOR_CHIEF_REVIEW"])
            self.assertFalse(output.exists())

if __name__ == "__main__":
    unittest.main()
