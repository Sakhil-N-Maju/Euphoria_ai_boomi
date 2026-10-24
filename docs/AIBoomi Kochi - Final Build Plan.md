# AIBoomi Kochi — Final Build Plan

Oct 23, 2026 · Team Euphoria

Online version: https://claude.ai/code/artifact/c3ca8531-b049-4a05-9c50-ad50dab1166e

## Key facts and deadlines

The real deadline is **Saturday 12:00 PM**, when the submission portal locks — not 4 PM. That gives us 20 hours from the 4:00 PM kickoff today, and we aim to submit by 11:00 AM.

| When | What happens |
| --- | --- |
| Fri 4:00 PM | Kickoff at Kinfra Hi-Tech Park, Kalamassery. Credits handed out at check-in. Declare any prior work here. |
| Fri evening | Dinner provided. Mentors on the floor all night. |
| Sat morning | Breakfast. Workshops (PMF, pitching, first customer) run in parallel — skip unless we are ahead. |
| **Sat 12:00 PM** | **Portal locks.** Repo + README, demo link, deck (6 slides max), AI Impact Statement (200 words max). Late = disqualified. |
| Sat after 12 PM | Round 1: judges at our desk, max 5 min, shortlist Top 5. Finals: 3-min live demo + 2-min Q&A. |

**Conflicts to confirm on the WhatsApp group at kickoff:**

- Finals time: the handbook says Sat 12–2 PM; the approval email says judging and demos run to Sat 4 PM.
- The handbook says "Sat ➝ Sun" in places; that is template text. The event is Fri 4 PM → Sat 4 PM.
- The flagship-event pass is "Feb 2027" in the handbook and "March 2027" in the email. Doesn't affect us.

**Rules that shape the plan:**

- **Fresh build.** Core features must be written after 4 PM. Libraries, boilerplates and model weights are allowed with attribution. If we reuse any code from our earlier video-editor work, we must declare it at kickoff and build the "surprise element" to stay eligible. Recommendation: start clean.
- **Data.** Only open-licensed or self-recorded clips with consent. We record our own test videos.
- **Disqualifiers.** A missed deadline, plagiarism, falsified data. Every number in the demo and deck must come from a real run.
- **Repo needs** README.md (with demo link) and a LICENSE file (MIT).
- Judges score **real-world utility and fundability**: "Ship something small that works > something grand that almost works."

Assumption: we build the AI video editor for Indian-language talking-head videos, as a duo. Open question: who covers the backend and who covers the UI (see Team split).

## The idea in four lines

**One-liner:** Drop in a raw Malayalam, Hindi or Manglish talking-head video and get back a clean, captioned, reel-ready cut in minutes — then change it by typing what you want. Product name: open question, pick one before the deck.

- **Pain:** Creators, teachers and small businesses record long takes full of pauses, "umm / athu / matlab" fillers and retakes. Cleaning one video by hand takes hours on a timeline editor.
- **Who:** Indian-language talking-head creators first; educators, coaches and local businesses are supported with the same tool. Wedge for the demo: Malayalam and code-mixed Manglish creators in Kerala posting reels.
- **Why now:** Multilingual speech-to-text with word timestamps plus LLMs that output structured edits make *edit-by-text* possible for Indian languages, where mainstream editors are English-first.
- **Our insight (video-as-code):** The AI never touches pixels. It writes an edit list (JSON) that points at real transcript words; FFmpeg renders it. Every edit is inspectable, undoable and cheap.
- **Where it goes next:** a growth partner, not just an editor. It connects to the creator's Instagram and YouTube analytics, shows what top creators in their niche do differently, and edits future videos to fix the moments where viewers drop off. Roadmap only for this event: we pitch it, we don't build it.

Validate at the event: ask 2–3 mentors and any creators in the room whether they would pay for this, and quote them in the deck (with permission).

## Demo slice: what we build in 20 hours

The "aha" we must show in the first 45 seconds: **a messy 2-minute Malayalam clip goes in, a tight captioned 9:16 cut comes out, with a real "X seconds removed" number on screen.** Everything else is secondary.

**Must ship (P0) — done by 1 AM**

1. Upload a video; extract audio with FFmpeg (keeps us under the 25 MB API file limit).
2. Transcribe with word-level timestamps; show the transcript.
3. Auto-clean: cut silences longer than a threshold, remove filler words (per-language list + LLM check), drop retakes (LLM spots a repeated sentence and keeps the last take).
4. Text-based editing: strike a word or sentence in the transcript and it is cut from the video.
5. Render with FFmpeg: cuts + burned-in captions in Malayalam script (Noto Sans Malayalam) + 9:16 crop.
6. Before/after player with real stats: original length, new length, number of cuts.

