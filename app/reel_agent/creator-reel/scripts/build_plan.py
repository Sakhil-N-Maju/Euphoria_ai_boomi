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
# faceless scene library (templates/scenes.js): full-frame scenes modelled on the reference reels
SCENE = {'phone', 'code', 'timeline', 'graph', 'commentcta', 'figures', 'tags', 'speech', 'icons', 'notepad', 'magnify',
         'polaroids', 'window'}
SCARD = {'glowword', 'bigtype'}

plan = json.load(open(sys.argv[1], encoding='utf-8'))
# Decisions from the previous build (zoom per cut, punch-in words, caption lines). Reused for every part the change
# didn't touch, so an edit at 0:05 leaves the rest of the reel exactly as it was (and its render cache valid).
STABLE = json.load(open('stable.json', encoding='utf-8')) if os.path.exists('stable.json') else {}
# Edit style chosen in the Studio (app/reel_agent/styles/<id>/style.json). No style = the original Euphoria look.
def load_style(sid, look=None):
    if not sid:
        return {}
    pth = os.path.join(HERE, '..', '..', 'styles', sid, 'style.json')
    if not os.path.exists(pth):
        return {}
    st = json.load(open(pth, encoding='utf-8'))
    look = (st.get('aliases') or {}).get(look, look)
    if st.get('looks'):
        st.update(st['looks'].get(look) or next(iter(st['looks'].values())))
    return st
STY = load_style(plan.get('style'), plan.get('look'))
FACELESS = plan.get('style') == 'faceless'
if FACELESS:                                          # scenes are a faceless thing: they behave like panels / cards
    PANEL = PANEL | SCENE
    CARD = CARD | SCARD
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
if (plan.get('cut_mode') or 'gaps') == 'none':        # a script timed at reading speed (faceless, no voice): no cuts
    kept = set(i for a, b in rngs for i in range(a, b + 1))
    CUTREP = {'fillers': [], 'sounds': 0, 'pauses': 0, 'pause_s': 0}
    merged = [[0.0, round(SRC['dur'], 3)]]
    if man.get('cut'):                                # words the creator removed: cut their time out
        merged = []
        for a, b in rngs:
            s0 = W[a]['s'] if a else 0.0
            s1 = W[b + 1]['s'] if b + 1 < N else SRC['dur']
            merged.append([round(s0, 3), round(min(s1, SRC['dur']), 3)])
elif (plan.get('cut_mode') or 'gaps') == 'gaps':        # keep everything said; audio decides what goes
    merged, CUTREP, kept = plan_cuts_audio(W, A, pace=PACE, cut_fillers=plan.get('cut_fillers', True),
                                           protect=forced, cut_words=man.get('cut') or [])
else:                                                 # "smart": the AI's keep ranges (retakes cut) + audio
    merged, CUTREP, kept = plan_cuts(W, rngs, A, pace=PACE, cut_fillers=plan.get('cut_fillers', True),
                                     protect=forced)
json.dump(merged, open('keep.json', 'w'))
subprocess.run([PY, os.path.join(HERE, 'cuts.py'), 'apply'], check=True)
E = json.load(open('edit.json'))
DUR = E['dur']

def SN(x):
    """snap an output time to the 1/120 s grid. Cuts move later parts by whole frames (1/30 s = 4 grid steps), so a
    moment that only moved keeps exactly the same times relative to its frames -> same cached frames (render cache)"""
    return round(round(x * 120) / 120, 6)

def out_t(src_t):
    """source time -> output time (None if cut)"""
    for s in E['segs']:
        if s['src0'] - 1e-3 <= src_t <= s['src1'] + 1e-3:
            return SN(s['out0'] + (src_t - s['src0']))
    return None

def out_span(s0, s1):
    """output time of the first kept moment inside [s0, s1] (a word whose first part was a cut "umm")"""
    for s in E['segs']:
        if s['src1'] > s0 + 0.02 and s['src0'] < s1 - 0.02:
            return SN(s['out0'] + (max(s0, s['src0']) - s['src0']))
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
# (captions are written after the graphics are placed: see "captions, final")

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

def _fid(p):
    st = os.stat(p); return f'{st.st_size}:{int(st.st_mtime)}'
