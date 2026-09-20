"""Regression cases for misleading reports, typed observations and unsafe artifacts."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_evidence_gate import (Invalid, add_ci, artifact_bytes, process_source,
                                real_sample, sample, validate_manifest, verify, write_bundle)


class VerificationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_tampered_report_cannot_accompany_valid_manifest(self):
        write_bundle(self.root, sample())
        (self.root / "report.md").write_text("All tests passed.")
        with self.assertRaisesRegex(Invalid, "report does not match"):
            verify(self.root, offline=True)

    def test_missing_report_rejected(self):
        write_bundle(self.root, sample())
        (self.root / "report.md").unlink()
        with self.assertRaisesRegex(Invalid, "report is missing"):
            verify(self.root, offline=True)

    def test_unlisted_payload_is_not_silently_accepted(self):
        write_bundle(self.root, sample())
        (self.root / "unlisted.txt").write_text("Unreviewed material")
        with self.assertRaisesRegex(Invalid, "unlisted file"):
            verify(self.root, offline=True)

    def test_boolean_and_integer_assertions_differ(self):
        m = sample()
        m["records"][0]["expected_result"] = {"one_effect": True}
        m["records"][0]["observed_result"] = {"one_effect": 1}
        with self.assertRaisesRegex(Invalid, "assertion differs"):
            validate_manifest(m)

    def test_source_artifact_cannot_replace_true_with_one(self):
        m = sample()
        m["records"][0]["expected_result"] = {"one_effect": True}
        m["records"][0]["observed_result"] = {"one_effect": True}
        write_bundle(self.root, m)
        payload = json.loads((self.root / "results.json").read_text())
        payload["observed_result"] = {"one_effect": 1}
        raw = json.dumps(payload).encode()
        (self.root / "results.json").write_bytes(raw)
        m["artifacts"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(Invalid, "does not match"):
            artifact_bytes(m, self.root)

    def test_failed_status_needs_failure(self):
        m = sample()
        m["records"][0]["status"] = "failed"
        with self.assertRaisesRegex(Invalid, "lacks an observed failure"):
            validate_manifest(m)

    def test_ci_run_identity_matches_source(self):
        m = real_sample()
        add_ci(m)
        validate_manifest(m)
        m["records"][2]["details"]["run_id"] = 2
        with self.assertRaisesRegex(Invalid, "run mismatch"):
            validate_manifest(m)

    def test_json_encoded_secret_and_media_metadata_are_rejected(self):
        for media, raw in (
            ("application/json", b'{"pass\\u0077ord": "invented-value"}'),
            ("image/png", b'\x89PNG\x00password=invented-value'),
        ):
            m = sample()
            write_bundle(self.root, m)
            a = json.loads(json.dumps(m["artifacts"][0]))
            a.update(id="A-extra", path="extra.bin", media_type=media, role="supporting",
                     sha256=hashlib.sha256(raw).hexdigest())
            m["artifacts"].append(a)
            m["records"][0]["artifact_ids"].append(a["id"])
            (self.root / "extra.bin").write_bytes(raw)
            with self.assertRaisesRegex(Invalid, "sensitive material"):
                artifact_bytes(m, self.root)

    def test_process_command_metadata_cannot_disagree(self):
        m = real_sample()
        m["records"][0]["provenance"]["metadata"]["argv"] = ["another-command"]
        with self.assertRaisesRegex(Invalid, "command mismatch"):
            validate_manifest(m)


if __name__ == "__main__":
    unittest.main()
