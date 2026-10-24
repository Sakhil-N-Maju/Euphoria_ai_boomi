"""Lean mode: turn Claude's small JSON edit plan into every file the renderer needs, with no more AI calls.
usage: python build_plan.py edit_plan.json        (run in the job folder; needs words.json, src.mp4, src.json, env.json)

edit_plan.json refers to WORD INDEXES from words.json (never to times), so Claude does no timing math:
  keep     [[first_word, last_word], ...]       word ranges to keep (fillers / retakes / false starts left out)
  fix      {"12": "Claude"}                       corrected spellings for misheard words
  accent   [12, 40]                               3-7 key words shown in the accent colour
  headline {"l1": "...", "l2": "..."}            hook text on frame 0 (l2 goes in the lime box)
  back     {"text": "GROW", "word": 5}            giant word behind the head for the first seconds, glows on that word
  beats    [{"type": "...", "from": i, "to": j, ...}]   graphics; see the rules file for the types and fields
  cta      {"keyword": "TEAM", "from": i, "label": "COMMENT THE WORD"}
Writes keep.json, edit.json (via cuts.py), subs.txt + subs.json (via subs.py), plan.json, pip.json, overlay_cfg.json,
sfx_events.json, overlay.html, words_out.json, and prints a short summary."""
import json, os, re, subprocess, sys
import numpy as np, cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from envlib import ENV, FF  # noqa: E402
from speech import Audio  # noqa: E402
from cutter import plan_cuts, plan_cuts_audio  # noqa: E402

PY = sys.executable
OW, OH, FPS = 1080, 1920, 30
PANEL = {'counter', 'list', 'checklist', 'toggle', 'typing', 'strike', 'steps', 'bars'}
CARD = {'statement'}
OVER = {'sticker'}

plan = json.load(open(sys.argv[1], encoding='utf-8'))
W = json.load(open('words.json', encoding='utf-8'))
SRC = json.load(open('src.json'))
N = len(W)
clampi = lambda i: max(0, min(N - 1, int(i)))
for src_fix in (plan.get('fix') or {}, plan.get('user_fix') or {}):     # the creator's own spellings win
    for k, v in src_fix.items():
        if str(k).isdigit() and int(k) < N and str(v).strip():
            W[int(k)]['w'] = str(v).strip()

# ---------- 1. cuts: word ranges -> time ranges; pauses, fillers and word edges come from the audio ----------
rngs = sorted([sorted([clampi(a), clampi(b)]) for a, b in (plan.get('keep') or [[0, N - 1]])])
man = plan.get('manual') or {}
if man.get('cut') or man.get('keep'):                 # words the creator cut or brought back by hand
    ks = set(i for a, b in rngs for i in range(a, b + 1))
    ks |= set(clampi(i) for i in man.get('keep') or [])
    ks -= set(clampi(i) for i in man.get('cut') or [])
    rngs, cur = [], None
    for i in range(N):
        if i in ks:
            cur = [cur[0], i] if cur else [i, i]
        elif cur:
            rngs.append(cur); cur = None
    if cur:
        rngs.append(cur)
forced = set(clampi(i) for i in man.get('keep') or [])
A = Audio('audio16k.wav')
PACE = plan.get('pace') or os.environ.get('REEL_PACE') or 'tight'
if (plan.get('cut_mode') or 'gaps') == 'gaps':        # keep everything said; audio decides what goes
    merged, CUTREP, kept = plan_cuts_audio(W, A, pace=PACE, cut_fillers=plan.get('cut_fillers', True),
                                           protect=forced, cut_words=man.get('cut') or [])
else:                                                 # "smart": the AI's keep ranges (retakes cut) + audio
    merged, CUTREP, kept = plan_cuts(W, rngs, A, pace=PACE, cut_fillers=plan.get('cut_fillers', True),
                                     protect=forced)
json.dump(merged, open('keep.json', 'w'))
subprocess.run([PY, os.path.join(HERE, 'cuts.py'), 'apply'], check=True)
E = json.load(open('edit.json'))
DUR = E['dur']

def out_t(src_t):
    """source time -> output time (None if cut)"""
    for s in E['segs']:
        if s['src0'] - 1e-3 <= src_t <= s['src1'] + 1e-3:
            return round(s['out0'] + (src_t - s['src0']), 3)
    return None

