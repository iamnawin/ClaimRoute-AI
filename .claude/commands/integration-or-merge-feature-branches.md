---
name: integration-or-merge-feature-branches
description: Workflow command scaffold for integration-or-merge-feature-branches in ClaimRoute-AI.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /integration-or-merge-feature-branches

Use this workflow when working on **integration-or-merge-feature-branches** in `ClaimRoute-AI`.

## Goal

Integrates a feature branch or merges multiple disjoint feature sets, ensuring both code and documentation are included.

## Common Files

- `app/*.py`
- `engine/**/*.py`
- `tests/**/*.py`
- `docs/**/*.md`
- `README.md`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Merge code files from both branches.
- Merge or reconcile test files.
- Merge or update documentation to reflect integrated features.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.