# Euphoria — AI Video Editor

Transcript-driven, offline-first video editor for Indian-language talking-head videos.
Built by **Team Euphoria** for the **AI BHOOMI** programme.

**Demo:** _TODO — add live demo link_ · **Demo video:** _TODO — add 2-minute recording link_

---

## Problem statement

Indian creators and educators spend hours per video cutting pauses, fumbles and retakes, and captioning by hand.
Existing AI editors are built for English-speaking marketing teams, handle Malayalam and code-mixed (Manglish)
speech poorly, and stop at the edit instead of helping the creator grow.

## Users & context

- **Primary:** Malayalam and Manglish talking-head creators (Instagram Reels, YouTube Shorts and long-form).
- **Secondary:** educators (teachers, coaching institutes) and small businesses using the same talking-head format.
- **Context:** creators often record on phones, edit on modest Windows PCs, and mix Malayalam, Hindi and English
  in one sentence. The app runs locally on the creator's PC; AI features use an API key or the team's Claude account.

## Solution overview

Upload a raw clip → the app transcribes it with word timestamps → suggests cuts (long pauses, fillers, retakes)
→ you click words to cut/restore or type edits in chat ("make a 30-second reel of the best part") → it renders an
MP4 with captions, evened audio and optional style, b-roll, sound and 9:16 reel format.

The edit is stored as **video as code** (`edit.yaml`): the AI only proposes word IDs and settings, and FFmpeg
renders deterministically.

```mermaid
flowchart LR
    A[Raw video] --> B[Transcribe<br/>faster-whisper + VAD<br/>word timestamps]
    B --> C[Plan<br/>pauses, fillers → cuts]
    C --> D[AI edits<br/>retakes, chat<br/>returns word IDs]
    D --> E{Validate IDs<br/>+ limits}
    E -->|valid| F[edit.yaml<br/>video as code]
    E -->|invalid| X[dropped]
    F --> G[Captions .ass<br/>from transcript]
    F --> H[Style / B-roll / SFX / Reel 9:16]
    G --> I[FFmpeg render<br/>H.264 + loudness norm]
    H --> I
    I --> J[Final MP4 + SRT/VTT + post kit]
```

| Module | File(s) | Role |
|---|---|---|
| Transcribe | `app/editor/transcribe.py` | faster-whisper, per-language models, optional OpenAI whisper-1 |
| Plan | `app/editor/plan.py` | removed words + long pauses → cut list (`edit.yaml`) |
| AI edits | `app/editor/aiedit.py`, `app/editor/llm.py` | retake detection, chat edits, ID validation |
| Captions | `app/editor/captions.py` | caption lines on edited timeline |
| Render | `app/editor/render.py` | single FFmpeg pass |
| Finishing | `style.py`, `timeline.py`, `broll.py`, `sfx.py` | titles, keyword pops, b-roll, synthesised SFX, music ducking |
| Reels / growth | `reel.py`, `montage.py`, `grow.py`, `extras*.py` | 9:16 reels, beat-sync montage, starter kit & scripts, exports |
| Claude reel studio | `app/reel_agent/creator-reel/` | one Claude call returns a JSON plan; build + render without AI |
| Web | `app/editor/server.py`, `app/web/` | FastAPI backend + review page; landing page in `website/` |

Full feature details: [`app/README.md`](app/README.md). Business plan and pitch: [`docs/`](docs/).

## Setup & run

Tested on Windows 10/11. Needs Python 3.12, FFmpeg, and (for the reel studio) Node.js.

1. **Clone**
   ```
   git clone https://github.com/Sakhil-N-Maju/Euphoria_ai_boomi.git
   cd Euphoria_ai_boomi
   ```
2. **Runtimes** — either:
   - *Portable (what `run.bat` expects):* put portable Python in `tools/python/`, FFmpeg in `tools/ffmpeg/bin/`,
     Node in `tools/node/`; or
   - *System install:* install Python 3.12, FFmpeg (on `PATH`) and Node.js.
3. **Python packages**
   ```
   pip install -r app/requirements.txt
   ```
4. **Speech-to-text models** (one time, ~1.5 GB for Malayalam) — run `app\download_models.bat`
   (or `python app/download_models.py`). Models land in `models/`.
5. **API key (optional, for AI edits)** — copy `app/.env.example` to `app/.env` and set `LLM_API_KEY`
   (any OpenAI-compatible provider; model in `app/config.yaml` or `LLM_MODEL`).
6. **Run**
   - Portable: double-click `app\run.bat`
   - System Python: `cd app` then `python -m editor.server`

   Open http://127.0.0.1:8000 (editor) or http://127.0.0.1:8000/site (website + Claude reel studio).
7. **Reel studio (optional)** — run `app\setup_reel.bat` once, or use the "Set up this PC" panel on `/site`.
8. **CLI**
   ```
   app\edit.bat "C:\videos\talk.mp4" --lang ml --retakes
   ```
9. **Tests**
   ```
   cd app
   python -m unittest discover tests
   ```

## Models & data

