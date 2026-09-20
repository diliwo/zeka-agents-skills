"""Deterministic Markdown and the existing review-loop evidence envelope."""

import json

from safety import require, scan_text
from validation import LEVELS, summarize


def text(value):
    # Treat all evidence as data. Prevent HTML, links and Markdown injection.
    value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", "!", "|"):
        value = value.replace(char, "\\" + char)
    return value.replace("\r", " ").replace("\n", " ")


def skip_report(manifest):
    """Expose skip accountability, including historical observations, in the report."""
    records = [r for r in manifest["records"] if r["class"] in ("unit", "integration")
               and r["details"] is not None and r["details"]["skipped"] > 0]
    if not records:
        return []  # Preserve existing zero-skip v1 reports byte-for-byte.
    current = {r["target_id"]: r for r in manifest["records"] if r["phase"] != "before"}
    lines = ["## Skipped tests", ""]
    for record in records:
        details = record["details"]
        lines += ["### " + text(record["id"]) + " (" + record["phase"] + ")", "",
                  f"Test counts: {details['passed']} passed / {details['failed']} failed / {details['skipped']} skipped.",
                  "Accounted skips: " + str(len(details["skips"])),
                  "Recorded OS: " + text(record["environment"]["os"]),
                  "Recorded prerequisites: " + text(json.dumps(record["environment"].get("prerequisites", []), sort_keys=True)), ""]
        for skip in details["skips"]:
            historical = record["phase"] == "before"
            if historical:
                related = ", ".join(skip["target_ids"]) or "none (outside declared targets)"
                effect = "Historical skips do not affect current completeness."
            elif skip["target_ids"]:
                related = ", ".join(t + " (" + current[t]["status"] + ")" for t in skip["target_ids"])
                effect = "; ".join("required target remains " + current[t]["status"] for t in skip["target_ids"])
            else:
                related = "none (explicitly outside declared targets)"
                effect = ("No effect on required-target completeness." if record["status"] == "passed" else
                          "Suite target remains " + record["status"] + "; it does not contribute to passing completeness.")
            lines += ["- Test: " + text(skip["test"]) + "; reason: " + text(skip["reason"]) +
                      "; Expected for environment: " + str(skip["expected_for_environment"]).lower() +
                      "; Condition: " + text(json.dumps(skip["condition"], sort_keys=True)) +
                      "; Required targets: " + text(related) + "; Effect: " + text(effect)]
        lines.append("")
    return lines


