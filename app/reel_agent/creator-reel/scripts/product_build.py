"""Product style: turn the planner's scene list for a screen recording into every file the renderer needs (no AI).
usage: python product_build.py edit_plan.json   (job folder: src.mp4, src.json, activity.json, env.json; words.json optional)

edit_plan.json (times in SOURCE seconds, see styles/product/planner.md):
  title {text, sub}  scenes [{from, to, speed, zoom: auto|wide|focus, focus [x,y], text, sub}]  outro {name, tagline, button}
  accent_color, look (dark|light)
Writes edit.json (segments with speed; a held last frame for the outro), plan.json (no grade, windowed view, camera),
camera.json (zoom + focus per output frame), pip.json (the floating window), subs.txt/subs.json (voice captions, if any),
overlay.html (titles, outro card), overlay_cfg.json, sfx_events.json, voice_cut.wav, words_out.json, cut_report.json."""
import json, os, re, subprocess, sys
import numpy as np, soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from envlib import FF, ff  # noqa: E402
os.chdir(os.environ.get('REEL_HOME') or os.getcwd())
PY = sys.executable
FPS, OW, OH = 30, 1080, 1920
SN = lambda x: round(round(x * 120) / 120, 6)          # 1/120 s grid (see build_plan.py: keeps the render cache valid)

plan = json.load(open(sys.argv[1], encoding='utf-8'))
SRC = json.load(open('src.json'))
ACT = json.load(open('activity.json')) if os.path.exists('activity.json') else {'rows': [], 'step': 0.5}
W = json.load(open('words.json', encoding='utf-8')) if os.path.exists('words.json') else []
sty = json.load(open(os.path.join(HERE, '..', '..', 'styles', 'product', 'style.json'), encoding='utf-8'))
look = sty['looks'].get(plan.get('look') or 'dark') or sty['looks']['dark']
WIN = sty['window']; ZMAX = float(sty.get('zoom_max', 2.2)); DUR_SRC = float(SRC['dur'])
SPEEDS = [1, 1.5, 2, 3, 4]

# ---------- 1. scenes -> segments (frame exact) ----------
sc = []
for _i, s in enumerate(plan.get('scenes') or []):
    if not isinstance(s, dict):
        continue
    try:
        a, b = float(s.get('from', 0)), float(s.get('to', 0))
    except (TypeError, ValueError):
        continue
    a, b = max(0.0, min(a, DUR_SRC)), max(0.0, min(b, DUR_SRC))
    if b - a < 0.3:
        continue
    sp = min(SPEEDS, key=lambda v: abs(v - float(s.get('speed') or 1)))
    sc.append(dict(s, **{'from': a, 'to': b, 'speed': sp, '_i': _i}))
sc.sort(key=lambda s: s['from'])
clean = []
for s in sc:                                           # no overlaps: trim the later scene
    if clean and s['from'] < clean[-1]['to']:
        s['from'] = clean[-1]['to']
    if (s['to'] - s['from']) / s['speed'] >= 0.6:
        clean.append(s)
if not clean:                                          # nothing usable: the whole recording, sped up to <= 40 s
    sp = min([v for v in SPEEDS if DUR_SRC / v <= 40] or [4])
    clean = [{'from': 0.0, 'to': DUR_SRC, 'speed': sp, 'zoom': 'auto', 'text': ''}]
# AI narration (ElevenLabs, recorded by the app before this script): a scene must last as long as its line
NARR = json.load(open('narration.json', encoding='utf-8')) if os.path.exists('narration.json') else {}
LEAD = 0.15                                            # the line starts this long after its scene
for s in clean:
    nd = NARR.get(str(s.get('_i', -1)))
    if nd:
        need = nd['dur'] + LEAD + 0.25
        if (s['to'] - s['from']) / s['speed'] < need:
            s['speed'] = round(max(0.5, (s['to'] - s['from']) / need), 4)   # slow the scene (down to half speed)
segs, o = [], 0
for s in clean:
    n = max(1, int(round((s['to'] - s['from']) / s['speed'] * FPS)))
    src0 = round(s['from'] * FPS) / FPS
    segs.append({'src0': src0, 'src1': src0 + n / FPS * s['speed'], 'out0': o / FPS, 'out1': (o + n) / FPS, 'speed': s['speed']})
    s['_n0'], s['_n1'] = o, o + n
    o += n
last_src = min(segs[-1]['src1'], DUR_SRC) - 1.0 / FPS
OUTRO_N = int(round(float(sty.get('outro_s', 2.6)) * FPS)) if plan.get('outro') is not False else 0
if OUTRO_N:
    segs.append({'src0': last_src, 'src1': last_src, 'out0': o / FPS, 'out1': (o + OUTRO_N) / FPS, 'speed': 0})
    o += OUTRO_N
