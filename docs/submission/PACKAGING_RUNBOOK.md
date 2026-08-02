# Packaging runbook

Executable procedure for building and validating the deliverable ZIP. Written so that
another engineer or agent can run it without prior context on this project.

Commands are Windows PowerShell 5.1, run from the repository root
(`claims-engine/`) unless stated otherwise.

**Do not create the ZIP until all four artifacts read `VALIDATED_FINAL` in
[`README_SUBMISSION.md`](README_SUBMISSION.md).** Step 12 is the gate.

## 0. The short version

Steps 1 to 19 below are the manual procedure and remain the reference for *why*
each check exists. Two scripts now automate them end to end:

```powershell
# Read-only. Reports every artifact, scan, and blocker. Never writes anything.
.\scripts\validate_submission_readiness.ps1

# Builds the ZIP, or refuses and explains why. Writes nothing on refusal.
.\scripts\finalize_submission.ps1
```

| Script | Covers | Exit codes |
|---|---|---|
| `validate_submission_readiness.ps1` | steps 2-8, 10, 11 | `0` = ELIGIBLE **or** BLOCKED_ONLY_BY_MP4; `1` = a real defect |
| `finalize_submission.ps1` | steps 12-16 | `0` = packaged; `1` = refused, no ZIP written |

The readiness script exits **0** while the recording is outstanding. A missing
MP4 is an expected state, not a system failure, so this can be used as a green
pre-recording gate. It also calls
`scripts/submission/validate_artifacts.py`, which reopens each artifact, extracts
the PDF text, loads the workbook, and checks that the rendered output carries the
derived precision and recall rather than the exact-match rate.

`finalize_submission.ps1` builds under a temporary name and only renames to
`DXtraAI_HealthcareAIHackathon.zip` after reopening the archive and confirming
exactly four root entries and no folders. A wrongly-populated archive never
carries the delivery name.

Run the manual steps when a script reports something you do not understand, or
when you need to justify a check to a reviewer.

## 1. Verify git state

```powershell
git status --short
git branch --show-current
git log -1 --format="%H %s"
```

Expect a clean tree. Record the commit; it goes in the submission record.

Do not package from a branch with uncommitted changes: the ZIP would not correspond to
any reproducible commit.

## 2. Inventory artifacts

```powershell
Get-ChildItem submission/final -File | Select-Object Name, Length, LastWriteTime
```

Expect exactly four files. Any other file present is a packaging error, not a bonus.

## 3. Reconcile evidence

Open [`EVIDENCE_REGISTER.md`](EVIDENCE_REGISTER.md). For each number in the PDFs and
XLSX, confirm a matching row exists and the value matches its source file.

```powershell
# Re-read the frozen source values rather than trusting the register text
Get-Content eval/frozen/final_benchmark_summary.json | ConvertFrom-Json |
  Select-Object -ExpandProperty blended
Get-Content eval/frozen/throughput_summary.json | ConvertFrom-Json
```

Stop if any deliverable number lacks a row, or disagrees with its source.

Check the open blockers section of the register. As of writing, precision and recall are
**not computed**; confirm the XLSX handles this honestly rather than substituting
`field_accuracy`.

## 4. Validate the PDFs

```powershell
foreach ($f in "01_Executive_Summary.pdf","02_Architecture.pdf") {
  $p = "submission/final/$f"
  if (-not (Test-Path $p)) { Write-Host "MISSING: $f"; continue }
  $bytes = [System.IO.File]::ReadAllBytes($p)
  $head  = [System.Text.Encoding]::ASCII.GetString($bytes[0..4])
  $tail  = [System.Text.Encoding]::ASCII.GetString($bytes[-1024..-1])
  Write-Host "$f header=$head eof=$($tail -match '%%EOF') size=$($bytes.Length)"
}
```

Header must be `%PDF-`, `eof=True`. Then open both manually and walk the content boxes in
[`DELIVERY_CHECKLIST.md`](DELIVERY_CHECKLIST.md). A structural check does not prove the
content is correct.

## 5. Validate the XLSX

```powershell
$p = "submission/final/05_Benchmark.xlsx"
$bytes = [System.IO.File]::ReadAllBytes($p)
# XLSX is a ZIP container: first two bytes must be PK
Write-Host "magic=$([char]$bytes[0])$([char]$bytes[1]) size=$($bytes.Length)"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $p))
$z.Entries | Select-Object -First 20 FullName
$z.Dispose()
```

Expect `magic=PK` and entries including `xl/workbook.xml`. Then open in Excel and confirm
no repair prompt, no `#REF!`, and no hidden sheets.

## 6. Validate the MP4

```powershell
$p = "submission/final/03_Demo.mp4"
$bytes = [System.IO.File]::ReadAllBytes($p)
$brand = [System.Text.Encoding]::ASCII.GetString($bytes[4..7])
Write-Host "brand=$brand size_MB=$([math]::Round($bytes.Length/1MB,2))"
```

`brand` must be `ftyp`. If `ffprobe` is available, prefer it:

```powershell
ffprobe -v error -show_entries format=duration,size,bit_rate `
  -show_entries stream=codec_name,width,height -of default=noprint_wrappers=1 `
  submission/final/03_Demo.mp4
```

Then watch it end to end with audio on. Structural validity does not prove a key is
absent from frame 4,300.

## 7. PHI and organiser-data scan

```powershell
# No organiser artifacts anywhere in the staging area
Get-ChildItem submission/final -Recurse -File |
  Where-Object { $_.Name -match '(?i)(tier[_-]?[abcd]|organiser|organizer|expected|specification)' }

# Confirm no protected directories were copied in
Get-ChildItem submission/final -Recurse -Directory |
  Where-Object { $_.Name -match '(?i)(diagnostics|crops|overlays|official)' }
```

