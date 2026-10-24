"""Clean, non-musical sound effects made in code (no downloads, no music).
usage: python3 sfx.py sfx_events.json -> ~/edit/sfx.wav
event: [time_sec, kind, level_dBFS, {options}]  kinds: air (whoosh), tap (UI tap), key (keyboard), hit (soft low impact),
  pop (bubble pop), riser (build-up into a hit), swipe (fast wipe), shutter (camera), glitch (digital), ticks (counter rolling)
levels: -36 tiny, -30 normal, -26 noticeable, -22 big moment (use 1-3 of these)"""
import numpy as np, soundfile as sf, json, sys, os
os.chdir((os.environ.get('REEL_HOME') or os.getcwd()))
from scipy import signal
SR=48000; DUR=json.load(open('edit.json'))['dur']
def R(seed): return np.random.default_rng(seed)
def filt(x,kind,f,o=2): return signal.sosfilt(signal.butter(o,f,btype=kind,fs=SR,output='sos'),x)
def nm(x): return x/(np.max(np.abs(x))+1e-9)
def pink(n,rng):
    w=rng.standard_normal(n); b=[0.049922035,-0.095993537,0.050612699,-0.004408786]; a=[1,-2.494956002,2.017265875,-0.522189400]
    return nm(signal.lfilter(b,a,w))
def st(y,pan=0.0,width=0.0,rng=None):
    L=y*(1-pan); Rr=y*(1+pan)
    if width>0:
        d=int(0.0007*SR); Rr=np.concatenate([np.zeros(d),Rr[:-d]])*(1-width*0.3)+Rr*width*0.3
    return np.stack([L,Rr],1)
def sweep_noise(dur,f0,f1,rng,bw=0.5,curve=1.0):
    n=int(dur*SR); x=pink(n+4096,rng); f,t,Z=signal.stft(x,SR,nperseg=1024,noverlap=768)
    u=np.clip(t/dur,0,1)**curve; fc=f0*(f1/f0)**u
    W=np.exp(-0.5*(np.log(np.maximum(f[:,None],1)/fc[None,:])/bw)**2)
    _,y=signal.istft(Z*W,SR,nperseg=1024,noverlap=768); return y[:n]
def air(dur=0.5,f0=350,f1=2600,peak=0.62,seed=1,out=False):
    rng=R(seed); y=sweep_noise(dur,f0,f1,rng,0.55); n=len(y); u=np.arange(n)/n
    env=np.where(u<peak,np.sin(np.pi/2*np.minimum(u/peak,1))**2,np.clip(np.cos(np.pi/2*np.clip((u-peak)/(1-peak),0,1)),0,1)**1.5)
    if out: env=env[::-1]
    y=nm(filt(y*env,'high',150)); p=np.linspace(-.3,.3,n)
    return np.stack([y*(1-p),y*(1+p)],1)
def tap(seed=2,f=2600):
    rng=R(seed); n=int(0.03*SR); t=np.arange(n)/SR
    y=np.sin(2*np.pi*f*t)*np.exp(-t/0.0035)*0.6+filt(rng.standard_normal(n),'high',4000)*np.exp(-t/0.0012)*0.5
    return st(nm(filt(y,'low',9000)))
def key(seed=3):
    rng=R(seed); n=int(0.06*SR); t=np.arange(n)/SR; f=220+rng.random()*80
    click=filt(rng.standard_normal(n),'band',[1500+rng.random()*800,6500])*np.exp(-t/0.006)
    thock=np.sin(2*np.pi*f*t)*np.exp(-t/0.014)*0.5
    return st(nm(click+thock),pan=(rng.random()-.5)*0.3)
def hit(seed=4,f0=62,dec=0.16):
    rng=R(seed); n=int(0.5*SR); t=np.arange(n)/SR; f=f0*(1+0.6*np.exp(-t/0.025))
    y=np.sin(2*np.pi*np.cumsum(f)/SR)*np.exp(-t/dec)+filt(rng.standard_normal(n),'low',900)*np.exp(-t/0.012)*0.35
    return st(nm(filt(y,'low',2500)))
