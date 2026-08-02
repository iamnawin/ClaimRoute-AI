# Security, PHI, and data-boundary audit

Real-provider escalation is disabled by default. If separately approved and enabled, only bounded
field crops may be sent to an approved named provider; full-page requests are rejected.
## Verified repository state

- The committed benchmark uses deterministic synthetic CMS-1500 and UB-04 claims only.
- Official-looking workspace data is not tracked, copied into evidence, or used for scoring.
- The frozen run made zero external calls and measured `$0` API spend.
- The offline oracle is local deterministic test code; its price is projected.
- The Streamlit UI exposes no real-provider control. Bundled synthetic samples may use the oracle;
  uploads force local-only processing with escalation disabled.
- Uploads are limited to PNG/JPEG/single-page TIFF, 10 MB, one page; temporary files/ledgers are
  cleaned after the active run.
- Screenshot-safe mode is on by default and hides pixels, crops, and extracted values.
- A tracked-file scan found no `.env`, private key, database, official-dataset filename, or literal
  provider secret. Provider adapters read credentials from environment variables only.

## Production gaps

The prototype has no authentication, authorization, encrypted durable audit store, retention
enforcement, review queue, tenant isolation, hard worker cancellation, DLP, consent/purpose control,
or approved-provider routing. It must remain local or access-controlled and synthetic-only until
those controls and organizer rules are verified.

Official-looking dataset use remains blocked on five explicit questions: authoritative input/output
mapping, permitted processing purpose, PHI classification, retention/deletion rules, and whether
field crops may be sent to named providers. Public Netlify hosting serves only the static project
status page; it does not host Python extraction or accept uploads.
