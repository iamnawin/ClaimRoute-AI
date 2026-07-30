# Licensing and dependency audit

Captured 2026-07-30 from the frozen Python 3.11.13 environment. `requirements.txt` intentionally
uses minimum versions for reproducible installation flexibility; exact evaluated versions are frozen
in `eval/frozen/environment_manifest.json`.

| Component | Frozen version | Declared metadata licence | Use |
|---|---:|---|---|
| Pillow | 12.3.0 | MIT-CMU | Image IO and transforms |
| NumPy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Arrays and preprocessing |
| PyYAML | 6.0.3 | MIT | Configuration |
| Faker | 40.36.0 | MIT | Synthetic data generation |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | Primary OCR |
| pytesseract | 0.3.13 | Apache-2.0 | Retry adapter |
| ONNX Runtime | 1.28.0 | MIT | Transitive inference runtime |
| opencv-python | 5.0.0.93 | Apache-2.0 | Transitive image operations |
| Streamlit | 1.60.0 | Apache-2.0 | Local demo UI |
| pytest | 9.1.1 | MIT | Development tests |
| Tesseract binary | 5.4.0 | Apache-2.0 | External local OCR binary |

The direct declarations match runtime imports: Pillow, Faker, PyYAML, NumPy, pytesseract,
rapidocr-onnxruntime, and Streamlit. ONNX Runtime and OpenCV are transitive through RapidOCR.
No new runtime dependency was added for the Day 11 harness.

The listed open-source licenses are permissive and do not impose a copyleft source-distribution
condition on this repository. That technical inventory is not legal advice. Provider API terms,
model/data-use terms, dataset organizer terms, and any model-weight licenses are separate approval
tracks and are not implied by Python-package compatibility.
