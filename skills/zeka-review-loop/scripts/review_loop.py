#!/usr/bin/env python3
"""CLI for a governed, agent-coordinated review loop. See references/execution.md."""

import argparse
import json
import sys
import time
from pathlib import Path

from common import Stop, config, read, require, timestamp, now, write
from findings import inventory
from freshness import freshness, size_limited
from github import capture, trigger
from report import build


def poll(cfg, ticket):
    # Deadline survives command restarts; polling cannot grant a fresh timeout.
    remaining = cfg["timeout_seconds"] - (timestamp(now()) - timestamp(ticket["requested_at"])).total_seconds()
    require(remaining > 0, "external_review_timeout")
    deadline = time.monotonic() + remaining
    while time.monotonic() < deadline:
        snapshot = capture(cfg)
        status = freshness(snapshot, ticket, cfg)
        if time.monotonic() >= deadline:
            break
        if status["fresh"]:
            return {"status": "fresh", "freshness": status, "snapshot": snapshot}
        if ticket["mode"] == "normal" and size_limited(snapshot, cfg):
            return {"status": "size_limit_requires_apps", "freshness": status, "snapshot": snapshot}
        print("Waiting for SHA-bound review evidence...", file=sys.stderr, flush=True)
        time.sleep(min(cfg["poll_seconds"], max(0, deadline - time.monotonic())))
    raise Stop("external_review_timeout")


def iteration(snapshot, ticket, cfg, previous=None):
    return {"snapshot": snapshot, "ticket": ticket,
            "coverage": [{"source_key": item["source_key"], "finding_ids": [], "rationale": ""}
                         for item in inventory(snapshot, cfg)],
            "findings": previous or [], "corrections": [],
            "evidence": {"repository": cfg["repository"], "pr": cfg["pr"],
                         "head_sha": snapshot["head_sha"],
                         **{key: {"status": "missing"} for key in ("focused", "regression", "protected_ci")}}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "trigger", "poll", "inventory", "prepare"):
        part = sub.add_parser(name)
        part.add_argument("--config", required=True)
        part.add_argument("--out", required=True)
        if name in ("trigger", "inventory", "prepare"):
            part.add_argument("--snapshot", required=True)
        if name in ("poll", "prepare"):
            part.add_argument("--ticket", required=True)
        if name == "trigger":
            part.add_argument("--mode", choices=("normal", "apps"), default="normal")
            part.add_argument("--send", action="store_true", help="explicitly post the configured review request")
    part = sub.add_parser("append")
    for flag in ("run", "snapshot", "ticket", "out"):
        part.add_argument("--" + flag, required=True)
    part = sub.add_parser("report")
    part.add_argument("--run", required=True)
    part.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        require(not Path(args.out).exists(), "artifact already exists")
        require(Path(args.out).parent.is_dir(), "artifact directory does not exist")
        if args.command in ("report", "append"):
            run = read(args.run)
            if args.command == "report":
                result = build(run)
            else:
                cfg = config(run["config"])
                require(len(run["iterations"]) < cfg["max_iterations"], "iteration_cap")
                run["iterations"].append(iteration(read(args.snapshot), read(args.ticket), cfg,
                                                   run["iterations"][-1]["findings"]))
                result = run
        else:
            cfg = config(read(args.config))
            if args.command == "capture":
                result = capture(cfg)
            elif args.command == "trigger":
                require(args.send, "trigger requires --send and session authorization")
                result = trigger(cfg, read(args.snapshot), args.mode)
            elif args.command == "poll":
                result = poll(cfg, read(args.ticket))
            elif args.command == "inventory":
                result = inventory(read(args.snapshot), cfg)
            else:
                result = {"schema_version": 1, "config": cfg, "stop_reason": None,
                          "iterations": [iteration(read(args.snapshot), read(args.ticket), cfg)]}
        write(args.out, result)
        if args.command == "report":
            return 0 if result["READY_FOR_CHIEF_REVIEW"] else 2
        if args.command == "poll" and result["status"] != "fresh":
            return 2
        return 0
    except (Stop, KeyError, IndexError, AttributeError, TypeError, ValueError, OSError) as exc:
        # Malformed inputs and transport errors are never treated as empty findings.
        failure = {"schema_version": 1, "READY_FOR_CHIEF_REVIEW": False,
                   "stop_reason": "invalid_input_or_collection_failure", "error_type": type(exc).__name__}
        if isinstance(exc, Stop):
            failure["detail"] = str(exc)
        print(json.dumps(failure), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
