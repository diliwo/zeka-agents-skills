"""Lossless source inventory and explicit, human-adjudicated finding gates."""

from common import require
from freshness import digest, sources

FLAGS = ("security", "tenant_isolation", "authorization", "data_integrity",
         "persistence_semantics", "runtime_privileges", "architecture_boundary",
         "scope_expansion", "cross_service_contract", "conflict")
DISPOSITIONS = ("accepted/actionable", "partially valid", "false positive", "informational",
                "pre-existing debt", "regression", "architecture decision required",
                "out of scope", "blocked pending evidence")
CONSEQUENTIAL = {"architecture_boundary", "scope_expansion", "cross_service_contract",
                 "runtime_privileges", "persistence_semantics"}


def inventory(snapshot, cfg):
    items = sources(snapshot, cfg)
    # The body can contain review material, but is never trusted as a freshness anchor.
    if snapshot.get("pr_body"):
        items.append({"id": "pr_body", "surface": "pr_body", "body": snapshot["pr_body"]})
    return [{**item, "source_key": item["id"] + "@" + digest(item["body"])} for item in items]


def coverage_gate(items, coverage, findings):
    expected = {item["source_key"] for item in items}
    require(len({c["source_key"] for c in coverage}) == len(coverage), "duplicate coverage entry")
    require({c["source_key"] for c in coverage} == expected, "source coverage incomplete or stale")
    by_id = {f["id"]: f for f in findings}
    require(len(by_id) == len(findings), "duplicate finding ID")
    for entry in coverage:
        require(isinstance(entry["finding_ids"], list), "invalid source mapping")
        require(entry.get("rationale"), "source assessment requires rationale")
        for fid in entry["finding_ids"]:
            require(fid in by_id and entry["source_key"] in by_id[fid]["source_keys"],
                    "source mapping does not match finding")
    for finding in findings:
        require(finding["source_keys"], "finding requires source provenance")
        for key in set(finding["source_keys"]) & expected:
            require(any(c["source_key"] == key and finding["id"] in c["finding_ids"] for c in coverage),
                    "finding missing from coverage mapping")


def assess(finding, cfg, head):
    fid = finding["id"]
    require(isinstance(fid, str) and fid, "invalid finding ID")
    require(finding["severity"] in ("low", "medium", "high", "critical", "unknown"), "invalid severity")
    require(finding["owner"] in ("software", "platform", "mixed", "unknown"), "invalid owner")
    require(finding["component"] and finding["summary"], "finding needs component and summary")
    require(set(finding["flags"]) == set(FLAGS) and
            all(type(v) is bool for v in finding["flags"].values()), "classify every risk flag")
    require(type(finding["reproduced"]) is bool, "reproduction must be explicit")
    require(finding["disposition"] in DISPOSITIONS, "invalid disposition")
    require(finding["state"] in ("open", "corrected", "dismissed", "deferred"), "invalid finding state")
    stops = [key for key, value in finding["flags"].items()
             if value and (key != "security" or finding["severity"] != "low")]
    if not finding["reproduced"]:
        stops.append("cannot_reproduce")
    if finding["severity"] == "unknown" or finding["owner"] in ("unknown", "mixed"):
        stops.append("classification_requires_adjudication")
    if finding["disposition"] in ("architecture decision required", "blocked pending evidence"):
        stops.append(finding["disposition"])
    decision = finding.get("decision") or {}
    approved = (decision.get("by") == "Chief" and bool(decision.get("ref"))
                and decision.get("scope_ref") == cfg["scope_ref"]
                and type(decision.get("blocking")) is bool
                and decision.get("action") in ("fix", "dismiss", "defer"))
    # A generic approval never silently clears a mandatory stop. A separate, explicit
    # adjudication for this head is needed before resuming a bounded run.
    adjudication = finding.get("adjudication") or {}
    cleared = (adjudication.get("by") == "Chief" and adjudication.get("ref")
               and adjudication.get("head_sha") == head
               and adjudication.get("scope_ref") == cfg["scope_ref"]
               and set(stops).issubset(set(adjudication.get("cleared_stops", []))))
    if set(stops) & CONSEQUENTIAL:
        cleared = cleared and bool(adjudication.get("final_authority_approval_ref"))
    # Missing reproduction/evidence cannot be overridden by an approval field.
    if "cannot_reproduce" in stops or "blocked pending evidence" in stops:
        cleared = False
    active_stops = [] if cleared else stops
    owner = {"software": "Codex", "platform": "Hephaestus"}.get(finding["owner"])
    authorized = bool(approved and decision["action"] == "fix" and not active_stops
                      and cfg["actor"] == owner and finding["severity"] != "unknown"
                      and decision.get("head_sha") == head
                      and finding["disposition"] in ("accepted/actionable", "partially valid", "regression"))
    resolved = False
    refs = finding.get("evidence_refs", [])
    require(isinstance(refs, list) and all(isinstance(ref, str) and ref.strip() for ref in refs),
            "evidence references must be nonempty strings in a list")
    if approved and refs:
        if finding["state"] == "corrected":
            resolved = (decision["action"] == "fix" and bool(finding.get("correction_ref"))
                        and finding["disposition"] in ("accepted/actionable", "partially valid", "regression"))
        elif finding["state"] == "dismissed":
            resolved = decision["action"] == "dismiss" and finding["disposition"] in ("false positive", "informational")
        elif finding["state"] == "deferred":
            resolved = (decision["action"] == "defer" and decision["blocking"] is False
                        and finding["disposition"] in ("pre-existing debt", "out of scope", "partially valid"))
    return {"id": fid, "approved": bool(approved), "active_stops": active_stops,
            "correction_authorized": authorized, "resolved": bool(resolved),
            "requires_chief": bool(not approved or active_stops),
            "blocking": decision.get("blocking", True)}