def render(manifest, summary=None):
    summary = summary or summarize(manifest)
    lines = ["# Evidence report", "", "Scope: " + text(manifest["scope"]),
             "Repository: " + text(manifest["repository"]),
             "Branch: " + text(manifest["branch"] or "detached HEAD"),
             "Immutable SHA: " + manifest["head_sha"],
             "Bundle: " + text(manifest["bundle_id"]),
             "Created: " + text(manifest["created_at"]), "",
             "Synthetic demonstration: " + str(manifest["synthetic"]).lower(),
             "Freshness: " + summary["freshness"],
             "Required-target completeness: " + ("complete" if summary["complete"] else "incomplete") +
             f" ({summary['passed_targets']}/{summary['required_targets']} passed)", ""]
    if manifest["synthetic"]:
        lines += ["Synthetic data cannot substantiate a real engineering claim.", ""]
    if "contract_ref" in manifest:
        lines += ["Contract reference: " + text(json.dumps(manifest["contract_ref"], sort_keys=True)), ""]
    for level in LEVELS:
        lines += ["## " + level.replace("_", " ").title(), "", "Result: " + summary["levels"][level], ""]
        for r in manifest["records"]:
            if r["level"] != level or r["phase"] == "before":
                continue
            lines += ["### " + text(r["id"] + ": " + r["requirement"]), "",
                      "Status: " + r["status"], "Target: " + text(r["target_id"]),
                      "Class: " + r["class"], "SHA: " + r["commit_sha"],
                      "Expected: " + text(json.dumps(r["expected_result"], sort_keys=True)),
                      "Observed: " + text(json.dumps(r["observed_result"], sort_keys=True)),
                      "Exit code: " + str(r["exit_code"]),
                      "Procedure: " + text(json.dumps(r["procedure"], sort_keys=True)),
                      "Environment: " + text(json.dumps(r["environment"], sort_keys=True)),
                      "Tool/runtime versions: " + text(json.dumps(r.get("versions", []), sort_keys=True)),
                      "Preconditions: " + text(json.dumps(r["preconditions"])),
                      "Source: " + text(json.dumps(r["provenance"], sort_keys=True)),
                      "Output excerpt: " + text(r["output_excerpt"]),
                      "Artifacts: " + text(", ".join(r["artifact_ids"]) or "none")]
            if r.get("reason"):
                lines.append("Reason: " + text(r["reason"]))
            target = next(t for t in manifest["required_targets"] if t["id"] == r["target_id"])
            for key in ("contract_ref", "requirement_ref"):
                reference = r.get(key, target.get(key))
                if reference:
                    lines.append(key + ": " + text(json.dumps(reference, sort_keys=True)))
            lines += ["Caveats: " + text("; ".join(r["caveats"]) or "none recorded"), ""]
    lines += skip_report(manifest)
    lines += ["## Before/after observations", ""]
    records = {r["id"]: r for r in manifest["records"]}
    for comparison in manifest["comparisons"]:
        before = records.get(comparison["before_id"])
        after = records[comparison["after_id"]]
        lines += ["- " + text(comparison["target_id"]) + ": " +
                  (text(before["id"]) + " at " + before["commit_sha"] + " (" + before["status"] +
                   "); observed " + text(json.dumps(before["observed_result"], sort_keys=True))
                   if before else "before untested: " + text(comparison["reason"])) +
                  "; after " + text(after["id"]) + " at " + after["commit_sha"] + " (" + after["status"] + ")."]
    if not manifest["comparisons"]:
        lines.append("No before/after comparison recorded.")
    lines += ["", "## Failed, blocked and untested assertions", ""]
    unresolved = [r for r in manifest["records"] if r["status"] != "passed" and r["phase"] != "before"]
    lines += ["- " + text(r["id"]) + ": " + r["status"] + "; " + text(r.get("reason", "Observed behavior did not satisfy the assertion.")) for r in unresolved]
    if not unresolved:
        lines.append("None among the declared current targets.")
    lines += ["", "## Artifact inventory", ""]
    lines += ["- " + text(a["id"] + ": " + a["path"]) + "; SHA-256 " + a["sha256"] for a in manifest["artifacts"]]
    lines += ["", "## Caveats and limits", ""]
    lines += ["- " + text(c) for c in manifest["caveats"]]
    lines += ["- Completeness covers declared targets only; it does not establish an omitted requirement.",
              "- Hashes establish consistency with the manifest, not authenticity of observations.",
              "- Sensitive-data scanning is heuristic; binary media requires separate review.",
              "- Focused, regression and protected CI evidence are separate obligations.",
              "- This report grants no architecture, review-readiness, merge or issue-closure decision.", ""]
    result = "\n".join(line.rstrip() for line in lines)
    scan_text(result)
    return result


def export_review_loop(manifest, summary, pr, reference):
    require(type(pr) is int and pr > 0, "positive PR number required")
    require(summary["freshness"] == "current" and not manifest["synthetic"],
            "adapter requires current non-synthetic verified evidence")
    require(bool(reference.strip()), "bundle reference required")
    scan_text(reference)
    mapping = {"passed": "passed", "failed": "failed", "blocked": "unavailable",
               "untested": "missing", "missing": "missing"}
    return {"repository": manifest["repository"], "pr": pr, "head_sha": manifest["head_sha"],
            **{level: {"status": mapping[summary["levels"][level]], "head_sha": manifest["head_sha"],
                       "ref": reference + "#" + level.replace("_", "-")} for level in LEVELS}}