_fc = json.load(open('face.json')) if os.path.exists('face.json') else {}
if _fc.get('src') == _fid('src.mp4') and _fc.get('v') == 1:
    fx, fy, head_top, face_h = _fc['face']
else:
    fx, fy, head_top, face_h = (float(v) for v in faces())
    json.dump({'src': _fid('src.mp4'), 'v': 1, 'face': [fx, fy, head_top, face_h]}, open('face.json', 'w'))
S0 = max(OW / SRC['w'], OH / SRC['h'])
head_top_out = head_top * S0
low_oy = int(round(880 - max(0, head_top_out - 70)))      # face area starts at y 880, head ~70 px below its top

# ---------- 4. beats ----------
beats, cta = [], plan.get('cta') or {}
for b in plan.get('beats') or []:
    ty = b.get('type')
    if ty not in PANEL | CARD | OVER or (FACELESS and ty in OVER):
        continue
    t0 = max(0.0, wt(b.get('from', 0)) - 0.15)
    t1 = min(DUR, wt(b.get('to', b.get('from', 0)), end=True) + 0.30)
    if t1 - t0 < 1.2:
        t1 = min(DUR, t0 + 1.2)
    items = [x for x in (b.get('items') or []) if isinstance(x, dict)][:6]
    if items and all('word' in x for x in items):
        ks = [wt(x['word']) for x in items]
    elif items:                                       # no word per item: spread them over the beat
        ks = [t0 + 0.35 + j * max(0.25, (t1 - t0 - 1.0) / len(items)) for j in range(len(items))]
    else:
        ks = [wt(b.get('word', b.get('from', 0)))]
    ks = [min(max(k, t0 + 0.25), t1 - 0.3) for k in ks]
    if items:
        b = {**b, 'items': items}
    d = {k: v for k, v in b.items() if k not in ('from', 'to', 'word')}
    d.update({'t0': round(t0, 6), 't1': round(t1, 6), 'k': [round(k, 6) for k in ks]})
    beats.append(d)
beats.sort(key=lambda b: b['t0'])
for i in range(1, len(beats)):                      # no two layouts at once: trim the earlier one
    p, c = beats[i - 1], beats[i]
    if c['type'] not in OVER and p['type'] not in OVER and c['t0'] < p['t1'] + 0.2:
        p['t1'] = round(max(p['t0'] + 0.8, c['t0'] - 0.2), 6)
hl = plan.get('headline') or {}
first_layout = min([b['t0'] for b in beats if b['type'] not in OVER] + [3.6])
if hl:
    hl = {'l1': hl.get('l1', ''), 'l2': hl.get('l2', ''), 'until': round(min(3.8, max(2.0, first_layout - 0.1)), 6)}
if cta.get('keyword'):
    c0 = max(0.0, wt(cta.get('from', N - 1)) - 0.1)
    if DUR - c0 < 2.2:
        c0 = max(0.0, DUR - 2.4)
    beats = [b for b in beats if b['t0'] < c0 - 0.5]
    for b in beats:
        b['t1'] = round(min(b['t1'], c0 - 0.15), 6)
    beats.append({'type': 'cta', 't0': round(c0, 6), 't1': round(DUR + 1, 6), 'k': [round(c0 + 0.45, 6)],
                  'keyword': cta['keyword'], 'label': cta.get('label', 'COMMENT THE WORD')})

# ---------- 5. layouts (pip.json) + caption placement ----------
states = {'full': [0, 0, 1080, 1920, 0, 1, 0, 0], 'low': [0, 880, 1080, 1040, 0, 1.0, 0, low_oy]}
keys, caps = [[0, 'full']], []
CAPS = {'panel': ['pill', 862], 'card': ['pill', 1500], 'cta': ['pill', 1320], **(STY.get('captions') or {})}
CAPS.setdefault('scene', CAPS['panel'])
for b in beats:
    if b['type'] in PANEL:
        a, z = b['t0'], b['t1']
        if not FACELESS:                              # faceless: the panel floats mid-screen, no video to move
            keys += [[max(0, a - 0.01), 'full'], [a + 0.35, 'low', 'eo5'], [z - 0.3, 'low'], [z + 0.05, 'full', 'eio']]
        caps.append([a + 0.2, z - 0.1, *CAPS['scene' if b['type'] in SCENE else 'panel']])
    elif b['type'] in CARD:
        caps.append([b['t0'], b['t1'], *CAPS['card']])
    elif b['type'] == 'cta':
        caps.append([b['t0'], DUR + 1, *CAPS['cta']])
