"""Background for split screens / cards. usage: python make_bg.py [dark|green|light]  -> ~/edit/bg.png"""
import numpy as np, cv2, sys, os
mode=sys.argv[1] if len(sys.argv)>1 else 'dark'
H,W=1920,1080; y,x=np.mgrid[0:H,0:W].astype(np.float32)
r=np.sqrt(((x-540)/900)**2+((y-760)/1300)**2); t=np.clip(r,0,1)[:,:,None]**1.2
if mode=='dark': c0,c1,g=np.array([30,27,25],np.float32),np.array([12,11,10],np.float32),5
elif mode=='green': c0,c1,g=np.array([22,40,30],np.float32),np.array([8,13,10],np.float32),5   # BGR: olive-green glow, like the reference reels
else: c0,c1,g=np.array([240,244,246],np.float32),np.array([222,228,232],np.float32),-6
img=c0*(1-t)+c1*t; grid=((x%60)<1.2)|((y%60)<1.2); img[grid]+=g
img+=np.random.default_rng(3).normal(0,2.0,img.shape)
cv2.imwrite(os.path.join(os.environ.get('REEL_HOME') or os.getcwd(),'bg.png'),np.clip(img,0,255).astype(np.uint8)); print('bg.png',mode)
