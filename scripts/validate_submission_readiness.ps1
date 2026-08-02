<#
.SYNOPSIS
    Reports submission readiness for Team DXtra AI - ClaimRoute AI.

.DESCRIPTION
    Read-only. Inspects the generated deliverables, the evidence register, the
    source-upload package, and scans the submission surface for PHI, secrets, and
    organiser data. Prints one status per required item and an overall finalization
    eligibility verdict.

    This script never creates, modifies, or deletes anything.

.EXAMPLE
    .\scripts\validate_submission_readiness.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Final    = Join-Path $RepoRoot 'submission\final'
$Rows     = @()

function Add-Row {
    param(
        [string]$Item,
        [string]$Status,
        [string]$Detail
    )
    $script:Rows += [pscustomobject]@{
        Item   = $Item
        Status = $Status
        Detail = $Detail
    }
}

function Test-PdfFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 'ABSENT' }
    $info = Get-Item -LiteralPath $Path
    if ($info.Length -eq 0) { return 'ZERO_BYTE' }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $head  = [System.Text.Encoding]::ASCII.GetString($bytes[0..4])
    if ($head -ne '%PDF-') { return 'INVALID_HEADER' }
    $tailLen = [Math]::Min(2048, $bytes.Length)
    $tail = [System.Text.Encoding]::ASCII.GetString($bytes[($bytes.Length - $tailLen)..($bytes.Length - 1)])
    if ($tail -notmatch '%%EOF') { return 'TRUNCATED' }
    return 'VALID'
}

function Test-XlsxFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 'ABSENT' }
    $info = Get-Item -LiteralPath $Path
    if ($info.Length -eq 0) { return 'ZERO_BYTE' }
    # xlsx is a zip: must start with PK\x03\x04
    $fs = [System.IO.File]::OpenRead($Path)
    try {
        $sig = New-Object byte[] 4
        $null = $fs.Read($sig, 0, 4)
    } finally {
        $fs.Dispose()
    }
    if ($sig[0] -ne 0x50 -or $sig[1] -ne 0x4B) { return 'INVALID_ZIP' }
    return 'VALID'
}

function Test-Mp4File {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 'RECORDING_REQUIRED' }
    $info = Get-Item -LiteralPath $Path
    if ($info.Length -eq 0) { return 'ZERO_BYTE' }

    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($null -eq $ffprobe) { return 'PRESENT_UNVERIFIED' }

    $streams = & $ffprobe.Source -v error -show_entries stream=codec_type -of csv=p=0 $Path
    if ($LASTEXITCODE -ne 0) { return 'UNPLAYABLE' }
    $joined = ($streams -join ',')
    if ($joined -notmatch 'video') { return 'NO_VIDEO_STREAM' }
    if ($joined -notmatch 'audio') { return 'NO_AUDIO_STREAM' }

    $dur = & $ffprobe.Source -v error -show_entries format=duration -of csv=p=0 $Path
    $seconds = 0.0
    [void][double]::TryParse($dur, [ref]$seconds)
    if ($seconds -le 0) { return 'UNPLAYABLE' }
    if ($seconds -gt 600) { return "TOO_LONG ($([Math]::Round($seconds/60,2)) min > 10 min cap)" }
    if ($seconds -lt 420) { return "SHORT ($([Math]::Round($seconds/60,2)) min < 7 min target)" }
    return "VALID ($([Math]::Round($seconds/60,2)) min)"
}

Write-Host ''
Write-Host '================================================================'
Write-Host ' ClaimRoute AI - Submission Readiness'
Write-Host ' Team DXtra AI'
Write-Host '================================================================'
Write-Host ''

# -- 1. Generated deliverables ------------------------------------------------

$execPath  = Join-Path $Final '01_Executive_Summary.pdf'
$archPath  = Join-Path $Final '02_Architecture.pdf'
$demoPath  = Join-Path $Final '03_Demo.mp4'
$benchPath = Join-Path $Final '05_Benchmark.xlsx'

$execState = Test-PdfFile  $execPath
$archState = Test-PdfFile  $archPath
$benchState= Test-XlsxFile $benchPath
$demoState = Test-Mp4File  $demoPath

if ($execState -eq 'VALID') {
    Add-Row 'Executive Summary' 'VALIDATED_FINAL' "$([Math]::Round((Get-Item $execPath).Length/1KB,1)) KB, valid PDF"
} else {
    Add-Row 'Executive Summary' $execState '01_Executive_Summary.pdf'
}

