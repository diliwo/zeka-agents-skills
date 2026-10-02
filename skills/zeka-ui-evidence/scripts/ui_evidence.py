"""Package reviewed UI captures locally. Never capture, execute inputs or publish."""

import argparse
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys
from urllib.parse import urlsplit

VIEWPORTS = {"desktop": (1440, 900), "mobile": (375, 812), "tablet": (768, 1024)}
SHA = re.compile(r"[0-9a-f]{40}\Z")
SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
                    r"\b(?:password|token|secret|api[_-]?key)\s*[:=]\s*[^\s]+|"
                    r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]+", re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, required, optional=()):
    require(isinstance(value, dict), "expected object")
    require(set(required) <= value.keys() <= set(required) | set(optional), "missing or unknown fields")


def text(value):
    require(isinstance(value, str) and value.strip() and not any(ord(c) < 32 for c in value),
            "expected nonblank text without control characters")
    require(not SECRET.search(value), "obvious secret-like text is forbidden")
    return value


def reference(value):
    keys(value, ("kind", "locator"), ("revision", "fragment"))
    require(value["kind"] in ("document", "issue", "decision", "repository_contract"), "invalid reference kind")
    for item in value.values():
        text(item)
    require(re.fullmatch(r"[a-z][a-z0-9-]*:[A-Za-z0-9_.:/-]+", value["locator"]),
            "use an opaque reference locator")


def timestamp(value):
    parsed = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "timestamp requires timezone")
    return parsed


def relative(root, value):
    text(value)
    parts = PurePosixPath(value)
    require(not parts.is_absolute() and "\\" not in value and ":" not in value
            and all(p not in ("", ".", "..") for p in value.split("/")), "unsafe relative image path")
    current = Path(root)
    for part in parts.parts:
        current = current / part
        require(not current.is_symlink() and not (hasattr(current, "is_junction") and current.is_junction()),
                "image links are forbidden")
    require(current.resolve().is_relative_to(Path(root).resolve()), "image escapes input directory")
    require(current.is_file(), "image is missing")
    return current


def png(data):
    require(len(data) >= 33 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR",
            "expected PNG capture")
    width, height = struct.unpack(">II", data[16:24])
    require(width > 0 and height > 0, "invalid PNG dimensions")
    return {"width": width, "height": height}


def duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def validate(spec, root):
    keys(spec, ("repository", "branch", "target_id", "assertion", "created_at", "before", "after",
                "before_reason", "reviewer_ref", "safety", "environment", "caveats"))
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", spec["repository"]), "invalid repository")
    for field in ("target_id", "assertion"):
        text(spec[field])
    require(re.fullmatch(r"[A-Za-z0-9_-]+", spec["target_id"]), "unsafe target ID")
    if spec["branch"] is not None:
        text(spec["branch"])
    created = timestamp(spec["created_at"])
    reference(spec["reviewer_ref"])
    keys(spec["safety"], ("reviewed", "safe_before_capture", "method", "review_ref"))
    safety = spec["safety"]
    require(safety["reviewed"] is True and safety["safe_before_capture"] is True,
            "safe content before capture and artifact review are required")
    require(safety["method"] in ("synthetic_fixture", "allowlisted_export"), "unsafe collection method")
    reference(safety["review_ref"])
    keys(spec["environment"], ("os", "data"))
    require(spec["environment"]["os"] in ("Windows", "Linux", "macOS", "FreeBSD"), "invalid OS")
    require(spec["environment"]["data"] in ("synthetic", "non_sensitive"), "use safe source data")
    require(isinstance(spec["caveats"], list), "caveats must be a list")
    for caveat in spec["caveats"]:
        text(caveat)
    blobs = {}
    require(spec["after"] is not None, "after assessment required")
    if spec["before"] is None:
        text(spec["before_reason"])
    else:
        require(spec["before_reason"] is None, "before_reason must be null when before exists")
    for phase in ("before", "after"):
        side = spec[phase]
        if side is None:
            continue
        keys(side, ("source", "sha", "revision_source", "timestamp", "viewport", "selector", "full_page",
                    "capture_result", "image", "outcome", "observation", "reviewed", "tool"))
        source = text(side["source"])
        if not source.startswith("source:"):
            url = urlsplit(source)
            require(url.scheme in ("http", "https") and url.hostname and not url.username
                    and not url.password and not url.query and not url.fragment,
                    "use safe HTTP(S) URL without credentials/query/fragment or opaque source: reference")
        else:
            require(re.fullmatch(r"source:[A-Za-z0-9_.-]+", source), "invalid opaque source")
        if side["sha"] is not None:
            require(isinstance(side["sha"], str) and SHA.fullmatch(side["sha"]), "invalid full SHA")
            reference(side["revision_source"])
        else:
            require(side["revision_source"] is None, "unknown SHA needs null revision source")
            require(bool(spec["caveats"]), "unknown revision needs a caveat")
        require(timestamp(side["timestamp"]) <= created, "capture is later than metadata")
        viewport = side["viewport"]
        if viewport is not None:
            keys(viewport, ("width", "height"))
            require(all(type(v) is int and 0 < v <= 32768 for v in viewport.values()), "invalid viewport")
        if side["selector"] is not None:
            text(side["selector"])
        require(type(side["full_page"]) is bool and type(side["reviewed"]) is bool, "expected boolean")
        if side["full_page"]:
            require(bool(spec["caveats"]), "full-page capture needs a recorded request or necessity caveat")
        require(side["capture_result"] in ("captured", "failed", "blocked"), "invalid capture result")
        require(side["outcome"] in ("passed", "failed", "untested", "blocked"), "invalid outcome")
        text(side["observation"])
        keys(side["tool"], ("name", "version"))
        text(side["tool"]["name"])
        if side["tool"]["version"] is not None:
            text(side["tool"]["version"])
        if side["capture_result"] == "captured":
            data = relative(root, side["image"]).read_bytes()
            dimensions = png(data)
            blobs[phase + ".png"] = data
            side["image"] = phase + ".png"
            side["image_dimensions"] = dimensions
            side["sha256"] = hashlib.sha256(data).hexdigest()
        else:
            require(side["image"] is None and side["outcome"] in ("untested", "blocked"),
                    "failed capture cannot prove an assertion")
        if side["outcome"] in ("passed", "failed"):
            require(side["reviewed"] and side["capture_result"] == "captured", "assertion requires visual review")
    return blobs