def pop(seed=5,f0=900,f1=380):
    n=int(0.07*SR); t=np.arange(n)/SR; f=f1+(f0-f1)*np.exp(-t/0.012)
    y=np.sin(2*np.pi*np.cumsum(f)/SR)*np.exp(-t/0.018)*(1-np.exp(-t/0.001))
    return st(nm(filt(y,'low',5000)))
def riser(dur=0.85,seed=6):
    rng=R(seed); y=sweep_noise(dur,250,6000,rng,0.4,1.6); n=len(y); u=np.arange(n)/n
    env=(u**2.2)*(1-np.clip((u-0.97)/0.03,0,1)); y=nm(filt(y*env,'high',200)); return st(y,width=0.6)
def swipe(dur=0.16,seed=7):
    rng=R(seed); n=int(dur*SR); y=filt(rng.standard_normal(n),'band',[2000,8000])*np.sin(np.pi*np.arange(n)/n)**2
    return st(nm(y),pan=0.1)
def shutter(seed=8):
    rng=R(seed); n=int(0.16*SR); y=np.zeros(n); t=np.arange(n)/SR
    for k,(at,a) in enumerate([(0.0,1.0),(0.075,0.7)]):
        i=int(at*SR); m=int(0.04*SR); tt=np.arange(m)/SR
        b=filt(rng.standard_normal(m),'band',[900,5000])*np.exp(-tt/0.007)*a; y[i:i+m]+=b
    return st(nm(y))
def glitch(dur=0.32,seed=9):
    rng=R(seed); n=int(dur*SR); y=rng.standard_normal(n)
    gate=np.repeat((rng.random(n//600+1)>0.45).astype(float),600)[:n]
    y=np.round(y*3)/3*gate; y=filt(y,'band',[600,7000])*np.hanning(n)**0.3
    return st(nm(y),width=0.8)
def ticks(dur=0.6,count=14,seed=10):
    rng=R(seed); n=int(dur*SR)+SR//10; y=np.zeros(n)
    times=np.cumsum(np.linspace(0.025,0.07,count)); times=times/times[-1]*dur
    for k,tt in enumerate(times):
        i=int(tt*SR); m=int(0.012*SR); u=np.arange(m)/SR
        y[i:i+m]+=np.sin(2*np.pi*3200*u)*np.exp(-u/0.0018)*(0.6+0.4*rng.random())
    return st(nm(filt(y,'low',8000)))
def file(path,seed=0):
    """a sound file you got elsewhere (e.g. made with the ElevenLabs connector) -> stereo 48k"""
    import subprocess; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); from envlib import FF
    raw=subprocess.run([FF,'-v','error','-i',path,'-f','f32le','-ac','2','-ar',str(SR),'-'],capture_output=True).stdout
    return np.frombuffer(raw,np.float32).reshape(-1,2).astype(np.float64)
GEN=dict(file=file,air=air,tap=tap,key=key,hit=hit,pop=pop,riser=riser,swipe=swipe,shutter=shutter,glitch=glitch,ticks=ticks)
def room(x,seed=11):
    rng=R(seed); n=int(0.25*SR); t=np.arange(n)/SR
    irL=filt(rng.standard_normal(n)*np.exp(-t/0.06),'low',6000); irR=filt(rng.standard_normal(n)*np.exp(-t/0.06),'low',6000)
    irL/=np.abs(irL).sum(); irR/=np.abs(irR).sum()
    wet=np.stack([signal.fftconvolve(x[:,0],irL)[:len(x)],signal.fftconvolve(x[:,1],irR)[:len(x)]],1)
    return x*0.85+wet*0.6
N=int(round(DUR*SR)); out=np.zeros((N+SR*2,2)); EV=json.load(open(sys.argv[1] if len(sys.argv)>1 else 'sfx_events.json'))
for ev in EV:
    t,kind,db=ev[:3]; kw=ev[3] if len(ev)>3 else {}
    x=GEN[kind](**kw); x=x if kind=='file' else room(x); x=x/np.max(np.abs(x))*10**(db/20); i=max(0,int(t*SR)); out[i:i+len(x)]+=x[:len(out)-i]
out=out[:N]
sf.write('sfx.wav',out.astype(np.float32),SR,subtype='FLOAT'); print('sfx events',len(EV))
