"""Composite: source video (cuts + zoom plan) -> colour grade -> subject pop / text-behind-person -> layouts (pip.json) -> graphics.
usage: python3 composite.py test <ovdir> <f1,f2,...> <sheet.jpg> [fullprefix]   |   python3 composite.py full <ovdir> <out.mp4>
plan.json: {"anchors":[{"until":999,"fx":0.5,"fy":0.42}],"zoom":[[z0,z1] per segment],"punch":[[t_from,z0,z1,t_to],...],"grade":1.0,"pop":0.84}"""
import json, sys, os, subprocess, numpy as np, cv2
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); import grade
from envlib import FF, probe
os.chdir((os.environ.get('REEL_HOME') or os.getcwd()))
E=json.load(open('edit.json')); SEG=E['segs']; PL=json.load(open('plan.json')); PIP=json.load(open('pip.json')) if os.path.exists('pip.json') else None
FPS=PL.get('fps',30); SRC=PL.get('src','src.mp4'); OW,OH=PL.get('out',[1080,1920]); N=int(round(E['dur']*FPS))
_p=probe(SRC); SW,SH=_p['w'],_p['h']
S0=max(OW/SW,OH/SH); BG=cv2.imread('bg.png').astype(np.float32) if os.path.exists('bg.png') else np.full((OH,OW,3),12,np.float32)
GRADE=PL.get('grade',1.0); POP=PL.get('pop',0.84); TINT=PL.get('tint'); VIG=PL.get('vignette',True)
if not os.path.exists('pip.json'): PIP={'states':{'full':[0,0,OW,OH,0,1,0,0]},'keys':[[0,'full']]}
def C(x): return max(0.0,min(1.0,x))
EASE={'eo':lambda x:1-(1-x)**3,'eo5':lambda x:1-(1-x)**5,'eio':lambda x:4*x**3 if x<.5 else 1-(-2*x+2)**3/2,
      'eb':lambda x:1+2.6*(C(x)-1)**3+1.6*(C(x)-1)**2,'lin':lambda x:x}
def pip_at(t):
    K=PIP['keys'];S=PIP['states'];i=0
    for j,k in enumerate(K):
        if k[0]<=t: i=j
    if i>=len(K)-1: return S[K[i][1]]
    a,b=K[i],K[i+1]
    if (len(b)>2 and b[2]=='step') or b[0]==a[0] or a[1]==b[1]: return S[a[1]]
    u=EASE[b[2] if len(b)>2 else 'eio']((t-a[0])/(b[0]-a[0]))
    return [v+(S[b[1]][k]-v)*u for k,v in enumerate(S[a[1]])]
def anchor(st):
    for a in PL['anchors']:
        if st<a['until']: return a['fx'],a['fy']
    return 0.5,0.4
def zoom_at(n):
    t=n/FPS
    for k,s in enumerate(SEG):
        if s['out0']-1e-6<=t<s['out1']-1e-6 or (k==len(SEG)-1 and t<=s['out1']+0.1):
            u=min(max((t-s['out0'])/(s['out1']-s['out0']),0),1); z0,z1=PL['zoom'][k]
            z=z0+(z1-z0)*(u*u*(3-2*u))
            for a,p0,p1,b in PL.get('punch',[]):
                if a<=t<b:
                    q=(t-a)/(b-a); z=p0+(p1-p0)*q
                    ein=min(1,(t-a)/0.12); z=z*ein+(z0+(z1-z0)*(u*u*(3-2*u)))*(1-ein) if 'smooth' in PL else z
            return z, s['src0']+(t-s['out0'])
    raise Exception(t)
def geom(n):
    z,st=zoom_at(n); fx,fy=anchor(st); s=S0*z
    W,H=int(round(SW*s)),int(round(SH*s))
    ox=min(max(fx*SW*s - fx*OW,0),W-OW); oy=min(max(fy*SH*s - fy*OH,0),H-OH)
    return W,H,ox,oy
