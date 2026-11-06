"""Composite: source video (cuts + zoom plan) -> colour grade -> subject pop / text-behind-person -> layouts (pip.json) -> graphics.
usage: python3 composite.py test <ovdir> <f1,f2,...> <sheet.jpg> [fullprefix]   |   python3 composite.py full <ovdir> <out.mp4> [--workers N]
plan.json: {"anchors":[{"until":999,"fx":0.5,"fy":0.42}],"zoom":[[z0,z1] per segment],"punch":[[t_from,z0,z1,t_to],...],"grade":1.0,"pop":0.84}
  optional: "view":[w,h]  the camera picture size when the video sits in a window smaller than the frame (product style)
            "camera":"camera.json"  per output frame [zoom, fx, fy] (overrides zoom/anchors; product auto-zoom)
            "shadow":0.5  soft drop shadow under a windowed video;  "vignette":false
edit.json segments may carry "speed" (source seconds per output second, default 1).

Render cache (why a fix at 0:05 no longer re-renders the whole reel):
  The output is cut into chunks of <= 2 s that never cross a cut. Each chunk gets a key = hash of everything that decides
  its pixels (source frames, zoom, layout, grade, masks, the graphics frames' content hashes from ov_map.json, encoder
  settings). Encoded chunks live in vcache/<key>.mp4; only chunks whose key changed are rendered (in parallel workers),
  then all chunks are joined without re-encoding. Times inside a key are relative, so a chunk that only moved later or
  earlier (a word cut before it) is reused as is."""
import json, sys, os, subprocess, hashlib, time, numpy as np, cv2
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import grade
from envlib import FF, probe
os.chdir((os.environ.get('REEL_HOME') or os.getcwd()))
VERSION='c3'
E=json.load(open('edit.json')); SEG=E['segs']; PL=json.load(open('plan.json')); PIP=json.load(open('pip.json')) if os.path.exists('pip.json') else None
FPS=PL.get('fps',30); SRC=PL.get('src','src.mp4'); OW,OH=PL.get('out',[1080,1920]); N=int(round(E['dur']*FPS))
VW,VH=PL.get('view',[OW,OH])
_p=probe(SRC); SW,SH=_p['w'],_p['h']
S0=max(VW/SW,VH/SH); BG=cv2.imread('bg.png').astype(np.float32) if os.path.exists('bg.png') else np.full((OH,OW,3),12,np.float32)
if BG.shape[:2]!=(OH,OW): BG=cv2.resize(BG,(OW,OH),interpolation=cv2.INTER_AREA)
GRADE=PL.get('grade',1.0); POP=PL.get('pop',0.84); TINT=PL.get('tint'); VIG=PL.get('vignette',True); SHADOW=float(PL.get('shadow',0) or 0)
CAM=json.load(open(PL['camera'])) if PL.get('camera') and os.path.exists(PL['camera']) else None
if not os.path.exists('pip.json'): PIP={'states':{'full':[0,0,OW,OH,0,1,0,0]},'keys':[[0,'full']]}
# subject pop only where the person cut-out is meant to be used (the text-behind-head range), so masks left over
# from an earlier version never change other frames
_cfg=json.load(open('overlay_cfg.json')) if os.path.exists('overlay_cfg.json') else {}
MASK_UNTIL=[int((b+0.1)*FPS)+1 for a,b in _cfg.get('back',[])]
MASK_FROM=[int(a*FPS) for a,b in _cfg.get('back',[])]
def mask_allowed(n): return any(a<=n<=b for a,b in zip(MASK_FROM,MASK_UNTIL))
OVMAP=json.load(open('ov_map.json')) if os.path.exists('ov_map.json') else None
if OVMAP and len(OVMAP.get('front',[]))!=N: OVMAP=None
def C(x): return max(0.0,min(1.0,x))
EASE={'eo':lambda x:1-(1-x)**3,'eo5':lambda x:1-(1-x)**5,'eio':lambda x:4*x**3 if x<.5 else 1-(-2*x+2)**3/2,
      'eb':lambda x:1+2.6*(C(x)-1)**3+1.6*(C(x)-1)**2,'lin':lambda x:x}
GQ=lambda x: round(x*120)          # compare times in 1/120 s steps (the grid build_plan snaps to)
def pip_at(t):
    K=PIP['keys'];S=PIP['states'];i=0
    for j,k in enumerate(K):
        if GQ(k[0])<=GQ(t): i=j
    if i>=len(K)-1: return S[K[i][1]]
    a,b=K[i],K[i+1]
    if (len(b)>2 and b[2]=='step') or b[0]==a[0] or a[1]==b[1]: return S[a[1]]
    u=EASE[b[2] if len(b)>2 else 'eio']((t-a[0])/(b[0]-a[0]))
    return [v+(S[b[1]][k]-v)*u for k,v in enumerate(S[a[1]])]
