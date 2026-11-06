"""Build caption chunks from a simple text file (subs.txt) that Claude writes after reading the transcript.
Format: one chunk per line, words as  <time> <word>  separated by ' ; '. Flags before a word:
  ^ = the big word of the chunk   * = accent colour   ~ = italic serif (English words)
example line:   3.16 edit ; 3.46 ചെയ്തത് ; 3.60 ^*~Claude ; 3.92 ആണ്
usage: python3 subs.py subs.txt  -> subs.json (times are OUTPUT times, i.e. after cuts)"""
import json, re, sys, os
os.chdir((os.environ.get('REEL_HOME') or os.getcwd()))
DUR=json.load(open('edit.json'))['dur']; chunks=[]
for line in open(sys.argv[1],encoding='utf-8'):
    line=line.strip()
    if not line or line.startswith('#'): continue
    ws=[]
    for item in line.split(';'):
        item=item.strip()
        if not item: continue
        t,w=item.split(' ',1); fl=re.match(r'^[\^\*~]*',w).group(0); w=w[len(fl):]
        ws.append({'t':float(t),'x':w,'big':'^' in fl,'a':'*' in fl,'serif':'~' in fl})
    chunks.append(ws)
out=[]
for k,c in enumerate(chunks):
    s=c[0]['t']-0.06; nxt=chunks[k+1][0]['t']-0.06 if k+1<len(chunks) else DUR
    e=DUR if k+1==len(chunks) else min(nxt,max(c[-1]['t']+0.85,s+0.6))
    out.append({'s':round(s,6),'e':round(e,6),'w':c})
json.dump(out,open('subs.json','w'),ensure_ascii=False); print(len(out),'caption chunks')
for o in out: print(f"{o['s']:6.2f}-{o['e']:6.2f}  "+' '.join(('^' if x['big'] else '')+x['x'] for x in o['w']))
