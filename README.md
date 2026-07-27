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
pip install -r requirements.txt
python -m data_factory.make_dataset --n 10 --seed 42 --out data/raw/cms1500
```

Every generated page ships with exact ground-truth JSON. The dataset is fully synthetic and
reproducible from a single seed — no PHI exists anywhere in this repository.

## Licensing

| Component | License |
|---|---|
| Pillow | MIT-CMU |
| Faker | MIT |
| PyYAML | MIT |

(Extend this table with every added dependency — documented licensing is a scored hackathon rule.)