keys.sort(key=lambda k: k[0])
json.dump({'states': states, 'keys': keys}, open('pip.json', 'w'))

# ---------- 6. zoom, grade, back text ----------
PAIRS = [[1.0, 1.035], [1.07, 1.1], [1.035, 1.07]]
skey = lambda s: f"{s['src0']:.3f}-{s['src1']:.3f}"
old_zoom = {z[0]: z[1] for z in STABLE.get('zoom') or []}
if not old_zoom:                                      # first build: alternate, so a cut never looks like a skip
    zoom = [PAIRS[k % 2] for k in range(len(E['segs']))]
else:                                                 # same piece of video as last time -> same zoom
    zoom = [old_zoom.get(skey(s)) for s in E['segs']]
    for k in range(len(zoom)):
        if zoom[k] is None:
            nb = [zoom[k - 1] if k else None, zoom[k + 1] if k + 1 < len(zoom) else None]
            zoom[k] = next(p for p in PAIRS if p not in nb)
stable_zoom = [[skey(s), z] for s, z in zip(E['segs'], zoom)]
if plan.get('zoom') is False or (plan.get('zoom') is None and STY.get('zoom') is False):
    zoom = [[1.0, 1.0] for _ in E['segs']]
busy = [(b['t0'] - 0.3, b['t1'] + 0.3) for b in beats if b['type'] in PANEL | CARD]
ok_punch = lambda w: w['i'] in accent and not any(a <= w['s'] <= z for a, z in busy) and w['s'] > 1.0
greedy = []
for w in WO:
    if ok_punch(w) and (not greedy or w['s'] - round(greedy[-1]['s'] + 0.5, 3) > 2.5):
        greedy.append(w)
if 'punch' in STABLE:                                 # keep last time's punch-ins where they still fit
    chosen = [POS[i] for i in STABLE['punch'] if i in POS and ok_punch(POS[i])]
    for w in greedy:
        if len(chosen) < 4 and all(abs(w['s'] - c['s']) > 3.0 for c in chosen):
            chosen.append(w)
    chosen.sort(key=lambda w: w['s'])
else:
    chosen = greedy[:4]
chosen = chosen[:4]
punch = [[round(w['s'] - 0.03, 6), 1.12, 1.13, round(w['s'] + 0.5, 6)] for w in chosen]
stable_punch = [w['i'] for w in chosen]
if plan.get('punch_ins') is False or (plan.get('punch_ins') is None and STY.get('punch_ins') is False):
    punch = []
json.dump({'anchors': [{'until': 9999, 'fx': round(float(fx), 3), 'fy': round(float(fy), 3)}], 'zoom': zoom,
           'punch': punch, 'grade': STY.get('grade', 0.9), 'tint': STY['tint'] if 'tint' in STY else [-0.012, 0.03, -0.006],
           'pop': STY.get('pop', 0.84), 'vignette': not FACELESS}, open('plan.json', 'w'))
back = None
bk = plan.get('back') or {}
if bk.get('text') and ENV.get('seg') and not FACELESS:
    until = round(min(4.2, max(2.0, first_layout - 0.05)), 6)
    size = 330 if len(bk['text']) <= 5 else max(170, int(1650 / len(bk['text'])))
    top = int(max(330 if hl else 150, head_top_out - 0.55 * size))   # stay under the headline
    back = {'text': bk['text'], 'top': top, 'size': size, 'until': until, 'glow': wt(bk.get('word', 0))}
json.dump({'back': [[0, back['until']]] if back else []}, open('overlay_cfg.json', 'w'))

