"""Validate, package and report sanitized evidence. Never execute manifest commands."""

import argparse
import json
from pathlib import Path
import sys

from reporting import export_review_loop, render
from safety import Invalid, read_json, require, safe_path, scan_text, scan_value
from validation import artifact_bytes, check_commit_safety, check_repository, validate_manifest, verify


def write_new(path, value):
    if not isinstance(value, str):
        scan_value(value)
        value = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    scan_text(value)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def initialize(candidate, output, repo=None):
    """Package pre-sanitized evidence without mutating or copying raw source logs."""
    candidate, output = Path(candidate), Path(output)
    require(not output.exists(), "output bundle already exists; preserve prior evidence")
    manifest = read_json(candidate)
    validate_manifest(manifest)
    blobs = artifact_bytes(manifest, candidate.parent)
    require(repo is not None, "repository required for commit-safety checks")
    check_commit_safety(output, repo)
    require(not manifest["synthetic"], "synthetic fixtures are for offline verification only")
    check_repository(manifest, output, repo)
    report = render(manifest)  # Validate all generated text before opening output files.
    output.mkdir(parents=True)
    for relative, data in blobs.items():
        path = safe_path(output, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    write_new(output / "manifest.json", manifest)
    write_new(output / "report.md", report)
    # Detect source movement during packaging. Retain any incomplete bundle for audit.
    verify(output, repo)
    return {"created": True, "artifact_count": len(blobs)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="package an already sanitized candidate bundle")
    init.add_argument("--input", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--repo", required=True)
    for name in ("verify", "report", "export-review-loop"):
        command = commands.add_parser(name)
        command.add_argument("bundle")
        command.add_argument("--repo")
        if name != "export-review-loop":
            command.add_argument("--offline", action="store_true", help="integrity only; no freshness or Git safety claim")
        if name == "verify":
            command.add_argument("--require-complete", action="store_true")
        if name == "report":
            command.add_argument("--output", help="new file; defaults to stdout")
        if name == "export-review-loop":
            command.add_argument("--pr", required=True, type=int)
            command.add_argument("--reference", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.input, args.output, args.repo)
        else:
            manifest, summary = verify(args.bundle, args.repo, getattr(args, "offline", False))
            if args.command == "verify":
                result = summary
                if args.require_complete and (not summary["complete"] or not summary["usable_as_current_evidence"]):
                    print(json.dumps(result, sort_keys=True))
                    return 2
            elif args.command == "report":
                report = render(manifest, summary)
                if args.output:
                    require(args.repo is not None, "repository required for output commit-safety check")
                    check_commit_safety(Path(args.output).parent, args.repo)
                    write_new(args.output, report)
                    result = {"written": True}
                else:
                    print(report, end="")
                    return 0
            else:
                result = export_review_loop(manifest, summary, args.pr, args.reference)
        scan_value(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        # Do not expose filesystem paths, input values, process output or credentials.
        message = str(exc) if isinstance(exc, Invalid) else "input or output could not be processed"
        print(json.dumps({"valid": False, "error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
