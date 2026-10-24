"""Shared helpers: paths from ~/edit/env.json, ffmpeg runner, probe without ffprobe."""
import json, os, re, subprocess
HOME=os.environ.get('REEL_HOME') or os.getcwd()
ENV=json.load(open(os.path.join(HOME,'env.json')))
FF=ENV['ffmpeg']
def ff(*args, check=True, capture=False):
    cmd=[FF,'-v','error','-y',*map(str,args)]
    r=subprocess.run(cmd,capture_output=True)
    if check and r.returncode: raise RuntimeError(r.stderr.decode()[-1500:])
    return r
def probe(path):
    """width, height (as displayed, rotation applied), fps, duration, has_audio"""
    e=subprocess.run([FF,'-hide_banner','-i',path],capture_output=True).stderr.decode(errors='ignore')
    m=re.search(r'Video:.*?(\d{2,5})x(\d{2,5})',e); w,h=int(m.group(1)),int(m.group(2))
    rot=re.search(r'rotation of (-?\d+(?:\.\d+)?) degrees',e) or re.search(r'rotate\s*:\s*(-?\d+)',e)
    if rot and abs(float(rot.group(1)))%180==90: w,h=h,w
    fps=re.search(r'(\d+(?:\.\d+)?) fps',e); d=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',e)
    dur=int(d.group(1))*3600+int(d.group(2))*60+float(d.group(3))
    return {'w':w,'h':h,'fps':float(fps.group(1)) if fps else 30.0,'dur':dur,'audio':'Audio:' in e}
def chrome_launch(p):
    if ENV['chrome'] in ('playwright',''): return p.chromium.launch(args=['--allow-file-access-from-files','--force-color-profile=srgb'])
    return p.chromium.launch(executable_path=ENV['chrome'],args=ENV['chrome_args']+['--allow-file-access-from-files','--force-color-profile=srgb'])