if ($archState -eq 'VALID') {
    Add-Row 'Architecture' 'VALIDATED_FINAL' "$([Math]::Round((Get-Item $archPath).Length/1KB,1)) KB, valid PDF"
} else {
    Add-Row 'Architecture' $archState '02_Architecture.pdf'
}

if ($benchState -eq 'VALID') {
    Add-Row 'Benchmark' 'VALIDATED_FINAL' "$([Math]::Round((Get-Item $benchPath).Length/1KB,1)) KB, valid workbook"
} else {
    Add-Row 'Benchmark' $benchState '05_Benchmark.xlsx'
}

if ($demoState -eq 'RECORDING_REQUIRED') {
    Add-Row 'Demo MP4' 'RECORDING_REQUIRED' 'submission/final/03_Demo.mp4 does not exist'
} elseif ($demoState -like 'VALID*') {
    Add-Row 'Demo MP4' 'VALIDATED_FINAL' $demoState
} else {
    Add-Row 'Demo MP4' 'INVALID' $demoState
}

# -- 2. Deep artifact validation ----------------------------------------------

$artifactsFailed = $false
$py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$validator = Join-Path $RepoRoot 'scripts\submission\validate_artifacts.py'
if (-not (Test-Path -LiteralPath $py)) {
    Add-Row 'Artifact deep validation' 'SKIPPED' '.venv python not found'
} elseif (-not (Test-Path -LiteralPath $validator)) {
    Add-Row 'Artifact deep validation' 'SKIPPED' 'scripts/submission/validate_artifacts.py not found'
} elseif ($demoState -eq 'RECORDING_REQUIRED' -and $execState -ne 'VALID') {
    # Nothing generated yet; deep validation would only restate that.
    Add-Row 'Artifact deep validation' 'SKIPPED' 'No generated artifacts to inspect'
} else {
    $out = & $py $validator
    if ($LASTEXITCODE -eq 0) {
        $line = ($out | Select-String -Pattern 'checks passed' | Select-Object -First 1)
        Add-Row 'Artifact deep validation' 'PASS' "$line"
    } else {
        $artifactsFailed = $true
        $failed = ($out | Select-String -Pattern '^\s*FAIL' | Select-Object -First 3) -join '; '
        Add-Row 'Artifact deep validation' 'FAIL' $failed
    }
}

# -- 3. Evidence register ------------------------------------------------------

$register = Join-Path $RepoRoot 'docs\submission\EVIDENCE_REGISTER.md'
if (Test-Path -LiteralPath $register) {
    $text = Get-Content -LiteralPath $register -Raw
    # Recall is 0.98135861 (TP/(TP+FN) = 3106/3165). 0.98042929 is the automated
    # exact-match rate (3106/3168); it stays in the register under its own name but
    # must never be the recall figure. See the resolved blocker in that file.
    $hasPrecision = $text -match '0\.99903506'
    $hasRecall    = $text -match '0\.98135861'
    $staleRecall  = $text -match '(?s)\|\s*\*\*Recall\*\*\s*\|[^|]*0\.98042929'
    if ($staleRecall) {
        Add-Row 'Evidence register' 'STALE' 'Recall row carries the exact-match rate (FN=62 regression)'
    } elseif ($hasPrecision -and $hasRecall) {
        Add-Row 'Evidence register' 'CURRENT' 'Precision 0.99903506, recall 0.98135861, TP+FP+FN=3168'
    } else {
        Add-Row 'Evidence register' 'STALE' 'Derived precision/recall not found as expected'
    }
} else {
    Add-Row 'Evidence register' 'MISSING' 'docs/submission/EVIDENCE_REGISTER.md'
}

# -- 4. Source upload readiness ------------------------------------------------

$srcDir = Join-Path $RepoRoot 'source_submission'
$srcRequired = @(
    'SOURCE_UPLOAD_CHECKLIST.md',
    'EXCLUSION_MANIFEST.md',
    'LICENSES_AND_DEPENDENCIES.md',
    'SOURCE_UPLOAD_VALIDATION_REPORT.md'
)
$srcMissing = @()
foreach ($f in $srcRequired) {
    if (-not (Test-Path -LiteralPath (Join-Path $srcDir $f))) { $srcMissing += $f }
}
if ($srcMissing.Count -eq 0) {
    Add-Row 'Source upload readiness' 'READY' 'All 4 upload documents present'
} else {
    Add-Row 'Source upload readiness' 'INCOMPLETE' "Missing: $($srcMissing -join ', ')"
}

