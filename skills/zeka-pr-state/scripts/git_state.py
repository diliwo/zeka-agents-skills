"""Read-only local Git observations; never fetch or repair a checkout."""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from validation import StateError, now, repo, require, sha


def command(workspace, *args, accepted=(0,)):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        result = subprocess.run(["git", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
                                 "-C", str(workspace), *args], capture_output=True, timeout=60, env=env)
    except FileNotFoundError as exc:
        raise StateError("unsupported_environment", "command_missing") from exc
    except subprocess.TimeoutExpired as exc:
        raise StateError("unavailable", "timeout") from exc
    except OSError as exc:
        raise StateError("unavailable", "command_failed") from exc
    require(result.returncode in accepted, "command_failed", "unavailable")
    return result.returncode, result.stdout


def read(workspace, *args):
    return command(workspace, *args)[1].decode("utf-8").strip()


def normalize_remote(value):
    # Recognize only standard GitHub forms, before exposing any value.
    patterns = (r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?",
                r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?",
                r"ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?/?")
    for pattern in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            try:
                return repo(match[1])
            except StateError:
                break
    credential = bool(re.match(r"https?://[^/]*@", value) or re.match(r"ssh://[^/]*:[^/]*@", value))
    raise StateError("unsupported_environment", "credential_remote" if credential else "unsupported_remote")


def worktree(raw):
    entries = raw.split(b"\0")
    flags = {k: False for k in ("staged", "unstaged", "untracked", "unmerged")}
    inventory, position = [], 0
    while position < len(entries):
        entry = entries[position]
        position += 1
        if not entry:
            continue
        require(len(entry) >= 4 and entry[2:3] == b" ", "invalid_response")
        code = entry[:2]
        if code == b"??":
            flags["untracked"] = True
        else:
            flags["staged"] |= code[:1] != b" "
            flags["unstaged"] |= code[1:2] != b" "
            flags["unmerged"] |= code in (b"DD", b"AU", b"UD", b"UA", b"DU", b"AA", b"UU")
        if b"R" in code or b"C" in code:
            require(position < len(entries) and bool(entries[position]), "invalid_response")
            entry += b"\0" + entries[position]
            position += 1
        inventory.append(entry)
    return {"clean": not any(flags.values()), **flags,
            "status_fingerprint": hashlib.sha256(b"\0".join(sorted(inventory))).hexdigest()}


def capture(workspace, workspace_id, remote, head_branch, clock=now):
    require(re.fullmatch(r"[A-Za-z0-9_:.-]+", workspace_id or ""), "invalid_workspace_id")
    require(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", remote), "invalid_remote_name")
    root = read(workspace, "rev-parse", "--show-toplevel")
    head = sha(read(root, "rev-parse", "--verify", "HEAD"))
    code, branch_raw = command(root, "symbolic-ref", "--quiet", "--short", "HEAD", accepted=(0, 1))
    branch = branch_raw.decode("utf-8").strip() if code == 0 else None
    flags = worktree(command(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none")[1])
    remote_data = {"name": remote, "repository": None, "identity_status": "available", "reason_code": None}
    try:
        remote_data["repository"] = normalize_remote(read(root, "remote", "get-url", remote))
    except StateError as exc:
        remote_data.update(identity_status=exc.category, reason_code=exc.reason)
    tracking = {"ref": None, "sha": None, "availability": "unavailable"}
    if head_branch:
        command(root, "check-ref-format", "refs/heads/" + head_branch)
        mapping_code, mapping = command(root, "config", "--get-all", "remote." + remote + ".fetch", accepted=(0, 1))
        standard = "+refs/heads/*:refs/remotes/" + remote + "/*"
        if mapping_code == 0 and mapping.decode().strip() == standard:
            tracking["ref"] = "refs/remotes/" + remote + "/" + head_branch
            code, value = command(root, "rev-parse", "--verify", "--quiet", tracking["ref"], accepted=(0, 1))
            if code == 0:
                tracking.update(sha=sha(value.decode().strip()), availability="available")
    return {"workspace_id": workspace_id, "branch": branch, "detached": branch is None, "head_sha": head,
            "remote": remote_data, "remote_tracking": tracking, "worktree": flags,
            "shallow": read(root, "rev-parse", "--is-shallow-repository") == "true", "observed_at": clock()}


def ancestry(workspace, ancestor, descendant):
    sha(ancestor)
    sha(descendant)
    if workspace is None:
        raise StateError("unavailable", "workspace_unavailable")
    # Grafts alter graph semantics even when replacement objects are disabled.
    grafts = read(workspace, "rev-parse", "--git-path", "info/grafts")
    grafts = Path(grafts) if Path(grafts).is_absolute() else Path(workspace) / grafts
    require(not grafts.exists(), "graph_query_failed", "unavailable")
    for commit in (ancestor, descendant):
        code, _ = command(workspace, "cat-file", "-e", commit + "^{commit}", accepted=(0, 1, 128))
        require(code == 0, "missing_object", "unavailable")
    code, _ = command(workspace, "merge-base", "--is-ancestor", ancestor, descendant, accepted=(0, 1))
    if code == 1 and read(workspace, "rev-parse", "--is-shallow-repository") == "true":
        raise StateError("unavailable", "shallow_history")
    _, bases = command(workspace, "merge-base", "--all", ancestor, descendant, accepted=(0, 1))
    return code == 0, sorted(sha(line) for line in bases.decode().splitlines())
