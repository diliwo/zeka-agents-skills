# Execution

Requires Python 3.10+, Git and an already authenticated GitHub CLI for live capture.
Verification/comparison are offline and use only Python's standard library.
No dependency installation or authentication mutation is performed.

Run paths relative to the installed skill folder:

```text
python scripts/pr_state.py capture --repository example/base --pr 7 --out .artifacts/pr-state/snapshot.json
python scripts/pr_state.py capture --repository example/base --pr 7 --workspace . --workspace-id checkout:task --remote origin --ancestor <full-sha> --out .artifacts/pr-state/local.json
python scripts/pr_state.py verify --snapshot snapshot.json --expectations expectations.json
python scripts/pr_state.py compare --previous previous.json --current current.json
python scripts/pr_state.py verify --snapshot current.json --expectations expectations.json --previous previous.json
```

Create output directories first. Existing outputs are never overwritten. Live output
inside a Git worktree must be untracked and ignored before capture. Symlink/junction
parent directories are rejected. Only synthetic fixture creation bypasses live
capture's ignored-output requirement.

`--repo` aliases `--repository`. Workspace capture requires `--workspace-id`, an
opaque public-safe identifier. It never persists the supplied path. Default remote is
origin. Ancestors can be repeated. Default capture includes check runs, legacy
statuses and review sources. `--skip-checks` and `--skip-reviews` mark those
collections not requested; review collection still reads check output when checks
are skipped. Live head ref collection remains enabled. Default maximum is 20 pages
per collection (100 records per page); `--max-pages` accepts 1–100. Individual
Git/gh calls time out after 60 seconds. No retries or indefinite polling occur.

JSON on stdout is authoritative. Capture also exclusively writes its snapshot file,
including a diagnostic snapshot when collection is unavailable or incoherent.
A failed process may therefore leave a useful immutable diagnostic file: use a new
path on the next capture. Preventive validation can fail before any file is written.
Compare returns zero when it successfully classifies changes; changes themselves
are not process failures. Verification returns zero only if all active assertions pass.

| Code | Meaning |
|---|---|
| 0 | Operation succeeded / requested assertions passed |
| 2 | Mismatch |
| 3 | Unavailable evidence |
| 4 | Unsupported environment |
| 5 | API failure |
| 6 | Stale or incoherent snapshot |
| 7 | Invalid input, schema or output path |

When multiple categories occur, precedence is 7, 5, 4, 6, 3, 2.
CLI syntax errors use argparse's code 2. Diagnostic JSON does not echo raw stderr,
unsupported remote values, API bodies or private paths.

## Synthetic demonstration

```text
python scripts/pr_state.py verify --snapshot tests/fixtures/fork-snapshot.json --expectations tests/fixtures/expectations.json
python scripts/pr_state.py compare --previous tests/fixtures/fork-snapshot.json --current tests/fixtures/fork-snapshot.json
python -m unittest discover -s tests -v
```

The fixture is a synthetic fork capture with passing explicit expectations.
The output must retain `proof_scope: synthetic`; it proves verifier behavior only.
Never relabel synthetic source records to pass a live consumer.

## Python entry points

`pr_state.capture(...)` supports injected transport/clock for offline tests.
`validation.validate`, `verify`, `compare`, `load`, `write_new`, and `exit_code`
provide the contract operations. `git_state.capture(workspace, workspace_id, remote,
head_branch)` returns local facts without requiring GitHub/PR capture.
`git_state.ancestry(workspace, ancestor, descendant)` queries the graph.

Scripts are self-contained within this skill. Future consumers should use a
versioned adapter/subprocess boundary or deliberate isolated imports: other skills
also contain modules called validation and must not share accidental Python module
resolution. The new GitHub helper is named github_state to reduce that risk.
