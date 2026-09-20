"""Read-only GitHub transport and normalized, body-free PR observations."""

import os
import subprocess
from urllib.parse import quote

from validation import StateError, body_hash, digest, parse, repo, require, safe_url, sha

API_VERSION = "2026-03-10"


class GitHub:
    def __init__(self, max_pages=20, runner=subprocess.run):
        require(type(max_pages) is int and 1 <= max_pages <= 100, "invalid_page_limit")
        self.max_pages, self.runner = max_pages, runner

    def get(self, endpoint):
        try:
            result = self.runner(["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint,
                                  "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: " + API_VERSION],
                                 capture_output=True, timeout=60,
                                 env={**os.environ, "GH_PROMPT_DISABLED": "1"})
        except FileNotFoundError as exc:
            raise StateError("unsupported_environment", "command_missing") from exc
        except subprocess.TimeoutExpired as exc:
            raise StateError("api_failure", "timeout") from exc
        except OSError as exc:
            raise StateError("api_failure", "api_failed") from exc
        require(result.returncode == 0, "api_failed", "api_failure")
        try:
            return parse(result.stdout)
        except StateError as exc:
            raise StateError("api_failure", "invalid_response") from exc

    def collect(self, endpoint, field=None):
        result, identities, expected_count = [], set(), None
        for page in range(1, self.max_pages + 1):
            separator = "&" if "?" in endpoint else "?"
            raw = self.get(endpoint + separator + f"per_page=100&page={page}")
            items = raw.get(field) if field and isinstance(raw, dict) else raw
            require(isinstance(items, list) and len(items) <= 100, "invalid_response", "api_failure")
            if field:
                count = raw.get("total_count") if isinstance(raw, dict) else None
                require(type(count) is int and count >= 0, "invalid_response", "api_failure")
                require(expected_count is None or expected_count == count, "pagination_changed", "unavailable")
                expected_count = count
            for item in items:
                require(isinstance(item, dict) and type(item.get("id")) is int, "invalid_response", "api_failure")
                require(item["id"] not in identities, "pagination_changed", "unavailable")
                identities.add(item["id"])
            result.extend(items)
            if expected_count is not None:
                require(len(result) <= expected_count, "pagination_changed", "unavailable")
                if len(result) == expected_count:
                    return result, page
            if len(items) < 100:
                require(expected_count is None, "pagination_changed", "unavailable")
                return result, page
        raise StateError("unavailable", "limit_reached")


def pr_identity(raw, repository, number):
    try:
        base, head = raw["base"], raw["head"]
        result = {"repository": repo(base["repo"]["full_name"]), "number": raw["number"],
                  "url": safe_url(raw["html_url"]), "state": "merged" if raw.get("merged") else raw["state"],
                  "draft": raw["draft"], "base": {"repository": repo(base["repo"]["full_name"]), "branch": base["ref"], "sha": sha(base["sha"])},
                  "head": {"repository": repo(head["repo"]["full_name"]) if head.get("repo") else None,
                           "branch": head["ref"], "sha": sha(head["sha"])}}
        require(result["repository"] == repository and result["number"] == number and result["url"] is not None,
                "invalid_response", "api_failure")
        return result
    except (KeyError, TypeError) as exc:
        raise StateError("api_failure", "invalid_response") from exc


def identity(raw, app=False):
    raw = raw or {}
    numeric = raw.get("id")
    return {"kind": "app" if app else "account" if numeric else "unknown", "id": numeric,
            "slug": raw.get("slug") if app else None}


def check_record(raw, repository, kind, requested_sha, source):
    run = kind == "check_run"
    provider = identity(raw.get("app") if run else raw.get("creator"), run)
    status = raw.get("status") if run else ("in_progress" if raw.get("state") == "pending" else "completed" if raw.get("state") in ("success", "failure", "error") else "unknown")
    conclusion = raw.get("conclusion") if run else (None if raw.get("state") == "pending" else raw.get("state"))
    statuses = ("queued", "in_progress", "completed")
    conclusions = ("success", "failure", "error", "neutral", "skipped", "cancelled", "timed_out", "action_required", "stale", "startup_failure")
    head = raw.get("head_sha") if run else requested_sha
    if head is not None:
        sha(head)
    return {"key": f"{kind}:{repository}:{raw['id']}", "kind": kind, "repository": repository, "id": raw["id"],
            "name": raw["name"] if run else raw["context"], "source": provider,
            "status": status if status in statuses else "unknown", "conclusion": conclusion if conclusion is None or conclusion in conclusions else "unknown",
            "head_sha": head, "binding": {"method": ("payload_sha" if run else "exact_sha_endpoint") if head else "unavailable", "source_id": source},
            "url": safe_url(raw.get("html_url") if run else raw.get("target_url")),
            "created_at": raw.get("created_at"), "started_at": raw.get("started_at"),
            "completed_at": raw.get("completed_at"), "updated_at": raw.get("updated_at")}


def review_record(raw, repository, kind, source):
    actor = identity(raw.get("app") if kind == "check_output" else raw.get("user"), kind == "check_output")
    if (raw.get("user") or {}).get("type") == "Bot":
        actor["kind"] = "bot"
    associated = raw.get("head_sha") if kind == "check_output" else raw.get("commit_id") if kind in ("review", "inline_comment") else None
    if associated is not None:
        sha(associated)
    if kind == "check_output":
        output = raw.get("output") or {}
        content = digest([output.get(k) or "" for k in ("title", "summary", "text")])
    else:
        content = body_hash(raw.get("body"))
    state = raw.get("status") if kind == "check_output" else raw.get("state") if kind == "review" else None
    allowed = ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "PENDING", "DISMISSED", "queued", "in_progress", "completed")
    return {"key": f"{kind}:{repository}:{raw['id']}", "source_type": kind, "repository": repository, "id": raw["id"],
            "actor": actor, "associated_sha": associated, "binding": "payload_sha" if associated else "unavailable",
            "created_at": raw.get("created_at"), "submitted_at": raw.get("submitted_at"), "updated_at": raw.get("updated_at"),
            "state": state if state is None or state in allowed else "unknown", "content_sha256": content,
            "url": safe_url(raw.get("html_url")), "source_id": source}


def ref_endpoint(repository, branch):
    return f"repos/{repo(repository)}/git/ref/heads/{quote(branch, safe='')}"
