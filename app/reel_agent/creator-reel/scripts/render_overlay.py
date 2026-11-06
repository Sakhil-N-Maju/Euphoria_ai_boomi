"""Render the graphics layer (overlay.html) to transparent PNGs.
usage: python3 render_overlay.py <outdir> all [k/m]        (run m shards at once: 0/2 and 1/2)
       python3 render_overlay.py <outdir> f1,f2,...        (only these frames, written as <outdir>/<frame>.png)
overlay_cfg.json: {"back":[[t0,t1],...]}  time ranges that also get a 'back' layer (text behind the person)

Render cache: overlay.html gives every frame a signature (what is on screen, with times relative to the frame), so
identical frames, and frames that only moved in time after an edit, are drawn once and reused from ovcache/<hash>.png.
Shard 0 writes ov_map.json (frame -> cached picture) for composite.py."""
import json, sys, os, time, hashlib, re, shutil
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); from envlib import chrome_launch
from playwright.sync_api import sync_playwright
os.chdir((os.environ.get('REEL_HOME') or os.getcwd())); FPS=30; CACHE='ovcache'
cfg=json.load(open('overlay_cfg.json')) if os.path.exists('overlay_cfg.json') else {}
cfg['subs']=json.load(open('subs.json')); cfg['pip']=json.load(open('pip.json')) if os.path.exists('pip.json') else {"states":{"full":[0,0,1080,1920,0,1,0,0]},"keys":[[0,"full"]]}
N=int(round(json.load(open('edit.json'))['dur']*FPS)); out=sys.argv[1]; BACK=cfg.get('back',[])
ALL=sys.argv[2]=='all'
fr=list(range(N)) if ALL else [int(x) for x in sys.argv[2].split(',')]
k,m=(map(int,sys.argv[3].split('/')) if len(sys.argv)>3 else (0,1))

def global_key():
    """everything that changes every frame's look at once: the template (minus the timed parts of the plan), fonts, bg"""
    html=open('overlay.html',encoding='utf-8').read()
    mt=re.search(r'/\*PLAN\*/(.*?)/\*END\*/',html,re.S); plan=json.loads(mt.group(1)) if mt else {}
    glob={kk:v for kk,v in plan.items() if kk not in ('beats','caps','headline','back')}
    tpl=html[:mt.start()]+html[mt.end():] if mt else html
    h=hashlib.sha1(('o2'+tpl+json.dumps(glob,sort_keys=True,ensure_ascii=False)).encode())
    for p in ('bg.png',):
        if os.path.exists(p): h.update(open(p,'rb').read())
    if os.path.isdir('fonts'):
        for root,_,files in os.walk('fonts'):
            for f in sorted(files): h.update(f'{f}:{os.path.getsize(os.path.join(root,f))}'.encode())
    return h.hexdigest()

os.makedirs(CACHE,exist_ok=True)
with sync_playwright() as p:
    S={'b':None,'pg':None}
    def open_page(new_browser=False):
        """(re)open the graphics page; a fresh page/browser recovers from Chromium's occasional failed capture"""
        if new_browser or S['b'] is None:
            if S['b'] is not None:
                try: S['b'].close()
                except Exception: pass
            S['b']=chrome_launch(p)
        elif S['pg'] is not None:
            try: S['pg'].close()
            except Exception: pass
        S['pg']=S['b'].new_page(viewport={'width':1080,'height':1920})
        S['pg'].goto(__import__('pathlib').Path('overlay.html').resolve().as_uri()); S['pg'].evaluate('c=>init(c)',cfg)
        return S['pg']
    FAIL=[int(os.environ.get('REEL_TEST_SHOT_FAILS') or 0)]     # tests only: make the first N captures fail
    def shot(f,md,path):
        """draw frame f and save it; retries, then a fresh page, then a fresh browser before giving up"""
        for attempt in range(6):
            try:
                if FAIL[0]>0:
                    FAIL[0]-=1; raise RuntimeError('simulated capture failure')
                S['pg'].evaluate(f'renderFrame({f/FPS},{f},"{md}")')
                S['pg'].screenshot(path=path,omit_background=True,clip={'x':0,'y':0,'width':1080,'height':1920})
                return
            except Exception as e:
                err=e
                print(f'capture of frame {f} failed ({str(e).splitlines()[0][:90]}); retry {attempt+1}',flush=True)
                time.sleep(0.4*(attempt+1))
                if attempt in (1,3): open_page()
                elif attempt==4: open_page(new_browser=True)
        raise RuntimeError(f'Could not draw graphics frame {f} after 6 tries: {err}')
    pg=open_page(); t0=time.time()
    G=global_key()
    sigs=pg.evaluate('([n,fps,back])=>window.frameSigs?window.frameSigs(n,fps,back):null',[N,FPS,BACK])
    if sigs is None:                                  # an old overlay.html without signatures: one unique id per frame
        sigs=[[f'{G}:{f}',f'{G}:{f}:b' if any(a<=f/FPS<bb for a,bb in BACK) else None] for f in range(N)]
    H=lambda s: hashlib.sha1((G+'|'+s).encode()).hexdigest()[:24]
    if os.environ.get('REEL_DEBUG') and k==0: json.dump(sigs,open('ov_sigs.json','w'))
    front=[H(s[0]) for s in sigs]; back={str(f):H(s[1]) for f,s in enumerate(sigs) if s[1]}
    if ALL:
        jobs={}
        for f in fr:
            jobs.setdefault(front[f],(f,'front'))
            if str(f) in back: jobs.setdefault(back[str(f)],(f,'back'))
        todo=[(h,f,md) for h,(f,md) in jobs.items() if not os.path.exists(f'{CACHE}/{h}.png')]
        # split by the hash itself, not by position in the list: the other shard may see a shorter list (frames this
        # shard already drew), and a position split would then leave some frames to nobody
        mine=[j for j in todo if int(j[0][:8],16)%m==k]
        if k==0: print(f'graphics: {N} frames, {len(jobs)} distinct, {len(todo)} to draw ({len(jobs)-len(todo)} reused)',flush=True)
        for i,(h,f,md) in enumerate(mine):
            tmp=f'{CACHE}/{h}.tmp{k}.png'
            shot(f,md,tmp); os.replace(tmp,f'{CACHE}/{h}.png')
            if i%100==0: print(i,len(mine),round(time.time()-t0),'s',flush=True)
        miss=[h for h,(f,md) in jobs.items() if int(h[:8],16)%m==k and not os.path.exists(f'{CACHE}/{h}.png')]
        if miss: sys.exit(f'{len(miss)} graphics frames were not drawn')
        if k==0:
            prev=json.load(open('ov_map.json')) if os.path.exists('ov_map.json') else {}
            keep=set(front)|set(back.values())|set(prev.get('front') or [])|set((prev.get('back') or {}).values())
            tmp='ov_map.json.tmp'; json.dump({'dir':CACHE,'front':front,'back':back},open(tmp,'w')); os.replace(tmp,'ov_map.json')
            for fn in os.listdir(CACHE):             # keep this version's and the previous version's frames only
                if fn.endswith('.png') and '.tmp' not in fn and fn[:-4] not in keep:
                    try: os.remove(os.path.join(CACHE,fn))
                    except OSError: pass
    else:                                             # a few frames for a test sheet
        os.makedirs(out,exist_ok=True); os.makedirs(out+'_back',exist_ok=True)
        for f in fr:
            shot(f,'front',f'{out}/{f:05d}.png')
            if str(f) in back:
                shot(f,'back',f'{out}_back/{f:05d}.png')
    S['b'].close()