# -- 4b. Packaging controls ------------------------------------------------------

$controlDocs = @(
    'docs\submission\PACKAGING_RUNBOOK.md',
    'docs\submission\DELIVERY_CHECKLIST.md',
    'docs\submission\README_SUBMISSION.md',
    'docs\submission\EVIDENCE_REGISTER.md'
)
$controlMissing = @($controlDocs | Where-Object { -not (Test-Path -LiteralPath (Join-Path $RepoRoot $_)) })
if ($controlMissing.Count -eq 0) {
    Add-Row 'Packaging controls' 'READY' 'Runbook, delivery checklist, README and register present'
} else {
    Add-Row 'Packaging controls' 'INCOMPLETE' "Missing: $($controlMissing -join ', ')"
}

# -- 4c. Recording package -------------------------------------------------------

$recDir = Join-Path $RepoRoot 'submission\working\demo_assets'
$recRequired = @(
    'DEMO_SCRIPT.md', 'DEMO_CLICK_PATH.md', 'RECORDING_CHECKLIST.md',
    'FAILURE_TALK_TRACKS.md', 'SCREENSHOT_CHECKLIST.md', 'DEMO_DATA_MANIFEST.md',
    'README.md'
)
$recMissing = @($recRequired | Where-Object { -not (Test-Path -LiteralPath (Join-Path $recDir $_)) })
if ($recMissing.Count -eq 0) {
    Add-Row 'Recording package' 'READY' "$($recRequired.Count) documents present; recording can proceed"
} else {
    Add-Row 'Recording package' 'INCOMPLETE' "Missing: $($recMissing -join ', ')"
}

# -- 5. Docker ------------------------------------------------------------------

$dockerFiles = @('Dockerfile', 'docker-compose.yml', 'docker-compose.yaml', '.dockerignore')
$dockerFound = @()
foreach ($f in $dockerFiles) {
    if (Test-Path -LiteralPath (Join-Path $RepoRoot $f)) { $dockerFound += $f }
}
if ($dockerFound.Count -eq 0) {
    Add-Row 'Docker' 'MISSING' 'No Dockerfile. Declared MISSING, not claimed anywhere'
} else {
    Add-Row 'Docker' 'PRESENT' ($dockerFound -join ', ')
}

# -- 6. Content scans -----------------------------------------------------------

$scanRoots = @(
    (Join-Path $RepoRoot 'submission'),
    (Join-Path $RepoRoot 'source_submission'),
    (Join-Path $RepoRoot 'docs\submission')
) | Where-Object { Test-Path -LiteralPath $_ }

$scanFiles = Get-ChildItem -Path $scanRoots -Recurse -File -Include *.md, *.txt -ErrorAction SilentlyContinue

# Secret scan: real assignments only, not the words "api key" in prose.
$secretPattern = '(sk-[A-Za-z0-9]{16,})|(AKIA[0-9A-Z]{12,})|((?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["'']?[A-Za-z0-9_\-]{16,})'
$secretHits = @()
foreach ($f in $scanFiles) {
    $m = Select-String -LiteralPath $f.FullName -Pattern $secretPattern -AllMatches -ErrorAction SilentlyContinue
    if ($m) { $secretHits += $m }
}
if ($secretHits.Count -eq 0) {
    Add-Row 'Secret scan' 'PASS' "$($scanFiles.Count) files scanned, no credential assignments"
} else {
    Add-Row 'Secret scan' 'FAIL' "$($secretHits.Count) potential secret(s)"
}

# PHI scan: real-looking identifiers in submission-facing text.
$phiPattern = '\b\d{3}-\d{2}-\d{4}\b'
$phiHits = @()
foreach ($f in $scanFiles) {
    $m = Select-String -LiteralPath $f.FullName -Pattern $phiPattern -AllMatches -ErrorAction SilentlyContinue
    if ($m) { $phiHits += $m }
}
if ($phiHits.Count -eq 0) {
    Add-Row 'PHI scan' 'PASS' 'No SSN-pattern identifiers in submission text'
} else {
    Add-Row 'PHI scan' 'REVIEW' "$($phiHits.Count) SSN-pattern match(es)"
}

