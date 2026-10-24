"""Landscape (podcast / interview) -> vertical 1080x1920, following faces. No extra tools needed (OpenCV face finder).
usage: python3 reframe.py follow|stack|center [--hold 1.5]
  follow = full-height 9:16 crop that cuts to whoever is talking (mouth movement), holds each shot >= --hold seconds
  stack  = two speakers, one on top of the other (left person on top)
  center = plain centre crop
reads ~/edit/src.mp4 (from prep.py), writes ~/edit/vertical.mp4 + reframe.json; then run: mv vertical.mp4 src.mp4 (prep's audio16k.wav stays valid)"""
import sys, os, json, subprocess, numpy as np, cv2
sys.path.insert(0,os.path.dirname(__file__)); from envlib import FF, probe, ENV
os.chdir((os.environ.get('REEL_HOME') or os.getcwd())); mode=sys.argv[1] if len(sys.argv)>1 else 'follow'
HOLD=float(sys.argv[sys.argv.index('--hold')+1]) if '--hold' in sys.argv else 1.5
p=probe('src.mp4'); SW,SH,FPS=p['w'],p['h'],30; N=int(p['dur']*FPS)
sw=640; sh=int(SH*sw/SW)//2*2; step=3
HAAR=hasattr(cv2,'CascadeClassifier')
if HAAR: casc=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
else:  # OpenCV 5 has no Haar cascades: find people with the cut-out model instead (heads = top of each person blob)
    import onnxruntime as ort
    S=ort.InferenceSession(os.path.join(ENV.get('models',''),'seg','u2net_human_seg.onnx'),providers=['CPUExecutionProvider'])
def heads_seg(bgr):
    x=cv2.resize(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB),(320,320)).astype(np.float32); x/=max(x.max(),1e-6)
    x=(x-np.array([0.485,0.456,0.406]))/np.array([0.229,0.224,0.225])
    m=S.run(None,{S.get_inputs()[0].name:x.transpose(2,0,1)[None].astype(np.float32)})[0][0,0]; m=(m-m.min())/(m.max()-m.min()+1e-6)
    m=(cv2.resize(m,(sw,sh))>0.5).astype(np.uint8)
    cols=np.where(m.any(0))[0]
    if len(cols)==0: return []
    top=np.full(sw,sh,np.float32); top[cols]=m[:,cols].argmax(0)
    top=np.convolve(top,np.ones(15)/15,'same'); out=[]
    # heads = local highest points of the people silhouette, at least 15% of the width apart
    order=np.argsort(top)
    for x in order:
        if top[x]>=sh*0.92: break
        d=int(sw*0.06); l=top[max(0,x-d)]; r=top[min(sw-1,x+d)]
        if top[x] > min(l,r)-sh*0.03: continue          # not a head-shaped bump
        if all(abs(x-(o[0]+o[2]/2))>sw*0.15 for o in out):
            hh=int(sh*0.28); out.append([int(max(0,x-hh*0.4)),int(top[x]),int(hh*0.8),hh])
        if len(out)>=3: break
    return out
