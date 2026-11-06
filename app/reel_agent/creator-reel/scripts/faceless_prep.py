"""Faceless style: make the 'footage' the engine edits - the style background as a still video - plus word timings.
usage: python faceless_prep.py script.txt [--voice voice_audio] [--wps 2.6]     (job folder; bg.png must exist)
  with --voice: src.mp4 = background + that voice-over (word timings then come from transcribe.py)
  without:      src.mp4 = background + silence, as long as the script read at --wps words a second, and
                words.json = the script's words timed at that pace (punctuation adds a pause)
Writes src.mp4, src.json, audio16k.wav (and words.json when there is no voice)."""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from envlib import ff, probe  # noqa: E402
os.chdir(os.environ.get('REEL_HOME') or os.getcwd())
text = open(sys.argv[1], encoding='utf-8').read().strip() if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else ''
voice = sys.argv[sys.argv.index('--voice') + 1] if '--voice' in sys.argv else None
wps = float(sys.argv[sys.argv.index('--wps') + 1]) if '--wps' in sys.argv else 2.6
V = ['-loop', '1', '-framerate', '30', '-i', 'bg.png']
ENC = ['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '20', '-pix_fmt', 'yuv420p', '-g', '30', '-r', '30']
if voice:
    dur = probe(voice)['dur']
    ff(*V, '-i', voice, '-map', '0:v', '-map', '1:a', *ENC, '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-t', f'{dur + 0.4:.3f}', 'src.mp4')
else:
    words, t = [], 0.45
    for tok in text.split():
        if not re.search(r'\w', tok):
            continue
        d = (0.62 + 0.38 * min(len(tok), 12) / 5) / wps
        words.append({'w': tok, 's': round(t, 3), 'e': round(t + d * 0.92, 3), 'p': 1.0})
        t += d + (0.38 if re.search(r'[.!?]["”’)]*$', tok) else 0.16 if re.search(r'[,;:—–-]$', tok) else 0)
    if not words:
        sys.exit('The script is empty.')
    dur = words[-1]['e'] + 1.2
    json.dump(words, open('words.json', 'w', encoding='utf-8'), ensure_ascii=False)
    ff(*V, '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a', *ENC, '-c:a', 'aac', '-b:a', '128k',
       '-t', f'{dur:.3f}', 'src.mp4')
ff('-i', 'src.mp4', '-vn', '-ac', '1', '-ar', '16000', 'audio16k.wav')
q = probe('src.mp4'); json.dump(q, open('src.json', 'w'))
print('faceless source', round(q['dur'], 1), 's', '(voice-over)' if voice else f'(script read at {wps} words/s, {len(text.split())} words)')
