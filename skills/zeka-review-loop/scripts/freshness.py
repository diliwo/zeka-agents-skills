"""Bind completed review evidence to a PR head and a recorded request boundary."""

import hashlib
import re
from datetime import timedelta

from common import require, sha, timestamp


def greptile_summary(body, repository):
    """Recognize the provider footer, never an incidental SHA in review prose."""
    if body.count("<!-- greptile_summary -->") != 1 or body.count("Last reviewed commit:") != 1:
        return None
    footer = re.search(
        r'<sub>Reviews \(([1-9][0-9]*)\) · Last reviewed commit: '
        r'\[[^\]\r\n]+\]\(https://github\.com/' + re.escape(repository) +
        r'/commit/([0-9a-f]{40})\)</sub>\s*$', body)
    return {"reviews": int(footer[1]), "sha": footer[2]} if footer else None


def digest(body):
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def sources(snapshot, cfg):
    result = []
    for surface in ("comments", "inline", "reviews"):
        for raw in snapshot[surface]:
            if raw.get("user", {}).get("login") not in cfg["bot_logins"]:
                continue
            result.append({"id": f"{surface}:{raw['id']}", "surface": surface,
                           "author": raw["user"]["login"], "created_at": raw.get("created_at"),
                           "body": raw.get("body") or "", "url": raw.get("html_url"),
                           "sha": raw.get("commit_id"),
                           "updated_at": raw.get("updated_at") or raw.get("submitted_at")
                           or raw.get("created_at"), "state": raw.get("state"),
                           "path": raw.get("path"), "line": raw.get("line"),
                           "review_id": raw.get("pull_request_review_id")})
    for raw in snapshot["checks"]:
        if raw.get("app", {}).get("slug") in cfg["check_app_slugs"]:
            output = raw.get("output") or {}
            result.append({"id": f"checks:{raw['id']}", "surface": "checks",
                           "body": "\n".join(str(output.get(k) or "")
                                             for k in ("title", "summary", "text")),
                           "url": raw.get("html_url"), "sha": raw.get("head_sha"),
                           "updated_at": raw.get("completed_at") or raw.get("started_at"),
                           "state": raw.get("status"), "conclusion": raw.get("conclusion")})
    return result


def baseline(snapshot, cfg):
    return {s["id"]: {"digest": digest(s["body"]), "updated_at": s["updated_at"],
                      "greptile_summary": greptile_summary(s["body"], snapshot["head_repository"])}
            for s in sources(snapshot, cfg)}


def size_limited(snapshot, cfg):
    return any(re.search(r"too many files|file[- ]count limit|exceeds? .{0,30}file limit",
                         s["body"], re.I) for s in sources(snapshot, cfg))


def greptile_completion(snapshot, ticket, cfg, latest_checks):
    """A stock Greptile result needs independent check and summary assertions."""
    trigger_id = ticket.get("trigger_id")
    if (type(trigger_id) is not int or trigger_id <= 0 or
            ticket.get("trigger_url") != f"https://github.com/{ticket['repository']}/pull/{ticket['pr']}#issuecomment-{trigger_id}" or
            ticket.get("mode") not in ("normal", "apps") or not snapshot["checks_available"] or
            "greptile-apps" not in cfg["check_app_slugs"] or
            "greptile-apps[bot]" not in cfg["bot_logins"]):
        return None
    boundary = timestamp(ticket["requested_at"])
    deadline = boundary + timedelta(seconds=cfg["timeout_seconds"])
    collected = timestamp(snapshot["collected_at"])
    check = latest_checks.get(("greptile-apps", "Greptile Review"))
    if not check or check.get("status") != "completed" or check.get("conclusion") != "success":
        return None
    check_id = f"checks:{check['id']}"
    if check_id in ticket["baseline"] or not check.get("started_at") or not check.get("completed_at"):
        return None
    started, completed = timestamp(check["started_at"]), timestamp(check["completed_at"])
    if not boundary < started <= completed <= min(deadline, collected):
        return None
    summaries = [s for s in sources(snapshot, cfg) if s["surface"] == "comments"
                 and s["author"] == "greptile-apps[bot]" and "<!-- greptile_summary -->" in s["body"]]
    # Multiple candidate summary comments are ambiguous, including stale duplicates.
    if len(summaries) != 1:
        return None
    summary = summaries[0]
    binding = greptile_summary(summary["body"], snapshot["head_repository"])
    if not binding or binding["sha"] != ticket["head_sha"] or not summary["updated_at"]:
        return None
    updated = timestamp(summary["updated_at"])
    if not completed < updated <= min(deadline, collected):
        return None
    previous = ticket["baseline"].get(summary["id"])
    if summary["id"] in ticket["baseline"]:
        if (not isinstance(previous, dict) or not previous.get("updated_at") or
                timestamp(previous["updated_at"]) > boundary or
                previous["digest"] == digest(summary["body"])):
            return None
        prior_binding = previous.get("greptile_summary")
        # New tickets record the review counter: unrelated edits cannot replay a result.
        # Missing or unparseable observations cannot prove counter advancement.
        if (not isinstance(prior_binding, dict) or
                type(prior_binding.get("reviews")) is not int or prior_binding["reviews"] <= 0 or
                not isinstance(prior_binding.get("sha"), str) or
                not re.fullmatch(r"[0-9a-f]{40}", prior_binding["sha"]) or
                binding["reviews"] <= prior_binding["reviews"]):
            return None
    elif not summary["created_at"] or not boundary < timestamp(summary["created_at"]) <= updated:
        return None
    return {"path": "greptile_check_summary", "trigger_id": trigger_id,
            "requested_at": ticket["requested_at"], "check_id": check_id,
            "summary_id": summary["id"], "head_sha": binding["sha"],
            "completed_at": summary["updated_at"]}