# ---------- block colours and numbers (styles with a palette) ----------
PAL = STY.get('palette') or []
CARDS = STY.get('cards') or []
if PAL:
    numbered = [b for b in beats if b['type'] in PANEL and b['type'] not in SCENE or b['type'] == 'window']
    for j, b in enumerate(numbered):
        b['num'], b['total'] = j + 1, len(numbered)
    for j, b in enumerate([b for b in beats if b['type'] != 'cta']):
        c = PAL[j % len(PAL)]
        b['color'], b['crgb'] = c, f'{int(c[1:3], 16)},{int(c[3:5], 16)},{int(c[5:7], 16)}'
    for j, b in enumerate([b for b in beats if b['type'] in CARD]):
        if CARDS:
            b['bgc'], b['fgc'] = CARDS[j % len(CARDS)]

# ---------- caption lines (chunks of 1-N words) ----------
# lines also break where a panel or card appears or leaves, so a line never has to move or overlap a graphic
CUTS_AT = sorted({b['t0'] + 0.15 for b in beats if b['type'] in PANEL | CARD} | {b['t1'] for b in beats if b['type'] in PANEL | CARD})
CUTS_AT = sorted(set(CUTS_AT) | {b['t0'] for b in beats if b['type'] == 'cta'})   # the CTA gets fresh lines too
if FACELESS and hl:                                   # the big hook sits mid-screen: captions go below it meanwhile
    CUTS_AT = sorted(set(CUTS_AT) | {hl['until']})
    caps.append([0.0, hl['until'], *CAPS['panel']])
def brk(cur, w):
    prev = cur[-1]
    if any(prev['s'] < x <= w['s'] + 0.05 for x in CUTS_AT):     # a graphic appears/leaves here: start a new line
        return True
    chars = sum(len(x['w']) for x in cur) + len(w['w'])
    nw, nc = STY.get('caption_len') or (4, 24)
    return len(cur) >= nw or chars > nc or w['s'] - prev['e'] > 0.35 or bool(re.search(r'[.!?]$' if nw > 5 else r'[.!?,]$', prev['w']))
OLD_LINES = {L['i'][0]: L for L in STABLE.get('lines') or [] if L.get('i')}
def intact(k):
    """the caption line that started at this word last time, if every word of it is still here unchanged"""
    L = OLD_LINES.get(WO[k]['i'])
    if not L:
        return 0
    seg = WO[k:k + len(L['i'])]
    if [w['i'] for w in seg] != L['i'] or [w['w'] for w in seg] != L['w']:
        return 0
    if any(seg[j]['s'] - seg[j - 1]['e'] > 0.35 for j in range(1, len(seg))):
        return 0
    if any(seg[0]['s'] < x <= seg[-1]['s'] + 0.05 for x in CUTS_AT):
        return 0
    return len(seg)
lines, k = [], 0
while k < len(WO):
    n = intact(k)
    if n:
        lines.append(WO[k:k + n]); k += n; continue
    cur = [WO[k]]; k += 1
    while k < len(WO) and not brk(cur, WO[k]) and not intact(k):
        cur.append(WO[k]); k += 1
    lines.append(cur)

# ---------- captions, final ----------
# 1. never say it twice: a caption line whose words are already on screen (a card, a statement, the hook, the CTA)
#    is left out. 2. a line keeps ONE place for its whole life: if a graphic appears while it is on screen, the
#    line starts where it will end, so it never jumps. 3. faceless: a line stays until the next one (no empty frames).
STOP = set('a an the and or but of to in on at for with is are was were be been it its this that these those i you we they '
           'he she my your our their as by from so if then than just very can will do does did not no yes me us them'.split())
def stem(x):
    x = re.sub(r"[^\w]", '', x.lower())
    for suf in ('ing', 'ed', 'es', 's'):
        if len(x) > 4 and x.endswith(suf):
            return x[:-len(suf)]
    return x
def toks(text):
    return {stem(x) for x in re.findall(r"[\w'’]+", str(text or '')) if stem(x) and x.lower() not in STOP}
NOT_SHOWN = {'type', 'mode', 'curve', 'kind', 'who', 'pose', 'prop', 'icon', 'left_pose', 'right_pose', 'left_mark',
             'right_mark', 'color', 'crgb', 'bgc', 'fgc', 't0', 't1', 'k', 'num', 'total', 'word', 'decimals', 'highlight',
             'strike', 'image', 'other'}