def warp(img,W,H,ox,oy,interp=cv2.INTER_AREA):
    r=cv2.resize(img,(W,H),interpolation=interp) if (img.shape[1],img.shape[0])!=(W,H) else img
    if (W,H)==(OW,OH) and ox==0 and oy==0: return r
    return cv2.warpAffine(r,np.float32([[1,0,-ox],[0,1,-oy]]),(OW,OH),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
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
    if len(_mask)>400: _mask.clear()
    _mask[key]=m; return m
def apply_pip(img,n):
    x,y,w,h,r,k,ox,oy=pip_at(n/FPS)
    if x<0.5 and y<0.5 and w>1079 and h>1919 and abs(k-1)<1e-4 and abs(ox)<0.5 and abs(oy)<0.5: return img
    sw,sh=int(round(OW*k)),int(round(OH*k))
    sc=cv2.resize(img,(sw,sh),interpolation=cv2.INTER_AREA) if k<1 else img
    lay=cv2.warpAffine(sc,np.float32([[1,0,ox],[0,1,oy]]),(OW,OH),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
    m=rrmask(x,y,w,h,r)[:,:,None]
    return (BG*(1-m)+lay.astype(np.float32)*m+0.5).astype(np.uint8)
def rgba(p):
    if not os.path.exists(p): return None
    o=cv2.imread(p,cv2.IMREAD_UNCHANGED)
    if o.shape[2]==3: return o,None
    a=o[:,:,3:4].astype(np.float32)/255
    if a.max()==0: return None
    return o[:,:,:3].astype(np.float32),a
def over(base,p):
    r=rgba(p)
    if r is None: return base
    c,a=r
    if a is None: return c.astype(np.uint8)
    return (base.astype(np.float32)*(1-a)+c*a+0.5).astype(np.uint8)
_prevm=[None]
def person_mask(n,W,H,ox,oy):
    sf=src_frame(n); p=f'masks/{sf:05d}.png'
    if not os.path.exists(p): return None
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
    bp=f'{ovdir}_back/{n:05d}.png'
    if m is not None and os.path.exists(bp):
        r=rgba(bp)
        if r is not None:
            c,a=r; gf=g.astype(np.float32); comp=gf*(1-a)+c*a; m3=m[:,:,None]
            g=(comp*(1-m3)+gf*m3+0.5).astype(np.uint8)
    img=apply_pip(g,n)
    return over(img,f'{ovdir}/{n:05d}.png')
def src_frame(n): return int(round(zoom_at(n)[1]*FPS))
def grab(sf):
    raw=subprocess.run([FF,'-v','error','-ss',f'{sf/FPS:.4f}','-i',SRC,'-frames:v','1','-f','rawvideo','-pix_fmt','bgr24','-'],capture_output=True).stdout
    return np.frombuffer(raw,np.uint8).reshape(SH,SW,3)
if __name__=='__main__':
    mode,ovdir=sys.argv[1],sys.argv[2]
    if mode=='test':
        fr=[int(x) for x in sys.argv[3].split(',')]; tiles=[]
        for n in fr:
            img=frame(grab(src_frame(n)),n,ovdir); tiles.append(cv2.resize(img,(360,640),interpolation=cv2.INTER_AREA))
            if len(sys.argv)>5: cv2.imwrite(f'{sys.argv[5]}_{n:05d}.jpg',img,[cv2.IMWRITE_JPEG_QUALITY,88])
        while len(tiles)%6: tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(sys.argv[4],np.vstack([np.hstack(tiles[i:i+6]) for i in range(0,len(tiles),6)]),[cv2.IMWRITE_JPEG_QUALITY,85])
    else:
        dec=subprocess.Popen([FF,'-v','error','-i',SRC,'-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE,bufsize=10**8)
        enc=subprocess.Popen([FF,'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OW}x{OH}','-r',str(FPS),'-i','-','-c:v','libx264','-preset','medium','-crf','15','-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',sys.argv[3]],stdin=subprocess.PIPE)
        need={}
        for n in range(N): need.setdefault(src_frame(n),[]).append(n)
        fsz=SW*SH*3; i=0; done=0
        while True:
            buf=dec.stdout.read(fsz)
            if len(buf)<fsz: break
            if i in need:
                src=np.frombuffer(buf,np.uint8).reshape(SH,SW,3)
                for n in need[i]:
                    enc.stdin.write(frame(src,n,ovdir).tobytes()); done+=1
                    if done%150==0: print('frames',done,'/',N,flush=True)
            i+=1
        enc.stdin.close(); enc.wait(); dec.kill(); print('done',done,'/',N)