Both must return nothing. Also confirm visually that no PDF page or video frame shows an
organiser document image.

## 8. Secret scan

```powershell
# Staging area must contain no env or credential files
Get-ChildItem submission/final -Recurse -File -Force |
  Where-Object { $_.Name -match '(?i)(^\.env|secret|credential|private[_-]?key|\.pem$)' }

# Repository-level check that nothing sensitive is tracked
git ls-files | Select-String -Pattern '(?i)(^\.env$|secret|credential|private[_-]?key)'
```

`.env.example` is expected and permitted; it must remain value-free. Anything else is a
stop condition.

## 9. Copy approved files to final

Only after steps 3 through 8 pass.

```powershell
New-Item -ItemType Directory -Force submission/final | Out-Null
# Copy each validated artifact explicitly. Never bulk-copy a working directory.
Copy-Item <validated-source> submission/final/01_Executive_Summary.pdf
Copy-Item <validated-source> submission/final/02_Architecture.pdf
Copy-Item <validated-source> submission/final/03_Demo.mp4
Copy-Item <validated-source> submission/final/05_Benchmark.xlsx
```

Explicit per-file copies are deliberate. A recursive copy is how working documents and
scratch files reach a deliverable.

## 10. Confirm exact filenames

```powershell
$expected = @(
  "01_Executive_Summary.pdf",
  "02_Architecture.pdf",
  "03_Demo.mp4",
  "05_Benchmark.xlsx"
)
$actual = (Get-ChildItem submission/final -File | Select-Object -ExpandProperty Name)
Write-Host "Missing : $(($expected | Where-Object { $_ -notin $actual }) -join ', ')"
Write-Host "Unexpected: $(($actual | Where-Object { $_ -notin $expected }) -join ', ')"
```

Both lines must report nothing. Filename comparison is case-sensitive by intent, even
though Windows is not.

## 11. Pre-recording step for the demo (before step 6, if re-recording)

A warm vision cache can display a lower cost figure than a cold run.

```powershell
# Gitignored and untracked; safe to delete. Verify first.
git check-ignore -v eval/results/vision_cache.jsonl
Remove-Item eval/results/vision_cache.jsonl -ErrorAction SilentlyContinue
```

Confirm `git check-ignore` reports the file as ignored before deleting. Frozen benchmark
evidence is unaffected by this step.

## 12. Approval gate

Stop and confirm all four artifacts read `VALIDATED_FINAL` in `README_SUBMISSION.md`,
and that every box in `DELIVERY_CHECKLIST.md` is ticked by someone who performed it.

If any artifact is not `VALIDATED_FINAL`, go to rollback (step 17).

## 13. Create the ZIP

```powershell
$zip = "submission/Name_HealthcareAIHackathon.zip"   # replace Name per organiser
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path submission/final/* -DestinationPath $zip -CompressionLevel Optimal
```

`submission/final/*` (not the directory) keeps the four files at the ZIP root with no
enclosing folder.

## 14. Inspect ZIP contents

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $zip))
$z.Entries | Select-Object FullName, Length, CompressedLength
Write-Host "Entry count: $($z.Entries.Count)"
$z.Dispose()
```

Entry count must be exactly 4. No `FullName` may contain `/` or `\`, which would indicate
an unwanted folder.

## 15. Extract and reopen

The decisive check. Validate what the judge receives, not what you built.

```powershell
$test = Join-Path $env:TEMP "claimroute_zip_verify"
if (Test-Path $test) { Remove-Item $test -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $test
Get-ChildItem $test -Recurse | Select-Object FullName, Length
```

Open all four extracted files. Play the extracted MP4. Open the extracted XLSX in Excel.
If any file fails here, the ZIP is not shippable regardless of how the originals behaved.

## 16. Record sizes and hashes

```powershell
Get-FileHash $zip -Algorithm SHA256 | Format-List
Get-ChildItem submission/final -File |
  ForEach-Object {
    [PSCustomObject]@{
      Name   = $_.Name
      Bytes  = $_.Length
      SHA256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
  } | Format-Table -AutoSize
```

Record all five hashes, the git commit from step 1, and the timestamp. This is the
submission record; without it there is no proof of what was sent.

Then delete the verification directory:

```powershell
Remove-Item $test -Recurse -Force
```

## 17. Source-code upload

Separate channel. Do not attach source to the email.

Follow [`../../source_submission/SOURCE_UPLOAD_CHECKLIST.md`](../../source_submission/SOURCE_UPLOAD_CHECKLIST.md)
and [`../../source_submission/EXCLUSION_MANIFEST.md`](../../source_submission/EXCLUSION_MANIFEST.md).

## 18. Email

Recipient: `ClaimsExtraction.Hackathon@datamatics.com`

- Attach the ZIP only
- State that source code was uploaded separately, and name the channel
- Quote no metric that is not already in the deliverables
- After sending, re-download from the sent copy and confirm it opens

## 19. Rollback

If validation fails at any step:

1. Do not send.
2. Delete the ZIP: `Remove-Item $zip`. A partially validated ZIP on disk gets sent by accident.
3. Set the offending artifact back to `IN_PROGRESS` or `BLOCKED` in `README_SUBMISSION.md`, with the reason.
4. Untick the affected boxes in `DELIVERY_CHECKLIST.md`. Do not leave a stale tick.
5. Delete the verification directory.
6. Fix, then restart from step 1. Not from the failing step: earlier state may have changed.

Never ship a ZIP that failed step 15 on the theory that the originals were fine.
