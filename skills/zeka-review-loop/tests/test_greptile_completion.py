"""Synthetic stock-provider fixtures; no production PR identifiers or content."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_review_loop import A, B, T0, T1, T2, cfg, snapshot, ticket, finding, evidence
from common import Stop, config, write
from findings import inventory
from freshness import baseline, freshness
from report import build
from review_loop import iteration, main, poll

T3, T4, T5 = (f"2026-01-01T00:00:0{i}Z" for i in (3, 4, 5))
BOT = "greptile-apps[bot]"


def summary(head=A, count=2, repository="example/project"):
    return ("<!-- greptile_summary -->\n<h3>Summary</h3>\nSynthetic review result.\n"
            f'<sub>Reviews ({count}) · Last reviewed commit: ["Synthetic change"]'
            f'(https://github.com/{repository}/commit/{head})</sub>')


def fixture():
    c = cfg()
    c.update(bot_logins=[BOT], check_app_slugs=["greptile-apps"])
    before = snapshot(time=T0)
    before["reviews"] = []
    before["comments"] = [{"id": 7, "user": {"login": BOT}, "created_at": T0,
                           "updated_at": T0, "body": summary(B, 1)}]
    t = ticket(before)
    t.update(trigger_id=5, trigger_url="https://github.com/example/project/pull/1#issuecomment-5",
             baseline=baseline(before, c))
    s = copy.deepcopy(before)
    s["collected_at"] = T5
    s["comments"][0].update(body=summary(), updated_at=T4)
    s["checks"] = [{"id": 9, "name": "Greptile Review", "app": {"slug": "greptile-apps"},
                    "head_sha": A, "status": "completed", "conclusion": "success",
                    "started_at": T2, "completed_at": T3,
                    "output": {"summary": "Greptile has reviewed the Pull Request.\n2 files reviewed, 0 comments added."}}]
    return s, t, c


def ledger(s, t, c, findings=None):
    i = iteration(s, t, c, findings)
    i["evidence"] = evidence()
    for entry in i["coverage"]:
        entry["rationale"] = "Synthetic source assessment, including historical context."
        entry["finding_ids"] = [f["id"] for f in i["findings"] if entry["source_key"] in f["source_keys"]]
    return {"schema_version": 1, "config": c, "iterations": [i]}


class GreptileCompletionTests(unittest.TestCase):
    def test_exact_head_check_and_updated_summary_accepted(self):
        s, t, c = fixture()
        result = freshness(s, t, c)
        self.assertTrue(result["fresh"])
        self.assertEqual(result["anchors"], ["checks:9", "comments:7"])
        self.assertEqual(result["completion"]["trigger_id"], 5)
        self.assertEqual(result["completion"]["head_sha"], A)
        self.assertEqual(len(result["fresh_source_keys"]), 2)

    def test_first_summary_created_after_request_accepted(self):
        s, t, c = fixture()
        t["baseline"] = {}
        s["comments"][0]["created_at"] = T4
        self.assertTrue(freshness(s, t, c)["fresh"])

    def test_old_sha_check_rejected(self):
        s, t, c = fixture()
        s["checks"][0]["head_sha"] = B
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_stale_tied_or_pre_completion_summary_rejected(self):
        for date in (T0, T1, T2, T3):
            with self.subTest(date=date):
                s, t, c = fixture()
                s["comments"][0]["updated_at"] = date
                self.assertFalse(freshness(s, t, c)["fresh"])

    def test_wrong_missing_ambiguous_or_incidental_sha_rejected(self):
        for body in (summary(B), "Confidence 5/5; commit " + A,
                     summary(A[:7]), summary().replace("Last reviewed commit:", "Commit:"),
                     summary() + "\n" + summary(B), summary() + "\nLast reviewed commit: " + B,
                     summary(repository="other/project"), summary().replace("<!-- greptile_summary -->", "")):
            with self.subTest(body=body):
                s, t, c = fixture()
                s["comments"][0]["body"] = body
                self.assertFalse(freshness(s, t, c)["fresh"])

    def test_duplicate_summary_comment_rejected(self):
        s, t, c = fixture()
        s["comments"].append({**s["comments"][0], "id": 8})
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_missing_pending_and_unsuccessful_checks_rejected(self):
        for status, conclusion in (("in_progress", None), ("queued", None),
                                   ("completed", "failure"), ("completed", "cancelled"),
                                   ("completed", "timed_out"), ("completed", "neutral"),
                                   ("completed", "skipped"), ("in_progress", "success")):
            with self.subTest(status=status, conclusion=conclusion):
                s, t, c = fixture()
                s["checks"][0].update(status=status, conclusion=conclusion)
                self.assertFalse(freshness(s, t, c)["fresh"])
        s, t, c = fixture()
        s["checks"] = []
        self.assertFalse(freshness(s, t, c)["fresh"])
        s, t, c = fixture()
        s["checks_available"] = False
        c["allow_unavailable_checks"] = True
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_generic_provider_even_if_configured_cannot_complete(self):
        for slug in ("github-actions", "looks-like-greptile", "review-app"):
            s, t, c = fixture()
            c["check_app_slugs"].append(slug)
            s["checks"][0]["app"]["slug"] = slug
            with self.subTest(slug=slug):
                self.assertFalse(freshness(s, t, c)["fresh"])

    def test_untrusted_summary_and_wrong_check_name_rejected(self):
        s, t, c = fixture()
        s["comments"][0]["user"]["login"] = "looks-like-greptile[bot]"
        c["bot_logins"].append("looks-like-greptile[bot]")
        self.assertFalse(freshness(s, t, c)["fresh"])
        s, t, c = fixture()
        s["checks"][0]["name"] = "Unrelated check"
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_pre_request_reused_and_malformed_check_times_rejected(self):
        for field, value in (("started_at", T0), ("started_at", T1),
                             ("started_at", T4), ("started_at", None),
                             ("completed_at", T0), ("completed_at", None),
                             ("completed_at", "2026-01-01T00:20:00Z")):
            with self.subTest(field=field, value=value):
                s, t, c = fixture()
                s["checks"][0][field] = value
                self.assertFalse(freshness(s, t, c)["fresh"])
        s, t, c = fixture()
        t["baseline"]["checks:9"] = {"digest": "old", "updated_at": T0}
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_latest_rerun_must_complete(self):
        s, t, c = fixture()
        s["checks"].append({**s["checks"][0], "id": 10, "status": "in_progress", "conclusion": None})
        self.assertFalse(freshness(s, t, c)["fresh"])
        s["checks"][-1].update(status="completed", conclusion="success")
        self.assertTrue(freshness(s, t, c)["fresh"])

    def test_request_identity_required(self):
        for key, value in (("trigger_id", None), ("trigger_id", True), ("trigger_id", 0),
                           ("trigger_url", "https://github.com/other/project/pull/1#issuecomment-5"),
                           ("mode", "invented")):
            with self.subTest(key=key, value=value):
                s, t, c = fixture()
                t[key] = value
                self.assertFalse(freshness(s, t, c)["fresh"])

    def test_unchanged_body_counter_and_legacy_baseline_rejected(self):
        for change in ("digest", "counter", "counter-regression", "legacy", "future-baseline"):
            with self.subTest(change=change):
                s, t, c = fixture()
                old = t["baseline"]["comments:7"]
                if change == "digest":
                    old["digest"] = baseline(s, c)["comments:7"]["digest"]
                elif change == "counter":
                    old["greptile_summary"]["reviews"] = 2
                elif change == "counter-regression":
                    old["greptile_summary"]["reviews"] = 3
                elif change == "legacy":
                    old.pop("greptile_summary")
                else:
                    old["updated_at"] = T2
                self.assertFalse(freshness(s, t, c)["fresh"])

    def test_same_sha_rerun_requires_advanced_counter(self):
        s, t, c = fixture()
        t["baseline"]["comments:7"]["greptile_summary"]["sha"] = A
        self.assertTrue(freshness(s, t, c)["fresh"])

    def test_unrecorded_historical_summary_rejected(self):
        s, t, c = fixture()
        t["baseline"] = {}
        self.assertFalse(freshness(s, t, c)["fresh"])

    def test_summary_after_deadline_or_snapshot_rejected(self):
        s, t, c = fixture()
        s["collected_at"] = "2026-01-01T00:20:00Z"
        s["comments"][0]["updated_at"] = s["collected_at"]
        self.assertFalse(freshness(s, t, c)["fresh"])
        s, t, c = fixture()
        s["collected_at"] = T3
        with self.assertRaises(Stop):
            freshness(s, t, c)

    def test_fork_commit_binding_uses_head_repository(self):
        s, t, c = fixture()
        s["head_repository"] = t["head_repository"] = "fork/project"
        s["comments"][0]["body"] = summary(repository="fork/project")
        self.assertTrue(freshness(s, t, c)["fresh"])

    def test_historical_comments_excluded_fresh_inline_collected(self):
        s, t, c = fixture()
        for ident, created, updated, head in ((11, T0, T0, A), (12, T0, T4, A),
                                               (13, T2, T3, B), (14, T2, T3, A),
                                               (15, T4, T5, A)):
            s["inline"].append({"id": ident, "user": {"login": BOT}, "body": f"Finding {ident}",
                                "created_at": created, "updated_at": updated, "commit_id": head,
                                "path": "src/example.py", "line": 2})
        s["comments"].append({"id": 16, "user": {"login": BOT}, "body": "Old discussion",
                              "created_at": T0, "updated_at": T4})
        result = freshness(s, t, c)
        accepted = {key.split("@")[0] for key in result["fresh_source_keys"]}
        self.assertEqual(accepted, {"comments:7", "checks:9", "inline:14", "inline:15"})
        self.assertEqual(len(inventory(s, c)), 8)  # Lossless historical audit retained.
        key = next(i["source_key"] for i in inventory(s, c) if i["id"] == "inline:14")
        f = finding()
        f["source_keys"] = [key]
        f.pop("decision")
        report = build(ledger(s, t, c, [f]))
        self.assertEqual(report["chief_adjudication_required"], ["F1"])
        self.assertFalse(report["READY_FOR_CHIEF_REVIEW"])
        f["source_keys"] = [next(i["source_key"] for i in inventory(s, c) if i["id"] == "inline:11")]
        with self.assertRaisesRegex(Stop, "outside accepted review window"):
            build(ledger(s, t, c, [f]))

    def test_historical_findings_are_retained_across_iterations(self):
        s, t, c = fixture()
        f = finding()
        f["source_keys"] = [inventory(s, c)[0]["source_key"]]
        first = ledger(s, t, c, [f])
        second = copy.deepcopy(first["iterations"][0])
        second["ticket"]["baseline"] = baseline(s, c)
        second["ticket"]["requested_at"] = T5
        second["snapshot"]["checks"][0].update(id=10, started_at="2026-01-01T00:00:06Z",
                                               completed_at="2026-01-01T00:00:07Z")
        second["snapshot"]["comments"][0].update(body=summary(count=3), updated_at="2026-01-01T00:00:08Z")
        second["snapshot"]["collected_at"] = "2026-01-01T00:00:09Z"
        second = ledger(second["snapshot"], second["ticket"], c, [f])["iterations"][0]
        first["iterations"].append(second)
        self.assertEqual(build(first)["findings_discovered"], 1)
        second["findings"] = []
        with self.assertRaisesRegex(Stop, "disappeared"):
            build(first)

    def test_poll_success_and_deadline_not_reset(self):
        s, t, c = fixture()
        with patch("review_loop.now", return_value=T5), patch("review_loop.capture", return_value=s):
            self.assertEqual(poll(c, t)["status"], "fresh")
        with patch("review_loop.now", return_value="2026-01-01T00:20:00Z"), patch("review_loop.capture") as capture:
            with self.assertRaisesRegex(Stop, "external_review_timeout"):
                poll(c, t)
            capture.assert_not_called()

    def test_poll_timeout_cli_still_exit_three_and_not_ready(self):
        s, t, c = fixture()
        s["checks"][0]["conclusion"] = "failure"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write(folder / "config.json", c)
            write(folder / "ticket.json", t)
            errors = io.StringIO()
            with patch("review_loop.now", return_value=T5), patch("review_loop.capture", return_value=s), \
                    patch("review_loop.time.monotonic", side_effect=[0, 0, 601]), contextlib.redirect_stderr(errors):
                code = main(["poll", "--config", str(folder / "config.json"), "--ticket",
                             str(folder / "ticket.json"), "--out", str(folder / "result.json")])
            self.assertEqual(code, 3)
            result = json.loads(errors.getvalue())
            self.assertEqual(result["detail"], "external_review_timeout")
            self.assertFalse(result["READY_FOR_CHIEF_REVIEW"])
            self.assertFalse((folder / "result.json").exists())

    def test_new_path_preserves_handoff_and_iteration_cap(self):
        s, t, c = fixture()
        r = ledger(s, t, c)
        r["iterations"] *= 3
        result = build(r)
        self.assertTrue(result["READY_FOR_CHIEF_REVIEW"])
        self.assertNotIn("MERGE_READY", result)
        r["iterations"] *= 2
        with self.assertRaisesRegex(Stop, "iteration cap"):
            build(r)

    def test_config_cannot_raise_three_review_ceiling(self):
        _, _, c = fixture()
        for cap in (1, 2, 3):
            self.assertEqual(config({**c, "max_iterations": cap})["max_iterations"], cap)
        with self.assertRaisesRegex(Stop, "maximum three"):
            config({**c, "max_iterations": 4})

    def test_legacy_paths_keep_precedence_with_stock_evidence(self):
        for native in (False, True):
            with self.subTest(native=native):
                s, t, c = fixture()
                if native:
                    s["reviews"] = [{"id": 42, "user": {"login": BOT}, "commit_id": A,
                                     "body": "Review complete", "state": "COMMENTED", "submitted_at": T4}]
                else:
                    s["comments"].append({"id": 43, "user": {"login": BOT}, "updated_at": T4,
                                          "body": f"<!-- zeka-review-complete sha={A} -->"})
                result = freshness(s, t, c)
                self.assertTrue(result["fresh"])
                self.assertNotIn("completion", result)

    def test_poll_waits_for_summary_and_never_posts_a_retry(self):
        s, t, c = fixture()
        pending = copy.deepcopy(s)
        pending["comments"][0]["updated_at"] = T0
        with patch("review_loop.now", return_value=T5), \
                patch("review_loop.capture", side_effect=[pending, s]) as capture, \
                patch("review_loop.time.sleep") as sleep, patch("review_loop.trigger") as trigger, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(poll(c, t)["status"], "fresh")
            self.assertEqual(capture.call_count, 2)
            sleep.assert_called_once()
            trigger.assert_not_called()

    def test_complete_review_does_not_override_finding_or_missing_evidence(self):
        s, t, c = fixture()
        s["comments"][0]["body"] = summary().replace("Synthetic review result.", "Confidence Score: 5/5")
        f = finding()
        f["source_keys"] = [inventory(s, c)[0]["source_key"]]
        f["flags"]["security"] = True
        result = build(ledger(s, t, c, [f]))
        self.assertEqual(result["chief_adjudication_required"], ["F1"])
        self.assertFalse(result["READY_FOR_CHIEF_REVIEW"])
        r = ledger(s, t, c)
        r["iterations"][0]["evidence"]["focused"]["status"] = "missing"
        self.assertFalse(build(r)["READY_FOR_CHIEF_REVIEW"])


if __name__ == "__main__":
    unittest.main()