dec=subprocess.Popen([FF,'-v','error','-i','src.mp4','-vf',f'scale={sw}:{sh}','-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE)
faces={}; prev=None; motion={}; i=0; last=[]
while True:
    b=dec.stdout.read(sw*sh*3)
    if len(b)<sw*sh*3: break
    bgr=np.frombuffer(b,np.uint8).reshape(sh,sw,3); g=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
    if i%step==0:
        if HAAR: fs=[list(map(int,f)) for f in casc.detectMultiScale(g,1.1,5,minSize=(sh//10,sh//10))]
        else: fs=heads_seg(bgr) if i%(step*5)==0 else last
        last=fs; faces[i]=fs
        if prev is not None:
            d=cv2.absdiff(g,prev).astype(np.float32); motion[i]=[float(d[y+int(h*.62):y+h,x+int(w*.2):x+int(w*.8)].mean()) for x,y,w,h in fs]
        prev=g
    i+=1
# cluster faces into people by x-centre
xs=np.array([(x+w/2)/sw for k in faces for x,y,w,h in faces[k]])
if len(xs)==0: print('no faces found -> centre crop'); mode='center'; people=[0.5]
else:
    srt=np.sort(xs); groups=[[srt[0]]]
    for v in srt[1:]:
        (groups[-1].append(v) if v-groups[-1][-1]<0.12 else groups.append([v]))
    people=sorted(float(np.median(g)) for g in groups if len(g)>=0.25*len(xs))[:3]
    if mode=='center': people=[0.5]
print('people at x =',[round(c,2) for c in people])
def who(f):
    fs=faces.get(f,[]); m=motion.get(f,[0]*len(fs)); act=np.zeros(len(people)); ys=[None]*len(people)
    for (x,y,w,h),mv in zip(fs,m):
        j=int(np.argmin([abs((x+w/2)/sw-c) for c in people])); act[j]=max(act[j],mv); ys[j]=(y+h/2)/sh
    return act,ys
sample=sorted(faces); A=np.array([who(f)[0] for f in sample]) if sample else np.zeros((1,len(people)))
win=max(1,int(0.5*FPS/step)); A=np.array([A[max(0,k-win):k+win].mean(0) for k in range(len(A))])
# speaker per sample with hold
cur=int(np.argmax(A[0])) if len(people)>1 else 0; last=0; track=[]
for k,f in enumerate(sample):
    t=f/FPS; best=int(np.argmax(A[k]))
    if best!=cur and A[k][best]>A[k][cur]*1.25 and t-last>=HOLD: cur=best; last=t
    track.append(cur)
spk=np.interp(np.arange(N),sample,track).round().astype(int) if sample else np.zeros(N,int)
OW,OH=1080,1920
def crop(img,cx,cy,cw,ch):
    x0=int(np.clip(cx-cw/2,0,SW-cw)); y0=int(np.clip(cy-ch/2,0,SH-ch)); return cv2.resize(img[y0:y0+int(ch),x0:x0+int(cw)],None,fx=1,fy=1)
dec=subprocess.Popen([FF,'-v','error','-i','src.mp4','-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE)
enc=subprocess.Popen([FF,'-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{OW}x{OH}','-r','30','-i','-','-i','src.mp4','-map','0:v','-map','1:a','-c:v','libx264','-preset','veryfast','-crf','14','-pix_fmt','yuv420p','-c:a','copy','-shortest','vertical.mp4'],stdin=subprocess.PIPE)
cxs=[c*SW for c in people]; sm=cxs[spk[0]] if mode=='follow' else SW/2; n=0; prev_s=spk[0]
while True:
    b=dec.stdout.read(SW*SH*3)
    if len(b)<SW*SH*3: break
    img=np.frombuffer(b,np.uint8).reshape(SH,SW,3)
    if mode=='stack' and len(people)>=2:
        ch=SH*0.9; cw=ch*OW/(OH/2)
        if cw>SW/len(people)*1.0: cw=SW/len(people)*1.0; ch=cw*(OH/2)/OW
        top=crop(img,cxs[0],SH*0.45,cw,ch); bot=crop(img,cxs[-1],SH*0.45,cw,ch)
        out=np.vstack([cv2.resize(top,(OW,OH//2),interpolation=cv2.INTER_AREA),cv2.resize(bot,(OW,OH//2),interpolation=cv2.INTER_AREA)])
    else:
        ch=SH; cw=ch*OW/OH
        if mode=='follow':
            s=spk[min(n,N-1)]; target=cxs[s]
            sm = target if s!=prev_s else sm+(target-sm)*0.08   # hard cut on speaker change, gentle drift otherwise
            prev_s=s
        cx=sm if mode=='follow' else SW/2
        out=cv2.resize(crop(img,cx,SH/2,cw,ch),(OW,OH),interpolation=cv2.INTER_AREA)
    enc.stdin.write(out.tobytes()); n+=1
enc.stdin.close(); enc.wait()
json.dump({'mode':mode,'people':people,'switches':int((np.diff(spk)!=0).sum())},open('reframe.json','w'))
print('vertical.mp4 written',mode,'people',len(people),'speaker switches',int((np.diff(spk)!=0).sum()))
