# Source-code upload checklist

Gates the **separate** source-code upload (organiser brief item 4). Source code must not
appear in the deliverable ZIP.

Upload channel: the Datamatics AI Engineering Hackathon 2026 source-code link, not email.

## Repository state

- [ ] Working tree clean (`git status --short` returns nothing)
- [ ] Upload branch chosen and recorded
- [ ] Branch commit SHA recorded
- [ ] Branch builds and tests pass from a clean checkout, not just the dev machine
- [ ] No uncommitted local fixes the upload depends on
- [ ] Four bundled synthetic demo samples under `data/generated/` are unmodified (`git status` clean for `data/`)

## Completeness

- [ ] `app/` present
- [ ] `engine/` present
- [ ] `eval/` harnesses present
- [ ] `data_factory/` present, so the dataset is reproducible
- [ ] `tests/` present
- [ ] `configs/` present, with values that are safe to publish
- [ ] `README.md` present
- [ ] `requirements.txt` present and matching imports
- [ ] `.env.example` present and **value-free**

## Documentation

- [ ] README states what the project is
- [ ] README has install instructions, including the separate Tesseract binary
- [ ] README has run instructions for the pipeline
- [ ] README has local Streamlit instructions
- [ ] README has test instructions
- [ ] README license table covers **every** dependency in `requirements.txt` (see `LICENSES_AND_DEPENDENCIES.md` for the verification command)
- [ ] Architecture docs present and matching the code

## Reproducibility

- [ ] A reader can regenerate the synthetic dataset from documented commands
- [ ] Frozen split manifest present and its guard intact
- [ ] Evaluation harness commands documented
- [ ] Known test failures documented, not silently shipped

Recorded known failure: two freeze-manifest hash tests fail on Windows checkouts with
`core.autocrlf=true`, caused by CRLF conversion of a pinned JSON file. Pre-existing, not
merge-caused, and reproducible on the pre-merge parent. Either fix it with a
`.gitattributes` entry on a separate branch before upload, or document it explicitly.
Do not weaken the test.

## Docker

- [ ] Docker status decided and recorded

Docker is **preferred, not required** by the organiser. Current state: not installed on
the build machine, so no Dockerfile has been validated.

- [ ] If Dockerfile included: it was built and run successfully at least once
- [ ] If Dockerfile included: it does not bake in secrets or organiser data
- [ ] If Dockerfile excluded: README states why, honestly

Do not ship an unvalidated Dockerfile. A Dockerfile that fails to build is worse than a
documented absence.

## Data and PHI

- [ ] No organiser datasets in the upload
- [ ] No expected-output or specification files from the organiser
- [ ] `eval/official/diagnostics/` absent (gitignored; confirm it was not force-added)
- [ ] No PHI in any tracked file
- [ ] No diagnostic crops, overlays, or annotated organiser pages
- [ ] No raw OCR text derived from organiser documents
- [ ] Only synthetic, zero-PHI samples are bundled

```powershell
git ls-files | Select-String -Pattern '(?i)(diagnostic|overlay|crop|holdout|organiser|organizer)'
```

Review every hit. Filenames matching these terms are not automatically violations, but each
must be justified.

## Secrets

- [ ] No `.env` tracked (only `.env.example`)
- [ ] `.env.example` contains keys with **empty** values
- [ ] No API keys, tokens, or credentials in any tracked file
- [ ] No `.streamlit/secrets.toml`
- [ ] No provider receipts showing account identifiers
- [ ] No absolute local paths such as `D:\AI-Workspace\...` in tracked files

```powershell
git ls-files | Select-String -Pattern '(?i)(^\.env$|secret|credential|private[_-]?key)'
git grep -nI -E '[A-Za-z]:\\\\(Users|AI-Workspace)' -- ':!*.md' 2>$null
```

## Build hygiene

- [ ] No `.venv/`, `venv/`, `node_modules/`
- [ ] No `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.egg-info/`
- [ ] No `eval/results/vision_cache.jsonl`
- [ ] No temporary export directories
- [ ] No `03_Demo.mp4` or recording working files
- [ ] No superseded PDFs or draft deliverables

## Final

- [ ] `EXCLUSION_MANIFEST.md` channel 2 reviewed in full
- [ ] Upload performed via the organiser's link
- [ ] Upload confirmation captured
- [ ] Uploaded commit SHA recorded alongside the ZIP submission record
