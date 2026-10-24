# AI Video Editor — Final Plan

Oct 23, 2026 · Team Euphoria

Online version: https://claude.ai/code/artifact/89d41118-be36-42e4-943c-10a61831344c

This is the final plan: every decision below is locked, chosen as the best option rather than a blend of earlier ideas. Start with "Start here", then follow the build sprint. The sections after Demo and pitch are the research behind the decisions.

**Update, 23 Oct 2026:** creators are now the primary market, with educators and small businesses as secondary segments. The plan also adds two growth features: an analytics-based growth coach and retention-driven editing (see Growth features below).

## Final decisions

The two decisions that matter most are new. Users fix the transcript before rendering, instead of you chasing perfect speech recognition. Captions are timed by phrase, so rough word timings never break a Reel.

| Area | Decision | Why this over the alternatives |
| --- | --- | --- |
| Company pitch | An AI growth partner for Indian-language talking-head creators: it edits the video, reads the creator's analytics, and edits the next video to keep viewers watching. First market: Malayalam and Manglish Reels | Editors such as Cardboard stop at the edit, and India-focused tools mostly stop at captions; no one connects analytics to the edit for Indian-language creators |
| First buyer | Malayalam and Manglish talking-head creators. Educators (coaching institutes, teachers) and small businesses are supported as secondary segments | Creators pay for views, which the growth features sell; educators use the same talking-head format at no extra build cost. Big edtech brands edit in-house; clinics face advertising rules |
| Promise | A raw Malayalam take becomes a post-ready Reel in under 3 minutes, with captions you don't have to fix, and each new Reel is edited using what the creator's analytics show | Measurable, and it beats caption-only tools |
| Growth coach | Connect Instagram and YouTube; compare the creator's stats with public videos of successful creators in the same niche. When the niche is very new, learn from adjacent niches and general patterns (hook timing, length, posting time) | Turns an editor into a growth tool; editors and analytics dashboards are separate products today |
| Retention-driven editing | Find where viewers drop off and edit future videos to avoid it. YouTube: full retention curve from the YouTube Analytics API. Instagram: the API gives averages such as watch time, so the first version reads a screenshot of the in-app retention graph | Sells more views, not an edited video; the screenshot route works around Instagram's API gap |
| Transcript | Sarvam Saaras in code-mix mode by default; WhisperX large-v3 as the offline baseline | Sarvam is built for mixed Indian speech; the bake-off can still overturn it |
| Word timing | Meta's MMS forced aligner (one pass over mixed scripts) by default; transliteration bridge with WhisperX's Malayalam aligner as fallback | Handles mid-sentence language switches without slicing the audio |
| Accuracy strategy | The user reviews and corrects the transcript in a text editor before render | Fastest route to "post as is"; every correction feeds the moat |
| Caption timing | 2–4 word phrases timed by phrase; a word pops only if its alignment confidence is high | Degrades gracefully when word timings are rough |
| Caption scripts | Each phrase stored three ways: as spoken (Malayalam with English words in Latin), Romanized Manglish, English. Ship the first two with a toggle; English is a stretch goal | Romanized demand is unproven, but it costs one extra field |
| Text rendering | One HTML/CSS overlay, rendered in Chromium for both preview and export, fonts bundled | Correct Malayalam shaping, identical preview and export |
| Preview | `<video>` plus overlay, synced with `requestVideoFrameCallback()` | Frame-accurate with a few lines of code |
| Export | 1080×1920 at 30 fps: Playwright captures transparent overlay frames, FFmpeg composites and muxes | 30 fps halves render time and matches phone footage |
| Cuts | Remove silences over 350 ms within a sentence and 500 ms between sentences, plus a filler-word list; LLM retake detection off by default | Deterministic and testable |
| Reframe | MediaPipe face detection at 5 fps on a 480p proxy, smoothed with a dead zone; skipped when the source is already vertical | Most creator and coaching clips are shot vertical |
| Edit planning | One LLM call writes the manifest in a strict schema; a validator checks it; at most one repair call | Bounded cost and latency |
| Revisions | Chat edits manifest fields only: text, style, position, script, keyword, hook. No re-transcription | Instant changes; only the overlay re-renders |
| Sound | The existing SciPy effects: whoosh on hook and scene changes, pop on keywords, at most one tick per 1.2 s; normalise to −14 LUFS, −1 dBTP | Already built; the clearest gap versus caption-only tools |
| Data | Consent checkbox, working delete, store the first and final manifest of every job | Legal and the moat in one step |
| Infrastructure | One GPU machine (own or rented), local disk, SQLite, background tasks | Zero infrastructure work during the sprint |
| Claims | Pitch only numbers measured on your own test clips | Verified in the fact-check below |

## Start here: setup (about 2 hours, before the sprint clock starts)

Do these in parallel: Builder A takes accounts, installs and the speech environment; Builder B takes fonts, the repo and the clips.

### Accounts and keys

- [ ] Sarvam API key; confirm in the docs whether Saaras returns word-level timestamps
- [ ] One LLM provider API key, with a spending limit set
- [ ] A GPU: your own laptop's, or one rented cloud GPU for the sprint

### Installs

- [ ] Python 3.11, Node 22, FFmpeg 7
- [ ] Playwright with Chromium
- [ ] Speech environment: `whisperx==3.8.6`, plus `torchaudio==2.8.*` and `uroman` for the MMS aligner. TorchAudio removed its forced-alignment API in 2.9, so pin 2.8. If its torch version clashes with WhisperX, put the aligner in its own virtual environment
- [ ] Backend: FastAPI, Pydantic v2, MediaPipe, NumPy, SciPy

### Fonts (all under the free OFL licence on Google Fonts)

- [ ] Noto Sans Malayalam, Manjari and Anek Malayalam for Malayalam script
- [ ] One bold Latin display font for Romanized captions
- [ ] Save the font files inside the repo, not as web links, so export works offline

### Test clips: the mini golden set

- [ ] Record 5 vertical clips, 30–90 seconds each, from team members, friends or family, with written consent
- [ ] Mix: 3 heavy Manglish, 2 mostly Malayalam; at least one with numbers and prices ("₹4,999", "2026"), one in a noisy room
- [ ] Topic: creator-style talking-head explainers to match the first buyer, plus one coaching-style clip for educators
- [ ] Type a reference transcript for each clip, in the as-spoken script and in Romanized Manglish
- [ ] Do not use other creators' Reels without permission

