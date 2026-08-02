<#
.SYNOPSIS
    Builds the final email ZIP for Team DXtra AI - ClaimRoute AI.

.DESCRIPTION
    Packages exactly four files, flat, into
    submission/DXtraAI_HealthcareAIHackathon.zip:

        01_Executive_Summary.pdf
        02_Architecture.pdf
        03_Demo.mp4
        05_Benchmark.xlsx

    The script refuses rather than guesses. It will not produce a
    correctly-named ZIP unless every required file is present, non-empty, and
    structurally valid, and unless submission/final contains nothing else.

    The ZIP is assembled under a temporary name and only renamed to the delivery
    name after the built archive has been reopened and its exact root contents
    verified. A half-built or wrongly-populated archive never carries the name
    that gets emailed.

.EXAMPLE
    .\scripts\finalize_submission.ps1

.EXAMPLE
    .\scripts\finalize_submission.ps1 -WhatIf
    Runs every check and reports the verdict without writing anything.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.IO.Compression.FileSystem

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Final    = Join-Path $RepoRoot 'submission\final'
$ZipName  = 'DXtraAI_HealthcareAIHackathon.zip'
$ZipPath  = Join-Path $RepoRoot "submission\$ZipName"
$TempZip  = Join-Path $RepoRoot 'submission\.finalize.partial.zip'

# Exactly these four, in this order, at the ZIP root. Nothing else.
$Required = @(
    '01_Executive_Summary.pdf',
    '02_Architecture.pdf',
    '03_Demo.mp4',
    '05_Benchmark.xlsx'
)

# Anything matching these must never enter the package.
$ForbiddenNames = @('README_RECORDING_REQUIRED.txt', '.env', '.env.local', 'credentials.json')
$ForbiddenExt   = @(
    '.md', '.py', '.ps1', '.ps1xml', '.psm1', '.sh', '.bat', '.cmd',
    '.json', '.jsonl', '.yaml', '.yml', '.csv', '.txt', '.log',
    '.key', '.pem', '.pfx', '.env', '.ini', '.cfg', '.toml',
    '.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp', '.gif',
    '.zip', '.7z', '.rar', '.tar', '.gz'
)

$problems = @()
$notes    = @()

function Fail {
    param([string]$Message)
    $script:problems += $Message
}

Write-Host ''
Write-Host '================================================================'
Write-Host ' ClaimRoute AI - Finalize Submission'
Write-Host ' Team DXtra AI'
Write-Host '================================================================'
Write-Host ''

# -- 1. The final folder itself -------------------------------------------------

if (-not (Test-Path -LiteralPath $Final)) {
    Fail "submission/final does not exist."
    Write-Host " submission/final is missing. Nothing to package."
    Write-Host ''
    exit 1
}

$subfolders = @(Get-ChildItem -LiteralPath $Final -Directory -Force -ErrorAction SilentlyContinue)
if ($subfolders.Count -gt 0) {
    Fail "submission/final contains subfolder(s): $(($subfolders | ForEach-Object { $_.Name }) -join ', '). The package must be flat."
}

$present = @(Get-ChildItem -LiteralPath $Final -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne '.gitkeep' })

# -- 2. Required files ----------------------------------------------------------

Write-Host 'Required files'
$missing = @()
foreach ($name in $Required) {
    $path = Join-Path $Final $name
    if (-not (Test-Path -LiteralPath $path)) {
        $missing += $name
        Write-Host ("  MISSING  {0}" -f $name)
        continue
    }
    $len = (Get-Item -LiteralPath $path).Length
    if ($len -le 0) {
        Fail "$name is zero bytes."
        Write-Host ("  EMPTY    {0}" -f $name)
    } else {
        Write-Host ("  OK       {0}  ({1:N0} bytes)" -f $name, $len)
    }
}

$mp4Missing = $missing -contains '03_Demo.mp4'
foreach ($name in $missing) {
    if ($name -eq '03_Demo.mp4') {
        Fail "03_Demo.mp4 has not been recorded yet."
    } else {
        Fail "$name is missing. Generate it with scripts/submission/."
    }
}
Write-Host ''