def window_sources(snapshot, ticket, cfg, completion):
    """Only changed provider sources in this request's bounded observation window."""
    boundary = timestamp(ticket["requested_at"])
    end = min(timestamp(snapshot["collected_at"]),
              boundary + timedelta(seconds=cfg["timeout_seconds"]))
    accepted = []
    for source in sources(snapshot, cfg):
        if not source["updated_at"] or not boundary < timestamp(source["updated_at"]) <= end:
            continue
        if source["sha"] and source["sha"] != ticket["head_sha"]:
            continue
        previous = ticket["baseline"].get(source["id"])
        if previous and (not previous.get("updated_at") or
                         timestamp(source["updated_at"]) <= timestamp(previous["updated_at"]) or
                         previous["digest"] == digest(source["body"])):
            continue
        if source["surface"] in ("inline", "comments"):
            # Editing a historical discussion does not turn it into this review's finding.
            if source["id"] != completion["summary_id"] and (
                    not source["created_at"] or timestamp(source["created_at"]) <= boundary):
                continue
        if source["surface"] == "inline" and source["sha"] != ticket["head_sha"]:
            continue
        accepted.append(source["id"] + "@" + digest(source["body"]))
    return accepted


def freshness(snapshot, ticket, cfg):
    expected = sha(ticket["head_sha"])
    for key in ("repository", "pr", "branch", "head_repository", "base_sha", "head_sha"):
        require(snapshot[key] == ticket[key], "PR identity/head/base changed: " + key)
    require(snapshot["repository"] == cfg["repository"] and snapshot["pr"] == cfg["pr"],
            "configuration does not match PR")
    boundary = timestamp(ticket["requested_at"])
    require(timestamp(snapshot["collected_at"]) >= boundary, "snapshot predates request")
    require(snapshot["checks_available"] or cfg["allow_unavailable_checks"],
            "check-run evidence unavailable")
    anchors, pending = [], []
    latest_checks = {}
    for raw in snapshot["checks"]:
        if raw.get("app", {}).get("slug") in cfg["check_app_slugs"] and raw.get("head_sha") == expected:
            key = (raw["app"]["slug"], raw["name"])
            if key not in latest_checks or raw["id"] > latest_checks[key]["id"]:
                latest_checks[key] = raw
    for raw in latest_checks.values():
        if raw.get("status") != "completed" or raw.get("conclusion") not in ("success", "neutral"):
            pending.append(f"checks:{raw['id']}")
    for source in sources(snapshot, cfg):
        if not source["updated_at"] or timestamp(source["updated_at"]) <= boundary:
            continue
        if timestamp(source["updated_at"]) > boundary + timedelta(seconds=cfg["timeout_seconds"]):
            continue
        require(timestamp(source["updated_at"]) <= timestamp(snapshot["collected_at"]),
                "review timestamp is newer than snapshot")
        previous = ticket["baseline"].get(source["id"])
        if previous and previous["updated_at"] and timestamp(source["updated_at"]) <= timestamp(previous["updated_at"]):
            continue
        if source["surface"] == "reviews" and source["state"] in (
                "APPROVED", "CHANGES_REQUESTED", "COMMENTED") and source["sha"] == expected:
            anchors.append(source["id"])
        # A generic mention of a SHA, score or trigger echo is not a review binding.
        marker = f"<!-- zeka-review-complete sha={expected} -->"
        if source["surface"] == "comments" and marker in source["body"]:
            if not previous or previous["digest"] != digest(source["body"]):
                anchors.append(source["id"])
    # Existing trusted paths retain their original contracts and precedence.
    completion = None if anchors else greptile_completion(snapshot, ticket, cfg, latest_checks)
    if completion:
        anchors.extend([completion["check_id"], completion["summary_id"]])
    result = {"fresh": bool(anchors) and not pending, "head_sha": expected,
            "anchors": anchors, "pending_or_failed_checks": pending,
            "checks_available": snapshot["checks_available"],
            "reason": "fresh" if anchors and not pending else "missing_fresh_completed_review"}
    if completion:
        result["completion"] = completion
        result["fresh_source_keys"] = window_sources(snapshot, ticket, cfg, completion)
    return result
