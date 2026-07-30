# Public demo deployment

The public application is a synthetic-only demonstration. It is not approved for real claims,
official datasets, or protected health information (PHI).

## Streamlit Community Cloud

- Repository: `iamnawin/ClaimRoute-AI`
- Branch: `main`
- Entrypoint: `app/streamlit_app.py`
- Python: `3.12`
- Secrets: none
- Custom subdomain: `claimroute-ai`

Community Cloud installs the pinned Python packages from `requirements.txt` and Debian packages
from `packages.txt`. Run Streamlit from the repository root so all relative paths match Linux.

## Safety boundary

- Only two committed, deterministic synthetic examples are selectable.
- Upload is disabled until the user attests that the file is synthetic and contains no PHI.
- PNG, JPEG, and single-page TIFF are accepted; the limit is 10 MB and one page.
- Uploads are decoded in temporary storage, which is deleted immediately after decoding.
- Uploaded images use local OCR only and cannot reach an external provider.
- Bundled samples can use only the deterministic `offline-oracle` test double.
- No API keys or other secrets are required or configured for the public app.
- No path references the official-looking dataset or a developer workstation.

The attestation is a user-facing control, not automated PHI detection. A public prototype cannot
prove that a user mislabeled content is synthetic; users must not upload real healthcare data.

## Hosting limitations

Community Cloud can hibernate inactive apps and has shared CPU and memory limits. Cold starts and
OCR latency may therefore be higher than the frozen workstation benchmark. The frozen benchmark
is evidence only and is not rerun or changed by deployment.
