"""Step 1: normalise the upload. Upright, constant 30 fps, H.264, vertical-ready, + 16k mono audio.
usage: python3 prep.py <input video> [--max 1440]
writes ~/edit/src.mp4, ~/edit/audio16k.wav, ~/edit/contact.jpg, prints size/fps/duration"""
import sys, os, json
sys.path.insert(0,os.path.dirname(__file__)); from envlib import ff, probe
inp=sys.argv[1]; mx=int(sys.argv[sys.argv.index('--max')+1]) if '--max' in sys.argv else 1440
W=(os.environ.get('REEL_HOME') or os.getcwd()); os.chdir(W)
p=probe(inp); print('input',p)
sc=min(1.0,mx/min(p['w'],p['h']))
w=int(p['w']*sc)//2*2; h=int(p['h']*sc)//2*2
ff('-i',inp,'-vf',f'scale={w}:{h}:flags=lanczos,fps=30,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','14','-c:a','aac','-b:a','256k','-ar','48000','src.mp4')
ff('-i','src.mp4','-vn','-ac','1','-ar','16000','audio16k.wav')
ff('-i','src.mp4','-vf','fps=1/2,scale=200:-1,tile=8x4','-frames:v','1','contact.jpg')
q=probe('src.mp4'); json.dump(q,open('src.json','w')); print('normalised',q)