**Should ship (P1) — only after P0 works end to end**

7. Chat edits: "make a 30-second reel of the best part", "remove the part about pricing" → the LLM patches the edit list → re-render.
8. Word-by-word highlighted (karaoke) captions and a punch-in zoom on every cut.
9. Translated captions (Malayalam → English) for reach.

**Won't build (say so on the roadmap slide)**

B-roll, AI dubbing or voice cloning, background music, multi-camera, user accounts, payments, mobile app, analytics connection and retention editing (roadmap slide only).

## Architecture and stack

The LLM only writes a JSON edit list that references transcript word IDs; a validator rejects anything else, and FFmpeg does all the video work.

*[Diagram in the online version: pipeline · transcript → edit list → render]*

Chat commands go through the LLM; striking words in the transcript edits the list directly, with no AI call.

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.11 + FastAPI, one background job per upload | Fastest for us; AI libraries are in Python |
| Frontend | React + Vite + Tailwind | UX is 15% of the score; we need fine control of the player and transcript |
| Speech-to-text | OpenAI `whisper-1` with word timestamps — per [OpenAI's speech-to-text guide](https://developers.openai.com/docs/guides/speech-to-text), the only model that returns them. Compare its Malayalam text against `gpt-transcribe`, OpenAI's recommended model | Word timestamps are what make edit-by-text work |
| LLM | A current GPT model from the event credits, with Structured Outputs (JSON schema = our EDL) | Always returns valid, parseable edits |
| Silence detection | FFmpeg `silencedetect` | Deterministic, free, no AI needed |
| Rendering | FFmpeg trim + concat; captions as an ASS file through the `subtitles` filter with Noto Sans Malayalam; crop to 9:16 | Proper Malayalam script rendering and styled captions |
| Hosting | A Neysa credits VM if it's up within an hour; otherwise run locally for the live demo + screen recording as the link | Rendering on free hosting tiers is slow |
| SerpAPI credits | Not used | Nothing in our flow needs web search; don't add it for show |

**The edit list (EDL) — agree this shape by 5:00 PM**

```json
{
  "source": "clip_01.mp4",
  "keep": [
    {"from_word": 3, "to_word": 41},
    {"from_word": 58, "to_word": 120}
  ],
  "removed": [
    {"words": [0, 2], "reason": "filler"},
    {"words": [42, 57], "reason": "retake"}
  ],
  "captions": {"lang": "ml", "style": "karaoke", "font": "Noto Sans Malayalam"},
  "format": {"aspect": "9:16", "zoom_on_cut": true}
}
```

The renderer maps word IDs to start/end times with a small padding so cuts don't clip syllables. To save credits: cache each transcript by file hash, send the LLM text (never audio), and keep test clips under 3 minutes.

## Hour-by-hour plan

Five gates keep us honest; if a gate slips by more than an hour, cut the next P1 item rather than sleep. **A** = backend/AI, **B** = UI/demo/pitch.

| Time | A (backend + AI) | B (UI + demo + pitch) | Gate at end |
| --- | --- | --- | --- |
| Fri 4:00–5:00 PM | Collect credits, declare prior work (if any). FastAPI skeleton, FFmpeg + STT call on a test clip. | Vite + React skeleton, upload page, video player. Repo, MIT LICENSE, README stub. | Transcript JSON with word timestamps printed for our clip |
| 5:00–9:00 PM | Silence detection, filler list, cut + concat render. Edit-list (EDL) JSON schema v1. | Transcript view with clickable words; upload → job status → result player. | **9 PM:** raw clip in, cleaned MP4 out (ugly UI is fine) |
| 9:00 PM–1:00 AM | Retake detection via LLM (structured JSON output). Malayalam captions as ASS subtitles, 9:16 crop. | Strike-to-cut editing wired to the EDL. Before/after view with real stats. | **1 AM:** all P0 working end to end |
| 1:00–5:00 AM | Chat edits (LLM patches the EDL). Cache transcripts by file hash. B sleeps 1:00–2:30. | Deploy (see stack). Record the fallback demo video. A sleeps 3:30–5:00. | **5 AM:** feature freeze |
| 5:00–9:00 AM | Bug fixes on 3 fresh test clips. Karaoke captions if time. Fill README setup, models, limits. | Deck (6 slides) with real screenshots. AI Impact Statement. Polish UI copy. | **9 AM:** deck + README complete |
| 9:00–11:00 AM | Final deploy check, tag release. | Rehearse the 3-minute demo three times with a timer. | **11 AM:** submitted (1 hour buffer) |
| 11:00 AM–12:00 PM | Buffer only. No new features. | Buffer only. | Portal locks 12:00 PM |

Book a mentor slot at ~7 PM (architecture check) and ~6 AM (pitch feedback). Bring them one specific question each.

## Team split

Whoever is stronger in Python and FFmpeg takes **A**; the other takes **B** and owns the pitch. Names: open question.

- **A — backend and AI:** STT, edit-list logic, LLM prompts, FFmpeg rendering, guardrails, the API that B calls.
- **B — product and story:** UI, deploy, demo video, deck, README, AI Impact Statement, presenting in Round 1 and finals.
- **Agree the contract first (by 5:00 PM):** the EDL JSON shape and three endpoints — `POST /upload`, `GET /job/{id}`, `POST /edit` (chat or strike). Then work in parallel against it.
- **Sync every 2 hours, 5 minutes:** what works, what's blocked, what we cut.
- **One rule:** `main` always runs. Commit small, push often — the repo URL is part of the submission.

## Submission package (due 11:00 AM, locks 12:00 PM)

- [ ] GitHub repo URL, public, with MIT LICENSE
- [ ] README.md following the outline below, including the demo link
- [ ] Live demo link (strongly favoured) **and** a 2-minute screen recording as backup
- [ ] Pitch deck, 6 slides max, as PDF
- [ ] AI Impact Statement, 200 words max

**README outline (handbook template, filled for us)**

1. Problem: 2–3 lines from "The idea in four lines".
2. Users and context: Indian-language talking-head creators; Malayalam wedge.
3. Solution overview: the architecture picture + the EDL example.
4. Setup and run: `ffmpeg` install, `.env` with API key, `pip install -r requirements.txt`, `npm run dev`.
5. Models and data: exact model names used, our self-recorded clips, Noto Sans Malayalam (SIL Open Font License), every library with its licence.
6. Evaluation and guardrails: word-ID validation, transcript review, measured results on our test clips.
7. Known limitations: STT accuracy on Malayalam and code-mixed speech, single speaker, file size limits.
8. Assumptions and trade-offs log (the handbook asks for this).
9. Team: names, roles, contacts.

**Deck — 6 slides**

| # | Slide | What goes on it |
| --- | --- | --- |
| 1 | Problem and who cares | A creator's raw clip timeline full of gaps; one line on hours lost per video; quote from a mentor or creator met at the event |
| 2 | Insight and why now | Video-as-code: AI writes the edit list, FFmpeg renders. Indic STT + structured LLM output made this possible now |
| 3 | Solution demo | 3 screenshots: upload → transcript with cuts → captioned 9:16 result, with the real before/after stats |
| 4 | Tech architecture | The pipeline picture from this plan; models named |
| 5 | Value and go-to-market | Creators first: freemium with free minutes per month and a paid creator plan; team plans for educators, coaching institutes and agencies. Reach via Kerala creator communities, then educators. Pricing: open question for mentors |
| 6 | Roadmap and risks | Next: retention-driven editing and a growth coach (reads Instagram and YouTube analytics, compares with top creators in the niche), then more languages and mobile. Risks: STT accuracy, Instagram API limits, rendering cost, competition from big editors such as Cardboard (YC W26) |

**AI Impact Statement — draft (fill the brackets with what we actually used)**

> **What the AI does:** It automates the cutting work in talking-head video editing. A speech-to-text model transcribes Malayalam, Hindi and English speech with word timestamps. An LLM proposes edits — removing fillers, pauses and retakes, or shortening to a target length — as a structured edit list. FFmpeg, not the AI, renders the video.
>
> **Models:** [STT model] for word-level timestamps; [GPT model] with structured outputs, chosen for reliable JSON and multilingual understanding.
>
> **Data:** Only clips we recorded ourselves with consent. Noto Sans Malayalam font (SIL Open Font License). User videos are not used for training.
>
> **Guardrails:** The LLM may only reference word IDs present in the transcript, so it cannot invent speech; every cut is validated against real timestamps. Captions come from the transcript, never from generated text. Users review and undo any cut. Low-confidence words are highlighted.
>
> **Expected impact:** Talking-head editing that takes hours by hand becomes a few minutes of review, in the creator's own language.

## Demo script (3 minutes) and fallback

Open on the result, not on slides. Round 1 at the desk is the same story in under 5 minutes.

| Time | What we show | What we say |
| --- | --- | --- |
| 0:00–0:20 | 8 seconds of the raw clip: pauses, "umm", a fumbled line | "This is how every creator's first take looks." |
| 0:20–0:45 | The cleaned 9:16 cut with Malayalam captions, then the stats card | "Same video, one click. [real numbers] removed, captions in Malayalam script." |
| 0:45–1:45 | Live: upload a fresh clip, transcript appears, strike a sentence, type "make it a 30-second reel" | "You edit the words; the video follows." |
| 1:45–2:20 | The EDL JSON beside the transcript | "The AI never touches pixels. It writes an edit list that can only point at real words, so it can't invent speech." |
| 2:20–3:00 | Deck slides 5–6 | Who pays, how we reach Kerala creators, what's next |

**Fallback:** if the network or render fails, say "chaos engineering" and switch to the recorded run of the same flow (handbook-approved). Keep the pre-rendered output and the screen recording open in tabs. Be clear it is a recording of the real build — never present a faked result.

**Q&A prep — have a one-line answer for each:**

- How accurate is it on Malayalam and Manglish? (Give our measured result on test clips, and the fallback STT plan.)
- Why not Descript, Cardboard or another big editor? (They stop at the edit and are English-first. We are Indian-language first, and our roadmap connects the creator's analytics to the edit.)
- What does one minute of video cost us to process? (Calculate from the API bills during the night.)
- Who pays, and how much? (Freemium creators; institutes and agencies on team plans.)
- What stops a big player copying this? (Language depth, the analytics-to-edit loop, anonymised regional creator benchmarks over time, speed; be honest that these are still being built.)
- How will you get Instagram retention data? (YouTube's API gives the full retention curve; Instagram's API gives averages such as watch time, so the first version reads a screenshot of the in-app retention graph.)
- What about privacy of uploaded videos? (Not used for training; deleted after processing in production.)

## How we score, and what could go wrong

Technical Execution (25%) is the biggest block and the first tie-breaker, so a working end-to-end pipeline beats extra features.

| Criterion | Weight | How we earn it |
| --- | --- | --- |
| Technical Execution | 25% | Real pipeline end to end, live; EDL validation; clean repo with setup steps |
| Problem Relevance | 20% | Indian-language creators, real pain, a quote from someone at the event |
| Innovation & Creativity | 20% | Video-as-code: edit-by-text and chat edits for Malayalam |
| UX/UI | 15% | Strike-to-cut transcript, before/after view, one-click clean |
| Business Viability | 10% | Freemium + team plans, Kerala creator wedge |
| Presentation | 10% | Aha in the first 45 seconds, rehearsed three times |

| Risk | Likelihood | Plan B |
| --- | --- | --- |
| STT is weak on Malayalam / code-mixed speech | High | Test before kickoff (see checklist). If poor: demo in Manglish/English with Malayalam captions via transliteration or translation; or run an open Indic STT model (e.g. AI4Bharat) on Neysa GPU credits only if setup is quick |
| Word timestamps unavailable or drifting | Medium | OpenAI's docs list `whisper-1` as the only model with word timestamps (deprecated, shuts down Feb 26, 2027 — fine for the demo). Fallback: segment-level cuts, or WhisperX alignment |
| FFmpeg render too slow for a live demo | Medium | Use short clips (1–2 min), 720p, `-preset ultrafast`; keep a pre-rendered result ready |
| LLM proposes bad cuts | Medium | Word-ID validation, show cuts for review before render, conservative defaults |
| Hosting fails | Medium | Run locally for the live demo; screen recording as the submitted demo link |
| We run out of time | High | Cut P1 items in reverse order (translation, karaoke, chat) — never cut the README or deck |

## Before 4 PM today

Prep only — no core product code before kickoff (fresh-build rule). Setup, test data and an STT check are fine.

- [ ] **Record 4 test clips (1–3 min each) on a phone:** pure Malayalam, Manglish, Hindi or English, and one with deliberate long pauses, fillers and a retake. Both of us consent; these are our dataset.
- [ ] **Run one STT test** on the Malayalam clip with your own OpenAI key if you have one (or first thing at 4 PM with event credits). Check word accuracy and that word timestamps come back. This decides our STT path.
- [ ] Install FFmpeg, Python 3.11+, Node 20+; confirm `ffmpeg -version` runs.
- [ ] Download the Noto Sans Malayalam font (SIL Open Font License).
- [ ] Create an empty public GitHub repo with an MIT LICENSE; both have push access.
- [ ] Decide A/B roles and a product name.
- [ ] Decide on earlier video-editor code: reuse and declare, or start clean (recommended).
- [ ] Join the WhatsApp group with the registered number; ask about finals timing and the "surprise element".
- [ ] Pack: laptops + chargers, extension board, adapters, earphones, hotspot, govt ID, water bottle, hoodie, neck pillow, any regular medicines.
- [ ] Leave with time to reach Kinfra Hi-Tech Park, Kalamassery before 4:00 PM.