### Repo and existing assets

- [ ] Unzip the skill archives; spend at most 30 minutes listing which files you will reuse and each one's licence
- [ ] Create the repo: `web/` (Next.js), `api/` (FastAPI), `media/` (Python workers), `render/` (overlay HTML, engine JS, fonts), `schema/` (manifest), `golden/` (clips and reference transcripts)
- [ ] Commit the manifest schema from the Manifest v1 section before any other code

## Build sprint: 20 hours, 2 builders

The sprint front-loads the riskiest part, speech, and ends every phase in something you can show. If a gate fails, apply its plan B from Risks and fallbacks rather than extending the phase.

*[Diagram in the online version: sprint plan · 5 phases, 2 builders, 5 gates]*

The speech bake-off is the only task that can sink the project, so it runs first and both builders support it if it slips. With more than two people, give a third person the golden set, demo script and pitch.

### Phase 1, H0–H3: prove speech

- [ ] A: run Sarvam (code-mix), WhisperX large-v3, and the MMS aligner on all 5 clips
- [ ] A: score word accuracy against the reference transcripts; a native speaker rates caption timing on each clip
- [ ] A: lock the winning transcript and aligner pair
- [ ] B: Next.js upload page and FastAPI job endpoint
- [ ] B: render one Malayalam and one Romanized phrase in Chromium with the bundled fonts; check the conjuncts
- [ ] Gate: speech choice written down, captions render correctly

### Phase 2, H3–H8: first captioned clip

- [ ] A: prepare step (probe, constant frame rate, 48 kHz audio, 480p proxy)
- [ ] A: silence and filler cuts from word timings; face-tracked 9:16 crop
- [ ] A: Pydantic manifest and validator, with tests on a hand-made manifest
- [ ] B: preview player with the overlay synced by `requestVideoFrameCallback()`
- [ ] B: transcript editor; a saved correction flows into the manifest
- [ ] Gate: upload a clip, see it cut and reframed with correctly timed phrase captions

### Phase 3, H8–H13: automatic edit

- [ ] A: one LLM call fills phrases, three text versions, keyword, hook and effects; validator plus one repair; template planner as fallback
- [ ] B: hook title, keyword pop (only on high-confidence words), caption styles from the motion engine
- [ ] B: script toggle between as-spoken and Romanized
- [ ] Gate: all 5 golden clips produce a full automatic edit that plays in the preview

### Phase 4, H13–H16: export

- [ ] A: sound effects from the SciPy code, two-pass loudness normalisation to −14 LUFS and −1 dBTP
- [ ] B: Playwright captures transparent overlay frames at 30 fps
- [ ] A + B: FFmpeg composites cuts, crop, overlay and audio into the final MP4
- [ ] Gate: a 60 s clip exports in under 2 minutes and plays correctly on a phone

### Phase 5, H16–H20: revise and demo

- [ ] A: chat revisions patch manifest fields; validator re-checks; only the overlay re-renders
- [ ] A: consent checkbox, delete button, store first and final manifest; log cost and time per job
- [ ] A: run all 5 golden clips and write down the measured numbers for the pitch
- [ ] B: before and after toggle; polish the upload-to-export flow
- [ ] B: record the backup demo video; rehearse the 3-minute script twice
- [ ] Gate: the demo runs end to end without help

### After the sprint

1. **Week 1:** grow the golden set to 20 clips from 5 speakers; fix the worst errors it shows.
2. **Weeks 2–8:** done-for-you validation with 10–20 Malayalam talking-head creators, plus a few educators, as described in After the MVP.

## Manifest v1: the contract both builders code against

One JSON file describes the whole edit. The backend writes it, the overlay reads it, the validator checks it, and chat revisions patch it. The most important rule: **the LLM never writes timestamps.** Code derives every time from the aligned words, and the LLM only groups words into phrases and picks text, keywords, hook and effects. That removes the most common class of AI editing bugs.

```json
{
  "version": 1,
  "job_id": "j_001",
  "source": { "path": "golden/clip1.mp4", "duration_ms": 61240, "width": 1080, "height": 1920, "fps": 30 },
  "output": { "width": 1080, "height": 1920, "fps": 30, "duration_ms": 48310 },
  "script_mode": "spoken",
  "style": { "preset": "coach_clean", "font_ml": "Manjari", "font_latin": "display", "accent": "#FFD400", "caption_y": 0.70, "caption_scale": 1.0 },
  "cuts": [ { "src_start_ms": 0, "src_end_ms": 4180, "zoom": 1.0 } ],
  "crop": [ { "t_ms": 0, "cx": 0.50, "cy": 0.40 } ],
  "face_boxes": [ { "t_ms": 0, "x": 0.30, "y": 0.18, "w": 0.40, "h": 0.30 } ],
  "hook": { "start_ms": 0, "end_ms": 2200, "text": { "spoken": "...", "roman": "...", "english": "..." } },
  "phrases": [
    {
      "id": "p1", "start_ms": 300, "end_ms": 1450, "keyword": "AI",
      "text": { "spoken": "ഇന്ന് നമ്മൾ new AI", "roman": "Innu nammal new AI", "english": "Today, a new AI" },
      "words": [ { "t": "ഇന്ന്", "s": 300, "e": 610, "c": 0.91 } ]
    }
  ],
  "sfx": [ { "type": "whoosh", "at_ms": 2200, "gain_db": -14 } ],
  "provenance": { "generated_broll": false }
}
```

### Rules

1. The Pydantic model is the only source of truth; generate the TypeScript types from its JSON Schema.
2. All times are whole milliseconds. `cuts` use source time; everything else uses output time, after cuts.
3. Who writes what:
   - Code: `cuts`, `crop`, `face_boxes`, `words`, and every `start_ms` and `end_ms`.
   - LLM: phrase grouping (by word index), the three text versions, `keyword`, `hook` text, `sfx` choices, `style`.
   - User (chat or editor): any text or style field.
4. The validator rejects a manifest when:
   - a phrase is outside the output duration, overlaps another phrase, or is shown too briefly to read;
   - the caption box overlaps a face box or a platform safe zone (zones defined in one config file);
   - a keyword does not appear in its phrase, or a text version is missing;
   - there is more than one keyword tick per 1.2 s.
5. On rejection, send the errors back to the LLM once. If it fails again, fall back to the template planner (see Risks).

