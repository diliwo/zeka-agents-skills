"""Offline schema, semantic, artifact and current-revision verification."""

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from safety import Invalid, json_equal, parse_json, read_json, require, safe_path, scan_text, scan_value

SCHEMA = Path(__file__).resolve().parents[1] / "references" / "manifest.schema.json"
LEVELS = ("focused", "regression", "protected_ci")


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timestamp requires timezone")
        return parsed
    except (ValueError, AttributeError) as exc:
        raise Invalid("invalid timestamp") from exc


def schema_check(value, node, root, location="manifest"):
    """Implement only the JSON Schema keywords used by the bundled schema.

    No remote resolution or dependencies. This is not a general JSON Schema engine.
    """
    if "$ref" in node:
        name = node["$ref"]
        require(name.startswith("#/$defs/"), "external schema references unsupported")
        schema_check(value, root["$defs"][name.split("/")[-1]], root, location)
    for key in ("anyOf", "oneOf"):
        if key in node:
            matches = 0
            for option in node[key]:
                try:
                    schema_check(value, option, root, location)
                    matches += 1
                except Invalid:
                    pass
            require(matches == 1 if key == "oneOf" else matches > 0,
                    location + ": no unambiguous permitted schema variant")
    if "const" in node:
        require(type(value) is type(node["const"]) and value == node["const"],
                location + ": invalid constant")
    if "enum" in node:
        require(value in node["enum"], location + ": invalid enumeration")
    types = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
             "string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int,
             "number": lambda v: type(v) in (int, float), "boolean": lambda v: type(v) is bool,
             "null": lambda v: v is None}
    if "type" in node:
        require(types[node["type"]](value), location + ": wrong type")
    if isinstance(value, dict):
        require(all(k in value for k in node.get("required", [])), location + ": required field missing")
        require(len(value) >= node.get("minProperties", 0), location + ": empty result")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            require(not value.keys() - properties.keys(), location + ": unknown field")
        for key, child in properties.items():
            if key in value:
                schema_check(value[key], child, root, location + "." + key)
    if isinstance(value, list):
        require(len(value) >= node.get("minItems", 0), location + ": too few entries")
        for item in value:
            schema_check(item, node.get("items", {}), root, location + "[]")
    if isinstance(value, str):
        require(len(value.strip()) >= node.get("minLength", 0), location + ": empty string")
        if "pattern" in node:
            require(re.search(node["pattern"], value) is not None, location + ": invalid format")
        if node.get("format") == "date-time":
            timestamp(value)
    if type(value) in (int, float):
        require(value >= node.get("minimum", float("-inf")), location + ": below minimum")
        require(value <= node.get("maximum", float("inf")), location + ": above maximum")


def index(items, label):
    result = {item["id"]: item for item in items}
    require(len(result) == len(items), "duplicate " + label + " ID")
    return result


def provenance_check(provenance, sha, synthetic, repository):
    kind, meta = provenance["kind"], provenance["metadata"]
    require((kind == "synthetic") == synthetic, "synthetic provenance/bundle mismatch")
    if kind in ("local_process", "testcontainers"):
        require(meta["start_sha"] == meta["end_sha"] == sha, "process revision changed or mismatched")
        require(timestamp(meta["started_at"]) <= timestamp(meta["finished_at"]),
                "process timestamps out of order")
    if kind in ("github_actions", "github_api"):
        require(meta["head_sha"] == sha and meta["repository"] == repository,
                "GitHub provenance belongs to a different revision or repository")
    if kind == "deployed_system":
        require(meta["build_sha"] == sha, "deployment revision mismatch")
    if kind == "manual_observation":
        require(meta["subject_sha"] == sha, "manual observation revision mismatch")


