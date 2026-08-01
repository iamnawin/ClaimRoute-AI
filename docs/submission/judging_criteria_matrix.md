# Submission judging criteria matrix

| Dimension | Evidence | UI proof | Frozen metric | Limitation | Safe presentation claim |
|---|---|---|---|---|---|
| Extraction accuracy | Frozen synthetic summary plus official Tier C receipt | Results and field evidence tabs | 99.716% field / 99.936% critical synthetic; 85.714% primary official Tier C | Synthetic and official denominators stay separate | Balanced achieved 99.716% on the frozen synthetic benchmark; Tier C separately measured 36/42 under a provisional denominator. |
| Cost per page | `docs/evaluation/final_cost_model.md` | Cost & performance tab | $0.0000722 measured local; $0.0000949 projected automated | No paid provider call | Projected automated cost is $0.0000949/page under documented selective-oracle assumptions. |
| Innovation | Architecture, ledger, ablations | Processing journey and provenance | 93.303% primary local resolution; 1.905% escalation | Oracle is a test double | ClaimRoute budgets intelligence per field and escalates only selected crops. |
| Scalability/performance | `throughput_summary.json` | Cost/performance tab | 9.200 pages/min measured | Development workstation only | The local prototype measured 9.2 pages/minute on the frozen synthetic run. |
| Simplicity/maintainability | `engine/extract.py`, tests, architecture | UI invokes the same pipeline | 207 release tests passed | Prototype deployment controls incomplete | One extraction spine serves tests, evaluation, and UI; no OCR/governor logic is duplicated in Streamlit. |