## Risks and fallbacks

Every risk has a plan B agreed in advance, so nobody debates it at 3 a.m. Check each one at the gate named in its row.

| Risk | How you notice | Plan B | Gate |
| --- | --- | --- | --- |
| Sarvam gives no word timestamps, or mangles Manglish | Bake-off scores on the 5 clips | Use its transcript with the MMS aligner; if the transcript is poor too, use WhisperX large-v3 and rely on the transcript editor | H3 |
| MMS aligner won't install or aligns badly | Install fails, or a native speaker scores timings poorly | Transliteration bridge with WhisperX's Malayalam aligner; worst case, time phrases from segment timestamps split by character count | H3 |
| Malayalam text renders wrongly | Broken conjuncts in the H3 render test | Switch to another of the three fonts; check the font files actually loaded | H3 |
| LLM returns invalid manifests | Validator rejects twice in a row | Template planner: phrases by sentence, hook from the first sentence, no keyword pops | H13 |
| Frame capture is too slow | Over 2 minutes to export a 60 s clip | Capture only frames where the overlay changes and hold static frames with FFmpeg durations | H16 |
| GPU or venue internet fails | Jobs hang | Results cached by file hash; play the pre-recorded demo video | Any time |
| Scope creep | Someone starts a feature not in Final decisions | Write it on a "later" list and return to the sprint | Any time |

## Demo and pitch

The demo must show three things caption-only tools can't: correct Manglish captions, a full edit with sound and motion, and instant changes.

### 3-minute script

1. **0:00–0:20, problem.** Kerala creators post talking-head Reels every week. A Malayalam editor costs ₹3–5 lakh a year (cite the job postings), and global AI tools skip Malayalam.
2. **0:20–1:20, live edit.** Upload a raw Manglish clip. Show the transcript editor and fix one word. Generate. Play the Reel.
3. **1:20–1:45, two toggles.** Flip before and after to show cuts, sound and motion. Flip the caption script from as-spoken to Romanized Manglish.
4. **1:45–2:10, chat.** Type "make the hook bigger and highlight the price". The preview updates without re-processing.
5. **2:10–2:30, export.** Play the final MP4 with sound.
6. **2:30–3:00, why us.** Show your measured numbers on the golden set, the data flywheel, the language expansion order, and what you are asking for.

### What you can claim on stage

- **Yes:** numbers you measured (processing time, caption accuracy on your clips, cost per minute); competitor prices and the India IT Rules, with their sources; the job-posting salaries.
- **No:** anything in the "Could not be verified" table, and any absolute claim such as "perfect" or "solves completely".

Record a full run of the demo as a backup video before you go on stage.

## Competitors: pricing and services

