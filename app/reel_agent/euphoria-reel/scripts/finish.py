"""Mix voice + SFX to Instagram loudness (-14 LUFS), encode a master and a <30 MB file for chat/phone, make check images.
usage: python3 finish.py <name> [--no-sfx]   (needs ~/edit/base_ov.mp4, voice_cut.wav, sfx.wav)
writes out/<name>-master.mp4 and out/<name>.mp4 inside the job folder (or $REEL_OUT)"""
import sys, os, re, subprocess, json
sys.path.insert(0,os.path.dirname(__file__)); from envlib import ff, FF, probe
os.chdir((os.environ.get('REEL_HOME') or os.getcwd())); name=sys.argv[1]
OUT=os.environ.get('REEL_OUT') or os.path.join(os.getcwd(),'out'); os.makedirs(OUT,exist_ok=True)
def lufs(f):
    e=subprocess.run([FF,'-hide_banner','-i',f,'-af','loudnorm=print_format=summary','-f','null','-'],capture_output=True).stderr.decode()
    return float(re.search(r'Input Integrated:\s*(-?\d+\.\d+)',e).group(1)), float(re.search(r'Input True Peak:\s*([+-]?\d+\.\d+)',e).group(1))
ff('-i','voice_cut.wav','-af','highpass=f=70,acompressor=threshold=-24dB:ratio=2.2:attack=8:release=140:makeup=2','-ar','48000','-c:a','pcm_f32le','v1.wav')
I,_=lufs('v1.wav')
ff('-i','v1.wav','-af',f'volume={-14-I+0.2:.2f}dB,alimiter=limit=0.82:attack=4:release=60:level=disabled','-ar','48000','-c:a','pcm_f32le','voice_proc.wav')
if '--no-sfx' in sys.argv or not os.path.exists('sfx.wav'): ff('-i','voice_proc.wav','-c:a','pcm_s16le','mix.wav')
else: ff('-i','voice_proc.wav','-i','sfx.wav','-filter_complex','[1:a]highpass=f=40,volume=4dB[s];[0:a][s]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.80:attack=3:release=50:level=disabled[a]','-map','[a]','-ar','48000','-c:a','pcm_s16le','mix.wav')
print('mix loudness (LUFS, dBTP):',lufs('mix.wav'))
ff('-i','base_ov.mp4','-i','mix.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','256k','-movflags','+faststart','-shortest',f'{OUT}/{name}-master.mp4')
dur=probe('base_ov.mp4')['dur']; kb=int(27*8000/dur-220); kb=min(kb,9000)
ff('-i','base_ov.mp4','-c:v','libx264','-preset','slow','-b:v',f'{kb}k','-maxrate',f'{int(kb*1.3)}k','-bufsize',f'{kb*2}k','-pass','1','-passlogfile','p2','-an','-f','null',os.devnull)
ff('-i','base_ov.mp4','-i','mix.wav','-map','0:v','-map','1:a','-c:v','libx264','-preset','slow','-b:v',f'{kb}k','-maxrate',f'{int(kb*1.3)}k','-bufsize',f'{kb*2}k','-pass','2','-passlogfile','p2','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',f'{OUT}/{name}.mp4')
ff('-i',f'{OUT}/{name}.mp4','-vf','fps=1,scale=216:384,tile=9x5','-frames:v','1','final_sheet.jpg')
ff('-ss','0','-i',f'{OUT}/{name}.mp4','-frames:v','1','first_frame.jpg')
print('files:',f'{OUT}/{name}.mp4',round(os.path.getsize(f'{OUT}/{name}.mp4')/1e6,1),'MB |',f'{OUT}/{name}-master.mp4',round(os.path.getsize(f'{OUT}/{name}-master.mp4')/1e6,1),'MB')
print('check: final_sheet.jpg (1 frame per second) and first_frame.jpg (the cover)')