N = o; DUR = N / FPS
# where each of the plan's scenes landed in the finished reel (for change requests and time-range corrections)
json.dump({'scenes': {str(s.get('_i', -1)): [round(s['_n0'] / FPS, 3), round(s['_n1'] / FPS, 3)] for s in clean},
           'outro': [round(segs[-1]['out0'], 3), round(DUR, 3)] if OUTRO_N else None, 'dur': round(DUR, 3)},
          open('scenes_out.json', 'w'))
json.dump({'segs': segs, 'dur': DUR}, open('edit.json', 'w'), indent=1)
json.dump([[s['src0'], s['src1']] for s in segs], open('keep.json', 'w'))

# ---------- 2. window (view) and layouts ----------
a = SRC['w'] / SRC['h']
w = float(WIN['max_w']); h = w / a
if h > WIN['max_h']:
    h = float(WIN['max_h']); w = h * a
VW, VH = int(round(w / 2)) * 2, int(round(h / 2)) * 2
x = (OW - VW) // 2; y = int(round(WIN['center_y'] - VH / 2))
R = WIN['radius']; k0 = 0.92
w0, h0 = VW * k0, VH * k0; x0, y0 = x + (VW - w0) / 2, y + (VH - h0) / 2 + 60
states = {'win': [x, y, VW, VH, R, 1.0, x, y], 'win0': [round(x0, 2), round(y0, 2), round(w0, 2), round(h0, 2), R * k0, k0, round(x0, 2), round(y0, 2)]}
json.dump({'states': states, 'keys': [[0, 'win0'], [0.7, 'win', 'eo5']]}, open('pip.json', 'w'))

# ---------- 3. camera: zoom to where the screen changes ----------
rows = [r for r in ACT.get('rows') or [] if r[2] is not None]
def target(s):
    mode = s.get('zoom') or 'auto'
    if mode == 'wide':
        return 1.0, 0.5, 0.5
    if mode == 'focus' and isinstance(s.get('focus'), list) and len(s['focus']) == 2:
        fx, fy = (min(0.95, max(0.05, float(v))) for v in s['focus'])
        return min(1.8, ZMAX), fx, fy
    act = [r for r in rows if s['from'] - 0.25 <= r[0] <= s['to'] and r[1] >= 0.002]
    if not act:
        return 1.08, 0.5, 0.5
    wts = np.array([r[1] for r in act]); B = np.array([r[2:6] for r in act])
    x0_, y0_ = np.percentile(B[:, 0], 20), np.percentile(B[:, 1], 20)
    x1_, y1_ = np.percentile(B[:, 2], 80), np.percentile(B[:, 3], 80)
    cx = float(np.average((B[:, 0] + B[:, 2]) / 2, weights=wts)); cy = float(np.average((B[:, 1] + B[:, 3]) / 2, weights=wts))
    size = max(x1_ - x0_, y1_ - y0_, 0.05)
    z = float(min(ZMAX, max(1.0, 0.72 / size)))
    return round(z, 4), round(min(0.95, max(0.05, cx)), 4), round(min(0.95, max(0.05, cy)), 4)
