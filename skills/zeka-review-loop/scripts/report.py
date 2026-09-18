"""Evaluate an append-only run ledger and emit the Chief handoff report."""

from collections import Counter

from common import config, require, sha
from evidence import evaluate
from findings import assess, coverage_gate, inventory
from freshness import freshness


def build(run):
    require(run.get("schema_version") == 1, "unsupported ledger version")
    cfg = config(run["config"])
    iterations = run["iterations"]
    require(iterations, "run has no iterations")
    require(len(iterations) <= cfg["max_iterations"], "iteration cap exceeded")
    summaries, known_sources, previous, all_corrections = [], set(), {}, []
    initial = iterations[0]["snapshot"]
    previous_sha = None
    for number, iteration in enumerate(iterations, 1):
        snapshot = iteration["snapshot"]
        head = sha(snapshot["head_sha"])
        for key in ("repository", "pr", "branch", "head_repository", "base_sha"):
            require(snapshot[key] == initial[key], "run identity/base changed: " + key)
        require(snapshot["worktree"]["clean"] is True and
                snapshot["worktree"]["head_sha"] == head and
                snapshot["worktree"]["branch"] == snapshot["branch"], "unverified worktree")
        fresh = freshness(snapshot, iteration["ticket"], cfg)
        items = inventory(snapshot, cfg)
        known_sources.update(i["source_key"] for i in items)
        findings = iteration["findings"]
        coverage_gate(items, iteration["coverage"], findings)
        current = {f["id"]: f for f in findings}
        require(set(previous).issubset(current), "previous findings disappeared from ledger")
        for finding in findings:
            require(set(finding["source_keys"]).issubset(known_sources), "unknown finding provenance")
            if finding["id"] in previous:
                require(set(previous[finding["id"]]["source_keys"]).issubset(finding["source_keys"]),
                        "finding provenance was removed")
        assessments = [assess(f, cfg, head) for f in findings]
        corrections = iteration.get("corrections", [])
        corrected_ids = set()
        for correction in corrections:
            fid = correction["finding_id"]
            require(fid in previous and fid in current, "correction has no preceding finding")
            require(fid not in corrected_ids, "duplicate correction")
            corrected_ids.add(fid)
            prior = assess(previous[fid], cfg, previous_sha)
            require(prior["correction_authorized"], "correction was not authorized at prior SHA")
            require(summaries[-1]["freshness"]["fresh"], "correction relied on stale review")
            require(not any(a["requires_chief"] for a in summaries[-1]["assessments"]),
                    "correction performed while adjudication stop was active")
            if number > 2 and iterations[number - 2].get("corrections"):
                require(summaries[-1]["evidence"]["passed"], "previous correction evidence gate failed")
            require(correction["focused_ref"] in current[fid].get("evidence_refs", []),
                    "correction focused evidence is not linked to finding")
            require(correction["from_sha"] == previous_sha and correction["to_sha"] == head
                    and previous_sha != head, "correction needs new immutable SHA")
            require(correction["owner"] == cfg["actor"] and correction.get("ref")
                    and correction.get("focused_ref"), "correction lacks owner/evidence")
            require(current[fid]["state"] == "corrected"
                    and current[fid].get("correction_ref") == correction["ref"], "correction not linked to finding")
        for fid, finding in current.items():
            if finding["state"] == "corrected" and previous.get(fid, {}).get("state") != "corrected":
                require(fid in corrected_ids, "corrected finding lacks audited correction")
        if previous_sha and head != previous_sha:
            require(corrections, "unexplained HEAD change; start a new bounded run")
        evidence = evaluate(iteration["evidence"], cfg, head)
        summaries.append({"iteration": number, "head_sha": head, "freshness": fresh,
                          "finding_count": len(findings),
                          "dispositions": dict(Counter(f["disposition"] for f in findings)),
                          "assessments": assessments, "evidence": evidence})
        all_corrections.extend(corrections)
        previous, previous_sha = current, head
    last = summaries[-1]
    adjudications = [a["id"] for a in last["assessments"] if a["requires_chief"]]
    unresolved = [a["id"] for a in last["assessments"] if not a["resolved"]]
    active_reason = run.get("stop_reason")
    ready = (last["freshness"]["fresh"] and not adjudications and not unresolved
             and last["evidence"]["passed"] and not active_reason)
    reason = (active_reason or ("ready_for_chief_review" if ready else
              "stale_or_missing_review" if not last["freshness"]["fresh"] else
              "chief_adjudication_required" if adjudications else
              "iteration_cap" if len(iterations) == cfg["max_iterations"] else
              "approved_findings_remaining" if unresolved else "evidence_gate_failed"))
    return {"schema_version": 1, "repository": cfg["repository"], "pr": cfg["pr"],
            "branch": initial["branch"], "starting_sha": initial["head_sha"],
            "final_sha": previous_sha, "iterations": summaries,
            "greptile_review_freshness": last["freshness"],
            "findings_discovered": len(previous), "findings": list(previous.values()),
            "corrections_performed": all_corrections, "chief_adjudication_required": adjudications,
            "focused_evidence_status": last["evidence"]["focused"],
            "regression_evidence_status": last["evidence"]["regression"],
            "protected_ci_status": last["evidence"]["protected_ci"],
            "remaining_unresolved_findings": unresolved, "stop_reason": reason,
            "READY_FOR_CHIEF_REVIEW": bool(ready)}
