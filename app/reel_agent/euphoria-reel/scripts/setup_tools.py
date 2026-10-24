"""One-time setup for the reel editor on this PC (safe to re-run; skips what is already there).
usage: python setup_tools.py <tools_dir>
  - installs the Python packages the render scripts need (playwright, opencv, scipy, soundfile)
  - installs Playwright's headless Chromium (draws the graphics layer)
  - downloads the fonts used by overlay.html (Inter Tight, Instrument Serif, JetBrains Mono, Anek Malayalam, Noto)
  - downloads the person cut-out model (text behind the head)
Writes <tools_dir>/tools.json with what it found."""
import json, os, re, subprocess, sys, urllib.request
from pathlib import Path

T = Path(sys.argv[1]).resolve(); T.mkdir(parents=True, exist_ok=True)
HERE = Path(__file__).resolve().parent
PY = sys.executable
def log(*a): print('[setup]', *a, flush=True)

def have(mod):
    return subprocess.run([PY, '-c', f'import {mod}'], capture_output=True).returncode == 0

need = [p for m, p in [('playwright', 'playwright'), ('cv2', 'opencv-python-headless'), ('scipy', 'scipy'),
                       ('soundfile', 'soundfile'), ('onnxruntime', 'onnxruntime'), ('numpy', 'numpy')] if not have(m)]
if need:
    log('pip install', *need)
    subprocess.run([PY, '-m', 'pip', 'install', '-q', '--disable-pip-version-check', *need], check=True)

ok = subprocess.run([PY, '-c', 'from playwright.sync_api import sync_playwright\n'
                     'with sync_playwright() as p: p.chromium.launch().close()'], capture_output=True).returncode == 0
if not ok:
    log('installing headless Chromium (one time, ~150 MB)')
    subprocess.run([PY, '-m', 'playwright', 'install', 'chromium'], check=True)

def get(url, dest):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'euphoria-setup'})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
            f.write(r.read())
        return True
    except Exception as e:  # noqa: BLE001
        log('could not download', url.split('/')[-1], '-', str(e)[:80])
        if dest.exists():
            dest.unlink()
        return False

# fonts: every fonts/<pkg>/files/<file>.woff2 referenced by the template or the example
refs = set()
for html in [HERE.parent / 'templates' / 'overlay.html', HERE.parent / 'examples' / 'claude-edit-reel-overlay.html']:
    refs |= set(re.findall(r'fonts/([a-z0-9-]+)/files/([a-z0-9-]+\.woff2)', html.read_text(encoding='utf-8')))
def from_npm(pkg, files):
    """Fallback when the CDN is blocked: take the files out of the package tarball on the npm registry."""
    import io, tarfile
    try:
        meta = json.load(urllib.request.urlopen(f'https://registry.npmjs.org/@fontsource/{pkg}/latest', timeout=60))
        data = urllib.request.urlopen(meta['dist']['tarball'], timeout=120).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
            for f in files:
                m = tf.extractfile(f'package/files/{f}')
                if m:
                    d = T / 'fonts' / pkg / 'files' / f; d.parent.mkdir(parents=True, exist_ok=True); d.write_bytes(m.read())
    except Exception as e:  # noqa: BLE001
        log('npm fallback failed for', pkg, '-', e)

got = 0
for pkg, f in sorted(refs):
    got += get(f'https://cdn.jsdelivr.net/npm/@fontsource/{pkg}@5/files/{f}', T / 'fonts' / pkg / 'files' / f)
missing = {}
for pkg, f in refs:
    if not (T / 'fonts' / pkg / 'files' / f).exists():
        missing.setdefault(pkg, []).append(f)
for pkg, files in missing.items():
    from_npm(pkg, files)
got = sum((T / 'fonts' / pkg / 'files' / f).exists() for pkg, f in refs)
log(f'fonts: {got}/{len(refs)}')

seg = get('https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx',
          T / 'models' / 'seg' / 'u2net_human_seg.onnx')
log('cut-out model:', 'yes' if seg else 'no (text-behind-head will be skipped)')
json.dump({'fonts': str(T / 'fonts'), 'models': str(T / 'models'), 'seg': bool(seg), 'chrome': 'playwright'},
          open(T / 'tools.json', 'w'), indent=1)
log('done ->', T / 'tools.json')
