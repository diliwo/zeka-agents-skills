"""Offline contract, artifact, Git and CLI behavior using synthetic inputs only."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from evidence_gate import initialize, main
from reporting import export_review_loop, render
from safety import Invalid, read_json, safe_path, scan_text
from validation import (SCHEMA, artifact_bytes, check_commit_safety, provenance_check,
                        schema_check, summarize, validate_manifest, verify)

FIXTURE = SKILL / "tests" / "fixtures" / "synthetic-backend"
SHA = "1" * 40
OTHER = "2" * 40
TIME = "2026-09-20T10:00:00Z"
REF = {"kind": "document", "locator": "fixture:source"}


def sample():
    return json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


def process_source(sha=SHA, kind="local_process"):
    meta = {"argv": sample()["records"][0]["procedure"]["argv"], "working_directory": ".",
            "started_at": TIME, "finished_at": TIME, "start_sha": sha, "end_sha": sha,
            "worktree_clean": True}
    if kind == "testcontainers":
        meta["images"] = [{"name": "postgres:17", "digest": "sha256:" + "3" * 64}]
    return {"kind": kind, "metadata": meta}


def real_sample(sha=SHA, branch="fix/duplicate-delivery"):
    m = sample()
    m.update(synthetic=False, head_sha=sha, branch=branch)
    for r in m["records"]:
        r.update(commit_sha=sha, branch=branch)
        r["provenance"] = (process_source(sha) if r["status"] == "passed" else
                           {"kind": "manual_observation", "metadata": {
                               "observer_ref": REF, "method": "Assess test prerequisites.",
                               "subject_sha": sha, "revision_source": REF, "observed_at": TIME}})
    m["artifacts"][0]["provenance"] = process_source(sha)
    m["artifacts"][0]["safety"]["method"] = "allowlisted_export"
    return m


def write_bundle(root, m):
    root.mkdir(parents=True, exist_ok=True)
    records = {r["id"]: r for r in m["records"]}
    for a in m["artifacts"]:
        if a["role"] == "result":
            r = next(r for r in records.values() if a["id"] in r["artifact_ids"])
            payload = {"record_id": r["id"], "commit_sha": r["commit_sha"],
                       **{k: r[k] for k in ("exit_code", "observed_result", "details")}}
            data = (json.dumps(payload, indent=2) + "\n").encode()
        else:
            data = b"Sanitized supporting observation.\n"
        path = root / a["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        a["sha256"] = hashlib.sha256(data).hexdigest()
    (root / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    (root / "report.md").write_text(render(m), encoding="utf-8", newline="\n")


class ContractTests(unittest.TestCase):
    def test_fixture_is_valid_but_incomplete(self):
        m, s = verify(FIXTURE, offline=True)
        self.assertTrue(s["valid"])
        self.assertFalse(s["complete"])
        self.assertEqual(s["levels"], {"focused": "passed", "regression": "untested", "protected_ci": "blocked"})
        self.assertEqual(s["freshness"], "not_checked")

    def test_report_is_deterministic_and_committed_fixture_matches(self):
        m = sample()
        self.assertEqual(render(m), render(copy.deepcopy(m)))
        self.assertEqual(render(m), (FIXTURE / "report.md").read_text(encoding="utf-8"))
        self.assertIn("Concurrent delivery", render(m))
        self.assertIn("before untested", render(m))

    def test_unknown_fields_kinds_and_missing_metadata_rejected(self):
        changes = [lambda m: m.update(extra=True),
                   lambda m: m["records"][0]["provenance"].update(kind="other"),
                   lambda m: m["records"][0]["provenance"]["metadata"].update(arbitrary="data"),
                   lambda m: m["records"][0]["provenance"]["metadata"].pop("fixture"),
                   lambda m: m.update(schema_version=2),
                   lambda m: m.update(schema_version=True)]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                m = sample()
                change(m)
                with self.assertRaises(Invalid):
                    validate_manifest(m)

    def test_omitted_target_record_rejected(self):
        m = sample()
        m["records"].pop()
        with self.assertRaisesRegex(Invalid, "required target"):
            validate_manifest(m)

    def test_duplicates_and_unknown_target_rejected(self):
        for field in ("required_targets", "records", "artifacts"):
            m = sample()
            m[field].append(copy.deepcopy(m[field][0]))
            with self.assertRaises(Invalid):
                validate_manifest(m)
        m = sample()
        m["records"][0]["target_id"] = "absent"
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_required_reference_inheritance_and_conflict(self):
        m = sample()
        del m["records"][0]["requirement_ref"]
        validate_manifest(m)
        self.assertIn("contract:duplicate", render(m))
        m["records"][0]["requirement_ref"] = REF
        with self.assertRaisesRegex(Invalid, "reference differs"):
            validate_manifest(m)

    def test_structured_versions_and_references_are_strict(self):
        for change in (
            lambda m: m["records"][0]["versions"][0].update(version=""),
            lambda m: m["records"][0]["environment"]["versions"][0].update(kind="unknown"),
            lambda m: m["required_targets"][0]["contract_ref"].update(contents="private contract"),
        ):
            m = sample()
            change(m)
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_passing_results_require_matching_assertion_and_exit(self):
        for mutate in (
            lambda r: r["observed_result"].update(durable_effect_count=2),
            lambda r: r.update(exit_code=1),
            lambda r: r["details"].update(passed=0),
            lambda r: r["details"].update(skipped=1),
            lambda r: r["details"].update(failed=1),
            lambda r: r.update(artifact_ids=[]),
        ):
            m = sample()
            mutate(m["records"][0])
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_failed_evidence_is_valid_and_not_complete(self):
        m = sample()
        r = m["records"][0]
        r.update(status="failed", exit_code=1, observed_result={"delivery_count": 2, "durable_effect_count": 2})
        r["details"].update(passed=0, failed=1)
        self.assertEqual(summarize(m)["levels"]["focused"], "failed")

    def test_unexecuted_records_need_reason_and_null_exit(self):
        for mutate in (lambda r: r.pop("reason"), lambda r: r.update(exit_code=0)):
            m = sample()
            mutate(m["records"][1])
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_placeholders_rejected(self):
        for word in ("TODO", "TBD", "FIXME", "<reason>"):
            m = sample()
            m["caveats"] = [word]
            with self.assertRaisesRegex(Invalid, "unfinished"):
                validate_manifest(m)

    def test_source_revision_bindings(self):
        m = real_sample()
        validate_manifest(m)
        for field in ("start_sha", "end_sha"):
            broken = copy.deepcopy(m)
            broken["records"][0]["provenance"]["metadata"][field] = OTHER
            with self.assertRaises(Invalid):
                validate_manifest(broken)
        m["records"][0]["provenance"]["metadata"]["worktree_clean"] = False
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_all_provenance_kinds_have_closed_metadata(self):
        sources = [process_source(), process_source(kind="testcontainers"),
                   {"kind": "github_actions", "metadata": {"repository": "example/backend", "run_id": 1,
                    "run_attempt": 1, "job": "test", "head_sha": SHA, "url": "https://github.com/example/backend/actions/runs/1"}},
                   {"kind": "github_api", "metadata": {"repository": "example/backend", "endpoint": "repos/example/backend/check-runs",
                    "retrieved_at": TIME, "head_sha": SHA, "url": "https://github.com/example/backend"}},
                   {"kind": "deployed_system", "metadata": {"system_ref": REF, "deployment_ref": REF,
                    "build_sha": SHA, "revision_source": REF, "observed_at": TIME}},
                   {"kind": "manual_observation", "metadata": {"observer_ref": REF, "method": "Observe",
                    "subject_sha": SHA, "revision_source": REF, "observed_at": TIME}}]
        schema = json.loads(SCHEMA.read_text())
        for source in sources:
            with self.subTest(kind=source["kind"]):
                schema_check(source, schema["$defs"]["provenance"], schema)
                provenance_check(source, SHA, False, "example/backend")
                with self.assertRaises(Invalid):
                    provenance_check(source, OTHER, False, "example/backend")
                source["metadata"]["unstructured"] = True
                with self.assertRaises(Invalid):
                    schema_check(source, schema["$defs"]["provenance"], schema)

    def test_mixed_synthetic_provenance_rejected(self):
        m = sample()
        m["records"][0]["provenance"] = process_source()
        with self.assertRaisesRegex(Invalid, "synthetic"):
            validate_manifest(m)

    def test_before_failure_preserved_but_not_current_failure(self):
        m = sample()
        before = copy.deepcopy(m["records"][0])
        before.update(id="E-before", phase="before", commit_sha=OTHER, status="failed", exit_code=1,
                      artifact_ids=["A-before"], observed_result={"delivery_count": 2, "durable_effect_count": 2})
        before["details"].update(passed=0, failed=1)
        artifact = copy.deepcopy(m["artifacts"][0])
        artifact.update(id="A-before", path="before.json")
        m["records"].append(before)
        m["artifacts"].append(artifact)
        m["comparisons"][0]["before_id"] = before["id"]
        validate_manifest(m)
        self.assertEqual(summarize(m)["levels"]["focused"], "passed")
        self.assertIn(OTHER, render(m))
        m["records"][0]["commit_sha"] = OTHER
        with self.assertRaisesRegex(Invalid, "SHA mismatch"):
            validate_manifest(m)

    def test_missing_before_reason_and_after_comparison_rejected(self):
        m = sample()
        del m["comparisons"][0]["reason"]
        with self.assertRaises(Invalid):
            validate_manifest(m)
        m["comparisons"] = []
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_class_specific_schemas(self):
        details = {
            "postgresql": {"role": "test_role", "database": "test_db", "catalog_query": "SELECT current_user",
                           "expected_state": {"role": "test_role"}, "observed_state": {"role": "test_role"},
                           "rls_result": {"foreign_rows": 0}, "transaction_context": None},
            "api": {"scenario": "GET synthetic resource", "request": {"method": "GET", "path": "/example"},
                    "response_status": 200, "response_body": {"ok": True}, "retry_duplicate": None, "timing_ms": 10},
            "messaging": {"event_id": "event-1", "revision": "1", "delivery_count": 2, "expected_disposition": "ack",
                          "durable_state": {"count": 1}, "retry_redelivery": {"duplicate": True}},
            "storage": {"canonical_path_assertion": True, "containment_assertion": True, "operation_id": "write-1",
                        "idempotency": {"passed": True}, "partial_write": None, "restart_reconciliation": None},
            "ui": {"scenario": "Synthetic screen", "assertions": ["Visible"], "capture_skill": None,
                   "visual_review": {"reviewed": True, "reviewer_ref": REF}},
        }
        for kind, value in details.items():
            m = sample()
            m["required_targets"][0]["class"] = kind
            m["records"][0].update({"class": kind, "details": value})
            validate_manifest(m)
            m["records"][0]["details"] = {"untyped": True}
            with self.assertRaises(Invalid):
                validate_manifest(m)


def add_ci(m):
    r = m["records"][2]
    r.update(status="passed", observed_result={"success": True}, artifact_ids=["A-ci"],
             details={"workflow": "checks", "run_id": 1, "job": "test", "head_sha": m["head_sha"],
                      "conclusion": "success", "url": "https://github.com/example/backend/actions/runs/1",
                      "required_checks": ["test"], "checks": [{"name": "test", "head_sha": m["head_sha"],
                      "conclusion": "success", "ref": "run:1/test"}], "requirements_ref": REF})
    if not m["synthetic"]:
        r["provenance"] = {"kind": "github_actions", "metadata": {"repository": m["repository"],
                           "head_sha": m["head_sha"], "run_id": 1, "run_attempt": 1,
                           "job": "test", "url": r["details"]["url"]}}
    a = copy.deepcopy(m["artifacts"][0])
    a.update(id="A-ci", path="ci.json", provenance=copy.deepcopy(r["provenance"]))
    m["artifacts"].append(a)


class CITests(unittest.TestCase):
    def test_green_ci_cannot_hide_missing_skipped_or_different_sha_checks(self):
        good = sample()
        add_ci(good)
        validate_manifest(good)
        for mutate in (
            lambda d: d.update(head_sha=OTHER),
            lambda d: d["checks"][0].update(head_sha=OTHER),
            lambda d: d["checks"][0].update(conclusion="skipped"),
            lambda d: d["required_checks"].append("security"),
            lambda d: d.update(conclusion="pending"),
        ):
            m = copy.deepcopy(good)
            mutate(m["records"][2]["details"])
            with self.assertRaises(Invalid):
                validate_manifest(m)

    def test_adapter_preserves_missing_and_unavailable(self):
        m = real_sample()
        s = summarize(m, freshness_checked=True)
        export = export_review_loop(m, s, 123, "report.md")
        self.assertEqual(export["focused"]["status"], "passed")
        self.assertEqual(export["regression"]["status"], "missing")
        self.assertEqual(export["protected_ci"]["status"], "unavailable")
        self.assertEqual(export["protected_ci"]["ref"], "report.md#protected-ci")
        self.assertNotIn("waiver", export["protected_ci"])

    def test_adapter_rejects_offline_and_synthetic(self):
        for m, s in ((sample(), summarize(sample(), freshness_checked=True)),
                     (real_sample(), summarize(real_sample()))):
            with self.assertRaises(Invalid):
                export_review_loop(m, s, 123, "report.md")

    def test_export_is_consumable_by_existing_review_loop(self):
        m = real_sample()
        r = m["records"][1]
        source = copy.deepcopy(m["records"][0])
        source.update(id=r["id"], target_id=r["target_id"], requirement=r["requirement"],
                      level="regression", phase="standalone", artifact_ids=["A-regression"],
                      requirement_ref=r["requirement_ref"])
        m["records"][1] = source
        a = copy.deepcopy(m["artifacts"][0])
        a.update(id="A-regression", path="regression.json")
        m["artifacts"].append(a)
        add_ci(m)
        envelope = export_review_loop(m, summarize(m, freshness_checked=True), 123, "report.md")
        script = SKILL.parent / "zeka-review-loop" / "scripts"
        sys.path.insert(0, str(script))
        try:
            spec = importlib.util.spec_from_file_location("review_evidence_adapter", script / "evidence.py")
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            result = adapter.evaluate(envelope, {"repository": m["repository"], "pr": 123}, SHA)
            self.assertTrue(result["passed"])
        finally:
            sys.path.remove(str(script))


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_and_tampered_artifacts_rejected(self):
        m = sample()
        write_bundle(self.root, m)
        (self.root / "results.json").write_bytes(b"changed")
        with self.assertRaisesRegex(Invalid, "hash"):
            verify(self.root, offline=True)
        (self.root / "results.json").unlink()
        with self.assertRaisesRegex(Invalid, "missing"):
            verify(self.root, offline=True)

    def test_source_result_disagreement_even_after_rehash(self):
        m = sample()
        write_bundle(self.root, m)
        payload = read_json(self.root / "results.json")
        payload["observed_result"]["durable_effect_count"] = 9
        raw = json.dumps(payload).encode()
        (self.root / "results.json").write_bytes(raw)
        m["artifacts"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(Invalid, "does not match"):
            artifact_bytes(m, self.root)

    def test_path_traversal_absolute_paths_and_reserved_names(self):
        for path in ("../secret", "/secret", "C:/secret", "a\\b", "a/./b", "a//b", "a/../b"):
            with self.subTest(path=path), self.assertRaises(Invalid):
                safe_path(self.root, path)
        m = sample()
        m["artifacts"][0]["path"] = "manifest.json"
        with self.assertRaises(Invalid):
            validate_manifest(m)

    def test_symlink_escape_rejected_where_supported(self):
        try:
            (self.root / "link").symlink_to(self.root.parent, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not grant symlink creation")
        with self.assertRaises(Invalid):
            safe_path(self.root, "link/secret")

    def test_obvious_secrets_rejected_without_echo(self):
        examples = ["password=example-secret", "Bearer invented-token", "postgres://user:secret@example.invalid/db",
                    "ghp_" + "a" * 30, "-----BEGIN PRIVATE KEY-----", "op://example/item"]
        for value in examples:
            with self.assertRaises(Invalid) as failure:
                scan_text(value)
            self.assertNotIn(value, str(failure.exception))

    def test_duplicate_json_fields_and_nonfinite_numbers_rejected(self):
        path = self.root / "invalid.json"
        for value in ('{"id":1,"id":2}', '{"value":NaN}'):
            path.write_text(value)
            with self.assertRaises(Invalid):
                read_json(path)

    def test_secret_rejected_before_any_output_creation(self):
        m = sample()
        write_bundle(self.root / "candidate", m)
        m["records"][0]["output_excerpt"] = "password=example-secret"
        (self.root / "candidate" / "manifest.json").write_text(json.dumps(m))
        with self.assertRaises(Invalid):
            initialize(self.root / "candidate" / "manifest.json", self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_cli_offline_status_and_completeness_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["verify", str(FIXTURE), "--offline"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["complete"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["verify", str(FIXTURE), "--offline", "--require-complete"]), 2)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["verify", str(FIXTURE)]), 1)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "user.name", "Fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.run_git("config", "commit.gpgsign", "false")
        self.run_git("remote", "add", "origin", "https://github.com/example/backend.git")
        (self.repo / ".gitignore").write_text(".artifacts/\n")
        (self.repo / "source.txt").write_text("synthetic\n")
        self.run_git("add", ".gitignore", "source.txt")
        self.run_git("commit", "-qm", "Synthetic fixture")
        self.sha = self.run_git("rev-parse", "HEAD")
        self.bundle = self.repo / ".artifacts" / "task"
        self.manifest = real_sample(self.sha, "main")
        write_bundle(self.bundle, self.manifest)

    def run_git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def test_current_then_stale_head(self):
        _, summary = verify(self.bundle, self.repo)
        self.assertEqual(summary["freshness"], "current")
        self.run_git("commit", "--allow-empty", "-qm", "Next revision")
        with self.assertRaisesRegex(Invalid, "stale"):
            verify(self.bundle, self.repo)

    def test_dirty_and_untracked_source_rejected(self):
        (self.repo / "new-source.txt").write_text("changed")
        with self.assertRaisesRegex(Invalid, "dirty"):
            verify(self.bundle, self.repo)

    def test_wrong_repository_rejected(self):
        self.run_git("remote", "set-url", "origin", "https://github.com/example/other.git")
        with self.assertRaisesRegex(Invalid, "remote"):
            verify(self.bundle, self.repo)

    def test_forced_staging_and_tracked_ignored_bundle_rejected(self):
        self.run_git("add", "-f", str(self.bundle / "manifest.json"))
        with self.assertRaisesRegex(Invalid, "tracked or staged"):
            check_commit_safety(self.bundle, self.repo)
        self.run_git("commit", "-qm", "Accidental evidence commit")
        with self.assertRaisesRegex(Invalid, "tracked or staged"):
            check_commit_safety(self.bundle, self.repo)

    def test_unignored_output_refused(self):
        with self.assertRaisesRegex(Invalid, "ignored"):
            check_commit_safety(self.repo / "unsafe-output", self.repo)

    def test_init_packages_and_refuses_overwrite(self):
        out = self.repo / ".artifacts" / "packaged"
        self.assertTrue(initialize(self.bundle / "manifest.json", out, self.repo)["created"])
        self.assertTrue((out / "report.md").is_file())
        verify(out, self.repo)
        with self.assertRaisesRegex(Invalid, "already exists"):
            initialize(self.bundle / "manifest.json", out, self.repo)

    def test_synthetic_cannot_pass_live_verification(self):
        write_bundle(self.bundle, sample())
        with self.assertRaisesRegex(Invalid, "synthetic"):
            verify(self.bundle, self.repo)


if __name__ == "__main__":
    unittest.main()
