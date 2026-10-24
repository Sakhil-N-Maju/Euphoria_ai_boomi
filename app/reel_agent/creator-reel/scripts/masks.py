"""Person cut-out masks for 'text behind the head' and subject pop. Optional (skips if the model is missing).
usage: python3 masks.py [t0 t1 ...]   output-time ranges to process (default: whole edit). writes ~/edit/masks/<srcframe>.png"""
import json, os, sys, subprocess, numpy as np, cv2, time
sys.path.insert(0,os.path.dirname(__file__)); from envlib import ENV, FF
import onnxruntime as ort
W=(os.environ.get('REEL_HOME') or os.getcwd()); os.chdir(W)
mp=os.path.join(ENV.get('models',W+'/models'),'seg','u2net_human_seg.onnx')
if not os.path.exists(mp): sys.exit('no cut-out model; skip text-behind-head effects')
o=ort.SessionOptions(); o.intra_op_num_threads=2; S=ort.InferenceSession(mp,o,providers=['CPUExecutionProvider'])
E=json.load(open('edit.json')); FPS=30; N=int(round(E['dur']*FPS)); src=json.load(open('src.json'))
rng=[float(x) for x in sys.argv[1:]] or [0,E['dur']]
def src_t(n):
    t=n/FPS
    for k,s in enumerate(E['segs']):
        if s['out0']-1e-6<=t<s['out1']-1e-6 or k==len(E['segs'])-1: return s['src0']+(t-s['out0'])
need=set()
for a,b in zip(rng[::2],rng[1::2]):
    for n in range(int(a*FPS),min(N,int(b*FPS)+1)): need.add(int(round(src_t(n)*FPS)))
os.makedirs('masks',exist_ok=True); h=540 if src['w']>=src['h'] else 960; w=int(src['w']*h/src['h'])//2*2
dec=subprocess.Popen([FF,'-v','error','-i','src.mp4','-vf',f'scale={w}:{h}','-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE)
fs=w*h*3; i=0; done=0; t0=time.time()
while True:
    b=dec.stdout.read(fs)
    if len(b)<fs: break
    if i in need and not os.path.exists(f'masks/{i:05d}.png'):
        img=np.frombuffer(b,np.uint8).reshape(h,w,3)
        x=cv2.resize(cv2.cvtColor(img,cv2.COLOR_BGR2RGB),(320,320),interpolation=cv2.INTER_AREA).astype(np.float32); x/=max(x.max(),1e-6)
        x=(x-np.array([0.485,0.456,0.406]))/np.array([0.229,0.224,0.225])
        m=S.run(None,{S.get_inputs()[0].name:x.transpose(2,0,1)[None].astype(np.float32)})[0][0,0]
        m=(m-m.min())/(m.max()-m.min()+1e-6); cv2.imwrite(f'masks/{i:05d}.png',(cv2.resize(m,(w,h))*255).astype(np.uint8)); done+=1
        if done%50==0: print(done,len(need),round(time.time()-t0),'s',flush=True)
    i+=1
print('masks done',done)