# -- 3. Nothing unexpected ------------------------------------------------------

Write-Host 'Package contents'
foreach ($file in $present) {
    if ($Required -contains $file.Name) { continue }

    if ($file.Name -eq 'README_RECORDING_REQUIRED.txt' -and $mp4Missing) {
        # The marker exists precisely because the recording does not. While that is
        # true it is not a second, independent problem - it is the same one. It
        # becomes a blocker once the MP4 lands and the marker was not cleaned up.
        Write-Host ("  PENDING  {0}  (delete once 03_Demo.mp4 exists)" -f $file.Name)
    } elseif ($ForbiddenNames -contains $file.Name) {
        Fail "$($file.Name) must be removed from submission/final before packaging."
        Write-Host ("  REJECT   {0}  (must be deleted first)" -f $file.Name)
    } elseif ($ForbiddenExt -contains $file.Extension.ToLower()) {
        Fail "$($file.Name) is not a deliverable and must not be packaged."
        Write-Host ("  REJECT   {0}  (disallowed type {1})" -f $file.Name, $file.Extension)
    } else {
        Fail "$($file.Name) is unexpected. Only the four deliverables may be present."
        Write-Host ("  REJECT   {0}  (unexpected)" -f $file.Name)
    }
}
if ($present.Count -eq $Required.Count -and $problems.Count -eq 0) {
    Write-Host '  Exactly the four deliverables, nothing else.'
}
Write-Host ''

# -- 4. Structural validation ---------------------------------------------------

Write-Host 'Structural validation'

function Test-PdfStructure {
    param([string]$Path, [string]$Label)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ([System.Text.Encoding]::ASCII.GetString($bytes[0..4]) -ne '%PDF-') {
        Fail "$Label is not a PDF (bad signature)."
        Write-Host ("  FAIL     {0}  bad %PDF- signature" -f $Label)
        return
    }
    $tailLen = [Math]::Min(2048, $bytes.Length)
    $tail = [System.Text.Encoding]::ASCII.GetString($bytes[($bytes.Length - $tailLen)..($bytes.Length - 1)])
    if ($tail -notmatch '%%EOF') {
        Fail "$Label is truncated (no %%EOF)."
        Write-Host ("  FAIL     {0}  truncated, no %%EOF" -f $Label)
        return
    }
    Write-Host ("  OK       {0}  valid PDF, opens to EOF" -f $Label)
}

function Test-XlsxStructure {
    param([string]$Path, [string]$Label)
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    } catch {
        Fail "$Label could not be opened as a workbook: $($_.Exception.Message)"
        Write-Host ("  FAIL     {0}  will not open as a workbook" -f $Label)
        return
    }
    try {
        $names = $archive.Entries | ForEach-Object { $_.FullName }
        if ($names -notcontains '[Content_Types].xml') {
            Fail "$Label is not a valid Office Open XML package."
            Write-Host ("  FAIL     {0}  missing [Content_Types].xml" -f $Label)
            return
        }
        if (-not ($names -match '^xl/workbook\.xml$')) {
            Fail "$Label has no workbook part."
            Write-Host ("  FAIL     {0}  missing xl/workbook.xml" -f $Label)
            return
        }
        $sheets = @($names | Where-Object { $_ -match '^xl/worksheets/sheet\d+\.xml$' })
        $charts = @($names | Where-Object { $_ -match '^xl/charts/chart\d+\.xml$' })
        Write-Host ("  OK       {0}  valid workbook, {1} sheets, {2} charts" -f $Label, $sheets.Count, $charts.Count)
    } finally {
        $archive.Dispose()
    }
}

