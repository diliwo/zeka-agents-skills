# Conceptual references

Consulted on 2026-09-18:

- [michaelshimeles/skills — greploop](https://github.com/michaelshimeles/skills/tree/main/greploop)
- [michaelshimeles/skills — greploop-apps](https://github.com/michaelshimeles/skills/tree/main/greploop-apps)

Retained concepts: bounded review/correction cycles, multiple review surfaces, edited
summaries, and an installation-dependent Apps fallback for size-limited reviews.

This implementation and workflow text are original; no upstream code or substantial
text was copied. Both referenced skills include MIT license files. Preserve applicable
copyright and licensing notices if future work reuses code or substantial material.
This note does not relicense upstream work.

Zeka uses Chief-adjudicated findings and exact-SHA evidence rather than a confidence
target or zero unresolved threads. It separates software/platform ownership, requires
consequential decisions outside autonomous correction, preserves finding history, and
leaves final review/merge authority outside the loop. The default cap is three reviews,
including fresh verification of the final correction. GitHub-only helpers keep transport
behavior small and auditable.

Primary API references:

- [GitHub reviews](https://docs.github.com/en/rest/pulls/reviews)
- [GitHub review comments](https://docs.github.com/en/rest/pulls/comments)
- [GitHub issue comments](https://docs.github.com/en/rest/issues/comments)
- [GitHub check runs](https://docs.github.com/en/rest/checks/runs)
- [GitHub CLI API pagination](https://cli.github.com/manual/gh_api)

Summary-only head proof is provider-dependent. The explicit adapter contract does not
claim that stock Greptile emits the required completion marker.