def placeholders(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("caveats", "reason"):
                for text in child if isinstance(child, list) else [child]:
                    require(not re.search(r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|<[^>]+>", text, re.I),
                            "unfinished caveat or reason")
            else:
                placeholders(child)
    elif isinstance(value, list):
        for child in value:
            placeholders(child)


def validate_skips(records, targets, current):
    """Validate producer-declared relationships; never infer them from test names."""
    for record in records.values():
        environment = record["environment"]
        prerequisites = index(environment.get("prerequisites", []), "environment prerequisite")
        details = record["details"]
        if record["class"] not in ("unit", "integration") or details is None:
            continue
        skips = details.get("skips", [])
        require(details["skipped"] == len(skips), "reported skip count differs from accounted inventory")
        identities = [skip["test"] for skip in skips]
        require(len(set(identities)) == len(identities), "duplicate skipped test identity")
        for skip in skips:
            require(skip["test"] == skip["test"].strip(), "skipped test identity must be canonical")
            ids = skip["target_ids"]
            require(len(ids) == len(set(ids)), "duplicate skip target reference")
            require(set(ids) <= set(targets), "skip refers to unknown required target")
            condition = skip["condition"]
            if condition is None:
                expected = False
            elif condition["kind"] == "platform":
                supported = condition["supported_os"]
                require(len(supported) == len(set(supported)), "duplicate supported OS in skip condition")
                require(environment["os"] in ("Windows", "Linux", "macOS", "FreeBSD"),
                        "platform skip requires a canonical recorded OS")
                expected = environment["os"] not in supported
            elif condition["kind"] == "prerequisite":
                require(condition["id"] in prerequisites, "skip prerequisite is not recorded in environment")
                expected = not prerequisites[condition["id"]]["available"]
            else:  # Strict schema admits only explicit_exclusion here; its authority is producer-verified.
                expected = True
            require(skip["expected_for_environment"] == expected,
                    "skip expectation contradicts its recorded environment condition")
            if record["status"] == "passed":
                require(expected, "unexpected skip cannot accompany a passing suite obligation")
                require(record["target_id"] not in ids, "passing suite target depends on a skipped scenario")
            if record["phase"] != "before":
                require(all(current[target_id]["status"] in ("untested", "blocked") for target_id in ids),
                        "skipped required target must be explicitly untested or blocked")


def validate_manifest(manifest):
    scan_value(manifest)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema_check(manifest, schema, schema)
    placeholders(manifest)
    targets = index(manifest["required_targets"], "target")
    records = index(manifest["records"], "record")
    artifacts = index(manifest["artifacts"], "artifact")
    paths = [a["path"].casefold() for a in artifacts.values()]
    require(len(paths) == len(set(paths)), "duplicate artifact path")
    require(not {"manifest.json", "report.md", "review-loop.json"}.intersection(paths),
            "artifact uses a reserved output path")
    current = {}
    for record in records.values():
        target = targets.get(record["target_id"])
        require(target is not None, "record refers to unknown target")
        require(record["repository"] == manifest["repository"], "record repository mismatch")
        require(record["level"] == target["level"] and record["class"] == target["class"],
                "record does not match target evidence class/level")
        require(record["requirement"] == target["requirement"], "record requirement differs from target")
        for name in ("contract_ref", "requirement_ref"):
            if name in target and name in record:
                require(target[name] == record[name], "record authoritative reference differs from target")
        require(timestamp(record["timestamp"]) <= timestamp(manifest["created_at"]),
                "record is later than bundle creation")
        if record["phase"] != "before":
            require(record["commit_sha"] == manifest["head_sha"], "current evidence SHA mismatch")
            require(record["branch"] == manifest["branch"], "current evidence branch mismatch")
            require(record["target_id"] not in current, "multiple current records for target; use separate targets")
            current[record["target_id"]] = record
        provenance_check(record["provenance"], record["commit_sha"], manifest["synthetic"], manifest["repository"])
        procedure = record["procedure"]
        require(bool(procedure.get("argv")) != bool(procedure.get("steps")),
                "procedure requires exactly one of argv or steps")
        meta = record["provenance"]["metadata"]
        if record["provenance"]["kind"] in ("local_process", "testcontainers"):
            require(procedure.get("argv") == meta["argv"] and procedure["working_directory"] == meta["working_directory"],
                    "procedure/provenance command mismatch")
        require(len(set(record["artifact_ids"])) == len(record["artifact_ids"]), "duplicate record artifact reference")
        for aid in record["artifact_ids"]:
            require(aid in artifacts, "record refers to unknown artifact")
            provenance_check(artifacts[aid]["provenance"], record["commit_sha"], manifest["synthetic"], manifest["repository"])
        status, details = record["status"], record["details"]
        executed = status in ("passed", "failed")
        if executed:
            require(record["observed_result"] is not None and details is not None, "executed evidence lacks observations")
            require(any(artifacts[a]["role"] == "result" for a in record["artifact_ids"]),
                    "executed evidence requires a structured result artifact")
        else:
            require(bool(record.get("reason")), "unexecuted evidence requires a reason")
            require(record["exit_code"] is None, "unexecuted evidence cannot have an exit code")
        if executed and record["provenance"]["kind"] in ("local_process", "testcontainers"):
            require(record["exit_code"] is not None, "process evidence requires exit code")
        if status == "passed":
            require(json_equal(record["expected_result"], record["observed_result"]), "passing assertion differs from expected result")
            require(record["exit_code"] is None or record["exit_code"] == procedure.get("expected_exit_code", 0),
                    "passing evidence has unexpected exit code")
        if status == "failed":
            require(not json_equal(record["expected_result"], record["observed_result"])
                    or record["exit_code"] is not None and record["exit_code"] != procedure.get("expected_exit_code", 0)
                    or record["class"] in ("unit", "integration") and details["failed"] > 0
                    or record["class"] == "ci" and details["conclusion"] != "success",
                    "failed evidence lacks an observed failure")
        if record["class"] == "postgresql" and status == "passed":
            require(json_equal(details["expected_state"], details["observed_state"]), "database expected/observed state mismatch")
        if record["class"] in ("unit", "integration") and executed:
            count = details["passed"] + details["failed"]
            require(count > 0, "no tests executed")
            if status == "passed":
                require(details["failed"] == 0 and record["exit_code"] == 0,
                        "passing test suite includes failures or lacks successful exit")
        if record["level"] == "protected_ci":
            require(record["class"] == "ci", "protected CI level requires CI evidence")
        if record["class"] == "ci" and executed:
            require(record["provenance"]["kind"] in ("github_actions", "github_api", "synthetic"),
                    "CI requires GitHub source provenance")
            require(details["head_sha"] == record["commit_sha"], "CI result SHA mismatch")
            if record["provenance"]["kind"] == "github_actions":
                require(details["run_id"] == meta["run_id"] and details["job"] == meta["job"]
                        and details["url"] == meta["url"], "CI result/provenance run mismatch")
            checks = {c["name"]: c for c in details["checks"]}
            require(len(checks) == len(details["checks"]), "duplicate CI check")
            require(len(set(details["required_checks"])) == len(details["required_checks"]), "duplicate required CI check")
            require(all(c["head_sha"] == record["commit_sha"] for c in checks.values()), "CI check SHA mismatch")
            if status == "passed":
                require(details["conclusion"] == "success" and all(
                    name in checks and checks[name]["conclusion"] == "success" for name in details["required_checks"]),
                    "required CI checks are missing or not successful")
        if record["class"] == "ui" and status == "passed":
            require(details["visual_review"]["reviewed"], "UI evidence needs visual review")
    require(set(current) == set(targets), "required target lacks current passed/failed/untested/blocked record")
    validate_skips(records, targets, current)
    used = {aid for r in records.values() for aid in r["artifact_ids"]}
    require(used == set(artifacts), "unreferenced artifact")
    compared = set()
    for comparison in manifest["comparisons"]:
        after = records.get(comparison["after_id"])
        require(after is not None and after["phase"] == "after" and after["target_id"] == comparison["target_id"],
                "invalid after comparison")
        require(after["id"] not in compared, "duplicate comparison")
        compared.add(after["id"])
        if comparison["before_id"] is None:
            require(bool(comparison.get("reason")), "missing reproduction needs explicit reason")
        else:
            before = records.get(comparison["before_id"])
            require(before is not None and before["phase"] == "before" and before["target_id"] == after["target_id"],
                    "invalid before comparison")
            require(before["commit_sha"] != after["commit_sha"], "before/after must retain distinct revisions")
    require(compared == {r["id"] for r in records.values() if r["phase"] == "after"}, "after record lacks comparison")
    require({r["id"] for r in records.values() if r["phase"] == "before"} <=
            {c["before_id"] for c in manifest["comparisons"]}, "before record lacks comparison")
    return current


def artifact_bytes(manifest, bundle):
    """Check all inputs before any output write; return exact checked bytes."""
    result = {}
    for artifact in manifest["artifacts"]:
        path = safe_path(bundle, artifact["path"])
        require(path.is_file(), "referenced artifact is missing")
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == artifact["sha256"], "artifact hash mismatch")
        # Recognizable ASCII credentials in media/metadata must also be rejected.
        scan_text(data.decode("latin-1"))
        if artifact["media_type"].startswith(("text/", "application/")):
            try:
                scan_text(data.decode("utf-8-sig"))
            except UnicodeError as exc:
                raise Invalid("text artifact is not UTF-8") from exc
        if artifact["media_type"] == "application/json":
            payload = parse_json(data.decode("utf-8-sig"))
        if artifact["role"] == "result":
            require(artifact["media_type"] == "application/json", "result artifact must be JSON")
            matching = [r for r in manifest["records"] if artifact["id"] in r["artifact_ids"]]
            require(len(matching) == 1, "result artifact must identify exactly one record")
            record = matching[0]
            expected = {"record_id": record["id"], "commit_sha": record["commit_sha"],
                        **{k: record[k] for k in ("exit_code", "observed_result", "details")}}
            require(json_equal(payload, expected), "structured source result does not match manifest")
        result[artifact["path"]] = data
    return result


def git(repo, *args):
    process = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    require(process.returncode == 0, "Git verification failed")
    return process.stdout.decode("utf-8", errors="strict").strip()


def check_repository(manifest, bundle, repo, remote="origin"):
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    require(git(root, "rev-parse", "HEAD") == manifest["head_sha"], "evidence stale for current HEAD")
    branch = git(root, "branch", "--show-current") or None
    require(branch == manifest["branch"], "current branch differs from bundle")
    # Never print remote URLs: they can contain credentials.
    url = git(root, "remote", "get-url", remote)
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", url)
    require(match is not None and match[1].casefold() == manifest["repository"].casefold(),
            "repository remote does not match public-safe GitHub identity")
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "worktree is dirty; revision binding is unproven")
    check_commit_safety(bundle, root)


