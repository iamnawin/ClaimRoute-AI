# Delivery checklist

Per-artifact gates. An artifact may be marked `VALIDATED_FINAL` in
[`README_SUBMISSION.md`](README_SUBMISSION.md) only when every box in its section is
ticked by someone who actually performed the check.

Ticking a box you did not verify invalidates the submission evidence chain.

## Automated pre-pass

Run this first. It clears the mechanical boxes below - existence, exact
filenames, openability, workbook sheets and charts, and the derived precision
and recall - so human attention goes to the ones a script cannot judge: page
counts, glyph rendering, claim wording, and what is visible in the recording.

```powershell
.\scripts\validate_submission_readiness.ps1
```

Exit `0` means either ELIGIBLE or BLOCKED_ONLY_BY_MP4. Exit `1` means a real
defect: fix it before ticking anything. The script never writes to the
repository.

A green pre-pass is **not** a substitute for this checklist. It cannot see
inside a PDF page, and it cannot watch the demo.

## 01_Executive_Summary.pdf

Existence and format:

- [ ] File exists at `submission/final/01_Executive_Summary.pdf`
- [ ] Filename matches exactly, including underscores and capitalisation
- [ ] Opens without error or repair prompt in a PDF reader other than the authoring tool
- [ ] Page count is 4 to 6
- [ ] No blank, placeholder, or `TODO` pages
- [ ] Fonts embedded; no missing-glyph boxes

Required content (organiser brief item 1):

- [ ] Problem understanding
- [ ] Solution overview
- [ ] Key innovations
- [ ] Results: accuracy
- [ ] Results: cost per page
- [ ] Results: throughput
- [ ] Results: latency
- [ ] Why this solution should win

Evidence integrity:

- [ ] Every number has a row in `EVIDENCE_REGISTER.md`
- [ ] Every number carries its evidence label, or the label is unambiguous in context
- [ ] Synthetic and official results are visibly separated
- [ ] No projected figure is presented as measured spend
- [ ] No provider-accuracy claim appears
- [ ] Prose matches approved wording in `claims_register.md`
- [ ] No phrasing from the prohibited column appears
- [ ] Tier A official result is handled honestly, not omitted
- [ ] Limitations section present and truthful

Safety:

- [ ] No PHI
- [ ] No organiser document images
- [ ] No API keys or credentials
- [ ] No absolute local filesystem paths
- [ ] No internal branch names, ticket IDs, or scratch notes

## 02_Architecture.pdf

Existence and format:

- [ ] File exists at `submission/final/02_Architecture.pdf`
- [ ] Filename matches exactly
- [ ] Opens without error in an independent reader
- [ ] Diagrams legible at 100% zoom and when printed greyscale
- [ ] No placeholder diagrams

Required content (organiser brief item 2):

- [ ] End-to-end architecture
- [ ] Component design
- [ ] OCR strategy
- [ ] LLM / Vision AI strategy
- [ ] Confidence-based routing
- [ ] Business rules validation
- [ ] Cost optimization strategy
- [ ] Scalability for 100M+ pages per year
- [ ] Failure handling and exception processing

Accuracy of description:

- [ ] Implemented capability and roadmap are clearly separated
- [ ] Offline oracle described as a deterministic test double, not a provider
- [ ] PHI trust boundary (crops only) described accurately
- [ ] Scalability section framed as projection, not demonstration
- [ ] Any provider integration status stated accurately, including what is not wired up
- [ ] Architecture matches `docs/architecture.md` v1.2; no aspirational redesign

Safety: same five checks as the executive summary.

## 03_Demo.mp4

Pre-recording:

- [ ] Vision-cache pre-recording step in `PACKAGING_RUNBOOK.md` completed
- [ ] Desktop cleared of unrelated windows, notifications silenced
- [ ] Browser has no visible bookmarks, tabs, or history revealing internal URLs
- [ ] No terminal shows API keys, `.env` contents, or absolute paths beyond the repo
- [ ] Demo runs on synthetic data only, unless organiser data is explicitly permitted on screen

Existence and format:

