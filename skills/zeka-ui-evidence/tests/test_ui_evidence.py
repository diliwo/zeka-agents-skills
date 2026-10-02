"""Behavioral checks using synthetic images only; no browser or network."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

SKILL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ui_evidence", SKILL / "scripts" / "ui_evidence.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
REF = {"kind": "document", "locator": "fixture:revision"}


def image():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


def sample():
    side = {"source": "https://example.org/ui", "sha": "a" * 40, "revision_source": REF,
            "timestamp": "2026-10-02T12:00:00Z", "viewport": {"width": 375, "height": 812},
            "selector": ".card", "full_page": False, "capture_result": "captured", "image": "input.png",
            "outcome": "passed", "observation": "Card has no horizontal overflow.", "reviewed": True,
            "tool": {"name": "synthetic-fixture", "version": "1"}}
    return {"repository": "example/frontend", "branch": "fix/card", "target_id": "mobile-card",
            "assertion": "Card does not overflow at 375px.", "created_at": "2026-10-02T12:05:00Z",
            "before": None, "before_reason": "No before deployment supplied.", "after": side,
            "reviewer_ref": REF, "safety": {"reviewed": True, "safe_before_capture": True,
            "method": "allowlisted_export", "review_ref": REF}, "environment": {"os": "Linux", "data": "synthetic"},
            "caveats": ["Synthetic test of packaging; not live UI evidence."]}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.png").write_bytes(image())

    def package(self, data=None, name="bundle"):
        (self.root / "input.json").write_text(json.dumps(data or sample()), encoding="utf-8")
        return ui.package(self.root / "input.json", self.root / name)

    def test_missing_before_is_reported_and_hashes_recorded(self):
        result = self.package()
        self.assertFalse(result["comparison_available"])
        metadata = ui.load(self.root / "bundle" / "metadata.json")
        self.assertEqual(metadata["after"]["image_dimensions"], {"width": 1, "height": 1})
        self.assertEqual(metadata["after"]["sha256"], ui.hashlib.sha256(image()).hexdigest())
        self.assertIn("comparison unavailable", (self.root / "bundle" / "report.md").read_text())
        self.assertFalse((self.root / "bundle" / "before.png").exists())
        with self.assertRaises(ValueError):
            self.package()

    def test_rejects_unsafe_paths_urls_and_metadata_before_writing(self):
        cases = [("image", "../input.png"), ("image", "C:/private.png"), ("image", "x\\input.png"),
                 ("source", "https://user:password@example.org"), ("source", "https://example.org?token=secret"),
                 ("source", "file:///private"), ("sha", "short"), ("viewport", {"width": True, "height": 812}),
                 ("reviewed", False), ("timestamp", "2026-10-02T12:00:00")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = sample()
                data["after"][field] = value
                with self.assertRaises((ValueError, TypeError)):
                    self.package(data)
                self.assertFalse((self.root / "bundle").exists())

    def test_privacy_and_missing_comparison_fail_closed(self):
        for change in ("safe_before_capture", "reviewed"):
            data = sample()
            data["safety"][change] = False
            with self.assertRaises(ValueError):
                self.package(data)
        data = sample()
        data["before_reason"] = ""
        with self.assertRaises(ValueError):
            self.package(data)

    def test_unknown_sha_can_package_but_cannot_export(self):
        data = sample()
        data["after"].update(sha=None, revision_source=None)
        self.package(data)
        with self.assertRaises(ValueError):
            ui.export_gate(self.root / "bundle", self.root / "gate", SKILL.parent / "zeka-evidence-gate")

    def test_secret_like_text_rejected_before_output(self):
        data = sample()
        data["caveats"] = ["password=private-value"]
        with self.assertRaises(ValueError):
            self.package(data)
        self.assertFalse((self.root / "bundle").exists())

    def test_custom_viewport_and_unknown_image_viewport_are_distinct_from_pixels(self):
        for name, viewport in (("custom", {"width": 1024, "height": 700}), ("unknown", None)):
            data = sample()
            data["after"]["viewport"] = viewport
            self.package(data, name)
            metadata = ui.load(self.root / name / "metadata.json")
            self.assertEqual(metadata["after"]["viewport"], viewport)
            self.assertEqual(metadata["after"]["image_dimensions"], {"width": 1, "height": 1})

    def test_full_page_requires_caveat(self):
        data = sample()
        data["after"]["full_page"] = True
        data["caveats"] = []
        with self.assertRaises(ValueError):
            self.package(data)

    def test_blocked_capture_preserves_unproven_outcome(self):
        data = sample()
        data["after"].update(capture_result="blocked", image=None, outcome="blocked", reviewed=False,
                             observation="Safe page state could not be established.")
        self.assertEqual(self.package(data)["outcome"], "blocked")
        self.assertFalse((self.root / "bundle" / "after.png").exists())

    def test_duplicate_keys_and_non_png_rejected(self):
        (self.root / "bad.json").write_text('{"a": 1, "a": 2}')
        with self.assertRaises(ValueError):
            ui.load(self.root / "bad.json")
        (self.root / "input.png").write_bytes(b"not PNG")
        with self.assertRaises(ValueError):
            self.package()

    def test_symlinks_rejected_when_supported(self):
        try:
            (self.root / "link.png").symlink_to(self.root / "input.png")
        except OSError:
            self.skipTest("Creating symlinks unavailable on this platform")
        data = sample()
        data["after"]["image"] = "link.png"
        with self.assertRaises(ValueError):
            self.package(data)

    def test_gate_export_validates_distinct_revision_pair_and_detects_tampering(self):
        gate = SKILL.parent / "zeka-evidence-gate"
        if not gate.exists():
            self.skipTest("Sibling gate not installed")
        data = sample()
        data["before"] = copy.deepcopy(data["after"])
        data["before"].update(sha="b" * 40, outcome="failed", observation="Card overflows.")
        data["before_reason"] = None
        self.package(data)
        ui.export_gate(self.root / "bundle", self.root / "gate", gate)
        manifest = ui.load(self.root / "gate" / "manifest.json")
        self.assertEqual(manifest["comparisons"][0]["before_id"], "before")
        self.assertEqual([r["status"] for r in manifest["records"]], ["failed", "passed"])
        (self.root / "bundle" / "after.png").write_bytes(image() + b"tampered")
        with self.assertRaises(ValueError):
            ui.export_gate(self.root / "bundle", self.root / "gate-two", gate)

    def test_unbound_before_not_attributed_to_after(self):
        gate = SKILL.parent / "zeka-evidence-gate"
        if not gate.exists():
            self.skipTest("Sibling gate not installed")
        data = sample()
        data["before"] = copy.deepcopy(data["after"])
        data["before"].update(sha=None, revision_source=None, viewport=None)
        data["before_reason"] = None
        self.package(data)
        ui.export_gate(self.root / "bundle", self.root / "gate", gate)
        manifest = ui.load(self.root / "gate" / "manifest.json")
        self.assertIsNone(manifest["comparisons"][0]["before_id"])
        self.assertFalse((self.root / "gate" / "before.png").exists())

    def test_failed_and_blocked_gate_records_remain_incomplete(self):
        gate = SKILL.parent / "zeka-evidence-gate"
        if not gate.exists():
            self.skipTest("Sibling gate not installed")
        for status in ("failed", "blocked", "untested"):
            data = sample()
            data["after"]["outcome"] = status
            if status == "blocked":
                data["after"].update(capture_result="blocked", image=None, reviewed=False)
            self.package(data, status)
            ui.export_gate(self.root / status, self.root / (status + "-gate"), gate)
            manifest = ui.load(self.root / (status + "-gate") / "manifest.json")
            self.assertEqual(manifest["records"][0]["status"], status)


if __name__ == "__main__":
    unittest.main()
