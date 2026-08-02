# Recording and audio checklist

## Recording

- [ ] Record at 1920x1080, 30 fps, with the app at 100% browser zoom.
- [ ] Close email, chat, password managers, terminals with environment output, and notifications.
- [ ] Use a fresh browser window with no personal bookmarks or account avatar visible.
- [ ] Keep screenshot-safe mode on except for the two confirmed bundled synthetic samples.
- [ ] Pre-run the clean sample and verify 46 local accepts, 0 retries, 0 escalations, 0 review.
- [ ] Pre-run the ugly sample; if it differs, use the committed receipt instead of improvising.
- [ ] Open the PDFs and backup PNGs before recording.
- [ ] Follow `10_minute_spoken_script.md` and `demo_sequence.md` exactly.
- [ ] Do not show official source files, filenames, record values, crops, or organiser folders.
- [ ] Do not show `.env`, environment variables, API keys, terminal history, or browser developer tools.
- [ ] Export as `submission/03_Demo.mp4` only after the final take is selected.

## Audio

- [ ] Use a dedicated microphone where possible; select it explicitly in the recorder.
- [ ] Record 10 seconds of room tone and listen for fan, traffic, hum, or keyboard noise.
- [ ] Keep peaks between -12 dBFS and -6 dBFS; avoid clipping.
- [ ] Disable automatic gain control if it pumps or raises background noise.
- [ ] Use headphones to prevent speaker feedback.
- [ ] Speak at a steady 115-125 words per minute and pause briefly after headline metrics.
- [ ] Play the exported MP4 from start to finish with headphones.
- [ ] Confirm speech exists on both channels and stays synchronized with the screen.

## Failure talk tracks

**Streamlit fails:** “The interface is a thin layer over the tested extraction service. I will use
the committed synthetic-safe visuals and immutable aggregate receipts loaded by the application.”

**OCR varies:** “OCR timing and candidates can vary by workstation. I will not substitute a
better-looking result. The submission claim comes from the frozen commit and receipts.”

**No internet:** “The judged path is local and synthetic. No external API is required. The
multimodal boundary is demonstrated by the deterministic offline oracle and audit evidence.”

**Ugly sample differs:** “This live variance is why ClaimRoute keeps receipts and routes uncertainty
instead of hiding it. I will show the committed pretested synthetic receipt.”

## MP4 validation gate

- [ ] Exact filename: `03_Demo.mp4`.
- [ ] `ffprobe` reports a video stream and an audio stream.
- [ ] Duration is recorded and within the organiser limit.
- [ ] The file plays from beginning to end without corruption.
- [ ] Frame sampling shows no PHI, organiser records, secrets, or personal notifications.
- [ ] Only after all checks pass may the final four-file ZIP be created.