# Organiser data scan: organiser payloads must not sit inside the packaged folder.
$organiserHits = @()
if (Test-Path -LiteralPath $Final) {
    $organiserHits = Get-ChildItem -Path $Final -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.pdf', '.tif', '.tiff', '.png', '.jpg', '.jpeg') } |
        Where-Object { $_.Name -notin @('01_Executive_Summary.pdf', '02_Architecture.pdf') }
}
if ($organiserHits.Count -eq 0) {
    Add-Row 'Organiser-data scan' 'PASS' 'No stray document images in submission/final'
} else {
    Add-Row 'Organiser-data scan' 'FAIL' "$($organiserHits.Count) unexpected image/pdf file(s)"
}

# -- 7. Packaging blockers -------------------------------------------------------

$markerPath = Join-Path $Final 'README_RECORDING_REQUIRED.txt'
$markerPresent = Test-Path -LiteralPath $markerPath
if ($markerPresent) {
    Add-Row 'Recording marker' 'PRESENT' 'Must be deleted before packaging'
} else {
    Add-Row 'Recording marker' 'ABSENT' 'Not blocking packaging'
}

$zipPath = Join-Path $RepoRoot 'submission\DXtraAI_HealthcareAIHackathon.zip'
if (Test-Path -LiteralPath $zipPath) {
    Add-Row 'Final ZIP' 'BUILT' $zipPath
} else {
    if ($demoState -eq 'RECORDING_REQUIRED') {
        Add-Row 'Final ZIP' 'BLOCKED_ONLY_BY_MP4' 'Not built. All other inputs ready'
    } else {
        Add-Row 'Final ZIP' 'NOT_BUILT' 'Run scripts/finalize_submission.ps1'
    }
}

# -- Output ----------------------------------------------------------------------

$Rows | Format-Table -AutoSize -Wrap

# A missing recording is an expected state, not a validation failure. It keeps the
# package blocked, but the readiness run itself still succeeds so this script can be
# used as a green pre-recording gate. Anything genuinely wrong exits non-zero.
$awaitingRecording = ($demoState -eq 'RECORDING_REQUIRED')

$blocking = @()
if ($execState  -ne 'VALID') { $blocking += 'Executive Summary invalid' }
if ($archState  -ne 'VALID') { $blocking += 'Architecture invalid' }
if ($benchState -ne 'VALID') { $blocking += 'Benchmark invalid' }
if ($demoState -notlike 'VALID*' -and -not $awaitingRecording) { $blocking += "Demo MP4 $demoState" }
if ($secretHits.Count    -gt 0) { $blocking += 'Secret scan failed' }
if ($organiserHits.Count -gt 0) { $blocking += 'Organiser-data scan failed' }
if ($srcMissing.Count     -gt 0) { $blocking += 'Source upload documents incomplete' }
if ($controlMissing.Count -gt 0) { $blocking += 'Packaging control documents incomplete' }
if ($recMissing.Count     -gt 0) { $blocking += 'Recording package incomplete' }
if ($artifactsFailed) { $blocking += 'Artifact deep validation failed' }

Write-Host '----------------------------------------------------------------'
if ($blocking.Count -gt 0) {
    Write-Host ' FINALIZATION ELIGIBILITY: NOT ELIGIBLE' -ForegroundColor Yellow
    foreach ($b in $blocking) { Write-Host "   - $b" }
} elseif ($awaitingRecording) {
    Write-Host ' FINALIZATION ELIGIBILITY: BLOCKED_ONLY_BY_MP4' -ForegroundColor Cyan
    Write-Host ''
    Write-Host ' Everything that can be prepared without a human is prepared.'
    Write-Host ' Remaining manual action:'
    Write-Host '   1. Record the demo and save it as submission/final/03_Demo.mp4'
    Write-Host '   2. Delete submission/final/README_RECORDING_REQUIRED.txt'
    Write-Host '   3. Re-run this script, then scripts/finalize_submission.ps1'
} else {
    Write-Host ' FINALIZATION ELIGIBILITY: ELIGIBLE' -ForegroundColor Green
    if ($markerPresent) {
        Write-Host ' Delete README_RECORDING_REQUIRED.txt, then run finalize_submission.ps1'
    } else {
        Write-Host ' Run scripts/finalize_submission.ps1'
    }
}
Write-Host '----------------------------------------------------------------'
Write-Host ''

# Exit 0 for both ELIGIBLE and BLOCKED_ONLY_BY_MP4; non-zero only for real defects.
if ($blocking.Count -eq 0) { exit 0 }
exit 1