def out_span(s0, s1):
    """output time of the first kept moment inside [s0, s1] (a word whose first part was a cut "umm")"""
    for s in E['segs']:
        if s['src1'] > s0 + 0.02 and s['src0'] < s1 - 0.02:
            return round(s['out0'] + (max(s0, s['src0']) - s['src0']), 3)
    return None

WO = []          # kept words with output times
for i, w in enumerate(W):
    e_src = w.get('e', w['s'] + 0.3)
    t = out_span(w['s'], max(e_src, w['s'] + 0.05))
    if i in kept and t is not None:
        e = out_t(e_src)
        WO.append({'i': i, 'w': w['w'], 's': t, 'e': e if e and e > t else t + 0.3})
json.dump(WO, open('words_out.json', 'w', encoding='utf-8'), ensure_ascii=False)
POS = {w['i']: w for w in WO}

def wt(i, end=False, default=None):
    """output time of word i (nearest kept word if i was cut)"""
    i = clampi(i)
    if i in POS:
        return POS[i]['e' if end else 's']
    near = [w for w in WO if (w['i'] >= i if not end else w['i'] <= i)]
    if near:
        w = near[0] if not end else near[-1]
        return w['e' if end else 's']
    return default if default is not None else (DUR if not end else 0.0)

# ---------- 2. captions: auto chunks of 1-4 words ----------
accent = set(int(x) for x in plan.get('accent') or [])
lines, cur = [], []
for k, w in enumerate(WO):
    if cur:
        prev = cur[-1]
        chars = sum(len(x['w']) for x in cur) + len(w['w'])
        if len(cur) >= 4 or chars > 24 or w['s'] - prev['e'] > 0.35 or re.search(r'[.!?,]$', prev['w']):
            lines.append(cur); cur = []
    cur.append(w)
if cur:
    lines.append(cur)
with open('subs.txt', 'w', encoding='utf-8') as f:
    for ln in lines:
        f.write(' ; '.join(f"{w['s']:.2f} {'*' if w['i'] in accent else ''}{w['w']}" for w in ln) + '\n')
subprocess.run([PY, os.path.join(HERE, 'subs.py'), 'subs.txt'], check=True, capture_output=True)

# ---------- 3. face position (no AI): OpenCV face finder on a few frames ----------
def grab_gray(t):
    sw, sh = SRC['w'], SRC['h']
    raw = subprocess.run([FF, '-v', 'error', '-ss', f'{t:.2f}', '-i', 'src.mp4', '-frames:v', '1', '-f', 'rawvideo',
                          '-pix_fmt', 'bgr24', '-'], capture_output=True).stdout
    return np.frombuffer(raw[:sw * sh * 3], np.uint8).reshape(sh, sw, 3) if len(raw) >= sw * sh * 3 else None

