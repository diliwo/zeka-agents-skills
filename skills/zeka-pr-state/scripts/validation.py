"""Strict state contracts, safe serialization, assertions and structural comparison."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
AVAILABILITY = ("available", "not_requested", "unavailable", "unsupported_environment", "api_failure")
EXIT = {"mismatch": 2, "unavailable": 3, "unsupported_environment": 4, "api_failure": 5,
        "stale_snapshot": 6, "invalid_input": 7}
PRECEDENCE = ("invalid_input", "api_failure", "unsupported_environment", "stale_snapshot", "unavailable", "mismatch")
DIMENSIONS = {
    "head_moved": ("pr", "head.sha"), "base_moved": ("pr", "base.sha"),
    "branch_changed": ("pr", "head.branch"), "base_branch_changed": ("pr", "base.branch"),
    "head_repository_changed": ("pr", "head.repository"), "base_repository_changed": ("pr", "base.repository"),
    "pr_state_changed": ("pr", None), "worktree_changed": ("workspace", "worktree"),
    "local_head_changed": ("workspace", "head_sha"), "local_branch_changed": ("workspace", "branch"),
    "remote_branch_changed": ("remote_branch", None), "remote_tracking_changed": ("workspace", "remote_tracking"),
    "checks_changed": ("checks", None), "review_sources_changed": ("review_sources", None),
    "mergeability_changed": ("mergeability", None), "required_check_contract_changed": ("required_check_contract", None),
    "workspace_identity_changed": ("workspace", "workspace_id"), "workspace_remote_changed": ("workspace", "remote"),
}


class StateError(ValueError):
    def __init__(self, category, reason):
        self.category, self.reason = category, reason
        super().__init__(reason)


def require(condition, reason, category="invalid_input"):
    if not condition:
        raise StateError(category, reason)


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timezone_required")
        return parsed
    except (ValueError, AttributeError) as exc:
        raise StateError("invalid_input", "invalid_timestamp") from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def body_hash(value):
    require(value is None or isinstance(value, str), "invalid_body")
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def scan(value):
    data = canonical(value)
    patterns = (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}",
                r"\bBearer\s+[A-Za-z0-9._~+/=-]+", r"\bAKIA[A-Z0-9]{16}\b", r"\bop://",
                r"\b(?:password|passwd|pwd|access_token|client_secret|api_key)[\s\"']*[:=][\s\"']*[^\s\"',;}]+",
                r"[a-z][a-z0-9+.-]*://[^\s/:\"]+:[^\s/@\"]+@")
    require(not any(re.search(p, data, re.I) for p in patterns), "sensitive_material")


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def constant(_):
        raise StateError("invalid_input", "nonfinite_number")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, StateError):
            raise
        raise StateError("invalid_input", "invalid_json") from exc


def load(path):
    result = parse(Path(path).read_text(encoding="utf-8-sig"))
    scan(result)
    return result


def write_new(path, value):
    scan(value)
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), "output_exists")
    # Do not create output directories implicitly or follow a supplied directory link.
    for parent in (path.parent, *path.parent.parents):
        require(not parent.is_symlink() and not getattr(parent, "is_junction", lambda: False)(), "output_link")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value) + "\n")


def repo(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value), "invalid_repository")
    require(all(v not in (".", "..") for v in value.split("/")), "invalid_repository")
    return value.lower()


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "invalid_sha")
    return value


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        u = urlsplit(value)
        if u.scheme != "https" or u.netloc != "github.com" or u.query or u.username or u.password:
            return None
        if not re.fullmatch(r"/[A-Za-z0-9_.%/~-]+", u.path) or not re.fullmatch(r"[A-Za-z0-9_-]*", u.fragment):
            return None
        return value
    except ValueError:
        return None


def envelope(data=None, status="available", reason=None, sources=()):
    return {"availability": status, "reason_code": reason, "source_ids": list(sources),
            "data": data if status == "available" else None}


def schema_check(value, node, root):
    """Only the bundled schema vocabulary; no remote resolution or dependencies."""
    if "$ref" in node:
        require(node["$ref"].startswith("#/$defs/"), "external_schema_ref")
        schema_check(value, root["$defs"][node["$ref"].split("/")[-1]], root)
    for key in ("anyOf", "oneOf"):
        if key in node:
            matches = 0
            for variant in node[key]:
                try:
                    schema_check(value, variant, root)
                    matches += 1
                except StateError:
                    pass
            require(matches == 1 if key == "oneOf" else matches > 0, "schema_variant")
    if "const" in node:
        require(canonical(value) == canonical(node["const"]), "schema_constant")
    if "enum" in node:
        require(any(canonical(value) == canonical(v) for v in node["enum"]), "schema_enum")
    types = {"object": lambda v: type(v) is dict, "array": lambda v: type(v) is list,
             "string": lambda v: type(v) is str, "integer": lambda v: type(v) is int,
             "boolean": lambda v: type(v) is bool, "null": lambda v: v is None}
    if "type" in node:
        require(types[node["type"]](value), "schema_type")
    if type(value) is dict:
        require(all(k in value for k in node.get("required", [])), "schema_required")
        require(len(value) >= node.get("minProperties", 0), "schema_empty_object")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            require(not value.keys() - properties.keys(), "schema_unknown_field")
        for key in value.keys() & properties.keys():
            schema_check(value[key], properties[key], root)
    if type(value) is list:
        require(len(value) >= node.get("minItems", 0), "schema_array_length")
        if node.get("uniqueItems"):
            require(len({canonical(v) for v in value}) == len(value), "schema_duplicate_item")
        for item in value:
            schema_check(item, node.get("items", {}), root)
    if type(value) is str:
        require(len(value.strip()) >= node.get("minLength", 0), "schema_empty_string")
        if "pattern" in node:
            require(re.fullmatch(node["pattern"], value) is not None, "schema_pattern")
        if node.get("format") == "date-time":
            timestamp(value)
    if type(value) is int:
        require(value >= node.get("minimum", value), "schema_minimum")


def validate(value, kind):
    scan(value)
    schema = parse((ROOT / "references" / (kind + ".schema.json")).read_text(encoding="utf-8"))
    schema_check(value, schema, schema)
    if kind == "expectation":
        require(any(value.get(k) for k in value if k not in ("schema_version", "expectation_id")), "no_expectations")
        return value
    require(timestamp(value["started_at"]) <= timestamp(value["captured_at"]), "capture_time_order")
    sources = {s["id"]: s for s in value["sources"]}
    require(len(sources) == len(value["sources"]), "duplicate_source")
    for source in sources.values():
        require((source["kind"] == "synthetic") == (value["capture_mode"] == "synthetic"), "synthetic_source_mismatch")
        require(timestamp(value["started_at"]) <= timestamp(source["observed_at"]) <= timestamp(value["captured_at"]), "source_time_outside_capture")
    for name in ("pr", "workspace", "remote_branch", "checks", "review_sources", "mergeability", "required_check_contract"):
        observation = value[name]
        require(set(observation["source_ids"]) <= sources.keys(), "unknown_source")
        available = observation["availability"] == "available"
        require(available == (observation["data"] is not None), "observation_availability_conflict")
        if available:
            require(bool(observation["source_ids"]), "observation_without_provenance")
            require(all(sources[i]["status"] == "available" and sources[i]["metadata"]["complete"]
                        for i in observation["source_ids"]), "incomplete_collection")
    pr = value["pr"]["data"]
    if pr:
        require(pr["repository"] == value["repository"] == pr["base"]["repository"]
                and pr["number"] == value["pr_number"], "pr_identity_conflict")
    workspace = value["workspace"]["data"]
    if workspace:
        flags = workspace["worktree"]
        require(flags["clean"] == (not any(flags[k] for k in ("staged", "unstaged", "untracked", "unmerged"))), "clean_flag_conflict")
        require(workspace["detached"] == (workspace["branch"] is None), "detached_flag_conflict")
        require((workspace["remote"]["identity_status"] == "available") == (workspace["remote"]["repository"] is not None), "remote_identity_conflict")
        require((workspace["remote_tracking"]["availability"] == "available") == (workspace["remote_tracking"]["sha"] is not None), "tracking_availability_conflict")
    for name in ("checks", "review_sources"):
        items = value[name]["data"] or []
        require(len({i["key"] for i in items}) == len(items), "duplicate_inventory_key")
        for item in items:
            require(item["repository"] == value["repository"], "inventory_repository_conflict")
            identity_kind = item["kind"] if name == "checks" else item["source_type"]
            require(item["key"] == f"{identity_kind}:{item['repository']}:{item['id']}", "inventory_key_conflict")
            sid = item["binding"]["source_id"] if name == "checks" else item["source_id"]
            require(sid in value[name]["source_ids"], "inventory_source_outside_collection")
            if name == "checks":
                method = item["binding"]["method"]
                require((method != "unavailable") == (item["head_sha"] is not None), "check_binding_conflict")
                if method == "exact_sha_endpoint":
                    meta = sources[sid]["metadata"]
                    require(item["kind"] == "commit_status" and meta["sha"] == item["head_sha"]
                            and meta["endpoint"] == f"repos/{item['repository']}/commits/{item['head_sha']}/statuses",
                            "status_endpoint_binding_conflict")
            else:
                require((item["binding"] != "unavailable") == (item["associated_sha"] is not None), "review_binding_conflict")
            require(item["url"] is None or safe_url(item["url"]) == item["url"], "unsafe_url")
    for item in value["ancestry"]:
        require(item["source_id"] in sources, "unknown_ancestry_source")
        source = sources[item["source_id"]]
        require(source["operation"] == "ancestry" and source["status"] == item["availability"], "ancestry_source_conflict")
        require(item["availability"] != "available" or source["metadata"]["complete"], "incomplete_ancestry")
        require(pr is not None and item["descendant_sha"] == pr["head"]["sha"], "ancestry_revision_conflict")
        require((item["availability"] == "available") == (item["is_ancestor"] is not None), "ancestry_availability_conflict")
    boundary = value["consistency"]["boundary_source_ids"]
    require(set(boundary) <= sources.keys(), "unknown_boundary_source")
    if value["consistency"]["status"] == "stable":
        require(pr is not None, "stable_capture_without_pr")
        for operation, data in (("pr", pr), ("workspace", workspace)):
            if operation == "workspace" and value["capture_mode"] == "github":
                continue
            if operation == "workspace" and data is None and value["capture_mode"] == "synthetic":
                continue
            group = [sources[i] for i in boundary if sources[i]["operation"] == operation]
            require(data is not None and len(group) == 2, "missing_capture_boundaries")
            expected = digest(without_observed_at(data))
            require(all(s["status"] == "available" and s["metadata"]["fingerprint"] == expected for s in group), "capture_boundary_conflict")
    return value


def without_observed_at(data):
    return {k: v for k, v in data.items() if k != "observed_at"}


def get(data, field):
    for key in field.split("."):
        data = data[key]
    return data


def semantic(snapshot, name, field):
    obs = snapshot[name]
    if obs["availability"] != "available":
        return None
    data = obs["data"]
    if name == "pr" and field is None:
        return {k: data[k] for k in ("state", "draft")}
    if field:
        return get(data, field)
    if isinstance(data, list):
        return sorted(data, key=lambda i: i["key"])
    return without_observed_at(data)


def compare(previous, current):
    validate(previous, "snapshot")
    validate(current, "snapshot")
    require((previous["capture_mode"] == "synthetic") == (current["capture_mode"] == "synthetic"), "mixed_synthetic_live_comparison")
    rows = []
    for label, (name, field) in DIMENSIONS.items():
        before, after = semantic(previous, name, field), semantic(current, name, field)
        known = previous[name]["availability"] == current[name]["availability"] == "available"
        # Collection source IDs are per-capture provenance, not semantic state.
        def strip_sources(v):
            if isinstance(v, dict):
                return {k: strip_sources(x) for k, x in v.items() if k not in ("source_id", "source_ids")}
            return [strip_sources(x) for x in v] if isinstance(v, list) else v
        row = {"change": label, "status": "unavailable" if not known else
               "unchanged" if canonical(strip_sources(before)) == canonical(strip_sources(after)) else "changed",
               "before": before, "after": after}
        if name in ("checks", "review_sources") and known:
            left, right = ({i["key"]: strip_sources(i) for i in items} for items in (before, after))
            row["items"] = {"added": sorted(right.keys() - left.keys()), "removed": sorted(left.keys() - right.keys()),
                            "changed": sorted(k for k in left.keys() & right.keys() if canonical(left[k]) != canonical(right[k]))}
        rows.append(row)
    identity_before, identity_after = ([s["repository"], s["pr_number"]] for s in (previous, current))
    rows.append({"change": "repository_or_pr_identity_changed", "status": "unchanged" if identity_before == identity_after else "changed",
                 "before": identity_before, "after": identity_after})
    avail = lambda s: {k: s[k]["availability"] for k in ("pr", "workspace", "remote_branch", "checks", "review_sources", "mergeability", "required_check_contract")}
    rows.append({"change": "availability_changed", "status": "unchanged" if avail(previous) == avail(current) else "changed",
                 "before": avail(previous), "after": avail(current)})
    return {"schema_version": 1, "previous_capture_id": previous["capture_id"], "current_capture_id": current["capture_id"],
            "changes": rows, "changed": [r["change"] for r in rows if r["status"] == "changed"],
            "unavailable": [r["change"] for r in rows if r["status"] == "unavailable"]}


def verify(snapshot, expectation, previous=None):
    validate(snapshot, "snapshot")
    validate(expectation, "expectation")
    assertions = []
    def add(name, expected, observed, sources=(), unavailable=None, reason="value_mismatch"):
        status = unavailable or ("passed" if canonical(expected) == canonical(observed) else "mismatch")
        assertions.append({"id": name, "expected": expected, "observed": observed, "source_ids": list(sources),
                           "status": status, "reason_code": None if status == "passed" else reason})
    def observe(name, field):
        obs = snapshot[name]
        category = None if obs["availability"] == "available" else ("unavailable" if obs["availability"] == "not_requested" else obs["availability"])
        return (get(obs["data"], field) if field and category is None else obs["data"]), obs["source_ids"], category
    add("capture_consistency", "stable", snapshot["consistency"]["status"], snapshot["consistency"]["boundary_source_ids"],
        None if snapshot["consistency"]["status"] == "stable" else "stale_snapshot", "capture_not_coherent")
    for section in ("identity", "workspace", "remote_branch"):
        for key, expected in expectation.get(section, {}).items():
            name = "pr" if section == "identity" else section
            fields = expected.items() if key in ("head", "base") else [(None, expected)]
            for subkey, wanted in fields:
                field = key + "." + subkey if subkey else key
                field = {"pr_number": "number", "must_be_clean": "worktree.clean", "remote_name": "remote.name", "remote_repository": "remote.repository"}.get(field, field)
                observed, ids, missing = observe(name, field)
                if key == "must_be_clean" and wanted is False:
                    continue
                if name == "workspace" and key == "remote_repository" and missing is None and observed is None:
                    missing = snapshot["workspace"]["data"]["remote"]["identity_status"]
                add(section + "." + field, wanted, observed, ids, missing)
    pairs = {"local_head_equals_pr_head": ("workspace", "head_sha", "head.sha"),
             "local_branch_equals_head_branch": ("workspace", "branch", "head.branch"),
             "live_remote_equals_pr_head": ("remote_branch", "sha", "head.sha"),
             "remote_tracking_equals_pr_head": ("workspace", "remote_tracking.sha", "head.sha")}
    for key, requested in expectation.get("agreement", {}).items():
        if not requested:
            continue
        name, field, prfield = pairs[key]
        actual, ids, missing = observe(name, field)
        wanted, prids, prmissing = observe("pr", prfield)
        if actual is None and missing is None:
            missing = "unavailable"
        if name == "remote_branch" and missing is None and prmissing is None:
            require(snapshot[name]["data"]["repository"] == snapshot["pr"]["data"]["head"]["repository"]
                    and snapshot[name]["data"]["branch"] == snapshot["pr"]["data"]["head"]["branch"], "live_ref_identity_conflict")
        if key == "remote_tracking_equals_pr_head" and missing is None and prmissing is None:
            remote = snapshot["workspace"]["data"]["remote"]
            head = snapshot["pr"]["data"]["head"]
            add(key + ".repository", head["repository"], remote["repository"], ids + prids,
                None if remote["identity_status"] == "available" and head["repository"] else "unavailable")
            expected_ref = "refs/remotes/" + remote["name"] + "/" + head["branch"]
            add(key + ".ref", expected_ref, snapshot["workspace"]["data"]["remote_tracking"]["ref"], ids)
        add(key, wanted, actual, ids + prids, missing or prmissing)
    for ancestor in expectation.get("ancestors", []):
        candidates = [a for a in snapshot["ancestry"] if a["ancestor_sha"] == ancestor]
        a = candidates[0] if len(candidates) == 1 else None
        add("ancestor:" + ancestor, True, a["is_ancestor"] if a else None, [a["source_id"]] if a else [],
            None if a and a["availability"] == "available" else "unavailable", "ancestry_not_established")
    prhead = snapshot["pr"]["data"]["head"]["sha"] if snapshot["pr"]["data"] else None
    for n, required in enumerate(expectation.get("required_checks", [])):
        obs = snapshot["checks"]
        candidates = [c for c in (obs["data"] or []) if c["kind"] == required["kind"] and c["name"] == required["name"]
                      and all(c["source"].get(k) == v for k, v in required.get("source", {}).items())]
        sources = {canonical([c["repository"], c["source"]]) for c in candidates}
        reason, category, selected = "missing_check", None, None
        if obs["availability"] != "available":
            category = "unavailable" if obs["availability"] == "not_requested" else obs["availability"]
        elif not candidates:
            category = "mismatch"
        elif any(c["source"]["id"] is None for c in candidates):
            category, reason = "unavailable", "check_source_identity_unavailable"
        elif any(c["head_sha"] is None for c in candidates):
            category, reason = "unavailable", "check_binding_unavailable"
        elif len(sources) > 1:
            category, reason = "unavailable", "ambiguous_check_source"
        else:
            exact = [c for c in candidates if c["head_sha"] == prhead and prhead is not None]
            if not exact:
                category, reason = ("unavailable", "check_binding_unavailable") if any(c["head_sha"] is None for c in candidates) else ("mismatch", "check_sha_mismatch")
            elif required.get("selection", "unique") == "unique" and len(exact) != 1:
                category, reason = "unavailable", "ambiguous_check_attempt"
            else:
                selected = max(exact, key=lambda c: c["id"])
        label = "required_check:" + str(n)
        if selected is None:
            add(label, "bound_check", None, obs["source_ids"], category or "unavailable", reason)
            continue
        add(label + ".sha", prhead, selected["head_sha"], [selected["binding"]["source_id"]])
        if required["must_be_completed"] or required["must_be_successful"]:
            add(label + ".completed", "completed", selected["status"], obs["source_ids"])
        if required["must_be_successful"]:
            add(label + ".successful", "success", selected["conclusion"], obs["source_ids"])
        assertions[-1]["selected_check_id"] = selected["id"]
        assertions[-1]["superseded_check_ids"] = sorted(c["id"] for c in candidates if c["head_sha"] == prhead and c["id"] != selected["id"])
    if "previous" in expectation:
        wanted = expectation["previous"]
        if previous is None:
            add("previous_snapshot", wanted["capture_id"], None, unavailable="unavailable", reason="previous_snapshot_missing")
        else:
            comparison = compare(previous, snapshot)
            add("previous_capture_consistency", "stable", previous["consistency"]["status"],
                previous["consistency"]["boundary_source_ids"],
                None if previous["consistency"]["status"] == "stable" else "stale_snapshot", "capture_not_coherent")
            add("previous_capture_id", wanted["capture_id"], previous["capture_id"])
            add("previous_pr_identity", [snapshot["repository"], snapshot["pr_number"]], [previous["repository"], previous["pr_number"]])
            if "head_sha" in wanted:
                oldhead = previous["pr"]["data"]["head"]["sha"] if previous["pr"]["data"] else None
                add("previous_head", wanted["head_sha"], oldhead, unavailable="unavailable" if oldhead is None else None)
            for dimension in wanted["unchanged"]:
                row = next(r for r in comparison["changes"] if r["change"] == dimension)
                category = None if row["status"] == "unchanged" else "unavailable" if row["status"] == "unavailable" else "stale_snapshot"
                add("previous." + dimension, "unchanged", row["status"], unavailable=category, reason="snapshot_changed")
    require(len(assertions) > 1, "no_active_expectations")
    failures = sorted({a["status"] for a in assertions if a["status"] != "passed"})
    return {"schema_version": 1, "capture_id": snapshot["capture_id"], "repository": snapshot["repository"],
            "pr_number": snapshot["pr_number"], "expected_head": expectation.get("identity", {}).get("head", {}).get("sha"),
            "observed_head": prhead, "assertions": assertions, "failure_categories": failures,
            "unavailable_assertions": [a["id"] for a in assertions if a["status"] in ("unavailable", "unsupported_environment", "api_failure")],
            "mismatch_reasons": [a["reason_code"] for a in assertions if a["status"] in ("mismatch", "stale_snapshot")],
            "overall": "failed" if failures else "passed",
            "proof_scope": "synthetic" if snapshot["capture_mode"] == "synthetic" else "compared_snapshots" if previous else "snapshot_only"}


def exit_code(categories):
    return next((EXIT[c] for c in PRECEDENCE if c in categories), 0)