| Item | Source | Licence |
|---|---|---|
| Whisper small (CTranslate2) | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) | MIT |
| Malayalam STT | [adalat-ai/ct2-whisper-medium-ml-rmft](https://huggingface.co/adalat-ai/ct2-whisper-medium-ml-rmft) | Apache-2.0 |
| Cloud STT (optional) | OpenAI `whisper-1` API | Provider terms |
| LLM for retakes / chat / b-roll / growth (optional) | Any OpenAI-compatible API; default `gpt-4.1-mini` | Provider terms |
| Reel planner | Claude via Claude Code (`claude -p`), signed-in account | Anthropic terms — team use only; public product needs API keys |
| Person cut-out | `u2net_human_seg` (rembg releases) | See rembg / U²-Net repos |
| Fonts | Fontsource / Google Fonts (incl. Noto Sans Malayalam) | SIL Open Font License |
| Sound effects | Synthesised in code (`app/editor/sfx.py`), no sample packs | Ours |
| Colour LUT "Look 01" | by @shakirc.ai | Not redistributed — kept out of git |
| Libraries | FastAPI, Uvicorn, faster-whisper, CTranslate2, NumPy, SciPy, OpenCV, ONNX Runtime, Playwright, PyYAML, FFmpeg | MIT / BSD / Apache-2.0 / LGPL (FFmpeg) |

**Data:** only self-recorded clips with consent are used for testing (`assets/` holds sample outputs).
User videos stay on the user's PC and are **not** used for training. Uploaded jobs and renders live in
`app/data/` (git-ignored).

## Evaluation & guardrails

**Hallucination mitigations**
- The LLM never writes captions or video content: it only returns **word IDs** from the transcript.
  Captions always come from the transcript.
- Every returned ID is checked against the transcript; invalid IDs are dropped.
- Hard limits: one retake can remove ≤ 80 words; all retakes together ≤ 50 % of the video; no edit may cut every word.
- Length requests ("30-second reel") are verified after the edit and adjusted once if missed.
- Every AI change is shown in the transcript (e.g. retakes in yellow, corrected caption words underlined)
  and can be **undone**; "Restore original words" reverts caption fixes.
- Growth tools never invent numbers — estimates are labelled "est." — and never log into, scrape or act on
  Instagram.
- Claude reel planner reads only the transcript, has no tools, and must return JSON matching
  `prompts/plan_schema.json`; build and render are deterministic.

**Bias / fairness mitigations**
- Language-specific STT model for Malayalam instead of an English-centric default; language picked or auto-detected.
- Chat edits accepted in Malayalam, Hindi and English; keyword picking falls back to the AI for non-English speech
  (rule-based picks are English-biased).
- Colour looks grade b-roll only by default, so the presenter's skin tone is left untouched; Look 01 warns when
  footage isn't S-Log3.

**Evaluation**
- Unit tests in `app/tests/` (plan, AI-edit validation, finishing, reels/montage/grow, marketplace skills).
- `app/compare_stt.bat` compares Whisper small vs the Malayalam model vs whisper-1 on a clip (speed, timestamp
  sanity, transcripts for counting errors).
- "Review render" sends frames of the render to a vision model to list problems with timestamps.

## Known limitations & risks

- **STT accuracy:** Malayalam model's published WER ≈ 40 %; Whisper small is weak on Malayalam and code-mixed
  speech. Word-timestamp quality of the Malayalam model is undocumented — check cut points.
- **Speed:** the medium Malayalam model is several times slower than small on CPU.
- **Fillers:** Whisper often omits "um/uh"; short ones may survive the cut.
- **Single speaker / talking-head focus;** split-screen reframing assumes a centred face.
- **Rule-based keyword picks** work best in English.
- **Third-party AI dependency:** AI features need an API key or Claude account; cost and terms vary; Claude
  account mode is for team use only.
- **Licensing:** LUTs and some reused skill assets belong to others — LUTs are excluded from the repo; any
  reused code must keep its licence and attribution.
- **Privacy:** videos stay local, but transcripts (and frames, for Review render / b-roll matching) are sent to the
  chosen AI provider when AI features are used.
- **Not included:** dubbing, voice cloning, TTS, lip-sync.

## Team

**Team Euphoria**

| Name | Role | Contact |
|---|---|---|
| Sakhil N Maju | Backend & AI Lead — speech-to-text, edit-list logic, LLM prompts and guardrails, FFmpeg rendering, API | sakhil.n.maju123@gmail.com · [LinkedIn](https://linkedin.com/in/sakhil-n-maju) |
| Nima Fathima | Product & Frontend Lead — web UI and website, demo, pitch deck, README, presenting | nimafathimapr@gmail.com · [LinkedIn](https://www.linkedin.com/in/nimafathima) |

---

### Repository layout

| Folder | Contents |
|---|---|
| `app/` | Editor code, web UI, reel agent, CLI, tests |
| `website/` | Landing page |
| `docs/` | Startup plan, AIBoomi Kochi build plan, mentor pitch, pitch deck (PDF + PPTX) |
| `assets/` | Sample rendered outputs |

## License

[MIT](LICENSE) © 2026 Team Euphoria. Third-party models, fonts, LUTs and reused skill assets keep their own
licences (see *Models & data*); the MIT licence covers the team's own code.

Git-ignored (set up locally): `tools/`, `models/`, `app/data/`, `app/.env`, `app/luts/*.cube`.
