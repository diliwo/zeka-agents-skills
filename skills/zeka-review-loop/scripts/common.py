"""Shared validation and artifact I/O; no third-party dependencies."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path


class Stop(ValueError):
    """A closed gate, not permission to continue with partial evidence."""


def require(condition, message):
    if not condition:
        raise Stop(message)


def timestamp(value):
    require(isinstance(value, str), "missing timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Stop("invalid timestamp") from exc
    require(result.tzinfo is not None, "timestamp requires timezone")
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
            "expected full lowercase GitHub commit SHA")
    return value


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    # Exclusive creation preserves each iteration's audit artifacts.
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def config(data):
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", data["repository"]),
            "repository must be owner/name")
    require(type(data["pr"]) is int and data["pr"] > 0, "invalid PR number")
    for key in ("bot_logins", "check_app_slugs"):
        require(isinstance(data[key], list) and data[key]
                and all(isinstance(v, str) and v for v in data[key]), key + " required")
    for key in ("scope_ref", "architecture_source"):
        require(isinstance(data[key], str) and data[key].strip(), key + " required")
    require(data["actor"] in ("Codex", "Hephaestus"), "invalid correction owner")
    result = {"max_iterations": 3, "timeout_seconds": 600, "poll_seconds": 10,
              "normal_trigger": "@greptile review", "apps_trigger": None,
              "remote": "origin", "allow_unavailable_checks": False, **data}
    for key in ("max_iterations", "timeout_seconds", "poll_seconds"):
        require(type(result[key]) is int and result[key] > 0, key + " must be positive")
    require(result["poll_seconds"] <= 60, "poll interval must be at most 60 seconds")
    require(type(result["allow_unavailable_checks"]) is bool, "invalid check availability policy")
    return result