Every major global tool already ships captions, silence and bad-take removal, auto-zoom, B-roll and sound effects for $12–$39 a month. Feature parity is not a differentiator. The open gap is depth in Indian languages: [Submagic's published subtitle-language list](https://www.submagic.co/pricing) has Hindi, Tamil and Marathi but no Malayalam, CapCut has been [banned in India since June 2020](https://fluxnote.io/guides/capcut-questions-answered), and most India-focused tools found so far do captions only.

Prices are USD per month for one seat, checked October 2026. "Official" means taken from the vendor's own pricing page; the rest come from third-party trackers and can be off by a few dollars.

### Global tools

| Tool | Main job | Paid plans (monthly / billed yearly) | What it includes | Source |
| --- | --- | --- | --- | --- |
| [Submagic](https://www.submagic.co/pricing) | Polish one short talking-head clip | Starter $19 / $12 (15 videos, 2 min each) · Pro $39 / $23 (40 videos, 5 min) · Business $69 / $41 (100 videos, 30 min) | Animated captions, auto-zoom, B-roll, sound effects, bad-take and silence removal, filler words, clean audio, eye contact, caption translation, hook titles, social publishing, API at $0.10–$0.23 per minute | Official |
| [OpusClip](https://www.opus.pro/pricing) | Cut a long video into many shorts | Free (60 credits, watermark) · Starter $15 (150 credits) · Pro $29 / $14.50 (300 credits) · Business custom | Virality score, captions in 20+ languages, reframe with tracking, AI B-roll, filler and bad-take removal, XML export to Premiere and Resolve, scheduler, API and MCP, "AI Producer" for raw footage | Official |
| [Captions (Mirage)](https://captions.ai/pricing) | Mobile-first AI editing and AI avatars | Max $24.99 (500 credits) · Frontier $69.99–$279.99 · Enterprise custom | Chat-based editor, AI Edit styles, captions in 100+ languages, AI twin and actors, generated B-roll, music and sound effects, translation and lip-dub | Official (iOS prices) |
| [Descript](https://knowlify.com/articles/descript-pricing) | Text-based editing of the whole video | Hobbyist $24 / $16 · Creator $35 / $24 · Business $65 / $50 | Edit video by editing the transcript, Studio Sound, Underlord AI agent; usage metered by media minutes and AI credits since September 2025 | Third-party |
| [Kapwing](https://costbench.com/software/video-editing/kapwing/) | Browser editor for teams | Pro $24 / $16 · Business $64 / $50 | Subtitles (including [Malayalam](https://www.kapwing.com/subtitles/video/Malayalam)), translation, AI tools, team workspace | Third-party |
| [VEED](https://dupple.com/pricing/veed) | Browser editor for marketers | Entry tier about $9–$12 · Pro about $24–$30 (plan names are changing) | Subtitles, Magic Cut, eye contact, clean audio, AI clips, brand kit, translation | Third-party |
| [Vizard](https://www.vmeg.ai/blog/vizard-ai-alternative/) | Long video to clips | Free (720p, watermark) · Creator about $14.50–$29 | Clipping, captions, reframe, B-roll, scheduling; 1 credit = 1 source minute | Third-party |
| [Klap](https://cut.pro/en/blog/klap-vs-opusclip-2026) | Long video to clips | About $14–$94 range; moved to per-minute pricing in 2026 | Clipping, captions, reframe, dubbing on higher tiers | Third-party |
| [Jupitrr](https://pricingsaas.com/companies/jupitrr/diffs/2026W42) | Talking-head videos for coaches | Starter $15 · Pro $33 (cut in October 2026) | Auto B-roll, subtitles in 50+ languages including Hindi and Telugu, stock media | Third-party |
| [CapCut](https://fluxnote.io/guides/capcut-questions-answered) | General mobile editor | Pro about $10–$20 | Full manual editor with AI tools; not officially available in India | Third-party |
| [invideo AI](https://subger.com/en/service/invideo) | Generate videos from prompts | Plus about $17–$28 up to $900 (Elite) | Text-to-video generation, not editing of your own raw footage; Mumbai and San Francisco company | Third-party |

### India-focused tools

| Tool | What it does | Price signal | Source |
| --- | --- | --- | --- |
| Captiq | Captions for Hindi, Gujarati, Nepali and 10+ regional languages, priced for Indian buyers | Free tier of 15 minutes a month | [Product Hunt listing](https://hunted.space/product/captiq) |
| aivideocaption | Word-level timed captions in Hindi, Hinglish and Gujarati | ₹99 per minute beyond plan limits | [Stork review](https://www.stork.ai/en/aivideocaption) |
| OpenCut AI | Open-source, local-first editor; 22 Indian languages through Sarvam AI | Free, bring your own API key | [Product Hunt listing](https://www.hunted.space/product/opencutai-video/launches/free-ai-video-editor-opencutai) |
| Atlabs | Malayalam caption generator inside a general AI video platform | Not checked | [Atlabs page](https://www.atlabs.ai/features/ai-subtitle-generator/malayalam) |
| Aalap | Voice-driven reel editor; speech recognition for Hindi, Hinglish, Malayalam and other Indian languages; Hinglish captions in Roman script | Free, paid from ₹499 a month | [Aalap site](https://159-65-147-234.sslip.io/) |

Aalap and OpenCut AI go furthest, but none of these does the full edit (cuts, reframe, motion typography, sound design) in Indian languages, and none connects the creator's analytics to the edit. That is the opening.

### Agentic editors

[Cardboard](https://www.ycombinator.com/companies/cardboard) (YC W26) is a browser-based editor that turns raw footage into a timeline from natural-language instructions. It targets growth and marketing teams, and [pricing starts at $60 a month](https://outlierkit.com/resources/cardboard-review/). Its launch material does not mention Indian languages. Like every tool above, it stops at the edit and does not use the creator's performance data.

### What a human editor costs

Indian companies are hiring Malayalam short-form editors at ₹3–4.8 lakh a year ([Lokal](https://apply.workable.com/lokal-app/jobs/view/7C08DCC6F2.md)) and up to ₹5 lakh a year ([Inertia Labs](https://jobs.weekday.works/video-editor-malayalam-at-inertialabs-technologies-wkdyj0elyd)). That salary is the budget your product competes for with businesses, not the $12 Submagic plan.

## Fact-check of the original plan

Of 30 claims checked, 13 hold up, 6 need correcting, and 11 could not be traced to any source. The projects the plan leans on (FilmCraft, FableCut, videopython, WhisperX 3.8.6, Marengo) are all real. Most invented-looking numbers are the precise percentages and speed-ups. Rule for the pitch deck: use only rows marked Verified or Corrected, and replace the rest with numbers you measure on your own clips.

### Verified

| Claim in the plan | What the source says | Source |
| --- | --- | --- |
| WhisperX v3.8.6 exists | Latest stable release, May 25, 2026; a 3.8.7 release candidate followed in June | [PyPI](https://pypi.org/project/whisperx/) |
| WhisperX runs about 70× real time | README: batched inference, 70× real time with large-v2 | [GitHub README](https://github.com/m-bain/whisperX) |
| Plain Whisper timestamps drift by seconds | README: Whisper timestamps are utterance-level and can be off by several seconds | [GitHub README](https://github.com/m-bain/whisperX) |
| Digits break WhisperX alignment | README limitation: words like "2014." or "£13.60" get no timing. Version 3.8.2 was also pulled for missing digit timestamps (issue #1372, not #1220) | [GitHub README](https://github.com/m-bain/whisperX), [PyPI history](https://pypi.org/project/whisperx/) |
| FilmCraft uses 254,016,000,000 ticks per second | Confirmed; FilmCraft is an open-source Rust clean-room rebuild of Premiere Pro, in alpha | [FilmCraft README](https://raw.githubusercontent.com/storytold/filmcraft/main/README.md) |
| videopython has a JSON schema, dry-run validation and auto-repair | `VideoEdit.json_schema()`, `edit.validate()` and `edit.repair()` (auto-clamps overruns) all exist; it now ships an MCP server too | [PyPI](https://pypi.org/project/videopython/0.55.2/) |
| FableCut is a browser editor driven by MCP through a JSON timeline | Confirmed: `project.json`, `fablecut_patch_project`, MIT licence | [Glama listing](https://images.glama.ai/mcp/servers/ronak-create/FableCut) |
| Marengo produces 512-dimension embeddings | True for Marengo 3.0 (version 2.7 was 1024) | [TwelveLabs](https://www.twelvelabs.io/marengo) |
| Modal snapshots cut vLLM boot from 95.7 s to 13.8 s | Reported from Modal's production data, February–April 2026 | [byteiota report](https://byteiota.com/gpu-inference-cold-starts-cut-40x-heres-the-stack/) |
| 1 TB stored + 3 TB egress costs about $291/month on S3 vs about $15 on R2 | Arithmetic holds at S3 $0.023/GB and $0.09/GB egress vs R2 $0.015/GB and $0 egress (request fees excluded) | [Mecanik](https://mecanik.dev/en/posts/cloudflare-r2-pricing-explained-real-costs-vs-s3-and-backblaze/) |
| Remotion Lambda limits: 1,000 concurrent functions, 10 GB storage, about 2 hours of Full HD | All three in Remotion's docs; the 15-minute limit is AWS's | [Remotion docs](https://cloudrun.remotion.dev/docs/lambda) |
| Descript exposes its Underlord editor to agents | Official hosted MCP server at api.descript.com | [Developers Digest](https://www.developersdigest.tech/mcp-servers/descript) |
| Whoosh starts 160 ms early so its peak lands on the cut | 42% of a 380 ms whoosh is 159.6 ms: internally consistent | Own arithmetic |

### Corrected

| Claim in the plan | Correction | Source |
| --- | --- | --- |
| WhisperX hits 91.2% word precision within 20 ms; plain Whisper 56.3% at 50 ms | Neither figure is in the WhisperX paper. The paper reports 84.1% precision and 60.3% recall on AMI, and 93.2% and 65.4% on Switchboard, at a 200 ms tolerance. A later study found WhisperX's word-timing F1 drops from 76.7 to 59.0 on noisy audio | [Emergent Mind summary](https://www.emergentmind.com/topics/whisperx), [CrisperWhisper paper](https://arxiv.org/pdf/2408.16589) |
| "EBU R128 −14 LUFS mastering" | EBU R128's target is −23 LUFS. −14 LUFS is the usual streaming level; TikTok and Instagram publish no official target. Use "−14 LUFS integrated, −1 dBTP true peak, measured with the R128 (BS.1770) meter" | [Wikipedia: EBU R 128](https://Www.Wikipedia.org/wiki/EBU_R_128), [Fora Soft](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026) |
| FableCut hot-reloads in under 50 ms and has a `fablecut_frame` tool | Its own docs say about 150 ms. The documented tool list has no `fablecut_frame`; its reference analyser is `fablecut_analyze_reference` | [Glama listing](https://images.glama.ai/mcp/servers/ronak-create/FableCut), [skill listing](https://skillsllm.com/skill/fablecut) |
| Browser holds about 67 uncompressed 4K frames in 2 GB | An RGBA 4K frame is about 31.6 MiB, so about 65 frames. Decoded frames are usually NV12 (half the size), about 130 frames. The 2 GB ceiling itself is not a browser spec | Own arithmetic |
| "Zero AI watermarks, never triggers AI labels" | India's IT Amendment Rules 2026 (in force February 20, 2026) require labelling of synthetic content. Reframe as "edits real footage; discloses generated B-roll" | [exchange4media](https://www.exchange4media.com/digital-news/new-rule-mandates-clear-labelling-of-synthetic-content-on-digital-platforms-151874.html) |
| Director LLM is "Claude 3.7/4.x Sonnet or Gemini 3" | Model names are out of date. Pick whichever current model gives the best Malayalam output in your own test | — |

### Could not be verified: remove or measure yourself

| Claim in the plan | What to do |
| --- | --- |
| Raw CLI agent loops cost $100–$445 per video | No source found. Remove, or log your own cost for one video done that way |
| Descript usage rose 200% within two weeks of its MCP listing | No source found. Remove |
| MCP output schemas give 95–98% success, 37% fewer steps, 43% lower latency | No source found. Remove |
| Kapwing renders 100,000+ projects a day, batches 50 subtitle PNGs, uses a 3-stage pipeline | No Kapwing engineering source found. Keep the technique (pre-rendered overlays, concat-copy splices), drop the numbers |
| WebCodecs gives a 300% speed-up, 2 ms vs 45 ms frames, 8% CPU; Wasm exception handling is 15% smaller | No source found. Benchmark on your own laptop if it matters |
| Remotion renders an 80-second video in 15 s at the same cost; raw output over 200 MB a minute | Not in Remotion's docs. Remove |
| Modal diffusion cold starts under 3 s, 70% of preempted compute recovered, 80–90% "GPU idle tax" | Only the vLLM figure was found. Remove the rest |
| Speech-to-speech costs $0.66/min vs $0.032/min (`gpt-realtime-2.1`) | Not checked; the deferral stands on its own. Drop the numbers |
| Unstable first 0.55 s on 5-second AI clips | A heuristic, not a measured fact. Keep as a tunable default |
| Contact-sheet QA costs $0.004 per pass; video costs 180,000–540,000 tokens a minute | Plausible orders of magnitude, but they depend on the model and image size. Measure on your chosen model |
| AIBoomi Kochi is 20 hours with a $17,500 credit pool | Only a 24-hour Bengaluru edition was found. Confirm with the organisers |

## Positioning and wedge

Pitch the growth partner, build the wedge. The company story is "an AI growth partner for talking-head creators: it edits the video, reads the analytics, and edits the next one to keep viewers watching"; the MVP is still "the best editor for Malayalam and Manglish talking-head Reels." Creators are the main market; educators and small businesses use the same pipeline, and every later language reuses it too, so the wedge is a first market, not a dead end.

### Why Malayalam first

- **The gap is real.** Global tools list dozens of languages, but Malayalam is missing from Submagic's list, CapCut is unavailable in India, and the India-focused tools only do captions.
- **The hard part is code-mixing.** Kerala creators speak Manglish: Malayalam with English words mid-sentence. WhisperX's Malayalam alignment model only knows Malayalam characters, so English words in Latin script fall back to a wildcard and get rough timings. Solving that well is defensible work.
- **Home-market access.** You can meet Kochi businesses and creators in person, test with native speakers, and judge caption quality yourselves.
- **Proven demand.** Kerala companies already pay ₹3–5 lakh a year for Malayalam short-form editors (see the competitor section).

### Who to build the MVP for

Pick one buyer for the MVP. These are hypotheses to test after the MVP, during the done-for-you phase:

| Segment | Why they might pay | Risk |
| --- | --- | --- |
| Malayalam and Manglish talking-head creators (chosen, primary) | They want more views; the growth coach and retention editing sell that outcome, not just an edit | Price-sensitive; prove a views lift on early users before charging |
| Kerala D2C and local brands posting Reels | Already pay editors or agencies; need volume | May want ad creatives, not talking heads |
| Coaching institutes: PSC, IELTS and OET, study abroad, entrance (secondary) | Talk to camera daily; Kerala has a strong edtech scene | Large edtech brands edit in-house, so target small and mid-size institutes |
| Small agencies serving Kerala clients | Multiply output per editor; pay for seats | Want control and export to Premiere |

Recommendation: build for Malayalam and Manglish talking-head creators first, because they care most about views and the growth features sell exactly that. Support educators (small and mid-size coaching institutes, teachers) as the second group: same talking-head format, same pipeline. Clinics are out: doctors' promotional content has advertising restrictions.

### Expansion order

1. Malayalam and Manglish (MVP).
2. Tamil, Telugu and Kannada: same South Indian creator economy, same code-mixing problem.
3. Hindi and Hinglish: the largest market, but the most crowded.
4. Global English talking-head: only once the moat (see Moat below) is working.

Move to the next language only when the current one hits the targets in "After the MVP".

### One-line positioning

> For Malayalam creators who post talking-head Reels, [product] turns a raw take into a finished, captioned, sound-designed Reel in minutes, then reads their Instagram and YouTube analytics to show what top creators in their niche do differently and edits the next video to keep viewers watching. Educators and small businesses get the same engine. Unlike global tools, it is built and tested on how Kerala speaks.

## MVP scope: the simple workflow

The MVP does one job: one raw Malayalam talking-head clip in, one finished 9:16 Reel out, plus one round of chat-based changes. Anything that does not serve that loop waits.

### The workflow

1. **Upload** one clip, up to 3 minutes, vertical or horizontal.
2. **Prepare**: probe with `ffprobe`, convert to constant frame rate, extract 48 kHz audio, make a 480p proxy.
3. **Transcribe and align**: Sarvam in code-mix mode for text, the MMS aligner for word timings.
4. **Review**: the user corrects the transcript in a text editor; timings are re-aligned for edited words.
5. **Clean cut**: remove silences and filler words, with short padding and crossfades so cuts don't click.
6. **Reframe** to 9:16 with face tracking; skip if the clip is already vertical.
7. **Plan the edit**: the LLM groups words into phrases and writes the three text versions, keyword, hook and effects. Code sets every time. The validator checks the result.
8. **Render** the caption and title overlay in headless Chromium with the motion engine.
9. **Mix and export**: add sound effects, normalise to −14 LUFS and −1 dBTP, export 1080×1920 at 30 fps.
10. **Revise by chat**: changes patch the manifest; only the overlay re-renders.

### Speech stack: decide by test, not by assumption

The defaults are set in Final decisions. The bake-off in the first 3 hours of the sprint confirms or overturns them on the 5-clip golden set, which grows to 20 clips after the sprint.

| Role | Option | Strength | Watch out for |
| --- | --- | --- | --- |
| Transcript (default) | [Sarvam Saaras](https://docs.sarvam.ai/api/getting-started/models.md), code-mix mode | Keeps English words in English inside Malayalam speech | Paid per audio hour; may not return word timings |
| Transcript (baseline) | WhisperX large-v3 | Free, offline | Weaker on Manglish |
| Transcript (later) | [AI4Bharat IndicConformer](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual) | Open, MIT licence, 22 Indian languages | Test after the sprint |
| Word timing (default) | [MMS forced aligner](https://docs.pytorch.org/audio/main/tutorials/forced_alignment_for_multilingual_data_tutorial.html) with `uroman` | One pass over mixed Malayalam and English text | Pin torchaudio 2.8; `uroman` drops digits, so write numbers as words first; English spelling isn't phonetic |
| Word timing (fallback) | Transliteration bridge: English words written in Malayalam script, then WhisperX's [Malayalam aligner](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py) | Cheap; uses an aligner trained on Malayalam | A wrong transliteration shifts timings |

Scoring: word error rate against the reference transcripts, plus a native speaker's 1–5 rating of caption timing on each clip. Pick the highest-scoring pair. On a tie, pick the one that runs offline. Because users correct the transcript and captions are timed by phrase, the target is "good enough to fix in seconds", not perfect recognition.

### Malayalam text rendering

Render all captions in the browser, not with FFmpeg `drawtext`. Malayalam conjuncts need proper text shaping, which browsers do by default and FFmpeg only does in builds with HarfBuzz enabled. Bundle the font files with the renderer so preview and export match. Candidate fonts: Noto Sans Malayalam, Manjari, Anek Malayalam.

### Stack

| Layer | MVP choice | Why |
| --- | --- | --- |
| Frontend | Next.js upload page, video preview, chat box | Simple, and the team knows it |
| Backend | FastAPI with a simple job queue | Wraps the existing Python scripts |
| Speech | Winner of the bake-off | See above |
| Planner LLM | Whichever current model writes the best Malayalam captions in your test | Swap-able behind one function |
| Validation | `videopython`-style dry run: time bounds, caption-face overlap, schema | Stops bad edits before render |
| Render | Headless Chromium for the overlay, FFmpeg for cuts, audio and final mux | Correct Malayalam shaping |
| Storage | Local disk or one cloud bucket | Scale later |
| Compute | One GPU machine or pay-per-use GPU for speech | No infrastructure work yet |

### Deferred until after the MVP

Multi-user editing, WebGPU and WebCodecs preview, OpenTimelineIO export, B-roll generation and search, paper-collage and live web-proof modes, text behind the speaker, "Style Match" cloning, the MCP server, the DAG router, integer tick timecodes, and serverless GPU snapshots.

### Definition of done

- [ ] A 60-second raw clip becomes a finished Reel in under 3 minutes, excluding the user's review time.
- [ ] Native speakers rate captions "usable without edits" on at least 4 of the 5 sprint clips, and 8 of 10 later.
- [ ] Transcript corrections and the script toggle work without re-running transcription.
- [ ] One chat revision updates the Reel without re-running transcription.
- [ ] Cost and time per job are logged for every job.

## Improvements to the original build phase

The original Phases 1–2 try to build about 15 services in parallel. The biggest improvements are to build a test set before features, build in a strict order with a working demo at each step, and fix three technical choices that would break on Malayalam.

### Changes, with the reason for each

1. **Open and audit the skill zips before planning around them.** The original plan admits their code was never read. Unzip everything, read each script, and record its licence. Rewrite anything you cannot confirm is licensed for commercial use.
2. **Build a golden test set on day 1.** Twenty clips from five Malayalam speakers, each with a hand-checked transcript. Every change to the pipeline re-runs them and reports word error rate, caption timing error in milliseconds, caption-face collisions, loudness and processing time. Without this, "it looks better" is the only quality signal.
3. **Swap the speech plan.** Replace "WhisperX everywhere" with the bake-off in the MVP section. The current WhisperX code already maps unknown characters such as digits to a wildcard, so the number normaliser is now a quality improvement, not a must-have. It does need to handle both Malayalam and English number words.
4. **Simplify the preview clock.** For the MVP, sync captions to `video.requestVideoFrameCallback()`, which reports the exact frame on screen. The AudioContext master clock and WebGPU path are only needed for multi-track scrubbing later. For export, drive the motion engine by frame number, as the plan already says.
5. **Render all text in Chromium.** This replaces any FFmpeg `drawtext` captions, so Malayalam conjuncts shape correctly. Bundle the fonts in the repo and wait for `document.fonts.ready` before capturing frames.
6. **Add platform safe zones to the validator.** Besides the speaker's face, keep captions clear of the areas Instagram and YouTube Shorts cover with buttons and captions (the bottom strip and right edge). Also check reading speed: flag any caption shown too briefly for its length.
7. **Generate types from one schema.** Write `TimelineManifest` once in Pydantic, export JSON Schema, and generate the TypeScript types from it. Two hand-written copies will drift.
8. **Log cost and time per job from the first run.** Record LLM tokens, GPU seconds and render time for every job. This is the data the pricing decision needs after the MVP.
9. **Store edit history, with consent.** Save the AI's first manifest and the user's final version for every job, behind a clear consent checkbox and a delete button. This is the raw material for the moat, and it is only usable if users agreed to it.
10. **Keep the offline demo mode.** Cache speech and LLM results by file hash so a live demo still works if the venue internet drops.

### Build order

The build order is now the Build sprint near the top of this doc: five phases, each ending at a gate with a working demo.

## Growth features

The editor makes the first Reel; the growth features make the next one perform better. They come after the editing MVP works, and they are what separates the product from Cardboard and the caption tools, which stop at the edit. The first two rows are decided; rows marked proposed are candidates for the roadmap.

| Feature | What it does | Data it needs | When |
| --- | --- | --- | --- |
| Retention-driven editing | Finds where viewers drop off and edits future videos to avoid those moments | YouTube retention curve; Instagram retention-graph screenshot | First growth feature after the MVP |
| Growth coach | Compares the creator's stats with public videos of successful creators in the same niche and explains the gap in the creator's language. When the niche is very new, learns from adjacent niches and general patterns | The creator's own Instagram and YouTube insights, with consent; public videos of top creators | After retention editing |
| Pre-publish drop-off prediction (proposed) | Marks likely drop-off points before the creator posts | Retention data from the creator's past videos | Later |
| Hook variants (proposed) | Three alternative openings cut from the same footage, to test | The edit manifest | Later |
| Comment mining (proposed) | Reads Malayalam, Manglish and Hinglish comments for requests (creators) or doubts (educators) | Comments on the creator's own posts | Later |
| What to shoot next (proposed) | A short script outline: hook, structure, target length | Growth coach output | Later |
| Creator benchmarks (proposed) | Compares against anonymised creators of the same language, niche and follower range | Consented analytics from many users | Once enough creators use it |

**Data access.** The YouTube Analytics API returns a retention curve of up to 100 points per video, plus a score against videos of similar length ([Zernio docs](https://docs.zernio.com/analytics/get-youtube-video-retention)). Instagram shows a per-second retention chart in the app ([Inro guide](https://www.inro.social/blog/instagram-reels-insights)), but its API documents aggregates such as average watch time and total view time ([Meta docs](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights)) and needs a Business or Creator account ([Benly](https://benly.ai/learn/dimensions-metrics/instagram-insights-dimensions-metrics)). The first version therefore reads a screenshot of the Instagram retention graph with a vision model.

**For educators.** The same features read differently: drop-offs show where students got lost, and comment mining surfaces doubts instead of content requests.

**Smallest first version:** YouTube retention curve or Instagram screenshot → AI marks the drop-offs → the next video's edit fixes them.

## Moat

The architecture is not the moat: anyone can wire WhisperX, an LLM and FFmpeg together. The moat is what builds up only through use: corrected Malayalam captions, a record of which AI edits people keep, and each customer's saved style.

*[Diagram in the online version: data flywheel · 4 steps around consented edit data]*

Each Reel a user fixes teaches the system something; the fixes improve the next Reel, which earns more users and more fixes. The loop only works if users agreed to let their edits improve the product.

### Five layers, strongest first

| Layer | What it is | Start building it during the MVP by | It is working when |
| --- | --- | --- | --- |
| Indian-language speech quality | Corrected Malayalam and Manglish transcripts and word timings, plus each brand's vocabulary (names, places, products) | Saving every caption correction users make, with consent | Caption word error rate on the golden set falls every month |
| Edit-acceptance data | The AI's first edit compared with what the user finally exported | Storing both versions of the manifest for every job | Edit acceptance rate rises every month |
| Brand style memory | Each customer's fonts, colours, pacing and rules, learned from their revisions | Saving chat revisions as style rules | Returning customers need fewer revisions per Reel |
| Workflow lock-in | Brand kits, team review and client approval links, publishing | Adding after the done-for-you phase | Most agency customers use review links |
| Local trust and distribution | Malayalam case studies, Kochi agency partners, honest disclosure of generated content | Collecting case studies from the first paying clients | A growing share of signups come from referrals |
| Creator performance benchmarks | Anonymised retention and growth data across regional creators, by language, niche and follower range | Storing connected analytics with consent from the first growth-feature user | Benchmarks cover enough creators per niche to show a useful comparison |

### What is not a moat

- The technical architecture in the original plan.
- Being first to Malayalam captions: a competitor can add a language in one release.
- Prompts on their own.

### Rules that protect the moat

- **Consent first.** A clear checkbox saying edits are used to improve the product, and a working delete button. Data collected without consent is a liability, not an asset.
- **Keep the golden test set private and growing.** It is how you prove quality to customers and investors.
- **Keep speech and LLM providers behind your own interface.** You can then switch providers without losing the data or the product.

## After the MVP: validation, pricing and metrics

Once the MVP works on the golden set, spend 6–8 weeks selling finished Reels before building self-serve features. Paying users tell you what to build next, what to charge, and whether the moat is forming.

### Step 1: Done-for-you validation

1. Sign 10–20 paying clients from the segment chosen in Positioning.
2. Deliver their Reels through your own pipeline, fixing anything wrong by hand.
3. Log every manual fix: what was wrong (caption word, timing, cut, framing, style) and how many minutes it took. The most frequent fixes are the next features to build.
4. Ask each client to rate every Reel as "post as is", "small fixes" or "redo".
5. Test two or three price points across clients rather than guessing one.

Starting price hypotheses to test, not conclusions: a monthly package of 12–20 Reels in the ₹5,000–15,000 range for businesses. The ceiling is what a part-time Malayalam editor costs them; the floor is Submagic's $19 self-serve plan.

### Step 2: Unit economics

Cost per exported minute = speech-to-text + LLM tokens + GPU render time + storage. Sum it from the job logs added in the build phase.

| Cost line | How to measure | Note |
| --- | --- | --- |
| Speech-to-text | Provider bill ÷ minutes processed | A third-party report puts Sarvam at about [₹30 per audio hour](https://smallest.ai/hi/blog/sarvam-ai-speech-to-text-pricing); confirm on Sarvam's own price page |
| LLM planning and revisions | Tokens per job × model price | Revisions are the variable part; cap them per plan |
| Rendering | GPU or CPU seconds per minute × hourly rate | Chromium overlay render is usually the slowest step |
| Storage | GB kept × days × rate | Delete raw uploads after a set period |

Aim for gross margin above 70% at your chosen price. If a plan cannot reach it, raise the price, cap revisions, or move the expensive step to a cheaper model.

### Step 3: Pricing model

- **Creators:** credits per finished Reel, not per uploaded minute. Per-minute billing is a common complaint about OpusClip and Descript, so this is a visible difference.
- **Businesses and agencies:** monthly plans by Reel volume, with brand kits and seats.
- **Price in rupees** for India from day 1; add USD plans only when you expand beyond India.

### Step 4: Startup metrics

Set these up when the first paying users arrive. The targets are starting goals to revise with real data.

| Metric | Definition | Why it matters | Starting goal |
| --- | --- | --- | --- |
| Time to first export | Signup to first downloaded Reel | Activation | Under 10 minutes |
| Edit acceptance rate | Share of AI-placed captions, cuts and titles the user keeps unchanged | Core quality signal and the moat's fuel | Rising every month |
| Post-as-is rate | Share of Reels rated "post as is" | Quality as the customer sees it | Above 60% |
| Weekly active exporters | Users who export at least one Reel in a week | Real usage, not signups | Growing week over week |
| Week-4 retention | Share of a signup week's users still exporting 4 weeks later | Whether the product sticks | Above 30% |
| Free-to-paid conversion | Paying users ÷ signups in a cohort | Willingness to pay | Measure first, then set |
| Cost per exported minute | From job logs | Margin safety | Falling every month |
| Gross margin | (Revenue − variable cost) ÷ revenue | Business viability | Above 70% |

Gate for the next language: move on when Malayalam reaches the post-as-is and retention goals with at least 20 paying customers.

## Sources

Pricing and features

- [Submagic pricing](https://www.submagic.co/pricing) · [OpusClip pricing](https://www.opus.pro/pricing) · [Captions pricing](https://captions.ai/pricing)
- [Descript pricing (Knowlify)](https://knowlify.com/articles/descript-pricing) · [Kapwing pricing (CostBench)](https://costbench.com/software/video-editing/kapwing/) · [VEED pricing (Dupple)](https://dupple.com/pricing/veed)
- [Vizard (VMEG)](https://www.vmeg.ai/blog/vizard-ai-alternative/) · [Klap vs OpusClip (Cut.pro)](https://cut.pro/en/blog/klap-vs-opusclip-2026) · [Jupitrr pricing change](https://pricingsaas.com/companies/jupitrr/diffs/2026W42)
- [CapCut pricing and India ban (FluxNote)](https://fluxnote.io/guides/capcut-questions-answered) · [invideo (Subger)](https://subger.com/en/service/invideo)
- [Captiq](https://hunted.space/product/captiq) · [aivideocaption](https://www.stork.ai/en/aivideocaption) · [OpenCut AI](https://www.hunted.space/product/opencutai-video/launches/free-ai-video-editor-opencutai) · [Atlabs Malayalam captions](https://www.atlabs.ai/features/ai-subtitle-generator/malayalam)
- [Lokal: Malayalam editor role](https://apply.workable.com/lokal-app/jobs/view/7C08DCC6F2.md) · [Inertia Labs: Malayalam editor role](https://jobs.weekday.works/video-editor-malayalam-at-inertialabs-technologies-wkdyj0elyd)

Fact-check and technical

- [WhisperX on GitHub](https://github.com/m-bain/whisperX) · [WhisperX on PyPI](https://pypi.org/project/whisperx/) · [WhisperX alignment models](https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py)
- [WhisperX results summary](https://www.emergentmind.com/topics/whisperx) · [CrisperWhisper paper](https://arxiv.org/pdf/2408.16589)
- [FilmCraft README](https://raw.githubusercontent.com/storytold/filmcraft/main/README.md) · [videopython](https://pypi.org/project/videopython/0.55.2/) · [FableCut](https://images.glama.ai/mcp/servers/ronak-create/FableCut)
- [TwelveLabs Marengo](https://www.twelvelabs.io/marengo) · [Modal cold-start report](https://byteiota.com/gpu-inference-cold-starts-cut-40x-heres-the-stack/) · [Remotion Lambda docs](https://cloudrun.remotion.dev/docs/lambda)
- [Cloudflare R2 vs S3 pricing](https://mecanik.dev/en/posts/cloudflare-r2-pricing-explained-real-costs-vs-s3-and-backblaze/) · [Descript MCP server](https://www.developersdigest.tech/mcp-servers/descript)
- [EBU R 128](https://Www.Wikipedia.org/wiki/EBU_R_128) · [Loudness targets by platform](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026)
- [India IT Amendment Rules 2026](https://www.exchange4media.com/digital-news/new-rule-mandates-clear-labelling-of-synthetic-content-on-digital-platforms-151874.html)
- [Sarvam speech models](https://docs.sarvam.ai/api/getting-started/models.md) · [Sarvam pricing report](https://smallest.ai/hi/blog/sarvam-ai-speech-to-text-pricing) · [AI4Bharat IndicConformer](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual)
- [MMS forced aligner tutorial](https://docs.pytorch.org/audio/main/tutorials/forced_alignment_for_multilingual_data_tutorial.html) · [TorchAudio forced-alignment API status](https://docs.pytorch.org/audio/main/tutorials/ctc_forced_alignment_api_tutorial.html)

Growth features and agentic editors

- [Cardboard – Y Combinator](https://www.ycombinator.com/companies/cardboard) · [Cardboard review – OutlierKit](https://outlierkit.com/resources/cardboard-review/) · [Aalap](https://159-65-147-234.sslip.io/)
- [YouTube retention curve – Zernio docs](https://docs.zernio.com/analytics/get-youtube-video-retention) · [Instagram Reels Insights guide – Inro](https://www.inro.social/blog/instagram-reels-insights) · [Instagram media insights – Meta](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) · [Instagram Insights metrics – Benly](https://benly.ai/learn/dimensions-metrics/instagram-insights-dimensions-metrics)