def shown(b):
    """every word a graphic puts on screen (any text field, nested items included)"""
    parts = []
    def walk(v):
        if isinstance(v, dict):
            for k2, x in v.items():
                if k2 not in NOT_SHOWN:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v not in (None, '') and not isinstance(v, bool):
            parts.append(str(v))
    walk(b)
    return toks(' '.join(parts))
WINDOWS = [(b['t0'], b['t1'], shown(b) | ({'comment'} if b['type'] == 'cta' else set())) for b in beats]
if hl:
    WINDOWS.append((0.0, hl['until'], toks(f"{hl.get('l1', '')} {hl.get('l2', '')}")))
def on_screen(a, z):
    out = set()
    for w0, w1, tk in WINDOWS:                         # on screen for at least half the line (else the line still says it)
        if min(z, w1) - max(a, w0) >= 0.5 * max(0.1, z - a):
            out |= tk
    return out
vis, dropped = [], 0
for ln in lines:
    a, z = ln[0]['s'], ln[-1]['e']
    content = set().union(*[toks(w['w']) for w in ln]) if ln else set()
    scr = on_screen(a, z)
    if (content and len(content & scr) >= 0.6 * len(content)) or (not content and scr):   # repeats the screen / bare filler next to it
        dropped += 1
        continue
    vis.append(ln)
def place(a, z):
    best, cover = None, 0.0
    for c0, c1, m, y in caps:
        ov = min(z, c1) - max(a, c0)
        if ov > cover:
            best, cover = (m, y), ov
    if best:
        return best
    return tuple(CAPS['face']) if CAPS.get('face') else None
with open('subs.txt', 'w', encoding='utf-8') as f:
    for ln in vis:
        f.write(' ; '.join(f"{w['s']:.6f} {(STY.get('captions') or {}).get('accent_flags', '*') if w['i'] in accent else ''}{w['w']}" for w in ln) + '\n')
subprocess.run([PY, os.path.join(HERE, 'subs.py'), 'subs.txt'], check=True, capture_output=True)
SUBS = json.load(open('subs.json', encoding='utf-8'))
for j, ch in enumerate(SUBS):
    spoken = (vis[j][0]['s'], vis[j][-1]['e'])                    # the words themselves, not the fade-out tail
    nxt = [x for x in CUTS_AT if x > spoken[1] - 0.02]
    if nxt and ch['e'] > nxt[0]:                                   # gone when the next card arrives / leaves
        ch['e'] = round(max(spoken[1], nxt[0] - 0.02), 6)
    nxt_cut = nxt[0] if nxt else 1e9
    gap_card = j + 1 < len(SUBS) and SUBS[j + 1]['s'] > nxt_cut or j + 1 < len(SUBS) and any(b['t0'] < SUBS[j + 1]['s'] and b['t1'] > ch['e'] for b in beats if b['type'] in CARD)
    if STY.get('hold_captions') and j + 1 < len(SUBS) and SUBS[j + 1]['s'] - ch['e'] < 2.5 and not gap_card:
        ch['e'] = SUBS[j + 1]['s']
    if ch['e'] - ch['s'] < 0.4:                                  # words Whisper squeezed together: still readable
        ch['e'] = round(min(ch['s'] + 0.5, SUBS[j + 1]['s']) if j + 1 < len(SUBS) else ch['s'] + 0.5, 6)
    pl = place(spoken[0], min(ch['e'], spoken[1] + 0.3))
    if pl:
        ch['m'], ch['y'] = pl[0], pl[1]
json.dump(SUBS, open('subs.json', 'w', encoding='utf-8'), ensure_ascii=False)

# ---------- 7. overlay.html ----------
P = {'accent': plan.get('accent_color') or STY.get('accent') or '#C6F432', 'headline': hl or None, 'back': back, 'beats': beats, 'caps': caps}
if STY:
    theme = dict(STY.get('theme') or {})
    if plan.get('accent_color') and plan['accent_color'].startswith('#') and len(plan['accent_color']) == 7:
        c = plan['accent_color']; theme['accrgb'] = f'{int(c[1:3], 16)},{int(c[3:5], 16)},{int(c[5:7], 16)}'
    P.update({'theme': theme, 'capDefault': {'m': CAPS['face'][0], 'y': CAPS['face'][1]} if CAPS.get('face') else None,
              'faceless': FACELESS, 'layout': STY.get('layout'), 'palette': PAL or None})
    if FACELESS:
        P['beats'] = [b for b in beats if b['type'] not in OVER]
        if STY.get('cta_scene'):
            P['ctaScene'] = STY['cta_scene']
        if STY.get('host'):                           # the cartoon host talks while the voice speaks
            P['host'] = {'talk': [[w['s'], w['e']] for w in WO]}