def anchor(st):
    for a in PL['anchors']:
        if st<a['until']: return a['fx'],a['fy']
    return 0.5,0.4
def seg_at(n):
    t=n/FPS
    for k,s in enumerate(SEG):
        if s['out0']-1e-6<=t<s['out1']-1e-6 or (k==len(SEG)-1 and t<=s['out1']+0.1): return k
    raise Exception(t)
def zoom_at(n):
    t=n/FPS; k=seg_at(n); s=SEG[k]
    u=min(max((t-s['out0'])/(s['out1']-s['out0']),0),1); z0,z1=PL['zoom'][k]
    z=z0+(z1-z0)*(u*u*(3-2*u))
    for a,p0,p1,b in PL.get('punch',[]):
        if GQ(a)<=GQ(t)<GQ(b):
            q=(t-a)/(b-a); z=p0+(p1-p0)*q
            ein=min(1,(t-a)/0.12); z=z*ein+(z0+(z1-z0)*(u*u*(3-2*u)))*(1-ein) if 'smooth' in PL else z
    return z, s['src0']+(t-s['out0'])*s.get('speed',1)
def geom(n):
    z,st=zoom_at(n)
    if CAM: z,fx,fy=CAM[min(n,len(CAM)-1)]
    else: fx,fy=anchor(st)
    s=S0*z
    W,H=int(round(SW*s)),int(round(SH*s))
    ox=min(max(fx*SW*s - fx*VW,0),W-VW); oy=min(max(fy*SH*s - fy*VH,0),H-VH)
    return W,H,ox,oy
