import numpy as np, cv2
_V={}
def vignette(h,w,fx=0.54,fy=0.42,strength=0.30):
    k=(h,w,fx,fy,strength)
    if k not in _V:
        y,x=np.mgrid[0:h,0:w].astype(np.float32); dx=(x/w-fx)/0.75; dy=(y/h-fy)/0.95
        r=np.sqrt(dx*dx+dy*dy); v=1-strength*np.clip((r-0.35)/0.75,0,1)**1.6
        _V[k]=v[:,:,None].astype(np.float32)
    return _V[k]
def grade(img, amt=1.0, vig=True, tint=None):
    """tint: optional [B,G,R] offsets added mostly to shadows/mids, e.g. [-0.01,0.035,-0.005] = olive-green look"""
    x=img.astype(np.float32)/255.0  # BGR
    b,g,r=x[:,:,0],x[:,:,1],x[:,:,2]
    lum=0.114*b+0.587*g+0.299*r
    # contrast S-curve blended
    s=lambda v: v*v*(3-2*v)
    x=x+(s(np.clip(x,0,1))-x)*0.38*amt
    x=(x-0.025*amt)/(1-0.025*amt)
    lum=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]
    sh=np.clip(1-lum*1.6,0,1)**2; hi=np.clip((lum-0.45)/0.55,0,1)**1.5
    tone=np.concatenate([0.045*sh-0.035*hi, 0.012*sh+0.006*hi, -0.025*sh+0.045*hi],axis=2)*amt  # B,G,R
    x=x+tone
    # saturation / vibrance
    l2=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]
    sat=np.abs(x-l2).max(axis=2,keepdims=True)
    x=l2+(x-l2)*(1+0.18*amt*(1-np.clip(sat*2.5,0,1)))
    if tint:
        l3=(0.114*x[:,:,0]+0.587*x[:,:,1]+0.299*x[:,:,2])[:,:,None]; w=np.clip(1.15-l3*1.2,0.15,1)
        x=x+np.array(tint,np.float32)[None,None,:]*w*amt
    if vig: x=x*vignette(*img.shape[:2])
    return np.clip(x*255+0.5,0,255).astype(np.uint8)
