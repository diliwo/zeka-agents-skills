"""GitHub transport via an already authenticated gh; mutations are explicit."""

import json
import re
import subprocess

from common import Stop, now, require, sha
from freshness import baseline, size_limited


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop("required command unavailable or timed out: " + args[0]) from exc
    # Do not echo stderr: it can contain credentials or private host details.
    require(result.returncode == 0, "command failed: " + args[0] + "; inspect locally")
    return result.stdout.strip()


def api(endpoint, pages=False, body=None):
    args = ["gh", "api", endpoint]
    if pages:
        args += ["--paginate", "--slurp"]
    if body is not None:
        args += ["--method", "POST", "--raw-field", "body=" + body]
    return json.loads(command(args))


def identity(raw, cfg):
    require(raw["state"] == "open", "PR must be open")
    require(raw["number"] == cfg["pr"], "wrong PR number")
    require(raw["base"]["repo"]["full_name"].lower() == cfg["repository"].lower(),
            "wrong base repository")
    require(raw["head"].get("repo"), "PR head repository unavailable")
    return {"repository": cfg["repository"], "pr": cfg["pr"],
            "branch": raw["head"]["ref"], "head_sha": sha(raw["head"]["sha"]),
            "base_sha": sha(raw["base"]["sha"]),
            "head_repository": raw["head"]["repo"]["full_name"]}


def local_state(expected, cfg):
    require(command(["git", "status", "--porcelain"]) == "", "worktree is dirty")
    branch = command(["git", "branch", "--show-current"])
    require(branch == expected["branch"], "local branch differs from PR branch")
    require(command(["git", "rev-parse", "HEAD"]) == expected["head_sha"],
            "local HEAD differs from PR head")
    remote = command(["git", "remote", "get-url", cfg["remote"]])
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?", remote)
    require(match and match[1].lower() == expected["head_repository"].lower(),
            "configured remote does not match PR head repository")
    return {"branch": branch, "head_sha": expected["head_sha"], "clean": True,
            "verified_at": now()}


def capture(cfg):
    root = f"repos/{cfg['repository']}"
    endpoint = f"{root}/pulls/{cfg['pr']}"
    raw = api(endpoint)
    state = identity(raw, cfg)
    local = local_state(state, cfg)
    result = {"schema_version": 1, **state, "worktree": local,
              "pr_body": raw.get("body") or "", "checks_available": True}
    for key, path in (("comments", f"{root}/issues/{cfg['pr']}/comments"),
                      ("inline", endpoint + "/comments"),
                      ("reviews", endpoint + "/reviews")):
        result[key] = [item for page in api(path + "?per_page=100", pages=True) for item in page]
    try:
        pages = api(f"{root}/commits/{state['head_sha']}/check-runs?per_page=100&filter=all", pages=True)
        result["checks"] = [item for page in pages for item in page["check_runs"]]
    except Stop:
        require(cfg["allow_unavailable_checks"], "check-run collection failed")
        result.update(checks=[], checks_available=False)
    require(identity(api(endpoint), cfg) == state, "PR moved during collection")
    local_state(state, cfg)
    result["collected_at"] = now()
    return result


def trigger(cfg, snapshot, mode):
    state = identity(api(f"repos/{cfg['repository']}/pulls/{cfg['pr']}"), cfg)
    require(all(snapshot[k] == v for k, v in state.items()), "PR moved before trigger")
    local_state(state, cfg)
    require(mode in ("normal", "apps"), "unsupported trigger mode")
    if mode == "apps":
        require(size_limited(snapshot, cfg), "Apps fallback requires recorded size-limit evidence")
    body = cfg["apps_trigger" if mode == "apps" else "normal_trigger"]
    require(isinstance(body, str) and body.strip(), "review trigger not configured")
    response = api(f"repos/{cfg['repository']}/issues/{cfg['pr']}/comments", body=body)
    # Use the server timestamp, avoiding client clock skew for the freshness boundary.
    return {"schema_version": 1, **state, "mode": mode,
            "requested_at": response["created_at"], "trigger_url": response["html_url"],
            "trigger_id": response["id"], "baseline": baseline(snapshot, cfg)}
