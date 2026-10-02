# Execution

Python 3.10+ is sufficient for packaging and tests; no packages are installed.
The capture mechanism is the explicitly configured existing browser tool, not this
helper. Check its documented capabilities/version and authorization before capture.
For a CLI mechanism, check availability without executing it:

```text
python skills/zeka-ui-evidence/scripts/ui_evidence.py preflight --executable configured-capture-tool
```

For a connector/in-app browser, check available capabilities through that tool's
own workflow instead. Missing tooling blocks capture; it does not justify automatic
installation. Do not pass credentials in URLs or commands. Do not use upstream
`--markdown`, upload helpers or upload flags: they may publish images.

## Capture and review

Use desktop 1440×900, mobile 375×812, tablet 768×1024, or explicit positive custom
dimensions. These are viewport presets, not device emulation. Record any material
device-pixel-ratio, touch, zoom, theme, fonts, readiness/wait criteria and browser
differences in caveats. Match settings and UI state across captures; explain differences.
Validate selectors and page readiness in the capture tool. Save page/component PNGs
only. Do not default to full-page capture. Document why it is necessary when used.
Existing images are supported; use null viewport if original viewport is unknown.

Establish that sources contain only synthetic/non-sensitive content before capture,
then inspect resulting images. Review the assertion separately from privacy. A safe
capture can still have an untested assertion. Failure to safely capture is blocked.
The helper checks declarations, obvious secret-like text and PNG headers, not pixel
content or full PNG decoding. Text scanning is a backstop, not a privacy guarantee.
Inspect images with an available image viewer before marking reviewed.

## Input and local package

Prepare task-local `input.json` beside reviewed PNGs in an ignored/private staging
directory. Image paths are portable paths relative to that directory; links,
absolute paths and traversal are rejected. Outputs are new directories and are never
overwritten. Use `.artifacts/` only after checking it is ignored in the target repository.
Only synthetic fixtures belong in source control. All source URLs/text must be safe to
retain; private URLs and image paths can be represented with opaque source identifiers.

Example input (replace example SHAs with independently verified revisions):

```json
{
  "repository": "example/frontend",
  "branch": "fix/card-overflow",
  "target_id": "mobile-card",
  "assertion": "The mobile card does not overflow at 375px.",
  "created_at": "2026-10-02T12:05:00Z",
  "before": null,
  "before_reason": "No explicit before source is available.",
  "after": {
    "source": "source:review-preview",
    "sha": null,
    "revision_source": null,
    "timestamp": "2026-10-02T12:00:00Z",
    "viewport": {"width": 375, "height": 812},
    "selector": ".beneficiary-card",
    "full_page": false,
    "capture_result": "captured",
    "image": "captured-after.png",
    "outcome": "untested",
    "observation": "Capture obtained; the overflow assertion has not been reviewed.",
    "reviewed": false,
    "tool": {"name": "configured-browser", "version": null}
  },
  "reviewer_ref": {"kind": "document", "locator": "review:ui-reviewer"},
  "safety": {
    "reviewed": true,
    "safe_before_capture": true,
    "method": "allowlisted_export",
    "review_ref": {"kind": "document", "locator": "review:safe-test-content"}
  },
  "environment": {"os": "Windows", "data": "synthetic"},
  "caveats": ["Deployment revision identity and browser version are unavailable."]
}
```

Each non-null side has the same fields. `sha` is a full lowercase 40-character SHA
or null. A known SHA requires a structured opaque `revision_source` reference to an
independently checked authority. Capture results are `captured`, `failed`, `blocked`;
assertion outcomes are `passed`, `failed`, `untested`, `blocked`. Failed/blocked captures
have null image and cannot pass/fail a behavioral assertion. Observations explain what
was seen or why evaluation was unavailable. Known pass/fail requires visual review.
Unknown revision requires a caveat, never a guessed SHA. Missing before requires a
concrete reason; an existing before uses null `before_reason`.

```text
python skills/zeka-ui-evidence/scripts/ui_evidence.py package --input .artifacts/ui-staging/input.json --output .artifacts/ui-pair
```

Output: available `before.png`/`after.png`, `metadata.json` with dimensions and SHA-256
hashes, and `report.md` with local Markdown image links. A visual diff may be generated
separately by an already configured safe tool; it is not a behavioral oracle. The
helper does not compute or export diffs. Failure can leave a partial output on I/O
errors; preserve it for diagnosis and retry to a new directory. Exit zero means
packaging succeeded, not that an assertion passed.

## Evidence-gate export

When `zeka-evidence-gate` is installed, read its evidence contract and export using
its configured skill directory:

```text
python skills/zeka-ui-evidence/scripts/ui_evidence.py export-gate .artifacts/ui-pair --gate skills/zeka-evidence-gate --output .artifacts/ui-gate-candidate
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify .artifacts/ui-gate-candidate --offline
python skills/zeka-evidence-gate/scripts/evidence_gate.py init --input .artifacts/ui-gate-candidate/manifest.json --output .artifacts/ui-gate --repo .
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify .artifacts/ui-gate --repo .
```

Export requires verified after revision identity. It creates a real-evidence candidate
with manual-observation provenance, structured UI results, reviewed PNGs, supporting
capture metadata and a deterministic gate report. The installed gate validates schema,
provenance, artifacts and hashes offline; live packaging/verification independently
checks Git identity, clean state and ignored output. Offline integrity is not current
revision evidence. Supply a trusted installed gate directory; its Python modules execute.

Before records require known, distinct SHAs. Otherwise use a null gate before ID and
explicit comparison limitation. An unbound before image remains in the original local
UI bundle; it is not exported with after provenance. Assertions that require proving
a change must remain untested when comparison evidence is unavailable. An independently
reviewed assertion about after behavior can pass with the comparison caveat.
The exporter covers one focused UI target; surrounding workflows inventory any other
required targets and levels. Tool settings, viewport and source metadata remain in a
supporting artifact, not unsupported gate schema fields. No gate schema is changed.

The script never uploads, edits PRs, captures browser content, fetches URLs, executes
input commands or authenticates a deployment. Safety and revision declarations are
producer assertions. Hashes do not authenticate their truth or detect sensitive pixels.

## Tests

```text
python -m unittest discover -s skills/zeka-ui-evidence/tests -v
```

Tests use generated synthetic PNGs and temporary directories. Gate compatibility
tests use the sibling gate when present; standalone packaging has no gate dependency.
