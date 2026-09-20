"""Standalone read-only capture, deterministic verification and comparison."""
import argparse
import sys
import uuid
from pathlib import Path

import git_state
from github_state import API_VERSION, GitHub, check_record, pr_identity, ref_endpoint, review_record
from validation import (StateError, canonical, digest, envelope, exit_code, load, now,
                        repo, require, sha, validate, verify, compare, without_observed_at, write_new)


def capture(repository, number, *, api=None, workspace=None, workspace_id=None,
            remote="origin", ancestors=(), checks=True, reviews=True, clock=now):
    repository = repo(repository)
    require(type(number) is int and number > 0, "invalid_pr_number")
    require(workspace is None or workspace_id is not None, "workspace_id_required")
    ancestors = sorted({sha(a) for a in ancestors})
    api = api or GitHub()
    started = clock()
    sources, boundary = [], []

    def observe(operation, fn, *, endpoint=None, revision=None, ref=None, local=False):
        sid = f"S-{len(sources) + 1:03d}"
        metadata = {"repository": repository, "pr_number": number, "sha": revision, "ref": ref,
                    "endpoint": endpoint, "workspace_id": workspace_id if local else None,
                    "api_version": None if local else API_VERSION, "pages": 0,
                    "complete": False, "fingerprint": None}
        source = {"id": sid, "kind": "git_command" if local else "github_rest",
                  "operation": operation, "status": "available", "reason_code": None,
                  "observed_at": clock(), "metadata": metadata}
        sources.append(source)
        try:
            data, pages = fn(sid)
            metadata.update(pages=pages, complete=True)
            if operation in ("pr", "workspace"):
                metadata["fingerprint"] = digest(without_observed_at(data))
            result = envelope(data, sources=[sid])
        except (StateError, KeyError, TypeError, ValueError) as exc:
            category = exc.category if isinstance(exc, StateError) else "api_failure"
            reason = exc.reason if isinstance(exc, StateError) else "invalid_response"
            if category == "invalid_input":
                category, reason = "api_failure" if not local else "unavailable", "invalid_response"
            source.update(status=category, reason_code=reason)
            result = envelope(status=category, reason=reason, sources=[sid])
        source["observed_at"] = clock()
        return result

    endpoint = f"repos/{repository}/pulls/{number}"
    raw_pr = {}
    def read_pr(_):
        raw = api.get(endpoint)
        normalized = pr_identity(raw, repository, number)
        raw_pr.clear()
        raw_pr.update(raw)
        return normalized, 1
    pr = observe("pr", read_pr, endpoint=endpoint)
    boundary.extend(pr["source_ids"])
    initial_raw = dict(raw_pr)
    head = pr["data"]["head"] if pr["data"] else None
    def local_read(_):
        return git_state.capture(workspace, workspace_id, remote, head["branch"] if head else None, clock), 0
    local = observe("workspace", local_read, local=True) if workspace else envelope(status="not_requested", reason="not_requested")
    boundary.extend(local["source_ids"])
    live = envelope(status="unavailable", reason="unknown_head_repository")
    if head and head["repository"]:
        ep = ref_endpoint(head["repository"], head["branch"])
        def read_ref(_):
            raw = api.get(ep)
            require(raw["ref"] == "refs/heads/" + head["branch"] and raw["object"]["type"] == "commit",
                    "invalid_response", "api_failure")
            return {"repository": head["repository"], "branch": head["branch"], "ref": raw["ref"],
                    "sha": sha(raw["object"]["sha"]), "observed_at": clock()}, 1
        live = observe("remote_ref", read_ref, endpoint=ep, ref="refs/heads/" + head["branch"])
        sources[-1]["metadata"]["repository"] = head["repository"]

    check_obs = envelope(status="not_requested", reason="not_requested")
    review_obs = envelope(status="not_requested", reason="not_requested")
    check_parts, review_parts = [], []
    if checks or reviews:
        if head:
            revision = head["sha"]
            ep = f"repos/{repository}/commits/{revision}/check-runs?filter=all"
            def read_runs(sid):
                raw, pages = api.collect(ep, "check_runs")
                normalized = [check_record(r, repository, "check_run", revision, sid) for r in raw]
                if reviews:
                    review_parts.append(envelope([review_record(r, repository, "check_output", sid) for r in raw], sources=[sid]))
                return normalized, pages
            runs = observe("check_runs", read_runs, endpoint=ep, revision=revision)
            check_parts.append(runs)
            if reviews and runs["availability"] != "available":
                review_parts.append(runs)
            if checks:
                ep = f"repos/{repository}/commits/{revision}/statuses"
                def read_statuses(sid):
                    raw, pages = api.collect(ep)
                    return [check_record(r, repository, "commit_status", revision, sid) for r in raw], pages
                check_parts.append(observe("commit_statuses", read_statuses, endpoint=ep, revision=revision))
        else:
            check_parts.append(envelope(status="unavailable", reason="boundary_unavailable"))
            review_parts.append(envelope(status="unavailable", reason="boundary_unavailable"))
    def combine(parts):
        ids = [sid for part in parts for sid in part["source_ids"]]
        failures = [p for p in parts if p["availability"] != "available"]
        if failures:
            worst = max(failures, key=lambda p: exit_code([p["availability"]]))
            return envelope(status=worst["availability"], reason=worst["reason_code"], sources=ids)
        return envelope(sorted([item for p in parts for item in p["data"]], key=lambda i: i["key"]), sources=ids)
    if checks:
        check_obs = combine(check_parts)
    if reviews:
        if pr["data"]:
            review_parts.append(envelope([review_record(initial_raw, repository, "pr_body", pr["source_ids"][0])],
                                         sources=pr["source_ids"]))
        for operation, suffix, kind in (("issue_comments", f"issues/{number}/comments", "issue_comment"),
                                        ("inline_comments", f"pulls/{number}/comments", "inline_comment"),
                                        ("reviews", f"pulls/{number}/reviews", "review")):
            ep = f"repos/{repository}/{suffix}"
            def read_reviews(sid):
                raw, pages = api.collect(ep)
                return [review_record(r, repository, kind, sid) for r in raw], pages
            review_parts.append(observe(operation, read_reviews, endpoint=ep))
        review_obs = combine(review_parts)
    graph = []
    for ancestor in ancestors:
        if not head:
            continue
        def read_graph(_):
            answer, bases = git_state.ancestry(workspace, ancestor, head["sha"])
            return {"answer": answer, "bases": bases}, 0
        obs = observe("ancestry", read_graph, revision=head["sha"], ref=ancestor, local=True)
        graph.append({"ancestor_sha": ancestor, "descendant_sha": head["sha"], "method": "git_merge_base",
                      "availability": obs["availability"], "source_id": obs["source_ids"][0],
                      "is_ancestor": obs["data"]["answer"] if obs["data"] else None,
                      "merge_bases": obs["data"]["bases"] if obs["data"] else [], "reason_code": obs["reason_code"]})
    final_pr = observe("pr", read_pr, endpoint=endpoint)
    boundary.extend(final_pr["source_ids"])
    final_local = observe("workspace", local_read, local=True) if workspace else None
    if final_local:
        boundary.extend(final_local["source_ids"])
    boundary_sources = [s for s in sources if s["id"] in boundary]
    coherent = "stable"
    if any(s["status"] != "available" for s in boundary_sources):
        coherent = "unknown"
    elif pr["data"] != final_pr["data"] or (workspace and
            without_observed_at(local["data"]) != without_observed_at(final_local["data"])):
        coherent = "changed"
    merge = envelope(status="unavailable", reason="boundary_unavailable")
    if final_pr["data"]:
        state = raw_pr.get("mergeable_state")
        merge = envelope({"mergeable": raw_pr.get("mergeable"),
                          "state": state if state in ("clean", "dirty", "blocked", "behind", "unstable", "draft") else "unknown",
                          "observed_at": clock()}, sources=final_pr["source_ids"])
    result = {"schema_version": 1, "capture_id": str(uuid.uuid4()), "started_at": started, "captured_at": clock(),
              "capture_mode": "github_workspace" if workspace else "github", "repository": repository, "pr_number": number,
              "consistency": {"status": coherent, "boundary_source_ids": boundary,
                              "reason_codes": [] if coherent == "stable" else ["capture_changed" if coherent == "changed" else "boundary_unavailable"]},
              "pr": pr, "workspace": local, "remote_branch": live, "checks": check_obs, "review_sources": review_obs,
              "mergeability": merge, "required_check_contract": envelope(status="not_requested", reason="not_requested"),
              "ancestry": graph, "sources": sources,
              "limitations": ["Bounded observations are not an atomic GitHub transaction.",
                              "Required-check policy is not collected in v1.",
                              "Hashes establish content consistency, not authenticity.",
                              "Worktree fingerprint hashes status inventory, not file contents.",
                              "Review bodies and provider semantics remain consumer responsibilities."]}
    validate(result, "snapshot")
    return result


