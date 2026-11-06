import os, hashlib, numpy as np, cv2
_V={}
def vignette(h,w,fx=0.54,fy=0.42,strength=0.30):
    k=(h,w,fx,fy,strength)
    if k not in _V:
        y,x=np.mgrid[0:h,0:w].astype(np.float32); dx=(x/w-fx)/0.75; dy=(y/h-fy)/0.95
        r=np.sqrt(dx*dx+dy*dy); v=1-strength*np.clip((r-0.35)/0.75,0,1)**1.6
        _V[k]=v[:,:,None].astype(np.float32)
    return _V[k]
def _tone(x, amt, tint):
    """the colour part of the grade: a per-pixel function of (B,G,R), floats 0..1"""
    b,g,r=x[:,:,0],x[:,:,1],x[:,:,2]
    s=lambda v: v*v*(3-2*v)
    x=x+(s(np.clip(x,0,1))-x)*0.38*amt
    x=(x-0.025*amt)/(1-0.025*amt)
    lum=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]
    sh=np.clip(1-lum*1.6,0,1)**2; hi=np.clip((lum-0.45)/0.55,0,1)**1.5
    tone=np.concatenate([0.045*sh-0.035*hi, 0.012*sh+0.006*hi, -0.025*sh+0.045*hi],axis=2)*amt  # B,G,R
    x=x+tone
    l2=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]
    sat=np.abs(x-l2).max(axis=2,keepdims=True)
    x=l2+(x-l2)*(1+0.18*amt*(1-np.clip(sat*2.5,0,1)))
    if tint:
        l3=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]; w=np.clip(1.15-l3*1.2,0.15,1)
        x=x+np.array(tint,np.float32)[None,None,:]*w*amt
    return x
def grade_slow(img, amt=1.0, vig=True, tint=None):
    """reference implementation (one float pass per frame, ~0.3-0.5 s at 1080x1920)"""
    x=_tone(img.astype(np.float32)/255.0, amt, tint)
    if vig: x=x*vignette(*img.shape[:2])
    return np.clip(x*255+0.5,0,255).astype(np.uint8)
_LUT={}; _V3={}
SC=16384.0   # table stores value*16384 as int16: covers -2..2, so values pushed past 0..1 by the curve still meet the vignette exactly like the float path
def lut(amt, tint):
    """the colour part as a 256x256x256 lookup table, built once (~2 s) and kept on disk (data/reels/_cache).
    Same per-pixel maths as grade_slow, so the picture matches it to within one level, at ~1/5 of the time."""
    key=hashlib.sha1(repr((round(float(amt),6),[round(float(v),6) for v in (tint or [])],'v2')).encode()).hexdigest()[:12]
    if key in _LUT: return _LUT[key]
    d=os.environ.get('REEL_CACHE') or os.path.join(os.path.dirname(os.path.abspath(os.environ.get('REEL_HOME') or '.')),'_cache')
    p=os.path.join(d,f'grade_{key}.npy'); t=None
    if os.path.exists(p):
        try:
            t=np.load(p)
            if t.shape!=(1<<24,3) or t.dtype!=np.int16: t=None
        except Exception: t=None
    if t is None:
        t=np.empty((1<<24,3),np.int16); g=np.arange(256,dtype=np.float32)/255.0
        for b in range(256):                      # one B plane at a time: 256x256 (G,R) pixels
            x=np.empty((256,256,3),np.float32); x[:,:,0]=g[b]; x[:,:,1]=g[:,None]; x[:,:,2]=g[None,:]
            y=_tone(x,amt,tint)
            t[b<<16:(b+1)<<16]=np.clip(np.rint(y*SC),-32767,32767).reshape(-1,3).astype(np.int16)
        try:
            os.makedirs(d,exist_ok=True); tmp=p[:-4]+f'.{os.getpid()}.tmp.npy'; np.save(tmp,t); os.replace(tmp,p)
        except Exception: pass
    _LUT[key]=t; return t
def _vig3(h,w,vig):
    k=(h,w,vig)
    if k not in _V3:
        v=vignette(h,w) if vig else np.ones((h,w,1),np.float32)
        _V3[k]=np.ascontiguousarray(np.repeat(v*(255.0/SC),3,axis=2)).astype(np.float32)
    return _V3[k]
def grade(img, amt=1.0, vig=True, tint=None):
    """tint: optional [B,G,R] offsets added mostly to shadows/mids, e.g. [-0.01,0.035,-0.005] = olive-green look"""
    if os.environ.get('REEL_GRADE_SLOW'): return grade_slow(img,amt,vig,tint)
    t=lut(amt,tint); h,w=img.shape[:2]
    idx=(img[:,:,0].astype(np.int32)<<16)|(img[:,:,1].astype(np.int32)<<8)|img[:,:,2]
    x=np.take(t,idx.ravel(),axis=0).reshape(h,w,3).astype(np.float32)
    y=cv2.multiply(x,_vig3(h,w,bool(vig)))
    return np.clip(y+0.5,0,255).astype(np.uint8)