def check_commit_safety(bundle, repo):
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    bundle = Path(bundle).resolve()
    if bundle.is_relative_to(root):
        relative = bundle.relative_to(root).as_posix()
        require(not git(root, "ls-files", "--", relative), "runtime evidence is tracked or staged")
        process = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", relative + "/manifest.json"],
                                 capture_output=True)
        require(process.returncode == 0, "runtime evidence must be ignored before writing")


def verify(bundle, repo=None, offline=False):
    bundle = Path(bundle)
    manifest = read_json(safe_path(bundle, "manifest.json"))
    current = validate_manifest(manifest)
    artifact_bytes(manifest, bundle)
    # Verify the delivered report too; stale prose cannot accompany valid measurements.
    from reporting import render
    report_path = safe_path(bundle, "report.md")
    require(report_path.is_file(), "human-readable report is missing")
    report = report_path.read_text(encoding="utf-8")
    scan_text(report)
    require(report == render(manifest), "stored report does not match manifest")
    expected_files = {"manifest.json", "report.md", *(a["path"] for a in manifest["artifacts"])}
    for parent, directories, files in os.walk(bundle, followlinks=False):
        for name in directories + files:
            item = Path(parent) / name
            relative = item.relative_to(bundle).as_posix()
            safe_path(bundle, relative)
        for name in files:
            require((Path(parent) / name).relative_to(bundle).as_posix() in expected_files,
                    "unlisted file in evidence bundle")
    if not offline:
        require(repo is not None, "repository required for live freshness and commit-safety checks")
        require(not manifest["synthetic"], "synthetic evidence cannot pass live verification")
        check_repository(manifest, bundle, repo)
    return manifest, summarize(manifest, current, not offline)


def summarize(manifest, current=None, freshness_checked=False):
    current = current or validate_manifest(manifest)
    levels = {}
    for level in LEVELS:
        statuses = [r["status"] for r in current.values() if r["level"] == level]
        levels[level] = ("missing" if not statuses else "failed" if "failed" in statuses else
                         "blocked" if "blocked" in statuses else "untested" if "untested" in statuses else "passed")
    return {"valid": True, "freshness": "current" if freshness_checked else "not_checked",
            "synthetic": manifest["synthetic"], "levels": levels,
            "required_targets": len(current), "passed_targets": sum(r["status"] == "passed" for r in current.values()),
            "complete": all(r["status"] == "passed" for r in current.values()),
            "usable_as_current_evidence": freshness_checked and not manifest["synthetic"]}
