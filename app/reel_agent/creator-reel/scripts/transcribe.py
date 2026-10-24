"""Word timings with the Euphoria app's own Whisper setup (faster-whisper, Malayalam fine-tuned model when downloaded).
usage: python transcribe.py <audio.wav> <out_words.json> [--lang ml|hi|en|auto] [--task transcribe|translate]
--engine openai = Malayalam + English text from OpenAI gpt-4o-transcribe (key in app/.env), timed from the audio.
--task translate = English captions for Malayalam/Hindi/... speech (Whisper's own translation, word timed).
Writes [{"w": word, "s": start, "e": end, "p": probability}] and prints the transcript with indexes and start times.
Language: --lang, else $REEL_LANG, else auto-detect. Times are seconds.
Needs $EUPHORIA_APP = the app folder (the backend sets it).

Transcribes in short pieces split at pauses (editor.transcribe.transcribe_chunked): given one long window, the
Malayalam model skipped most of a Manglish take or wrote it out as an English translation. For English, a tiny
prompt made of fillers nudges Whisper to write the "umm / uh" it usually drops, so the cutter can remove them.
Then word times are repaired: zero-length words get a share of the time after them."""
import json, os, sys

app = os.environ.get('EUPHORIA_APP')
if not app:
    sys.exit('EUPHORIA_APP is not set; it must point at the app folder that contains editor/')
sys.path.insert(0, app)
os.environ.setdefault('HF_HUB_OFFLINE', '1')
from editor.transcribe import transcribe_chunked, transcribe_openai_hybrid  # noqa: E402

# Only English gets the filler prompt: tested on a Manglish take, a prompt made the Malayalam model drop words.
# For other languages the cutter finds umm / aa sounds in the audio instead.
PROMPTS = {'en': 'Umm, uh... hmm.'}

src, out = sys.argv[1], sys.argv[2]
lang = sys.argv[sys.argv.index('--lang') + 1] if '--lang' in sys.argv else os.environ.get('REEL_LANG', 'auto')
lang = lang or 'auto'
task = sys.argv[sys.argv.index('--task') + 1] if '--task' in sys.argv else 'transcribe'
if '--engine' in sys.argv and sys.argv[sys.argv.index('--engine') + 1] == 'openai':
    r = transcribe_openai_hybrid(src, lang)          # accurate Manglish text, timing laid over the speech
else:
    r = transcribe_chunked(src, lang, prompt=None if task == 'translate' else PROMPTS.get(lang), task=task)
W = [{'w': w['text'], 's': w['start'], 'e': w['end'], 'p': w.get('prob', 1.0)} for w in r['words']]
W = [w for w in W if not set(w['w']) <= set('.,…-!? ')]

for i, w in enumerate(W):                      # keep times in order; no zero-length words
    if i and w['s'] < W[i - 1]['s']:
        w['s'] = W[i - 1]['s']
    nxt = W[i + 1]['s'] if i + 1 < len(W) else w['e'] + 0.3
    if w['e'] - w['s'] < 0.08:
        w['e'] = round(min(w['s'] + 0.12, max(nxt, w['s'] + 0.08)), 3)
json.dump(W, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
print('language', r.get('language'), '| model', r.get('model'), '| pieces', len(r.get('chunks', [])) - 1, '|',
      r.get('note') or '')
print(' '.join(w['w'] for w in W))
print()
print(' '.join(f"{i}:{w['w']}@{w['s']}" + ('?' if w['p'] < 0.5 else '') for i, w in enumerate(W)))
print('\n(? = low-confidence word, check it against the context)')