def warp(img,W,H,ox,oy,interp=cv2.INTER_AREA):
    r=cv2.resize(img,(W,H),interpolation=interp) if (img.shape[1],img.shape[0])!=(W,H) else img
    if (W,H)==(VW,VH) and ox==0 and oy==0: return r
    return cv2.warpAffine(r,np.float32([[1,0,-ox],[0,1,-oy]]),(VW,VH),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
_mask={}
def rrmask(x,y,w,h,r):
    key=tuple(round(v,1) for v in (x,y,w,h,r))
    if key in _mask: return _mask[key]
    SS=4; m=np.zeros((OH,OW),np.float32)
    x0,y0,x1,y1=int(np.floor(x)),int(np.floor(y)),int(np.ceil(x+w)),int(np.ceil(y+h))
    x0,y0=max(x0,0),max(y0,0); x1,y1=min(x1,OW),min(y1,OH)
    sm=np.zeros(((y1-y0)*SS,(x1-x0)*SS),np.uint8)
    rx,ry,rw,rh,rr=(x-x0)*SS,(y-y0)*SS,w*SS,h*SS,max(r*SS,0)
    cv2.rectangle(sm,(int(rx+rr),int(ry)),(int(rx+rw-rr),int(ry+rh)),255,-1)
    cv2.rectangle(sm,(int(rx),int(ry+rr)),(int(rx+rw),int(ry+rh-rr)),255,-1)
    for cx,cy in [(rx+rr,ry+rr),(rx+rw-rr,ry+rr),(rx+rr,ry+rh-rr),(rx+rw-rr,ry+rh-rr)]:
        cv2.circle(sm,(int(cx),int(cy)),int(rr),255,-1)
    m[y0:y1,x0:x1]=cv2.resize(sm,(x1-x0,y1-y0),interpolation=cv2.INTER_AREA)/255.0
    if len(_mask)>60: _mask.clear()          # 8 MB each; layouts use a handful of shapes
    _mask[key]=m; return m
_shadow={}
def shadow_bg(key,m):
    if key not in _shadow:
        sm=cv2.GaussianBlur(np.roll(m,28,axis=0),(0,0),34)
        if len(_shadow)>20: _shadow.clear()
        _shadow[key]=BG*(1-SHADOW*sm[:,:,None])
    return _shadow[key]
def apply_pip(img,n):
    x,y,w,h,r,k,ox,oy=pip_at(n/FPS)
    if (VW,VH)==(OW,OH) and x<0.5 and y<0.5 and w>1079 and h>1919 and abs(k-1)<1e-4 and abs(ox)<0.5 and abs(oy)<0.5: return img
    sw,sh=int(round(VW*k)),int(round(VH*k))
    sc=cv2.resize(img,(sw,sh),interpolation=cv2.INTER_AREA) if (k<1 or (VW,VH)!=(OW,OH)) and (sw,sh)!=(VW,VH) else img
    lay=cv2.warpAffine(sc,np.float32([[1,0,ox],[0,1,oy]]),(OW,OH),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
    m=rrmask(x,y,w,h,r)
    bg=shadow_bg(tuple(round(v,1) for v in (x,y,w,h,r)),m) if SHADOW>0 else BG
    m=m[:,:,None]
    return (bg*(1-m)+lay.astype(np.float32)*m+0.5).astype(np.uint8)
def rgba(p):
    if not p or not os.path.exists(p): return None
    o=cv2.imread(p,cv2.IMREAD_UNCHANGED)
    if o is None: return None
    if o.shape[2]==3: return o,None
    a=o[:,:,3:4].astype(np.float32)/255
    if a.max()==0: return None
    return o[:,:,:3].astype(np.float32),a
def over(base,p):
    if OVMAP and p and not os.path.exists(p): raise RuntimeError(f'graphics frame missing: {p} (render the graphics again)')
    r=rgba(p)
    if r is None: return base
    c,a=r
    if a is None: return c.astype(np.uint8)
    return (base.astype(np.float32)*(1-a)+c*a+0.5).astype(np.uint8)
def ov_path(ovdir,n,back=False):
    """graphics frame n: from the content-addressed cache (ov_map.json) when present, else <ovdir>/<n>.png"""
    if OVMAP:
        h=(OVMAP.get('back') or {}).get(str(n)) if back else OVMAP['front'][n]
        return os.path.join(OVMAP.get('dir','ovcache'),h+'.png') if h else None
    return f'{ovdir}_back/{n:05d}.png' if back else f'{ovdir}/{n:05d}.png'
def mask_path(n):
    if not mask_allowed(n): return None
    p=f'masks/{src_frame(n):05d}.png'
    return p if os.path.exists(p) else None
def person_mask(n,W,H,ox,oy):
    p=mask_path(n)
    if not p: return None
    m=cv2.imread(p,0).astype(np.float32)/255.0
    m=np.clip((m-0.35)/0.4,0,1)
    m=warp(m,W,H,ox,oy,cv2.INTER_LINEAR)
    m=cv2.GaussianBlur(m,(0,0),2.2)
    return m
def frame(src,n,ovdir):
    W,H,ox,oy=geom(n); base=warp(src,W,H,ox,oy)
    g=grade.grade(base,GRADE,VIG,TINT) if GRADE>0 else base
    m=person_mask(n,W,H,ox,oy)
    if m is not None:
        m3=m[:,:,None]; g=(g.astype(np.float32)*(m3+(1-m3)*POP)).astype(np.uint8)  # subject pop
    bp=ov_path(ovdir,n,True)
    if OVMAP and m is not None and bp and not os.path.exists(bp): raise RuntimeError(f'graphics frame missing: {bp}')
    if m is not None and bp and os.path.exists(bp):
        r=rgba(bp)
        if r is not None:
            c,a=r; gf=g.astype(np.float32); comp=gf*(1-a)+c*a; m3=m[:,:,None]
            g=(comp*(1-m3)+gf*m3+0.5).astype(np.uint8)
    img=apply_pip(g,n)
    return over(img,ov_path(ovdir,n))
def src_frame(n): return int(round(zoom_at(n)[1]*FPS))
def grab(sf):
    raw=subprocess.run([FF,'-v','error','-ss',f'{sf/FPS:.4f}','-i',SRC,'-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    return np.frombuffer(raw,np.uint8).reshape(SH,SW,3)

# ---------------- chunked, cached, parallel render ----------------
CH=int(os.environ.get('REEL_CHUNK',60))
ENC=['-c:v','libx264','-preset',os.environ.get('REEL_PRESET','veryfast'),'-crf',os.environ.get('REEL_CRF','17'),'-pix_fmt','yuv420p',
     '-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-g',str(CH*5),'-movflags','+faststart']
def _fh(p):
    """content id of a file we depend on (size + mtime is enough: these files are only ever replaced, never edited)"""
    try: st=os.stat(p); return f'{st.st_size}:{int(st.st_mtime)}'
    except OSError: return '-'
def global_key():
    bgh=hashlib.sha1(open('bg.png','rb').read()).hexdigest() if os.path.exists('bg.png') else '-'
    return json.dumps([VERSION,FPS,SW,SH,OW,OH,VW,VH,GRADE,POP,TINT,VIG,SHADOW,bgh,_fh(SRC),ENC,CH])
_SEG0={}
def seg_first(k):
    if k not in _SEG0:
        n=int(SEG[k]['out0']*FPS)-2
        while seg_at(max(n,0))<k: n+=1
        _SEG0[k]=max(n,0)
    return _SEG0[k]
def pip_key(t):
    K=PIP['keys'];S=PIP['states'];i=0
    for j,k in enumerate(K):
        if GQ(k[0])<=GQ(t): i=j
    if i>=len(K)-1: return [K[i][1],S[K[i][1]]]
    a,b=K[i],K[i+1]
    if (len(b)>2 and b[2]=='step') or b[0]==a[0] or a[1]==b[1]: return [a[1],S[a[1]]]
    return [a[1],S[a[1]],b[1],S[b[1]],b[2] if len(b)>2 else 'eio',GQ(a[0])-GQ(t),GQ(b[0])-GQ(t)]
def geom_key(n):
    """what decides the camera at frame n, in exact shift-proof terms (segment identity + frame offset, punch-in
    times relative to the frame); interpolated floats would differ in the last digit after a shift"""
    if CAM: return ['cam',[round(v,5) for v in CAM[min(n,len(CAM)-1)]]]
    k=seg_at(n); s=SEG[k]; t=n/FPS
    pu=[[GQ(a)-GQ(t),GQ(b)-GQ(t),p0,p1] for a,p0,p1,b in PL.get('punch',[]) if GQ(a)<=GQ(t)<GQ(b)]
    return [round(s['src0'],4),round(s['src1'],4),round(s.get('speed',1),4),PL['zoom'][k],n-seg_first(k),round((s['out1']-s['out0'])*FPS,3),pu,anchor(zoom_at(n)[1])]
def frame_sig(n,ovdir):
    sf=src_frame(n); mp=mask_path(n)
    fr=ov_path(ovdir,n); bk=ov_path(ovdir,n,True) if mp else None
    if OVMAP: fo,bo=OVMAP['front'][n],((OVMAP.get('back') or {}).get(str(n)) if mp else None)
    else: fo,bo=_fh(fr),(_fh(bk) if bk else None)
    return [sf,geom_key(n),pip_key(n/FPS),mp is not None,fo,bo]
def plan_chunks(ovdir):
    """[(key, [n...])] in output order; a chunk never crosses a cut, so chunks after an edit realign by themselves"""
    G=global_key(); out=[]; cur=[]; ck=None
    for n in range(N):
        k=seg_at(n)
        if cur and (k!=ck or len(cur)>=CH): out.append(cur); cur=[]
        cur.append(n); ck=k
    if cur: out.append(cur)
    res=[]
    for fr in out:
        h=hashlib.sha1(G.encode())
        for n in fr: h.update(json.dumps(frame_sig(n,ovdir)).encode())
        res.append((h.hexdigest()[:24],fr))
    return res
class Reader:
    """decodes the source forward from a frame; reopens (with an exact seek) only when asked to go backwards or far ahead"""
    def __init__(self): self.p=None; self.pos=None; self.fsz=SW*SH*3; self.buf=None
    def _open(self,sf):
        self.close()
        self.p=subprocess.Popen([FF,'-v','error','-ss',f'{max(0,sf-0.5)/FPS:.6f}','-i',SRC,'-an','-vsync','passthrough','-f','rawvideo','-pix_fmt','bgr24','-'],
                                stdout=subprocess.PIPE,bufsize=10**8)
        self.pos=sf; self.buf=None
    def get(self,sf):
        if self.p is None or sf<self.pos-(1 if self.buf is not None else 0) or sf>self.pos+90: self._open(sf)
        if self.buf is not None and sf==self.pos-1: return self.buf
        while self.pos<=sf:
            b=self.p.stdout.read(self.fsz)
            if len(b)<self.fsz:
                if self.buf is not None: return self.buf       # past the end: hold the last frame
                raise RuntimeError(f'could not read source frame {sf}')
            self.buf=np.frombuffer(b,np.uint8).reshape(SH,SW,3); self.pos+=1
        return self.buf
    def close(self):
        if self.p: self.p.kill(); self.p.wait(); self.p=None
def render_chunk(key,frames,ovdir,rd):
    os.makedirs('vcache',exist_ok=True); tmp=f'vcache/{key}.{os.getpid()}.tmp.mp4'
    enc=subprocess.Popen([FF,'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OW}x{OH}','-r',str(FPS),'-i','-',*ENC,
                          '-threads',os.environ.get('REEL_X264_THREADS','0'),tmp],stdin=subprocess.PIPE)
    for n in frames:
        enc.stdin.write(frame(rd.get(src_frame(n)),n,ovdir).tobytes())
    enc.stdin.close()
    if enc.wait(): raise RuntimeError('encoder failed')
    os.replace(tmp,f'vcache/{key}.mp4')
def full(ovdir,outp,workers):
    os.makedirs('vcache',exist_ok=True)
    if OVMAP:
        need=set(OVMAP['front'])|set((OVMAP.get('back') or {}).values())
        gone=[h for h in need if not os.path.exists(os.path.join(OVMAP.get('dir','ovcache'),h+'.png'))]
        if gone: raise RuntimeError(f'{len(gone)} graphics frames are missing; render the graphics again')
    chunks=plan_chunks(ovdir)
    todo=[(k,f) for k,f in chunks if not os.path.exists(f'vcache/{k}.mp4')]
    todo=list({k:(k,f) for k,f in todo}.values())       # identical chunks render once
    total=sum(len(f) for _,f in todo)
    print(f'chunks {len(chunks)} | reuse {len(chunks)-len(todo)} | render {len(todo)} ({total} of {N} frames)',flush=True)
    if todo:
        cpu=os.cpu_count() or 2
        workers=max(1,min(workers or max(1,min(4,cpu//2)),len(todo)))
        # contiguous blocks per worker (the source decoder then only reads forward), balanced by frame count
        blocks=[[] for _ in range(workers)]; per=total/workers; acc=0; w=0
        for k,f in todo:
            if acc>=per*(w+1) and w<workers-1: w+=1
            blocks[w].append([k,f]); acc+=len(f)
        blocks=[b for b in blocks if b]
        if len(blocks)==1: worker_jobs(blocks[0],ovdir)
        else:
            ps=[]
            for i,b in enumerate(blocks):
                jf=f'vcache/job{i}.json'; json.dump(b,open(jf,'w'))
                env=dict(os.environ,REEL_X264_THREADS=str(max(1,(os.cpu_count() or 2)//len(blocks))))
                ps.append(subprocess.Popen([sys.executable,os.path.abspath(__file__),'worker',jf,ovdir],env=env))
            bad=[p.wait() for p in ps]
            if any(bad): raise RuntimeError('a render worker failed')
    lst='vcache/list.txt'
    with open(lst,'w') as f:
        for k,_ in chunks: f.write(f"file '{k}.mp4'\n")
    tmp=outp+'.tmp.mp4'
    r=subprocess.run([FF,'-v','error','-y','-f','concat','-safe','0','-i',lst,'-c','copy','-movflags','+faststart',tmp],capture_output=True)
    if r.returncode: raise RuntimeError('joining chunks failed: '+r.stderr.decode()[-800:])
    os.replace(tmp,outp)
    keep={k for k,_ in chunks}
    prev=json.load(open('vcache/keys.json')) if os.path.exists('vcache/keys.json') else []
    json.dump(sorted(keep),open('vcache/keys.json','w'))
    for fn in os.listdir('vcache'):          # keep this version's and the previous version's chunks only
        if fn.endswith('.mp4') and fn[:-4] not in keep and fn[:-4] not in prev: os.remove(os.path.join('vcache',fn))
    print('done',N,'/',N,'| rendered',total,'frames',flush=True)
def worker_jobs(jobs,ovdir):
    rd=Reader(); t0=time.time(); done=0
    for key,frames in jobs:
        render_chunk(key,frames,ovdir,rd); done+=len(frames)
        if done%150<len(frames): print('frames',done,'/',sum(len(f) for _,f in jobs),round(time.time()-t0),'s',flush=True)
    rd.close()
if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='test':
        ovdir=sys.argv[2]; fr=[int(x) for x in sys.argv[3].split(',')]; tiles=[]
        for n in fr:
            img=frame(grab(src_frame(n)),n,ovdir); tiles.append(cv2.resize(img,(360,640),interpolation=cv2.INTER_AREA))
            if len(sys.argv)>5: cv2.imwrite(f'{sys.argv[5]}_{n:05d}.jpg',img,[cv2.IMWRITE_JPEG_QUALITY,88])
        while len(tiles)%6: tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(sys.argv[4],np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]),[cv2.IMWRITE_JPEG_QUALITY,85])
    elif mode=='worker':
        worker_jobs(json.load(open(sys.argv[2])),sys.argv[3])
    else:
        w=int(sys.argv[sys.argv.index('--workers')+1]) if '--workers' in sys.argv else int(os.environ.get('REEL_WORKERS','0') or 0)
        full(sys.argv[2],sys.argv[3],w)
