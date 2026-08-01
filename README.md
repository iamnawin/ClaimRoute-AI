# Claims Engine — Cost-Governed Healthcare Claims Extraction

**Datamatics AI Engineering Hackathon 2026** · Architecture v1.2 (locked, see `docs/architecture.md`)

> A claims extraction engine that treats intelligence as a budgeted resource. Deterministic OCR
> and healthcare validation resolve most fields for fractions of a cent; only the uncertain few
> earn a multimodal call. The operator sets the cost; the engine finds the accuracy.

## Layout

```
configs/        field policy, attempt budgets, prices, pipeline presets
data_factory/   synthetic CMS-1500 / UB-04 generator + degradation (zero PHI by construction)
engine/         pipeline: preprocess, router, ocr, layout, validators, fusion, governor, escalation
eval/           benchmark harness, metrics, ablations, frontier
app/            Streamlit demo
tests/          validator + schema unit tests
docs/           architecture, assumptions, cost model
data/           generated datasets (reproducible from seed; not committed)
```

## Quickstart

```bash
uv venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
python -m data_factory.make_dataset --n-per-form 10 --seed 42 --out data/generated
```

Every generated page ships with exact ground-truth JSON. The dataset is fully synthetic and
reproducible from a single seed — no PHI exists anywhere in this repository.

## Interactive synthetic-claim demo

```bash
.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
```

Open `http://localhost:8501`. The demo defaults to a bundled synthetic claim and Balanced
mode. Public uploads are limited to user-attested synthetic PNG, JPEG, and single-page TIFF
files up to 10 MB. Temporary upload files are deleted after decoding, and uploads never invoke
an external provider. Real claims and PHI are prohibited. See
`docs/operations/local_app_runbook.md` and `docs/demo_script.md` before a judged demo.

For Streamlit Community Cloud, deploy `app/streamlit_app.py` from the repository root with
Python 3.12 and no secrets. Python dependencies are pinned in `requirements.txt`; Debian OCR
packages are declared in `packages.txt`. See `docs/operations/public_deployment.md`.

## Frozen Day 11 evidence

Balanced mode achieved **99.716% exact field accuracy** and **99.936% critical-field accuracy**
on the frozen synthetic test split: 30 documents rendered across clean, noisy, and ugly tiers
(90 pages / 3,168 fields). Measured external API spend was **$0**. Measured local processing
prices to **$0.0000722/page** at the configured compute rate; projected selective-oracle automated
cost is **$0.0000949/page**. Prototype throughput was **9.20 pages/minute** on the recorded
development workstation.

These are synthetic-test results, not real-claim or provider-accuracy claims. Start with
`docs/submission/evidence_index.md` and `docs/submission/claims_register.md`; exact manifests and
receipts are under `eval/frozen/`.

## Official organiser evidence

The separate local-only adapter under `eval/official/` decoded all 30 organiser TIFF containers
(67 pages) without committing source data or values. No combined official score is published
because four record links abstained. On deterministically linked evaluable Tier B items, 4/4 claim
pages were selected and 15/15 attachments rejected. A separate one-time Tier C UB-04 holdout
measured 36/42 primary normalized fields (85.714%), 36/63 extended fields (57.143%), 16/18 critical
fields (88.889%), and 3/3 registrations under a provisional denominator policy, with zero external
calls. These results are separate from the synthetic benchmark. See
`docs/official_dataset_benchmark.md` and `docs/evaluation/official_ub04_holdout.md`.

## Licensing

Every component below is open source and permissively licensed (MIT, BSD, or Apache-2.0);
none is copyleft. Licences are as declared by each package's own distribution metadata at
the installed version, not inferred.

| Component | Version | Purpose | Licence | Scope | Source |
|---|---|---|---|---|---|
| Pillow | 12.3.0 | Image IO, rendering, geometric ops | MIT-CMU | runtime | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) |
| NumPy | 2.4.6 | Array maths for preprocessing, router, guardrail | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime | [numpy/numpy](https://github.com/numpy/numpy) |
| PyYAML | 6.0.3 | Config loading (`configs/*.yaml`) | MIT | runtime | [yaml/pyyaml](https://github.com/yaml/pyyaml) |
| Faker | 40.36.0 | Synthetic claim field values (data factory) | MIT | runtime | [joke2k/faker](https://github.com/joke2k/faker) |
| rapidocr-onnxruntime | 1.4.4 | PP-OCR inference via ONNX (primary OCR, on-prem) | Apache-2.0 | runtime | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) |
| pytesseract | 0.3.13 | Python wrapper for the Tesseract binary (retry OCR) | Apache-2.0 | runtime | [madmaze/pytesseract](https://github.com/madmaze/pytesseract) |
| Tesseract OCR | 5.4.0 | OCR engine binary — **not a Python package**, installed separately | Apache-2.0 | runtime, external | [tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) |
| onnxruntime | 1.28.0 | Inference runtime (transitive, via rapidocr-onnxruntime) | MIT | runtime, transitive | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |
| OpenCV (opencv-python) | 5.0.0.93 | Image ops (transitive, via rapidocr-onnxruntime) | Apache-2.0 | runtime, transitive | [opencv/opencv-python](https://github.com/opencv/opencv-python) |
| Streamlit | 1.60.0 | Local demo application | Apache-2.0 | runtime | [streamlit/streamlit](https://github.com/streamlit/streamlit) |
| pytest | 9.1.1 | Test runner | MIT | development | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) |

No cloud OCR or vision service is required to run the pipeline: Tier-1 extraction is fully
on-premise. The Tier-2 escalation adapters (`engine/vision/`) call provider HTTP APIs through
the Python standard library (`urllib`), so enabling a paid model adds no new dependency.

(Extend this table with every added dependency — documented licensing is a scored hackathon rule.)