def capture_exit(snapshot):
    categories = [s["status"] for s in snapshot["sources"] if s["status"] != "available"]
    if snapshot["consistency"]["status"] != "stable":
        categories.append("stale_snapshot")
    if snapshot["remote_branch"]["availability"] != "available":
        categories.append(snapshot["remote_branch"]["availability"])
    local = snapshot["workspace"]["data"]
    if local and local["remote"]["identity_status"] != "available":
        categories.append(local["remote"]["identity_status"])
    return exit_code(categories)


def output_path(path):
    """Keep live captures out of tracked or accidentally publishable Git paths."""
    path = Path(path).absolute()
    require(path.parent.is_dir(), "output_parent_missing")
    require(not path.exists() and not path.is_symlink(), "output_exists")
    for parent in (path.parent, *path.parent.parents):
        require(not parent.is_symlink() and not getattr(parent, "is_junction", lambda: False)(), "output_link")
    code, raw = git_state.command(path.parent, "rev-parse", "--show-toplevel", accepted=(0, 128))
    if code == 0:
        root = Path(raw.decode("utf-8").strip()).resolve()
        relative = path.relative_to(root).as_posix()
        tracked = git_state.read(root, "ls-files", "--", relative)
        require(not tracked, "runtime_output_tracked")
        ignored, _ = git_state.command(root, "check-ignore", "-q", "--", relative, accepted=(0, 1))
        require(ignored == 0, "runtime_output_must_be_ignored")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--repository", "--repo", dest="repo", required=True)
    cap.add_argument("--pr", type=int, required=True)
    cap.add_argument("--workspace")
    cap.add_argument("--workspace-id")
    cap.add_argument("--remote", default="origin")
    cap.add_argument("--ancestor", action="append", default=[])
    cap.add_argument("--max-pages", type=int, default=20)
    cap.add_argument("--skip-checks", action="store_true")
    cap.add_argument("--skip-reviews", action="store_true")
    cap.add_argument("--out", required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--snapshot", required=True)
    ver.add_argument("--expectations", required=True)
    ver.add_argument("--previous")
    diff = sub.add_parser("compare")
    diff.add_argument("--previous", required=True)
    diff.add_argument("--current", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            destination = output_path(args.out)
            result = capture(args.repo, args.pr, api=GitHub(args.max_pages), workspace=args.workspace,
                             workspace_id=args.workspace_id, remote=args.remote, ancestors=args.ancestor,
                             checks=not args.skip_checks, reviews=not args.skip_reviews)
            write_new(destination, result)
            code = capture_exit(result)
        elif args.command == "verify":
            result = verify(load(args.snapshot), load(args.expectations), load(args.previous) if args.previous else None)
            code = exit_code(result["failure_categories"])
        else:
            result = compare(load(args.previous), load(args.current))
            code = 0
        print(canonical(result))
        return code
    except (StateError, OSError, UnicodeError) as exc:
        category = exc.category if isinstance(exc, StateError) else "invalid_input"
        reason = exc.reason if isinstance(exc, StateError) else "file_access_failed"
        print(canonical({"overall": "failed", "failure_categories": [category], "reason_code": reason}))
        return exit_code([category])


if __name__ == "__main__":
    sys.exit(main())