def faces():
    """face centre (fx, fy as fractions), head top and face height in source pixels. Haar cascade when OpenCV has it,
    else the person cut-out model (head = top of the silhouette), else a centred default."""
    sw, sh = SRC['w'], SRC['h']
    times = np.linspace(0.5, max(0.6, SRC['dur'] - 0.5), 6)
    found = []
    if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data'):
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        for t in times:
            img = grab_gray(t)
            if img is None:
                continue
            fs = casc.detectMultiScale(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(sw // 8, sw // 8))
            if len(fs):
                x, y, w, h = max(fs, key=lambda r: r[2] * r[3]); found.append((x + w / 2, y + h / 2, y - 0.35 * h, h))
    mp = os.path.join(ENV.get('models', ''), 'seg', 'u2net_human_seg.onnx')
    if not found and os.path.exists(mp):
        import onnxruntime as ort
        S = ort.InferenceSession(mp, providers=['CPUExecutionProvider'])
        for t in times:
            img = grab_gray(t)
            if img is None:
                continue
            x = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (320, 320)).astype(np.float32); x /= max(x.max(), 1e-6)
            x = (x - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
            m = S.run(None, {S.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
            m = cv2.resize((m - m.min()) / (m.max() - m.min() + 1e-6), (sw, sh)) > 0.5
            rows = np.where(m.any(1))[0]
            if not len(rows):
                continue
            top = rows[0]; hh = 0.16 * sh
            band = m[top:int(top + hh)]
            cols = np.where(band.any(0))[0]
            cx = cols.mean() if len(cols) else sw / 2
            found.append((cx, top + hh * 0.55, top, hh * 0.8))
    if not found:
        return 0.5, 0.40, 0.18 * sh, 0.25 * sh
    a = np.median(np.array(found), axis=0)
    return a[0] / sw, a[1] / sh, a[2], a[3]

fx, fy, head_top, face_h = faces()
S0 = max(OW / SRC['w'], OH / SRC['h'])
head_top_out = head_top * S0
low_oy = int(round(880 - max(0, head_top_out - 70)))      # face area starts at y 880, head ~70 px below its top

# ---------- 4. beats ----------
beats, cta = [], plan.get('cta') or {}
for b in plan.get('beats') or []:
    ty = b.get('type')
    if ty not in PANEL | CARD | OVER:
        continue
    t0 = max(0.0, wt(b.get('from', 0)) - 0.15)
    t1 = min(DUR, wt(b.get('to', b.get('from', 0)), end=True) + 0.30)
    if t1 - t0 < 1.2:
        t1 = min(DUR, t0 + 1.2)
    items = b.get('items') or []
    ks = [wt(x.get('word', b.get('from', 0))) for x in items] if items else [wt(b.get('word', b.get('from', 0)))]
    ks = [min(max(k, t0 + 0.25), t1 - 0.3) for k in ks]
    d = {k: v for k, v in b.items() if k not in ('from', 'to', 'word')}
    d.update({'t0': round(t0, 3), 't1': round(t1, 3), 'k': [round(k, 3) for k in ks]})
    beats.append(d)
beats.sort(key=lambda b: b['t0'])
for i in range(1, len(beats)):                      # no two layouts at once: trim the earlier one
    p, c = beats[i - 1], beats[i]
    if c['type'] not in OVER and p['type'] not in OVER and c['t0'] < p['t1'] + 0.2:
        p['t1'] = round(max(p['t0'] + 0.8, c['t0'] - 0.2), 3)
hl = plan.get('headline') or {}
first_layout = min([b['t0'] for b in beats if b['type'] not in OVER] + [3.6])
if hl:
    hl = {'l1': hl.get('l1', ''), 'l2': hl.get('l2', ''), 'until': round(min(3.8, max(2.0, first_layout - 0.1)), 3)}
if cta.get('keyword'):
    c0 = max(0.0, wt(cta.get('from', N - 1)) - 0.1)
    if DUR - c0 < 2.2:
        c0 = max(0.0, DUR - 2.4)
    beats = [b for b in beats if b['t0'] < c0 - 0.5]
    for b in beats:
        b['t1'] = round(min(b['t1'], c0 - 0.15), 3)
    beats.append({'type': 'cta', 't0': round(c0, 3), 't1': round(DUR + 1, 3), 'k': [round(c0 + 0.45, 3)],
                  'keyword': cta['keyword'], 'label': cta.get('label', 'COMMENT THE WORD')})

# ---------- 5. layouts (pip.json) + caption placement ----------
states = {'full': [0, 0, 1080, 1920, 0, 1, 0, 0], 'low': [0, 880, 1080, 1040, 0, 1.0, 0, low_oy]}
keys, caps = [[0, 'full']], []
for b in beats:
    if b['type'] in PANEL:
        a, z = b['t0'], b['t1']
        keys += [[max(0, a - 0.01), 'full'], [a + 0.35, 'low', 'eo5'], [z - 0.3, 'low'], [z + 0.05, 'full', 'eio']]
        caps.append([a + 0.2, z - 0.1, 'pill', 862])
    elif b['type'] in CARD:
        caps.append([b['t0'], b['t1'], 'pill', 1500])
    elif b['type'] == 'cta':
        caps.append([b['t0'], DUR + 1, 'pill', 1320])
keys.sort(key=lambda k: k[0])
json.dump({'states': states, 'keys': keys}, open('pip.json', 'w'))

# ---------- 6. zoom, grade, back text ----------
zoom = [[1.0, 1.035] if k % 2 == 0 else [1.07, 1.1] for k in range(len(E['segs']))]
if plan.get('zoom') is False:
    zoom = [[1.0, 1.0] for _ in E['segs']]
busy = [(b['t0'] - 0.3, b['t1'] + 0.3) for b in beats if b['type'] in PANEL | CARD]
punch = []
for w in WO:
    if w['i'] in accent and not any(a <= w['s'] <= z for a, z in busy) and w['s'] > 1.0:
        if not punch or w['s'] - punch[-1][3] > 2.5:
            punch.append([round(w['s'] - 0.03, 3), 1.12, 1.13, round(w['s'] + 0.5, 3)])
if plan.get('punch_ins') is False:
    punch = []
json.dump({'anchors': [{'until': 9999, 'fx': round(float(fx), 3), 'fy': round(float(fy), 3)}], 'zoom': zoom,
           'punch': punch[:4], 'grade': 0.9, 'tint': [-0.012, 0.03, -0.006], 'pop': 0.84}, open('plan.json', 'w'))
back = None
bk = plan.get('back') or {}
if bk.get('text') and ENV.get('seg'):
    until = round(min(4.2, max(2.0, first_layout - 0.05)), 3)
    size = 330 if len(bk['text']) <= 5 else max(170, int(1650 / len(bk['text'])))
    top = int(max(330 if hl else 150, head_top_out - 0.55 * size))   # stay under the headline
    back = {'text': bk['text'], 'top': top, 'size': size, 'until': until, 'glow': wt(bk.get('word', 0))}
json.dump({'back': [[0, back['until']]] if back else []}, open('overlay_cfg.json', 'w'))

# ---------- 7. overlay.html ----------
P = {'accent': plan.get('accent_color') or '#C6F432', 'headline': hl or None, 'back': back, 'beats': beats, 'caps': caps}
tpl = open(os.path.join(HERE, '..', 'templates', 'lean_overlay.html'), encoding='utf-8').read()
tpl = re.sub(r'/\*PLAN\*/.*?/\*END\*/', lambda m: '/*PLAN*/' + json.dumps(P, ensure_ascii=False) + '/*END*/', tpl, count=1, flags=re.S)
open('overlay.html', 'w', encoding='utf-8').write(tpl)

# ---------- 8. sound effects ----------
ev = [[0.04, 'hit', -24, {}]]
for b in beats:
    if b['type'] in PANEL | CARD:
        ev.append([max(0, b['t0'] - 0.05), 'air', -30, {}])
    if b['type'] in ('list', 'checklist', 'steps'):
        ev += [[k, 'pop', -32, {}] for k in b['k']]
    if b['type'] in ('counter', 'sticker', 'bars'):
        ev.append([b['k'][0], 'ticks', -33, {'dur': 0.85}])
    if b['type'] == 'toggle':
        ev.append([b['k'][0] + 0.7, 'tap', -28, {}])
    if b['type'] == 'strike':
        ev += [[b['k'][0], 'swipe', -30, {}], [b['k'][0] + 0.35, 'pop', -28, {}]]
    if b['type'] == 'typing':
        n = len(b.get('text') or '')
        ev += [[round(b['k'][0] + j / 20, 3), 'key', -38, {'seed': j}] for j in range(0, min(n, 60), 2)]
    if b['type'] == 'statement':
        ev.append([b['t0'] + 0.05, 'hit', -26, {}])
    if b['type'] == 'cta':
        ev += [[max(0, b['t0'] - 0.85), 'riser', -30, {'dur': 0.85}], [b['t0'], 'hit', -25, {}]]
        ev += [[round(b['k'][0] + j / 8, 3), 'key', -36, {'seed': 50 + j}] for j in range(len(b['keyword']))]
ev = sorted([e for e in ev if 0 <= e[0] < DUR], key=lambda e: e[0])
if plan.get('sfx') is False:
    ev = []
json.dump(ev, open('sfx_events.json', 'w'))

json.dump(CUTREP, open('cut_report.json', 'w'))
print(f'cut {SRC["dur"]:.1f}s -> {DUR:.1f}s in {len(E["segs"])} pieces | {len(CUTREP["fillers"])} filler words + '
      f'{CUTREP["sounds"]} umm sounds removed | {CUTREP["pauses"]} pauses tightened | {len(lines)} captions | '
      f'{len(beats)} graphics | {len(punch[:4])} punch-ins | face fx={fx:.2f} fy={fy:.2f} | back text: {"yes" if back else "no"}')