function Test-Mp4Structure {
    param([string]$Path, [string]$Label)

    # An MP4 begins with a box header whose type is 'ftyp' at bytes 4..7.
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $head = New-Object byte[] 12
        $null = $stream.Read($head, 0, 12)
    } finally {
        $stream.Dispose()
    }
    $boxType = [System.Text.Encoding]::ASCII.GetString($head[4..7])
    if ($boxType -ne 'ftyp') {
        Fail "$Label is not an MP4 container (no ftyp box)."
        Write-Host ("  FAIL     {0}  no ftyp box, found '{1}'" -f $Label, $boxType)
        return
    }

    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($null -eq $ffprobe) {
        $script:notes += 'ffprobe not installed: stream and duration checks were skipped. Play the file manually before sending.'
        Write-Host ("  OK       {0}  valid ftyp container (ffprobe unavailable, streams unverified)" -f $Label)
        return
    }

    $streams = & $ffprobe.Source -v error -show_entries stream=codec_type -of csv=p=0 $Path
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label could not be probed; the file is likely corrupt."
        Write-Host ("  FAIL     {0}  ffprobe could not read it" -f $Label)
        return
    }
    $joined = ($streams -join ',')
    if ($joined -notmatch 'video') {
        Fail "$Label has no video stream."
        Write-Host ("  FAIL     {0}  no video stream" -f $Label)
        return
    }
    if ($joined -notmatch 'audio') {
        Fail "$Label has no audio stream."
        Write-Host ("  FAIL     {0}  no audio stream" -f $Label)
        return
    }

    $durationRaw = & $ffprobe.Source -v error -show_entries format=duration -of csv=p=0 $Path
    $seconds = 0.0
    [void][double]::TryParse($durationRaw, [ref]$seconds)
    if ($seconds -le 0) {
        Fail "$Label reports no duration."
        Write-Host ("  FAIL     {0}  zero duration" -f $Label)
        return
    }
    if ($seconds -gt 600) {
        Fail ("$Label is {0:N2} minutes, over the 10-minute organiser cap." -f ($seconds / 60))
        Write-Host ("  FAIL     {0}  {1:N2} min exceeds the 10-minute cap" -f $Label, ($seconds / 60))
        return
    }
    if ($seconds -lt 420) {
        $script:notes += ("03_Demo.mp4 is {0:N2} minutes, under the 7-minute target. Allowed, but confirm it covers the full script." -f ($seconds / 60))
    }
    Write-Host ("  OK       {0}  video+audio, {1:N2} min" -f $Label, ($seconds / 60))
}

foreach ($name in @('01_Executive_Summary.pdf', '02_Architecture.pdf')) {
    $path = Join-Path $Final $name
    if (Test-Path -LiteralPath $path) { Test-PdfStructure $path $name }
}
$benchPath = Join-Path $Final '05_Benchmark.xlsx'
if (Test-Path -LiteralPath $benchPath) { Test-XlsxStructure $benchPath '05_Benchmark.xlsx' }
$demoPath = Join-Path $Final '03_Demo.mp4'
if (Test-Path -LiteralPath $demoPath) {
    Test-Mp4Structure $demoPath '03_Demo.mp4'
} else {
    Write-Host '  PENDING  03_Demo.mp4  not recorded'
}
Write-Host ''

# -- 5. Verdict before writing anything -----------------------------------------

if ($problems.Count -gt 0) {
    Write-Host '----------------------------------------------------------------'
    Write-Host ' REFUSED - no ZIP was created' -ForegroundColor Yellow
    Write-Host ''
    foreach ($p in $problems) { Write-Host "   - $p" }
    Write-Host ''

    $onlyMp4 = ($problems.Count -eq 1 -and $mp4Missing)
    if ($onlyMp4) {
        Write-Host ' This is the expected pre-recording state.'
        Write-Host ' Everything except the demo recording is ready to package.'
        Write-Host ''
        Write-Host ' To unblock:'
        Write-Host '   1. Record the demo (submission/working/demo_assets/DEMO_SCRIPT.md)'
        Write-Host '   2. Save it as submission/final/03_Demo.mp4'
        Write-Host '   3. Delete submission/final/README_RECORDING_REQUIRED.txt'
        Write-Host '   4. Re-run this script'
    }
    Write-Host '----------------------------------------------------------------'
    Write-Host ''
    exit 1
}

