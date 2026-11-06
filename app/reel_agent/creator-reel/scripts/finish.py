"""Mix voice + SFX (+ optional music) to Instagram loudness (-14 LUFS), write a master and a <30 MB file for chat/phone,
make check images.
usage: python3 finish.py <name> [--no-sfx]   (needs base_ov.mp4, voice_cut.wav; optional sfx.wav, music.wav)
writes out/<name>-master.mp4 and out/<name>.mp4 inside the job folder (or $REEL_OUT)
Speed: the video stream is never re-encoded when it already fits the size limit (it is copied); otherwise one fast pass."""
import sys, os, re, subprocess, json
sys.path.insert(0,os.path.dirname(__file__)); from envlib import ff, FF, probe
os.chdir((os.environ.get('REEL_HOME') or os.getcwd())); name=sys.argv[1]
OUT=os.environ.get('REEL_OUT') or os.path.join(os.getcwd(),'out'); os.makedirs(OUT,exist_ok=True)
def lufs(f):
    e=subprocess.run([FF,'-hide_banner','-i',f,'-af','loudnorm=print_format=summary','-f','null','-'],capture_output=True).stderr.decode()
    i=re.search(r'Input Integrated:\s*(-?\d+\.\d+|-inf)',e); p=re.search(r'Input True Peak:\s*([+-]?\d+\.\d+|-inf)',e)
    val=lambda m: -99.0 if not m or 'inf' in m.group(1) else float(m.group(1))
    return val(i), val(p)
dur=probe('base_ov.mp4')['dur']
ff('-i','voice_cut.wav','-af','highpass=f=70,acompressor=threshold=-24dB:ratio=2.2:attack=8:release=140:makeup=2','-ar','48000','-c:a','pcm_f32le','v1.wav')
I,_=lufs('v1.wav'); has_voice=I>-60
if has_voice: ff('-i','v1.wav','-af',f'volume={-14-I+0.2:.2f}dB,alimiter=limit=0.82:attack=4:release=60:level=disabled','-ar','48000','-c:a','pcm_f32le','voice_proc.wav')
else: ff('-i','v1.wav','-ar','48000','-c:a','pcm_f32le','voice_proc.wav')
inputs=['-i','voice_proc.wav']; chain=[]; mixin=['[0:a]']
if '--no-sfx' not in sys.argv and os.path.exists('sfx.wav'):
    inputs+=['-i','sfx.wav']; chain.append(f'[{len(inputs)//2-1}:a]highpass=f=40,volume=4dB[s]'); mixin.append('[s]')
if os.path.exists('music.wav'):
    mcfg=json.load(open('music.json')) if os.path.exists('music.json') else {}
    vol=float(mcfg.get('db',-17 if has_voice else -12))
    inputs+=['-stream_loop','-1','-i','music.wav']; mi=len([x for x in inputs if x=='-i'])-1
    fade=f'afade=t=in:d=0.6,afade=t=out:st={max(0,dur-1.2):.2f}:d=1.2'
    if has_voice:   # duck the music under the voice
        chain.append(f'[{mi}:a]atrim=0:{dur:.3f},volume={vol}dB,{fade}[m0];[0:a]asplit=2[v0][vk];[m0][vk]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350[m]')
        mixin[0]='[v0]'
    else:
        chain.append(f'[{mi}:a]atrim=0:{dur:.3f},volume={vol}dB,{fade}[m]')
    mixin.append('[m]')
if len(mixin)==1: ff('-i','voice_proc.wav','-t',f'{dur:.3f}','-c:a','pcm_s16le','mix.wav')
else:
    fc=';'.join(chain+[''.join(mixin)+f'amix=inputs={len(mixin)}:normalize=0:duration=first,alimiter=limit=0.80:attack=3:release=50:level=disabled[a]'])
    ff(*inputs,'-filter_complex',fc,'-map','[a]','-t',f'{dur:.3f}','-ar','48000','-c:a','pcm_s16le','mix.wav')
if not has_voice and os.path.exists('music.wav'):            # music-only reels: bring the whole mix to -14 LUFS
    I2,_=lufs('mix.wav')
    if I2>-60: ff('-i','mix.wav','-af',f'volume={-14-I2:.2f}dB,alimiter=limit=0.85:level=disabled','-c:a','pcm_s16le','mix2.wav'); os.replace('mix2.wav','mix.wav')
print('mix loudness (LUFS, dBTP):',lufs('mix.wav'))
ff('-i','base_ov.mp4','-i','mix.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','256k','-movflags','+faststart','-shortest',f'{OUT}/{name}-master.mp4')
limit=27.5e6
if os.path.getsize('base_ov.mp4')+192000/8*dur<=limit:          # already small enough: same picture, no re-encode
    ff('-i','base_ov.mp4','-i','mix.wav','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',f'{OUT}/{name}.mp4')
else:
    kb=min(int(27*8000/dur-220),9000)
    ff('-i','base_ov.mp4','-i','mix.wav','-map','0:v','-map','1:a','-c:v','libx264','-preset',os.environ.get('REEL_SMALL_PRESET','veryfast'),
       '-crf','19','-maxrate',f'{kb}k','-bufsize',f'{kb*2}k','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',f'{OUT}/{name}.mp4')
ff('-i',f'{OUT}/{name}.mp4','-vf','fps=1,scale=216:384,tile=9x5','-frames:v','1','final_sheet.jpg')
ff('-ss','0','-i',f'{OUT}/{name}.mp4','-frames:v','1','first_frame.jpg')
print('files:',f'{OUT}/{name}.mp4',round(os.path.getsize(f'{OUT}/{name}.mp4')/1e6,1),'MB |',f'{OUT}/{name}-master.mp4',round(os.path.getsize(f'{OUT}/{name}-master.mp4')/1e6,1),'MB')
print('check: final_sheet.jpg (1 frame per second) and first_frame.jpg (the cover)')
