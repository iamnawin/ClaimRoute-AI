================================================================================
ACTION REQUIRED: 03_Demo.mp4 IS MISSING
Team DXtra AI - ClaimRoute AI
Datamatics AI Engineering Hackathon 2026
================================================================================

This folder is NOT ready to package. Three of the four required deliverables are
present and validated. The demo recording does not exist and must be recorded by
a human.

--------------------------------------------------------------------------------
WHAT IS REQUIRED
--------------------------------------------------------------------------------

  Filename (exact):  03_Demo.mp4
  Location:          submission/final/03_Demo.mp4

  Recommended duration:  7 to 9 minutes
  Maximum duration:      10 minutes (organiser cap)

--------------------------------------------------------------------------------
CURRENT FOLDER STATE
--------------------------------------------------------------------------------

  [PRESENT]  01_Executive_Summary.pdf
  [PRESENT]  02_Architecture.pdf
  [MISSING]  03_Demo.mp4          <-- record this
  [PRESENT]  05_Benchmark.xlsx

--------------------------------------------------------------------------------
MUST NOT APPEAR IN THE RECORDING
--------------------------------------------------------------------------------

  - PHI of any kind
  - API keys, credentials, or .env contents
  - Desktop or application notifications
  - Sensitive local absolute paths (for example D:\AI-Workspace\...)
  - Organiser source documents, filenames, folders, or expected outputs
  - Terminal history or environment-variable output
  - Browser developer tools

The bundled demo samples are fully synthetic and carry zero PHI by construction.

--------------------------------------------------------------------------------
HOW TO RECORD
--------------------------------------------------------------------------------

  Narration script    submission/demo_assets/10_minute_spoken_script.md
  7-9 minute cut      submission/working/demo_assets/DEMO_SCRIPT.md
  Click path          submission/working/demo_assets/DEMO_CLICK_PATH.md
  Pre-flight checks   submission/working/demo_assets/RECORDING_CHECKLIST.md
  If something breaks submission/working/demo_assets/FAILURE_TALK_TRACKS.md
  Backup visuals      submission/working/demo_assets/SCREENSHOT_CHECKLIST.md
  Permitted data      submission/working/demo_assets/DEMO_DATA_MANIFEST.md

--------------------------------------------------------------------------------
AFTER ADDING THE RECORDING
--------------------------------------------------------------------------------

  1. Place the file at:  submission/final/03_Demo.mp4

  2. Check readiness:
       .\scripts\validate_submission_readiness.ps1

  3. Build the final ZIP:
       .\scripts\finalize_submission.ps1

     This creates submission/DXtraAI_HealthcareAIHackathon.zip containing
     exactly four root-level files and no subfolders.

  4. Delete this file. finalize_submission.ps1 refuses to package while
     README_RECORDING_REQUIRED.txt is present in submission/final/.

================================================================================
