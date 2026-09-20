# zeka-agents-skills

Engineering skills developed while building Zeka with coding agents.

## Skills

- [zeka-evidence-gate](skills/zeka-evidence-gate/SKILL.md): behavior-first evidence
  manifests, reports and verification bound to an immutable revision, with structured
  provenance and a review-loop adapter. Requires Python 3.10+ and Git. See its
  [execution reference](skills/zeka-evidence-gate/references/execution.md).

- [zeka-review-loop](skills/zeka-review-loop/SKILL.md): bounded GitHub/Greptile review
  and correction with Zeka governance, SHA-bound evidence and a Chief handoff.
  Requires Python 3.10+, Git and an authenticated GitHub CLI for live collection.
  See its [execution reference](skills/zeka-review-loop/references/execution.md) for
  configuration, commands and provider limitations.

Install by copying the desired folder from `skills/` into the skill directory
supported by your coding agent. Keep its scripts and references together.

Run offline behavioral tests without installing dependencies:

```text
python -m unittest discover -s skills/zeka-review-loop/tests -v
python -m unittest discover -s skills/zeka-evidence-gate/tests -v
```

Live review artifacts and environment-specific configuration must stay out of this
public repository. Helpers do not install dependencies, merge or force-push.