- [ ] File exists at `submission/final/03_Demo.mp4`
- [ ] Filename matches exactly
- [ ] Container is MP4, H.264 video, AAC audio
- [ ] Plays start to finish in an independent player
- [ ] Duration recorded and appropriate for a 10-minute live demo slot
- [ ] Resolution at least 1080p; text readable at playback size
- [ ] Audio present, clear, and level throughout

Required coverage (organiser brief item 3):

- [ ] Input documents
- [ ] Processing pipeline
- [ ] Output (JSON / CSV / EDI)
- [ ] Accuracy dashboard
- [ ] Cost dashboard

Safety:

- [ ] No API key visible in any frame, including transient toasts
- [ ] No PHI visible
- [ ] No organiser filenames on screen unless permitted
- [ ] No `.env`, secrets file, or credential prompt visible
- [ ] Spoken narration makes no prohibited claim
- [ ] Backup copy stored outside `submission/final/`

## 05_Benchmark.xlsx

Existence and format:

- [ ] File exists at `submission/final/05_Benchmark.xlsx`
- [ ] Filename matches exactly, including the `05_` prefix
- [ ] Opens with no repair warning
- [ ] No broken formulas, `#REF!`, or `#DIV/0!`
- [ ] No hidden sheets containing internal notes
- [ ] No external workbook links

Overall metrics (organiser brief item 5):

- [ ] Total pages processed
- [ ] Processing time
- [ ] Average latency
- [ ] Pages per second
- [ ] Accuracy
- [ ] Precision **(blocked: not computed; see `EVIDENCE_REGISTER.md`)**
- [ ] Recall **(blocked: not computed; see `EVIDENCE_REGISTER.md`)**

Component-wise cost per page:

- [ ] OCR (or honestly marked not separately metered)
- [ ] LLM
- [ ] Vision AI
- [ ] GPU (or honestly marked not used)
- [ ] CPU (or honestly marked not separately metered)
- [ ] Total cost per page

Evidence integrity:

- [ ] Every cell traces to a row in `EVIDENCE_REGISTER.md`
- [ ] Evidence label present per metric, as a column or adjacent note
- [ ] Synthetic and official results on separate sheets or clearly separated blocks
- [ ] Measured and projected values never summed into one unlabelled total
- [ ] `field_accuracy` is **not** entered into a Precision or Recall cell
- [ ] Cache hits reported separately from cost per page
- [ ] Methodology or notes sheet naming dataset, denominators, and exclusions

## Final ZIP

- [ ] Named `Name_HealthcareAIHackathon.zip` with `Name` replaced as the organiser intends
- [ ] Contains exactly four files
- [ ] Contains zero subfolders
- [ ] Contains no source code
- [ ] Contains no README or documentation file
- [ ] Contains no `.env` or credential file
- [ ] Contains no organiser data
- [ ] Contains no PHI
- [ ] Contains no `__MACOSX`, `.DS_Store`, or `Thumbs.db`
- [ ] All four filenames match the organiser spec exactly
- [ ] No `04_` file was invented to fill the numbering gap
- [ ] ZIP extracts cleanly to an empty directory
- [ ] All four files open **from the extracted copy**, not the original
- [ ] ZIP total size recorded
- [ ] SHA-256 of the ZIP recorded
- [ ] SHA-256 of each of the four files recorded

## Source-code upload

Gated separately by
[`../../source_submission/SOURCE_UPLOAD_CHECKLIST.md`](../../source_submission/SOURCE_UPLOAD_CHECKLIST.md).

- [ ] That checklist fully completed
- [ ] Upload performed via the organiser's link, not email
- [ ] Upload confirmation captured

## Email submission

- [ ] Recipient is `ClaimsExtraction.Hackathon@datamatics.com`
- [ ] Subject line identifies the team
- [ ] ZIP attached and within the provider's attachment size limit
- [ ] Body states that source code was uploaded separately
- [ ] Body contains no metric not present in the deliverables
- [ ] Attachment re-downloaded from the sent copy and verified to open
- [ ] Sent timestamp recorded
