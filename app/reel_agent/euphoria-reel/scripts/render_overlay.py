"""Render the graphics layer (overlay.html) to transparent PNGs, one per frame.
usage: python3 render_overlay.py <outdir> all|f1,f2,... [k/m]   (run 2 shards in parallel: 0/2 and 1/2)
overlay_cfg.json: {"back":[[t0,t1],...]}  time ranges that also get a 'back' layer (text behind the person)"""
import json, sys, os, time
sys.path.insert(0,os.path.dirname(__file__)); from envlib import chrome_launch
from playwright.sync_api import sync_playwright
os.chdir((os.environ.get('REEL_HOME') or os.getcwd())); FPS=30
cfg=json.load(open('overlay_cfg.json')) if os.path.exists('overlay_cfg.json') else {}
cfg['subs']=json.load(open('subs.json')); cfg['pip']=json.load(open('pip.json')) if os.path.exists('pip.json') else {"states":{"full":[0,0,1080,1920,0,1,0,0]},"keys":[[0,"full"]]}
N=int(round(json.load(open('edit.json'))['dur']*FPS)); out=sys.argv[1]; BACK=cfg.get('back',[])
fr=list(range(N)) if sys.argv[2]=='all' else [int(x) for x in sys.argv[2].split(',')]
if len(sys.argv)>3: k,m=map(int,sys.argv[3].split('/')); fr=[f for f in fr if f%m==k]
os.makedirs(out,exist_ok=True); os.makedirs(out+'_back',exist_ok=True)
with sync_playwright() as p:
    b=chrome_launch(p); pg=b.new_page(viewport={'width':1080,'height':1920})
    pg.goto(__import__('pathlib').Path('overlay.html').resolve().as_uri()); pg.evaluate('c=>init(c)',cfg); t0=time.time()
    for i,f in enumerate(fr):
        t=f/FPS
        pg.evaluate(f'renderFrame({t},{f},"front")'); pg.screenshot(path=f'{out}/{f:05d}.png',omit_background=True,clip={'x':0,'y':0,'width':1080,'height':1920})
        if any(a<=t<bb for a,bb in BACK):
            pg.evaluate(f'renderFrame({t},{f},"back")'); pg.screenshot(path=f'{out}_back/{f:05d}.png',omit_background=True,clip={'x':0,'y':0,'width':1080,'height':1920})
        if i%100==0: print(i,len(fr),round(time.time()-t0),'s',flush=True)
    b.close()
