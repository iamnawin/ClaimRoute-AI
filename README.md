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

## Local demo application

```bash
.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py
```

Open `http://localhost:8501`. The demo defaults to a bundled synthetic claim and Balanced
mode. PNG, JPEG, and single-page TIFF uploads are accepted up to 10 MB. Uploaded documents
always remain local-only and never invoke an external provider. See
`docs/operations/local_app_runbook.md` and `docs/demo_script.md` before a judged demo.

## Licensing

Every component below is open source and permissively licensed (MIT, BSD, or Apache-2.0);
none is copyleft. Licences are as declared by each package's own distribution metadata at
the installed version, not inferred.

| Component | Version | Purpose | Licence | Scope | Source |
|---|---|---|---|---|---|
| Pillow | 12.1.1 | Image IO, rendering, geometric ops | MIT-CMU | runtime | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) |
| NumPy | 2.3.0 | Array maths for preprocessing, router, guardrail | BSD-3-Clause | runtime | [numpy/numpy](https://github.com/numpy/numpy) |
| PyYAML | 6.0.2 | Config loading (`configs/*.yaml`) | MIT | runtime | [yaml/pyyaml](https://github.com/yaml/pyyaml) |
| Faker | 40.36.0 | Synthetic claim field values (data factory) | MIT | runtime | [joke2k/faker](https://github.com/joke2k/faker) |
| rapidocr-onnxruntime | 1.2.3 | PP-OCR inference via ONNX (primary OCR, on-prem) | Apache-2.0 | runtime | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) |
| pytesseract | 0.3.13 | Python wrapper for the Tesseract binary (retry OCR) | Apache-2.0 | runtime | [madmaze/pytesseract](https://github.com/madmaze/pytesseract) |
| Tesseract OCR | 5.4.0 | OCR engine binary — **not a Python package**, installed separately | Apache-2.0 | runtime, external | [tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) |
| onnxruntime | 1.20.1 | Inference runtime (transitive, via rapidocr-onnxruntime) | MIT | runtime, transitive | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |
| OpenCV (opencv-python) | 5.0.0.93 | Image ops (transitive, via rapidocr-onnxruntime) | Apache-2.0 | runtime, transitive | [opencv/opencv-python](https://github.com/opencv/opencv-python) |
| Streamlit | 1.41+ | Local demo application | Apache-2.0 | runtime | [streamlit/streamlit](https://github.com/streamlit/streamlit) |
| pytest | 9.1.1 | Test runner | MIT | development | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) |

No cloud OCR or vision service is required to run the pipeline: Tier-1 extraction is fully
on-premise. The Tier-2 escalation adapters (`engine/vision/`) call provider HTTP APIs through
the Python standard library (`urllib`), so enabling a paid model adds no new dependency.

(Extend this table with every added dependency — documented licensing is a scored hackathon rule.)
