"""Read-only graph edge cases and existing consumer parity on temporary Git."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
import test_pr_state as fixture

git_state, v = fixture.git_state, fixture.v


class LocalEdgeTests(unittest.TestCase):
    setUp = fixture.LocalGitTests.setUp
    tearDown = fixture.LocalGitTests.tearDown
    git = fixture.LocalGitTests.git
    capture = fixture.LocalGitTests.capture

    def test_shallow_negative_is_unavailable(self):
        (self.root / "tracked").write_text("two")
        self.git("commit", "-am", "second")
        second = self.git("rev-parse", "HEAD")
        (self.root / ".git" / "shallow").write_text(second + "\n")
        with self.assertRaises(v.StateError) as exc:
            git_state.ancestry(self.root, self.first, second)
        self.assertEqual(exc.exception.reason, "shallow_history")

    def test_replace_objects_do_not_fake_ancestry(self):
        (self.root / "tracked").write_text("two")
        self.git("commit", "-am", "second")
        second = self.git("rev-parse", "HEAD")
        self.git("replace", self.first, second)
        # Without --no-replace-objects this replacement corrupts the apparent parent graph.
        self.assertTrue(git_state.ancestry(self.root, self.first, second)[0])

    def test_credential_remote_redacted(self):
        self.git("remote", "set-url", "origin", "https://user:secret@github.com/example/fork.git")
        s = self.capture()
        self.assertEqual(s["remote"]["identity_status"], "unsupported_environment")
        self.assertIsNone(s["remote"]["repository"])
        self.assertNotIn("secret", v.canonical(s))

    def test_custom_tracking_mapping_is_unavailable(self):
        self.git("config", "remote.origin.fetch", "+refs/heads/*:refs/custom/*")
        self.assertEqual(self.capture()["remote_tracking"]["availability"], "unavailable")

    def test_output_requires_ignore(self):
        import pr_state
        path = self.root / "snapshot.json"
        with self.assertRaises(v.StateError) as exc:
            pr_state.output_path(path)
        self.assertEqual(exc.exception.reason, "runtime_output_must_be_ignored")
        (self.root / ".gitignore").write_text("snapshot.json\n")
        self.assertEqual(pr_state.output_path(path), path)

    def test_staged_deleted_output_rejected(self):
        import pr_state
        path = self.root / "snapshot.json"
        path.write_text("{}")
        self.git("add", "snapshot.json")
        path.unlink()
        with self.assertRaises(v.StateError) as exc:
            pr_state.output_path(path)
        self.assertEqual(exc.exception.reason, "runtime_output_tracked")

    def test_legacy_consumers_local_fact_parity(self):
        siblings = fixture.SCRIPTS.parents[1]
        if not (siblings / "zeka-review-loop").exists():
            self.skipTest("consumer repository not installed alongside standalone skill")
        observed = self.capture()
        review_script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import github
expected = json.loads(sys.stdin.read())
result = github.local_state(expected, {"remote": "origin"})
result.pop("verified_at")
print(json.dumps(result))
"""
        expected = {"head_sha": observed["head_sha"], "branch": observed["branch"],
                    "head_repository": observed["remote"]["repository"]}
        result = subprocess.run([sys.executable, "-c", review_script, str(siblings / "zeka-review-loop" / "scripts")],
                                input=json.dumps(expected), text=True, capture_output=True, cwd=self.root, check=True)
        self.assertEqual(json.loads(result.stdout), {"head_sha": observed["head_sha"], "branch": observed["branch"],
                                                    "clean": observed["worktree"]["clean"]})
        evidence_script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import validation
manifest = json.loads(sys.stdin.read())
validation.check_repository(manifest, sys.argv[3], sys.argv[2])
print("passed")
"""
        manifest = {"head_sha": observed["head_sha"], "branch": observed["branch"],
                    "repository": observed["remote"]["repository"]}
        result = subprocess.run([sys.executable, "-c", evidence_script,
                                 str(siblings / "zeka-evidence-gate" / "scripts"),
                                 str(self.root), str(self.root.parent / "synthetic-outside-bundle")],
                                input=json.dumps(manifest), text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.strip(), "passed")
        # Explicitly retain the old gate's fork-role rejection; the new base identity must not replace it.
        manifest["repository"] = "example/base"
        result = subprocess.run([sys.executable, "-c", evidence_script,
                                 str(siblings / "zeka-evidence-gate" / "scripts"),
                                 str(self.root), str(self.root.parent / "synthetic-outside-bundle")],
                                input=json.dumps(manifest), text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
