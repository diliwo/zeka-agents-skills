"""Prevent unsafe bundle paths and reject recognizable sensitive material."""

import json
import re
from pathlib import Path, PurePosixPath


class Invalid(ValueError):
    """Evidence cannot safely be accepted."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


# These are rejection heuristics, not a DLP guarantee. Do not echo matched values.
SECRET_PATTERNS = (
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----",
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
    r"\bAKIA[A-Z0-9]{16}\b",
    r"\bBearer\s+[A-Za-z0-9._~+/=-]+",
    r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    r"[a-z][a-z0-9+.-]*://[^\s/:\"<>]+:[^\s/@\"<>]+@",
    r"\b(?:password|passwd|pwd|access_token|api[_-]?key|client_secret|connection_string)"
    r"[\s\"']*[:=][\s\"']*[^\s\"',;}]+",
    r"\bop://",
)


def scan_text(value):
    require(not any(re.search(p, value, re.IGNORECASE) for p in SECRET_PATTERNS),
            "possible sensitive material; sanitize at the source before retrying")


def scan_value(value):
    scan_text(json.dumps(value, ensure_ascii=False, allow_nan=False))


def safe_path(root, relative):
    require(isinstance(relative, str) and relative, "artifact path required")
    require("\\" not in relative and ":" not in relative and "\x00" not in relative,
            "artifact path must be a portable relative path")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in relative.split("/")),
            "artifact path escapes bundle or is not canonical")
    root = Path(root).resolve()
    target = root.joinpath(*path.parts)
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink() and not getattr(current, "is_junction", lambda: False)(),
                "artifact links are not supported")
    require(target.resolve().is_relative_to(root), "artifact path escapes bundle")
    return target


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_):
        raise Invalid("non-finite JSON number")

    try:
        scan_text(raw)
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        scan_value(value)
        return value
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Invalid("invalid UTF-8 JSON") from exc


def read_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8-sig"))


def json_equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
