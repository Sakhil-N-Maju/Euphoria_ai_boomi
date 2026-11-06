"""Where and how much the screen changes over time (no AI): the planner's map of a screen recording.
usage: python activity.py [--step 0.5]   (job folder: src.mp4, src.json)  -> activity.json
{"dur": s, "step": 0.5, "w": W, "h": H, "rows": [[t, score, x0, y0, x1, y1] ...]}
score = fraction of the screen that changed in that step (0..1); box = where it changed, in fractions of the frame
(None when nothing moved)."""
import json, os, sys, subprocess, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from envlib import FF
os.chdir(os.environ.get('REEL_HOME') or os.getcwd())
STEP = float(sys.argv[sys.argv.index('--step') + 1]) if '--step' in sys.argv else 0.5
SRC = json.load(open('src.json'))
FPS = 10
w = 192; h = max(2, int(round(SRC['h'] * w / SRC['w'] / 2)) * 2)
p = subprocess.Popen([FF, '-v', 'error', '-i', 'src.mp4', '-an', '-vf', f'fps={FPS},scale={w}:{h}:flags=area,format=gray',
                      '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
prev = None; per = int(round(STEP * FPS)); acc = []; rows = []; i = 0
def flush(t):
    if not acc:
        return
    m = np.maximum.reduce(acc)
    score = float((m > 0).mean())
    if score < 0.0008:
        rows.append([round(t, 2), round(score, 4), None, None, None, None])
    else:
        ys, xs = np.nonzero(m)
        x0, x1 = np.percentile(xs, [3, 97]); y0, y1 = np.percentile(ys, [3, 97])
        rows.append([round(t, 2), round(score, 4), round(x0 / w, 3), round(y0 / h, 3), round((x1 + 1) / w, 3), round((y1 + 1) / h, 3)])
    acc.clear()
while True:
    b = p.stdout.read(w * h)
    if len(b) < w * h:
        break
    f = np.frombuffer(b, np.uint8).reshape(h, w).astype(np.int16)
    if prev is not None:
        acc.append((np.abs(f - prev) > 14).astype(np.uint8))
    prev = f; i += 1
    if i % per == 0:
        flush((i - per) / FPS)
flush((i - len(acc)) / FPS)
p.wait()
json.dump({'dur': SRC['dur'], 'step': STEP, 'w': SRC['w'], 'h': SRC['h'], 'rows': rows}, open('activity.json', 'w'))
act = [r for r in rows if r[1] >= 0.002]
print(f'activity: {len(rows)} steps, {len(act)} with movement, busiest {max([r[1] for r in rows] or [0]):.3f}')
