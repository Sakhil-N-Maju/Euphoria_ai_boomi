"""Background for split screens / cards / windows.
usage: python make_bg.py [dark|green|light|neutral|glow_dark|glow_light|paper|ink|crimson|midnight|violet] [#RRGGBB accent for the glow]  -> bg.png"""
import numpy as np, cv2, sys, os
mode=sys.argv[1] if len(sys.argv)>1 else 'dark'
acc=sys.argv[2] if len(sys.argv)>2 else '#4F8BFF'
A=np.array([int(acc[5:7],16),int(acc[3:5],16),int(acc[1:3],16)],np.float32)   # BGR
H,W=1920,1080; y,x=np.mgrid[0:H,0:W].astype(np.float32)
r=np.sqrt(((x-540)/900)**2+((y-760)/1300)**2); t=np.clip(r,0,1)[:,:,None]**1.2
grid=((x%60)<1.2)|((y%60)<1.2); noise=np.random.default_rng(3).normal(0,2.0,(H,W,3))
def blob(cx,cy,rx,ry): return np.exp(-(((x-cx)/rx)**2+((y-cy)/ry)**2))[:,:,None]
if mode in ('dark','green','light'):           # the original looks, unchanged
    if mode=='dark': c0,c1,g=np.array([30,27,25],np.float32),np.array([12,11,10],np.float32),5
    elif mode=='green': c0,c1,g=np.array([22,40,30],np.float32),np.array([8,13,10],np.float32),5   # BGR: olive-green glow, like the reference reels
    else: c0,c1,g=np.array([240,244,246],np.float32),np.array([222,228,232],np.float32),-6
    img=c0*(1-t)+c1*t; img[grid]+=g; img+=noise
elif mode=='neutral':                          # talking head: soft charcoal, no colour cast
    img=np.array([26,25,24],np.float32)*(1-t)+np.array([10,10,10],np.float32)*t; img[grid]+=3; img+=noise
elif mode=='glow_dark':                        # product: deep navy with an accent glow behind the window
    base=np.array([22,12,8],np.float32)*(1-t)+np.array([8,5,4],np.float32)*t
    img=base+A*0.55*blob(540,1030,620,520)+A*0.25*blob(140,300,500,420)+A*0.18*blob(980,1700,520,420); img+=noise*0.8
elif mode=='glow_light':                       # product: light pastel with a soft accent haze
    base=np.array([246,244,242],np.float32)
    img=base*(1-0.06*t)+(A-base)*0.22*blob(540,1030,700,600)+(np.array([200,235,255],np.float32)-base)*0.25*blob(150,250,520,420); img+=noise*0.6
elif mode=='paper':                            # faceless light: editorial paper with a faint grid
    img=np.array([236,241,243],np.float32)*(1-0.10*t); img[grid]-=7; img+=noise*1.2
elif mode=='ink':                              # faceless dark: near black with one accent glow
    img=np.array([14,13,12],np.float32)*(1-0.4*t)+A*0.10*blob(540,860,700,700); img[grid]+=4; img+=noise
elif mode=='crimson':                         # faceless dark: black with a deep red glow (ugoki references)
    img=np.array([10,8,12],np.float32)*(1-0.3*t)+np.array([16,18,120],np.float32)*0.38*blob(540,1000,760,820)+np.array([10,12,70],np.float32)*0.5*blob(540,1900,900,500); img+=noise*1.2
elif mode=='midnight':                        # faceless: deep navy, soft centre lift (salesmen reference)
    img=np.array([34,20,11],np.float32)*(1-0.5*t)+np.array([40,26,14],np.float32)*0.6*blob(540,860,700,800); img+=noise*0.8
elif mode=='violet':                          # faceless light: near-white with a lilac haze
    img=np.array([248,246,246],np.float32)*(1-0.04*t)+(np.array([255,210,228],np.float32)-248)*0.35*blob(900,300,600,500); img[grid]-=4; img+=noise*0.6
else:
    sys.exit('unknown background '+mode)
cv2.imwrite(os.path.join(os.environ.get('REEL_HOME') or os.getcwd(),'bg.png'),np.clip(img,0,255).astype(np.uint8)); print('bg.png',mode)