def escape(value):
    escaped = str(value)
    for character, replacement in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                                   ("|", "&#124;"), ("`", "&#96;"), ("[", "&#91;"), ("]", "&#93;"),
                                   ("*", "&#42;"), ("_", "&#95;")):
        escaped = escaped.replace(character, replacement)
    return escaped


def render(spec):
    lines = ["# UI evidence", "", escape(spec["assertion"]), "",
             "Repository: " + escape(spec["repository"]), "", "| State | SHA | Viewport | Capture | Outcome |",
             "| --- | --- | --- | --- | --- |"]
    for phase in ("before", "after"):
        side = spec[phase]
        if side is None:
            lines += ["", "Before/after comparison unavailable: " + escape(spec["before_reason"])]
            continue
        viewport = side["viewport"]
        size = f'{viewport["width"]}×{viewport["height"]}' if viewport else "unknown"
        lines.append(f'| {phase} | {side["sha"] or "unknown"} | {size} | {side["capture_result"]} | {side["outcome"]} |')
    for phase in ("before", "after"):
        side = spec[phase]
        if side:
            lines += ["", f'**{phase.title()}** — {escape(side["observation"])}', "",
                      "Source: " + escape(side["source"]), "",
                      "Captured: " + escape(side["timestamp"]), "",
                      "Selector: " + escape(side["selector"] or "viewport"), ""]
            if side["image"]:
                lines.append(f'![{phase}]({phase}.png)')
    if spec["caveats"]:
        lines += ["", "Caveats:", ""] + ["- " + escape(c) for c in spec["caveats"]]
    return "\n".join(lines) + "\n"


def package(candidate, output):
    candidate, output = Path(candidate), Path(output)
    require(not output.exists(), "output exists; preserve previous evidence")
    spec = load(candidate)
    blobs = validate(spec, candidate.parent)
    blobs.update({"metadata.json": encoded(spec), "report.md": render(spec).encode("utf-8")})
    output.mkdir(parents=True)
    for name, data in blobs.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    return {"created": True, "outcome": spec["after"]["outcome"], "comparison_available": spec["before"] is not None}


