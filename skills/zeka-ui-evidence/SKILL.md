---
name: zeka-ui-evidence
description: Produce local, revision-aware visual before/after evidence for Angular UI changes, visual regressions, responsive layouts, component redesigns and visual accessibility states. Use for screenshot evidence in reviews; backend behavior requires tests or structured probes.
---

# Zeka UI evidence

Demonstrate a stated behavior, such as “The mobile beneficiary card no longer
overflows at 375px.” Screenshot creation alone does not prove the assertion.

Read [execution.md](references/execution.md) for capture configuration, input format,
packaging and optional `zeka-evidence-gate` integration.

1. Identify the repository, assertion, target and explicit before/after sources.
   Accept supplied production/staging/local URLs, previous deployments or images.
   Never invent before state or switch branches, stash, or manipulate a worktree
   to manufacture it. If before is unavailable, state the comparison limitation.
2. Verify the configured capture tool and its viewport/selector capabilities before
   capture. Use existing installed tooling or the available browser skill; read that
   skill before using its browser. Do not globally install dependencies without
   authorization. The Python helper packages captures; it does not drive a browser.
3. Establish safe content before capture. Prefer controlled synthetic/test data.
   Refuse capture exposing beneficiary personal information, credentials, tokens,
   private administrative data, password managers, unrelated windows or notifications.
   Capture the page/component only. Do not capture sensitive data then redact it.
4. Use matched desktop, mobile, tablet or custom viewports and relevant device settings.
   Capture selectors when requested. Full-page capture requires a request or a stated
   necessity. Record viewport separately from image dimensions; an existing image
   does not establish an unknown original viewport. Record tool/version, timestamp,
   source, selector, capture result and observed assertion outcome for each side.
5. Verify each source SHA independently through its authoritative build/revision
   source. Local HEAD does not identify a deployment; dirty code is not clean HEAD.
   Unknown SHAs stay null with a caveat. Never infer revision identity from a filename.
6. Review safe artifacts and observed behavior, then package locally in a new ignored
   runtime directory. Keep unreviewed assertions untested. Preserve failed/blocked
   captures and missing comparisons honestly; do not claim accessibility compliance
   or backend correctness from screenshots.

Keep evidence local. Publication requires an explicitly approved trusted destination;
never automatically upload to public hosts. Generate Markdown for PR inclusion;
invocation does not authorize PR edits, commits, pushes, merging or external posting.

Public skill files and fixtures must contain no secrets, personal/beneficiary data,
private infrastructure identifiers, internal hostnames, private paths or non-public
configuration. Resolve environment-specific sources through task-local configuration.
Use opaque references for authoritative architecture/decision sources; do not copy
private architecture documents. Runtime URLs must be reviewed safe to retain; use an
opaque `source:` identifier when a URL itself contains private information.

Gate exports use the installed gate's existing `ui` class and validators. They do not
replace regression/protected CI obligations or establish merge readiness. Metadata,
hashes and review declarations are not independent authentication or PII detection.

Reference design: [michaelshimeles/skills before-and-after](https://github.com/michaelshimeles/skills/tree/main/before-and-after).
This implementation is original; no upstream code or substantial text is copied.
