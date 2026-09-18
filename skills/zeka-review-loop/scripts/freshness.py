"""Bind completed review evidence to a PR head and a recorded request boundary."""

import hashlib
import re
from datetime import timedelta

from common import require, sha, timestamp


def digest(body):
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def sources(snapshot, cfg):
    result = []
    for surface in ("comments", "inline", "reviews"):
        for raw in snapshot[surface]:
            if raw.get("user", {}).get("login") not in cfg["bot_logins"]:
                continue
            result.append({"id": f"{surface}:{raw['id']}", "surface": surface,
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
    return {s["id"]: {"digest": digest(s["body"]), "updated_at": s["updated_at"]}
            for s in sources(snapshot, cfg)}


def size_limited(snapshot, cfg):
    return any(re.search(r"too many files|file[- ]count limit|exceeds? .{0,30}file limit",
                         s["body"], re.I) for s in sources(snapshot, cfg))


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
    return {"fresh": bool(anchors) and not pending, "head_sha": expected,
            "anchors": anchors, "pending_or_failed_checks": pending,
            "checks_available": snapshot["checks_available"],
            "reason": "fresh" if anchors and not pending else "missing_fresh_completed_review"}