def export_gate(bundle, output, gate):
    """Export a candidate for the installed gate to package and verify independently."""
    bundle, output = Path(bundle), Path(output)
    require(not output.exists(), "gate output exists")
    # Revalidate stored metadata against its original input shape and hashes.
    spec = load(bundle / "metadata.json")
    hashes = {}
    for phase in ("before", "after"):
        if spec[phase] and spec[phase]["image"]:
            hashes[phase] = spec[phase].pop("sha256")
            spec[phase].pop("image_dimensions")
    blobs = validate(spec, bundle)
    for phase, digest in hashes.items():
        require(spec[phase]["sha256"] == digest, "capture hash mismatch")
    require((bundle / "report.md").read_text(encoding="utf-8") == render(spec), "report changed")
    require(spec["after"]["sha"] is not None, "unknown after SHA cannot export revision-bound evidence")
    sys.path.insert(0, str(Path(gate).resolve() / "scripts"))
    validation = importlib.import_module("validation")
    reporting = importlib.import_module("reporting")
    target = {"id": spec["target_id"], "requirement": spec["assertion"], "class": "ui", "level": "focused"}
    manifest = {"schema_version": 1, "bundle_id": spec["target_id"], "created_at": spec["created_at"],
                "synthetic": False, "repository": spec["repository"], "branch": spec["branch"],
                "head_sha": spec["after"]["sha"], "scope": spec["assertion"], "required_targets": [target],
                "records": [], "artifacts": [], "comparisons": [], "caveats": spec["caveats"]}
    output_blobs = {}
    safety = {k: spec["safety"][k] for k in ("reviewed", "method", "review_ref")}
    def artifact(name, data, role, provenance):
        output_blobs[name] = data
        manifest["artifacts"].append({"id": name, "path": name, "media_type": "image/png" if name.endswith(".png") else "application/json",
                                      "sha256": hashlib.sha256(data).hexdigest(), "role": role,
                                      "provenance": provenance, "safety": safety})
        return name
    before = spec["before"]
    comparable = before is not None and before["sha"] is not None and before["sha"] != spec["after"]["sha"]
    for phase in (("before", "after") if comparable else ("after",)):
        side = spec[phase]
        provenance = {"kind": "manual_observation", "metadata": {"observer_ref": spec["reviewer_ref"],
                      "method": "Review configured capture and independently verified revision identity.",
                      "subject_sha": side["sha"], "revision_source": side["revision_source"], "observed_at": side["timestamp"]}}
        details = {"scenario": spec["assertion"], "assertions": [spec["assertion"]], "capture_skill": "zeka-ui-evidence",
                   "visual_review": {"reviewed": side["reviewed"], "reviewer_ref": spec["reviewer_ref"]}}
        record = {"id": phase, "timestamp": side["timestamp"], "repository": spec["repository"], "branch": spec["branch"],
                  "commit_sha": side["sha"], "target_id": target["id"], "requirement": target["requirement"], "class": "ui",
                  "level": "focused", "phase": phase, "preconditions": ["Safe source content reviewed before capture"],
                  "environment": spec["environment"], "procedure": {"working_directory": ".", "steps": [side["observation"]]},
                  "exit_code": None, "expected_result": {"assertion_satisfied": True},
                  "observed_result": {"assertion_satisfied": side["outcome"] == "passed"} if side["outcome"] in ("passed", "failed") else None,
                  "status": side["outcome"], "output_excerpt": side["observation"], "artifact_ids": [],
                  "caveats": spec["caveats"], "provenance": provenance, "details": details}
        if side["outcome"] in ("untested", "blocked"):
            record["reason"] = side["observation"]
        if side["image"]:
            record["artifact_ids"].append(artifact(phase + ".png", blobs[phase + ".png"], "visual", provenance))
        payload = {"record_id": phase, "commit_sha": side["sha"], **{k: record[k] for k in ("exit_code", "observed_result", "details")}}
        record["artifact_ids"].append(artifact(phase + "-result.json", encoded(payload), "result", provenance))
        if phase == "after":
            record["artifact_ids"].append(artifact("capture-metadata.json", encoded(spec), "supporting", provenance))
        manifest["records"].append(record)
    comparison = {"target_id": target["id"], "before_id": "before" if comparable else None, "after_id": "after"}
    if not comparable:
        comparison["reason"] = spec["before_reason"] if before is None else "Before image has unknown or identical revision; historical revision comparison unavailable."
        if before:
            manifest["caveats"] = [*spec["caveats"], "Unbound before image retained only in the local UI bundle; not attributed to after SHA."]
    manifest["comparisons"].append(comparison)
    validation.validate_manifest(manifest)
    report = reporting.render(manifest)
    output.mkdir(parents=True)
    for name, data in {**output_blobs, "manifest.json": encoded(manifest), "report.md": report.encode("utf-8")}.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    validation.verify(output, offline=True)
    return {"created": True, "verification": "offline integrity only; run gate init/verify with --repo for live evidence"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--executable", required=True)
    pack = sub.add_parser("package")
    pack.add_argument("--input", required=True)
    pack.add_argument("--output", required=True)
    gate = sub.add_parser("export-gate")
    gate.add_argument("bundle")
    gate.add_argument("--output", required=True)
    gate.add_argument("--gate", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            require(shutil.which(args.executable) is not None, "configured capture executable unavailable")
            result = {"available": True, "capabilities": "must be checked in configured tool before capture"}
        elif args.command == "package":
            result = package(args.input, args.output)
        else:
            result = export_gate(args.bundle, args.output, args.gate)
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, TypeError, KeyError, ImportError) as error:
        # Do not echo source URLs, private paths or raw input in failure output.
        print(json.dumps({"valid": False, "error_type": type(error).__name__, "message": "Invalid input or unavailable prerequisite; inspect locally."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
