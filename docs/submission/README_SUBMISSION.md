# ClaimRoute AI: submission control center

Entry point for packaging and submitting the Datamatics AI Engineering Hackathon 2026
deliverable. Anyone picking this up cold should be able to read this file and know what
must be submitted, what is ready, what is blocked, and what must never be included.

This document is **operational control only**. It does not create, restate, or approve
metrics. Wording and numbers are governed by:

- [`claims_register.md`](claims_register.md): approved and prohibited wording (canonical)
- [`EVIDENCE_REGISTER.md`](EVIDENCE_REGISTER.md): metric to evidence traceability
- [`evidence_index.md`](evidence_index.md): evidence file map (canonical)

If this file and the registers disagree, **the registers win**.

## Submission destination

| Channel | Target |
|---|---|
| Deliverable ZIP | `ClaimsExtraction.Hackathon@datamatics.com` |
| Source code | Datamatics AI Engineering Hackathon 2026 upload link (separate) |

## Required ZIP

```text
Name_HealthcareAIHackathon.zip
├── 01_Executive_Summary.pdf
├── 02_Architecture.pdf
├── 03_Demo.mp4
└── 05_Benchmark.xlsx
```

Exactly four files. No subfolders. No source code.

`04_` is intentionally absent: item 4 in the organiser brief is Source Code, which is
uploaded separately and must not appear in the ZIP. Do not renumber the remaining files
to close the gap, and do not add a `04_` file to "fix" it.

## Current status

Statuses are restricted to: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`,
`EXISTS_NOT_VALIDATED`, `VALIDATED_FINAL`, `RECORDING_REQUIRED`, `NOT_APPLICABLE`.

Verified against the working tree on the branch that introduced this file. No artifact is
claimed to exist unless it was confirmed on disk.

| Artifact | Owner | Status | Last validated | Blocking issue |
|---|---|---|---|---|
| `01_Executive_Summary.pdf` | TBD | `NOT_STARTED` | never | No source document exists yet. Content is available in `final_submission_package.md`. |
| `02_Architecture.pdf` | Naveen | `VALIDATED_FINAL` | 2026-08-02 | Generated reproducibly from frozen evidence plus the separately labelled synthetic OpenRouter smoke receipt; 10 pages visually reviewed. |
| `03_Demo.mp4` | Naveen | `RECORDING_REQUIRED` | never | No recording exists. `docs/demo_script.md` holds the script. See the vision-cache caveat below. |
| `05_Benchmark.xlsx` | TBD | `BLOCKED` | never | Precision and recall are required by the organiser and are **not computed** anywhere in frozen evidence. See `EVIDENCE_REGISTER.md`. |
| Source-code upload | TBD | `IN_PROGRESS` | never | Final branch not chosen; `SOURCE_UPLOAD_CHECKLIST.md` gates it. |
| Docker setup | TBD | `BLOCKED` | never | Docker is not installed on the build machine. Organiser marks it preferred, not required. |

### Known caveat affecting the demo recording

A warm vision cache can display a lower cost figure than a cold run on the benchmark cost
display. Classified P1 (demo display), not a frozen-benchmark correctness issue. Before
recording, follow the pre-recording step in `PACKAGING_RUNBOOK.md`. Frozen evidence is
unaffected.

## Evidence labels

Every number in a PDF or the XLSX must carry one of these labels, and must have a row in
`EVIDENCE_REGISTER.md`:

| Label | Meaning |
|---|---|
| `MEASURED` | Directly observed in a recorded run |
| `PROJECTED` | Computed from measured usage times a configured price |
| `ASSUMED` | Rests on a stated assumption, not observation |
| `SYNTHETIC` | Measured on the generated dataset, not organiser data |
| `OFFICIAL` | Measured on organiser-supplied documents |
| `OFFLINE_ORACLE` | Produced by the deterministic test double, not a real provider |

`SYNTHETIC` and `OFFICIAL` results must never be merged into one figure.
`OFFLINE_ORACLE` is not evidence about any real provider's accuracy.

## Prohibited in the deliverable ZIP

Source code, git history, `.env`, API keys, organiser datasets, expected-output files,
PHI, diagnostic crops, overlays, raw provider responses, internal notes, scratch files,
screenshots, README files, working documents, and absolute local paths.

Full list: [`../../source_submission/EXCLUSION_MANIFEST.md`](../../source_submission/EXCLUSION_MANIFEST.md)

## Final approval gate

The ZIP may be created only when all four artifacts read `VALIDATED_FINAL` in the table
above **and** every number in them traces to an approved row in `EVIDENCE_REGISTER.md`.

Packaging procedure: [`PACKAGING_RUNBOOK.md`](PACKAGING_RUNBOOK.md)
Item-level gates: [`DELIVERY_CHECKLIST.md`](DELIVERY_CHECKLIST.md)
