"""python3 cuts.py env <t0> <t1> [...]   loudness strip, 10 ms per character ('.'/' ' = silence)
   python3 cuts.py apply                 keep.json [[src0,src1],...] -> edit.json, voice_cut.wav, voice_cut16.wav"""
import json, sys, os, numpy as np, soundfile as sf
sys.path.insert(0,os.path.dirname(__file__)); from envlib import ff
os.chdir((os.environ.get('REEL_HOME') or os.getcwd()))
if sys.argv[1]=='env':
    a,sr=sf.read('audio16k.wav'); hop=sr//100
    db=20*np.log10(np.array([np.sqrt(np.mean(a[i:i+hop]**2)) for i in range(0,len(a)-hop,hop)])+1e-9)
    v=sys.argv[2:]
    for t0,t1 in zip(map(float,v[::2]),map(float,v[1::2])):
        print(f"{t0:6.2f} |"+''.join(' .:-=+*#%@'[min(9,max(0,int((db[i]+55)/4)))] for i in range(int(t0*100),min(len(db),int(t1*100))))+f"| {t1:.2f}")
else:
    FPS=30; K=[(round(a*FPS)/FPS,round(b*FPS)/FPS) for a,b in json.load(open('keep.json'))]
    segs=[];o=0
    for a,b in K: segs.append({'src0':a,'src1':b,'out0':o,'out1':o+b-a}); o+=b-a
    json.dump({'segs':segs,'dur':o},open('edit.json','w'),indent=1)
    ff('-i','src.mp4','-vn','-ac','2','-ar','48000','audio48.wav')
    a,sr=sf.read('audio48.wav'); xf=int(0.012*sr); f=np.linspace(0,1,xf)[:,None]; out=[]
    for s in segs:
        x=a[int(round(s['src0']*sr)):int(round(s['src1']*sr))].copy(); x[:xf]*=f; x[-xf:]*=f[::-1]; out.append(x)
    sf.write('voice_cut.wav',np.concatenate(out),sr); ff('-i','voice_cut.wav','-ac','1','-ar','16000','voice_cut16.wav')
    print('output duration',round(o,2),'s,',len(segs),'segments')