tpl = open(os.path.join(HERE, '..', 'templates', 'lean_overlay.html'), encoding='utf-8').read()
if FACELESS:                                          # the scene library goes in with the faceless styles
    scn = open(os.path.join(HERE, '..', 'templates', 'scenes.js'), encoding='utf-8').read()
    tpl = tpl.replace('/*SCENES*/', scn.replace('</script', '<\\/script'), 1)
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
    ty, k0 = b['type'], b['k'][0]
    if ty in ('phone', 'tags', 'icons', 'speech', 'polaroids', 'timeline', 'figures') or ty == 'window' and b.get('kind') in ('checklist', 'chat', None) and b.get('items'):
        ev += [[k, 'pop', -32, {}] for k in b['k']]
    if ty == 'phone' and b.get('value') is not None or ty == 'graph':
        ev.append([k0, 'ticks', -33, {'dur': 0.9}])
    if ty == 'code':
        for j, (x, k) in enumerate(zip(b.get('items') or [], b['k'])):
            n = len(str(x.get('text') or ''))
            ev += [[round(k + c / 30, 3), 'key', -40, {'seed': 7 * j + c}] for c in range(0, min(n, 48), 4)]
    if ty == 'window' and (b.get('kind') or ('checklist' if b.get('items') else 'prompt')) == 'prompt':
        n = len(b.get('text') or '')
        ev += [[round(k0 + c / 24, 3), 'key', -38, {'seed': c}] for c in range(0, min(n, 72), 2)]
        ev.append([round(k0 + n / 24 + 0.2, 3), 'tap', -28, {}])
    if ty == 'window' and b.get('kind') == 'folder':
        ev.append([b['t0'] + 1.15, 'tap', -28, {}])
    if ty in SCARD:
        ev.append([b['t0'] + 0.05, 'hit', -26, {}])
    if ty == 'bigtype' or ty == 'notepad' and b.get('circle') or ty == 'magnify':
        ev.append([k0, 'swipe', -30, {}])
    if ty == 'notepad' and b.get('big'):
        ev.append([k0 + 0.5, 'hit', -27, {}])
    if b['type'] == 'cta':
        ev += [[max(0, b['t0'] - 0.85), 'riser', -30, {'dur': 0.85}], [b['t0'], 'hit', -25, {}]]
        if STY.get('cta_scene') == 'commentcta':      # the comment box types the word a little later, a bit faster
            ev += [[round(k0 + 0.5 + j / 10, 3), 'key', -36, {'seed': 50 + j}] for j in range(len(b['keyword']))]
        else:
            ev += [[round(k0 + j / 8, 3), 'key', -36, {'seed': 50 + j}] for j in range(len(b['keyword']))]
ev = sorted([e for e in ev if 0 <= e[0] < DUR], key=lambda e: e[0])
if plan.get('sfx') is False:
    ev = []
json.dump(ev, open('sfx_events.json', 'w'))

json.dump(CUTREP, open('cut_report.json', 'w'))
json.dump({'zoom': stable_zoom, 'punch': stable_punch, 'lines': [{'i': [w['i'] for w in ln], 'w': [w['w'] for w in ln]} for ln in lines]},
          open('stable.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(f'cut {SRC["dur"]:.1f}s -> {DUR:.1f}s in {len(E["segs"])} pieces | {len(CUTREP["fillers"])} filler words + '
      f'{CUTREP["sounds"]} umm sounds removed | {CUTREP["pauses"]} pauses tightened | {len(lines)} captions | '
      f'{len(beats)} graphics | {dropped} caption lines already on screen | {len(punch)} punch-ins | face fx={fx:.2f} fy={fy:.2f} | back text: {"yes" if back else "no"}')