eio = lambda u: 4 * u ** 3 if u < .5 else 1 - (-2 * u + 2) ** 3 / 2
cam = [None] * N; prev = (1.0, 0.5, 0.5)
for s in clean:
    tz, tx, ty = target(s); n0, n1 = s['_n0'], s['_n1']; L = max(1, n1 - n0); tr = min(int(0.55 * FPS), max(1, L // 2))
    for n in range(n0, n1):
        u = (n - n0) / L
        drift = 1 + 0.035 * u                          # slow push-in keeps the shot alive
        if n - n0 < tr:
            e = eio((n - n0) / tr)
            z = prev[0] + (tz * drift - prev[0]) * e; fx = prev[1] + (tx - prev[1]) * e; fy = prev[2] + (ty - prev[2]) * e
        else:
            z, fx, fy = tz * drift, tx, ty
        cam[n] = [round(min(ZMAX * 1.04, max(1.0, z)), 5), round(fx, 5), round(fy, 5)]
    prev = tuple(cam[n1 - 1])
for n in range(N):
    if cam[n] is None:
        cam[n] = list(prev)
json.dump(cam, open('camera.json', 'w'))
json.dump({'anchors': [{'until': 1e9, 'fx': 0.5, 'fy': 0.5}], 'zoom': [[1.0, 1.0] for _ in segs], 'punch': [],
           'grade': 0, 'vignette': False, 'pop': 1, 'view': [VW, VH], 'camera': 'camera.json',
           'shadow': WIN.get('shadow', 0.5)}, open('plan.json', 'w'))
json.dump({'back': []}, open('overlay_cfg.json', 'w'))

# ---------- 4. voice: kept at normal speed, silent where sped up or held ----------
SR = 48000
ff('-i', 'src.mp4', '-vn', '-ac', '2', '-ar', str(SR), 'audio48.wav', check=False)
au = sf.read('audio48.wav')[0] if os.path.exists('audio48.wav') else np.zeros((1, 2))
if au.ndim == 1:
    au = np.stack([au, au], 1)
out = np.zeros((int(round(DUR * SR)) + 1, 2)); xf = int(0.012 * SR); fade = np.linspace(0, 1, xf)[:, None]
for s in segs:
    if s['speed'] != 1 or NARR:                       # narration replaces the recording's own sound
        continue
    piece = au[int(round(s['src0'] * SR)):int(round(s['src1'] * SR))].copy()
    if len(piece) > 2 * xf:
        piece[:xf] *= fade; piece[-xf:] *= fade[::-1]
    i0 = int(round(s['out0'] * SR)); out[i0:i0 + len(piece)] = piece[:len(out) - i0]
NWO = []                                               # narration words on the output timeline (for captions)
for s in clean:
    nd = NARR.get(str(s.get('_i', -1)))
    if not nd or not os.path.exists(nd['wav']):
        continue
    v, vsr = sf.read(nd['wav'])
    if vsr != SR:
        raise SystemExit(f"{nd['wav']}: expected {SR} Hz audio")
    v = np.stack([v, v], 1) if v.ndim == 1 else v
    t0 = s['_n0'] / FPS + LEAD; i0 = int(round(t0 * SR))
    if i0 < len(out):
        out[i0:i0 + len(v)] += v[:len(out) - i0]
    NWO += [{'w': w['w'], 's': SN(t0 + w['s']), 'e': SN(t0 + w['e'])} for w in nd.get('words') or [] if t0 + w['s'] < DUR]
sf.write('voice_cut.wav', out[:int(round(DUR * SR))], SR)

# ---------- 5. captions for the voice (only scenes at normal speed) ----------
def out_t(t):
    for s in segs:
        if s['speed'] == 1 and s['src0'] - 1e-3 <= t <= s['src1'] + 1e-3:
            return SN(s['out0'] + (t - s['src0']))
    return None
WO = []
for i, wd in enumerate([] if NARR else W):
    t = out_t(wd['s'])
    if t is not None and (not OUTRO_N or t < segs[-1]['out0'] - 0.2):
        e = out_t(wd.get('e', wd['s'] + 0.3)) or t + 0.3
        WO.append({'i': i, 'w': str((plan.get('fix') or {}).get(str(i), wd['w'])), 's': t, 'e': max(e, t + 0.05)})
if NARR:
    WO = [{'i': 100000 + k, **w, 'e': max(w['e'], w['s'] + 0.05)} for k, w in enumerate(NWO)
          if not OUTRO_N or w['s'] < segs[-1]['out0'] - 0.2]
json.dump(WO, open('words_out.json', 'w', encoding='utf-8'), ensure_ascii=False)
lines, cur = [], []
for wd in WO:
    if cur and (len(cur) >= 4 or sum(len(x['w']) for x in cur) + len(wd['w']) > 24 or wd['s'] - cur[-1]['e'] > 0.35
                or re.search(r'[.!?,]$', cur[-1]['w'])):
        lines.append(cur); cur = []
    cur.append(wd)
if cur:
    lines.append(cur)
# never say it twice: drop caption lines whose words are already in the title on screen at that moment
STOP = set('a an the and or but of to in on at for with is are was were be it this that i you we they my your our as by from so'.split())
def _toks(t):
    out = set()
    for x in re.findall(r"[\w']+", str(t or '').lower()):
        if x not in STOP:
            out.add(x[:-1] if len(x) > 4 and x.endswith('s') else x)
    return out
TW = []
_t = plan.get('title') or {}
if _t.get('text'):
    TW.append((0.0, max(1.6, min(clean[0]['_n1'] / FPS, 3.4)), _toks(f"{_t['text']} {_t.get('sub', '')}")))
for _j, _s in enumerate(clean):
    if _s.get('text'):
        TW.append((_s['_n0'] / FPS, _s['_n1'] / FPS, _toks(f"{_s['text']} {_s.get('sub', '')}")))
def _dup(ln):
    c = set().union(*[_toks(x['w']) for x in ln]); a, z = ln[0]['s'], ln[-1]['e']
    scr = set().union(*[tk for w0, w1, tk in TW if w0 < z and w1 > a]) if TW else set()
    return bool(c) and len(c & scr) >= 0.6 * len(c)
lines = [ln for ln in lines if not _dup(ln)]
with open('subs.txt', 'w', encoding='utf-8') as f:
    for ln in lines:
        f.write(' ; '.join(f"{x['s']:.6f} {x['w']}" for x in ln) + '\n')
subprocess.run([PY, os.path.join(HERE, 'subs.py'), 'subs.txt'], check=True, capture_output=True)
if not lines:
    json.dump([], open('subs.json', 'w'))

# ---------- 6. graphics: hook, scene titles, outro card ----------
beats = []
TY = int(max(200, y - 300))                            # titles sit just above the window
title = plan.get('title') or {}
first = clean[0]
t_end0 = first['_n1'] / FPS
if title.get('text'):
    beats.append({'type': 'title', 'text': title['text'][:60], 'sub': (title.get('sub') or '')[:80], 'pos': 'top', 'y': TY,
                  't0': 0.0, 't1': SN(max(1.6, min(t_end0 - 0.05, 3.4))), 'k': [SN(0.2)]})
for j, s in enumerate(clean):
    if not s.get('text') or (j == 0 and title.get('text')):
        continue
    t0, t1 = SN(s['_n0'] / FPS + 0.05), SN(s['_n1'] / FPS - 0.05)
    if t1 - t0 >= 0.8:
        beats.append({'type': 'title', 'text': str(s['text'])[:60], 'sub': str(s.get('sub') or '')[:80], 'pos': 'top', 'y': TY,
                      't0': t0, 't1': t1, 'k': [SN(t0 + 0.1)]})
od = plan.get('outro') or {}
if OUTRO_N:
    o0 = SN(segs[-1]['out0'])
    beats.append({'type': 'outro', 'text': (od.get('name') or '')[:40], 'sub': (od.get('tagline') or '')[:80],
                  'label': (od.get('button') or '')[:30], 't0': o0, 't1': SN(DUR + 1), 'k': [SN(o0 + 0.05)]})
wb = y + VH
cap_y = int(min(1700, max(wb + 120, 1560)))
caps = [[SN(segs[-1]['out0']), SN(DUR + 1), 'none', 0]] if OUTRO_N else []
acc = plan.get('accent_color') if re.match(r'^#[0-9a-fA-F]{6}$', str(plan.get('accent_color') or '')) else look['accent']
theme = dict(look['theme']); theme['accrgb'] = f'{int(acc[1:3], 16)},{int(acc[3:5], 16)},{int(acc[5:7], 16)}'
P = {'accent': acc, 'theme': theme, 'headline': None, 'back': None, 'beats': beats, 'caps': caps,
     'capDefault': {'m': 'pill', 'y': cap_y}}
tpl = open(os.path.join(HERE, '..', 'templates', 'lean_overlay.html'), encoding='utf-8').read()
tpl = re.sub(r'/\*PLAN\*/.*?/\*END\*/', lambda m: '/*PLAN*/' + json.dumps(P, ensure_ascii=False) + '/*END*/', tpl, count=1, flags=re.S)
open('overlay.html', 'w', encoding='utf-8').write(tpl)

# ---------- 7. sound ----------
ev = [[0.05, 'hit', -26, {}]]
for j, s in enumerate(clean[1:], 1):
    ev.append([max(0, s['_n0'] / FPS - 0.12), 'air', -31, {'seed': j}])
for b in beats:
    if b['type'] == 'title':
        ev.append([b['k'][0], 'pop', -34, {}])
if OUTRO_N:
    o0 = segs[-1]['out0']
    ev += [[max(0, o0 - 0.85), 'riser', -31, {'dur': 0.85}], [o0 + 0.05, 'hit', -24, {}]]
json.dump(sorted([e for e in ev if 0 <= e[0] < DUR], key=lambda e: e[0]) if plan.get('sfx') is not False else [],
          open('sfx_events.json', 'w'))
json.dump({'fillers': [], 'sounds': 0, 'pauses': 0, 'pause_s': 0}, open('cut_report.json', 'w'))
sp = sum(1 for s in clean if s['speed'] > 1)
print(f'product: {DUR_SRC:.1f}s recording -> {DUR:.1f}s reel | {len(clean)} scenes ({sp} sped up) | window {VW}x{VH} | '
      f'{len(beats)} titles | {len(lines)} captions' + (f' | narration {len(NARR)} lines' if NARR else ''))
