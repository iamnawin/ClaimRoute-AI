---
name: feature-development-with-tests-and-docs
description: Workflow command scaffold for feature-development-with-tests-and-docs in ClaimRoute-AI.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /feature-development-with-tests-and-docs

Use this workflow when working on **feature-development-with-tests-and-docs** in `ClaimRoute-AI`.

## Goal

Implements a new feature, adds or updates corresponding tests, and documents the new functionality.

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

- Implement new feature in one or more app/engine files.
- Add or update corresponding tests in tests/.
- Update or add relevant documentation in docs/ or README.md.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.