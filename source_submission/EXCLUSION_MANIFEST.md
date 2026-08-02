# Exclusion manifest

What must never leave this repository, split by channel. The two channels have different
rules: source code is required in one and prohibited in the other.

## Channel 1: the deliverable ZIP

`Name_HealthcareAIHackathon.zip` contains **exactly four files and nothing else**:
`01_Executive_Summary.pdf`, `02_Architecture.pdf`, `03_Demo.mp4`, `05_Benchmark.xlsx`.

Prohibited:

**Code and repository internals**
- All source code, in any form, including snippets pasted as separate files
- `.git/` and any git metadata
- `.venv/`, `venv/`, `node_modules/`
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.egg-info/`
- `requirements.txt`, lockfiles, `configs/`

**Secrets and configuration**
- `.env` and every `.env.*` variant
- `.streamlit/secrets.toml`
- API keys, tokens, credentials, private keys, `.pem` files
- Any file matching `secret`, `credential`, `private_key`, `private-key`

**Organiser and protected data**
- Organiser claim documents in any format (TIFF, PDF, PNG, numeric-extension)
- Expected-output files, specification documents
- `eval/official/diagnostics/` (renders organiser page pixels; potential PHI)
- Consumed holdout inputs
- Any PHI in any form, including inside a screenshot or video frame

**Derived data that can carry PHI**
- Diagnostic crops, field crops, overlays, annotated pages
- Raw OCR text from organiser documents
- Raw provider request or response payloads
- `eval/results/vision_cache.jsonl`

**Documents and working material**
- README files of any kind
- The control documents in `docs/submission/`
- Internal notes, `HANDOFF.md`, scratchpad files, planning documents
- Superseded or draft PDFs
- Recording project files, raw footage, edit timelines
- Screenshots
- Logs, `.jsonl` benchmark rows, temporary exports
- Any file containing an absolute local path such as `D:\AI-Workspace\...`

**Packaging noise**
- `__MACOSX/`, `.DS_Store`, `Thumbs.db`, `desktop.ini`
- Nested folders (all four files sit at the ZIP root)
- Any invented `04_` file: item 4 is the separate source upload

## Channel 2: the source-code upload

Source code is **required** here. The exclusions are about data and secrets.

Prohibited:

- Organiser datasets and any derivative that reveals their content
- Expected-output and specification files supplied by the organiser
- `eval/official/diagnostics/`
- PHI in any form
- `.env` and `.env.*` (except the value-free `.env.example`)
- Real API keys, tokens, credentials, provider receipts showing account identifiers
- `eval/results/vision_cache.jsonl` and cached provider responses
- `03_Demo.mp4` and recording working files
- Diagnostic crops and overlays
- Benchmark rows containing organiser-derived values
- Temporary export directories
- Absolute local paths in committed files
- `.venv/`, `__pycache__/`, `.pytest_cache/`, build artifacts

Required (do not strip these):

- Complete source: `app/`, `engine/`, `eval/` harnesses, `data_factory/`, `tests/`
- `README.md` with run instructions
- `requirements.txt`
- `configs/` templates
- `.env.example`, value-free
- Test instructions and local Streamlit instructions
- Licensing information
- Docker files **only when validated**; an unvalidated Dockerfile is worse than none

## Enforcement

`.gitignore` already covers many of these at the repository level, notably `.env*`,
`eval/official/diagnostics/`, `eval/results/vision_cache.jsonl`, `.streamlit/secrets.toml`,
and `data/` with a narrow allowlist for four bundled synthetic demo samples.

Gitignore protects the repository. It does **not** protect a ZIP assembled by hand from
files on disk. The scans in
[`../docs/submission/PACKAGING_RUNBOOK.md`](../docs/submission/PACKAGING_RUNBOOK.md)
steps 7 and 8 are the control that applies at packaging time, and they must be run.

## Note on bundled demo samples

Four synthetic CMS-1500 samples under `data/generated/cms1500/{clean,ugly}/` are
deliberately tracked as gitignore exceptions, because the public Streamlit demo depends on
them. They are **synthetic, zero-PHI by construction** and are permitted in the source
upload.

They are still prohibited in the deliverable ZIP, which takes only the four files.

Regenerating the dataset overwrites these four tracked files. If `git status` shows them
modified, restore with `git checkout -- data/` before committing or packaging.