# -- 6. Build ------------------------------------------------------------------

if (-not $PSCmdlet.ShouldProcess($ZipPath, 'Create submission ZIP')) {
    Write-Host ' All checks passed. -WhatIf specified, so nothing was written.'
    Write-Host ''
    exit 0
}

if (Test-Path -LiteralPath $TempZip) { Remove-Item -LiteralPath $TempZip -Force }

$archive = [System.IO.Compression.ZipFile]::Open($TempZip, 'Create')
try {
    foreach ($name in $Required) {
        $null = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, (Join-Path $Final $name), $name, 'Optimal')
    }
} finally {
    $archive.Dispose()
}

# -- 7. Verify the built archive before it takes the delivery name --------------

Write-Host 'Built archive verification'
$verify = [System.IO.Compression.ZipFile]::OpenRead($TempZip)
try {
    $entries = @($verify.Entries | ForEach-Object { $_.FullName })
    $nested  = @($entries | Where-Object { $_ -match '[\\/]' })
    $extra   = @($entries | Where-Object { $Required -notcontains $_ })
    $absent  = @($Required | Where-Object { $entries -notcontains $_ })
    $empty   = @($verify.Entries | Where-Object { $_.Length -le 0 } | ForEach-Object { $_.FullName })

    if ($nested.Count -gt 0)  { Fail "Archive contains folders: $($nested -join ', ')" }
    if ($extra.Count -gt 0)   { Fail "Archive contains unexpected entries: $($extra -join ', ')" }
    if ($absent.Count -gt 0)  { Fail "Archive is missing: $($absent -join ', ')" }
    if ($empty.Count -gt 0)   { Fail "Archive contains zero-byte entries: $($empty -join ', ')" }
    if ($entries.Count -ne 4) { Fail "Archive has $($entries.Count) root entries, expected exactly 4." }

    if ($problems.Count -eq 0) {
        Write-Host ("  OK       exactly {0} root entries, no folders" -f $entries.Count)
        foreach ($e in $verify.Entries) {
            Write-Host ("             {0}  ({1:N0} bytes)" -f $e.FullName, $e.Length)
        }
    }
} finally {
    $verify.Dispose()
}

if ($problems.Count -gt 0) {
    Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host '----------------------------------------------------------------'
    Write-Host ' REFUSED - built archive failed verification and was deleted' -ForegroundColor Red
    foreach ($p in $problems) { Write-Host "   - $p" }
    Write-Host '----------------------------------------------------------------'
    Write-Host ''
    exit 1
}

if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Move-Item -LiteralPath $TempZip -Destination $ZipPath -Force
Write-Host ''

# -- 8. Hashes ------------------------------------------------------------------

Write-Host 'SHA-256'
foreach ($name in $Required) {
    $hash = (Get-FileHash -LiteralPath (Join-Path $Final $name) -Algorithm SHA256).Hash
    Write-Host ("  {0}  {1}" -f $hash.ToLower(), $name)
}
$zipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
Write-Host ("  {0}  {1}" -f $zipHash.ToLower(), $ZipName)
Write-Host ''

Write-Host '----------------------------------------------------------------'
Write-Host ' PACKAGED' -ForegroundColor Green
Write-Host ("   {0}  ({1:N0} bytes)" -f $ZipPath, (Get-Item -LiteralPath $ZipPath).Length)
Write-Host ''
Write-Host ' Email to: ClaimsExtraction.Hackathon@datamatics.com'
Write-Host ' Source archive goes to SharePoint separately; see'
Write-Host ' source_submission/SOURCE_UPLOAD_CHECKLIST.md'
if ($notes.Count -gt 0) {
    Write-Host ''
    Write-Host ' Notes:'
    foreach ($n in $notes) { Write-Host "   - $n" }
}
Write-Host '----------------------------------------------------------------'
Write-Host ''
exit 0
