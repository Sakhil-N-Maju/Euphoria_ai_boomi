"""Word timings with the Euphoria app's own Whisper setup (faster-whisper, Malayalam fine-tuned model when downloaded).
usage: python transcribe.py <audio.wav> <out_words.json> [--lang ml|hi|en|auto]
Writes [{"w": word, "s": start, "e": end, "p": probability}] and prints the transcript with indexes and start times.
Language: --lang, else $REEL_LANG, else auto-detect. Times are seconds.
Needs $EUPHORIA_APP = the app folder (the backend sets it)."""
import json, os, sys

app = os.environ.get('EUPHORIA_APP')
if not app:
    sys.exit('EUPHORIA_APP is not set; it must point at the app folder that contains editor/')
sys.path.insert(0, app)
os.environ.setdefault('HF_HUB_OFFLINE', '1')
from editor.transcribe import transcribe_local  # noqa: E402

src, out = sys.argv[1], sys.argv[2]
lang = sys.argv[sys.argv.index('--lang') + 1] if '--lang' in sys.argv else os.environ.get('REEL_LANG', 'auto')
r = transcribe_local(src, lang or 'auto')
W = [{'w': w['text'], 's': w['start'], 'e': w['end'], 'p': w.get('prob', 1.0)} for w in r['words']]
json.dump(W, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
print('language', r.get('language'), '| model', r.get('model'), '|', r.get('note') or '')
print(' '.join(w['w'] for w in W))
print()
print(' '.join(f"{i}:{w['w']}@{w['s']}" + ('?' if w['p'] < 0.5 else '') for i, w in enumerate(W)))
print('\n(? = low-confidence word, check it against the context)')
