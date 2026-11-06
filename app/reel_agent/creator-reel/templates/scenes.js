/* ===== SCENE LIBRARY (faceless styles) =====================================================================
   Hand-built scene types modelled on the reference reels in assets/style/no talking head:
     devices  : phone, code, timeline, graph, glowword (card), commentcta        (dark "device" explainers)
     story    : figures, tags, speech, icons                                    (stick-figure stories)
     editorial: notepad, bigtype (card), magnify, polaroids                     (paper + objects + big type)
     presenter: window, phone + a cartoon host who talks along (PLAN.host)      (host + app windows)
   Every draw(t) depends only on times relative to the beat (shift-proof for the render cache).
   Scenes sit in #scenes (unscaled), inside a 1080x1000 box at --sceneY (each look sets it). */
(function(){
const css=`
#scenes{position:absolute;inset:0}
.scn{position:absolute;left:0;top:var(--sceneY,360px);width:1080px;height:1000px;transform-origin:540px 0;transform:scale(var(--sceneS,1))}
.dev{position:absolute;border-radius:62px;background:linear-gradient(145deg,#3a3a40,#121214 40%,#2a2a2e);padding:14px;box-shadow:0 60px 120px rgba(0,0,0,.6),inset 0 0 0 2px rgba(255,255,255,.08)}
.dev .scr{position:relative;width:100%;height:100%;border-radius:50px;overflow:hidden;background:var(--scr,#0B0B0D);color:var(--scrtxt,#fff)}
.dev .isl{position:absolute;left:50%;top:16px;width:120px;height:34px;margin-left:-60px;border-radius:20px;background:#000;z-index:3}
.dev .gloss{position:absolute;inset:0;border-radius:50px;background:linear-gradient(115deg,rgba(255,255,255,.14),rgba(255,255,255,0) 38%);pointer-events:none;z-index:4}
.sb{display:flex;justify-content:space-between;padding:22px 34px 0;font:600 22px IT}
.glass2{background:var(--gpanel,linear-gradient(180deg,rgba(40,40,46,.85),rgba(16,16,20,.92)));border:1.5px solid var(--gborder,rgba(255,255,255,.12));border-radius:30px;box-shadow:0 40px 90px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.08)}
.chip{display:inline-flex;align-items:center;gap:10px;padding:8px 18px;border-radius:30px;font:600 24px IT;background:#fff;color:#111}
.chip.acc{background:rgba(var(--accrgb),.16);color:var(--acc);border:1.5px solid rgba(var(--accrgb),.5)}
.mono2{font:500 22px JB;letter-spacing:.14em;text-transform:uppercase;opacity:.6}
.neon{stroke:currentColor;fill:none;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 8px currentColor)}
.otag{display:flex;align-items:center;justify-content:center;text-align:center;padding:0 22px;height:92px;border-radius:16px;border:3px solid var(--c);color:var(--c);font:800 32px IT,LOC;letter-spacing:.04em;text-transform:uppercase;box-shadow:0 0 26px rgba(var(--crgb),.35),inset 0 0 18px rgba(var(--crgb),.12);background:rgba(8,14,26,.6)}
.paper{background:#F8F6F0;box-shadow:0 30px 60px rgba(0,0,0,.18),0 2px 6px rgba(0,0,0,.08)}
.hand{font:italic 400 64px/1.2 IS,LOC;color:#1B1B1B}
.cond{font:800 190px/0.86 IT,LOC;letter-spacing:-0.06em;text-transform:uppercase;transform:scaleY(1.32);transform-origin:center bottom;display:inline-block}
.win{position:absolute;background:#fff;border-radius:26px;box-shadow:0 40px 80px rgba(0,0,0,.22),0 0 0 1.5px rgba(0,0,0,.06);overflow:hidden;color:#141414}
.win .tb{height:58px;display:flex;align-items:center;gap:12px;padding:0 24px;background:#F3F3F5;border-bottom:1.5px solid #E6E6EA;font:500 22px JB;color:#888}
.win .tb i{width:16px;height:16px;border-radius:50%;display:inline-block}
.badge2{position:absolute;width:86px;height:86px;border-radius:20px;background:#141414;color:#fff;display:grid;place-items:center;font:800 52px IT;box-shadow:0 14px 30px rgba(0,0,0,.3)}
#host{position:absolute;left:0;right:0;bottom:0;height:760px;display:none}
`;
const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
const sc=document.createElement('div');sc.id='scenes';$('stage').insertBefore(sc,$('hl'));
const hs=document.createElement('div');hs.id='host';$('stage').insertBefore(hs,$('cap'));

const kk=(b,i)=>(b.k&&b.k[i]!=null)?b.k[i]:b.t0+0.35;
const sin=(t,f)=>Math.sin(t*f);
function sIn(t,b,el,mode){                       // scene entrance / exit
  const e=ent(t,b.t0,0.5),o=1-eo(P(t,b.t1-0.25,0.25)),s=eb(P(t,b.t0,0.55),1.3);
  setT(el.firstElementChild||el,C(P(t,b.t0,0.25))*o,`scale(var(--sceneS,1)) translateY(${(1-e)*70}px) scale(${0.88+0.12*s}) rotate(${(1-e)*(mode==='tilt'?-4:-1.5)}deg)`,(1-e)*8)}
const items=b=>(b.items||[]).slice(0,6);
const hexrgb=h=>{h=String(h||'#ffffff').replace('#','');if(h.length===3)h=h.split('').map(x=>x+x).join('');const n=parseInt(h,16);return `${(n>>16)&255},${(n>>8)&255},${n&255}`};

/* ---------- line icons (24x24, stroke) ---------- */
const ICON={check:'M5 12.5l4.5 4.5L19 7.5',x:'M6 6l12 12M18 6L6 18',search:'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.5 15.5L20 20',
 bulb:'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z',chart:'M4 20V10M10 20V4M16 20v-7M22 20H2',
 clock:'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',money:'M12 3v18M16.5 7.5c-1-1.3-2.7-2-4.5-2-2.5 0-4.5 1.3-4.5 3.2 0 4.3 9 2.3 9 6.6 0 1.9-2 3.2-4.5 3.2-1.9 0-3.6-.7-4.6-2',
 user:'M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM4 21c0-4.4 3.6-7 8-7s8 2.6 8 7',users:'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21c0-4 3.1-6.5 7-6.5s7 2.5 7 6.5M16 3.5a4 4 0 0 1 0 7.5M18 14.6c2.4.8 4 2.9 4 6.4',
 chat:'M4 5h16v11H9l-5 4z',lock:'M6 11h12v10H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11',star:'M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z',
 bolt:'M13 2L4 14h7l-1 8 9-12h-7z',doc:'M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7',folder:'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
 globe:'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 2.7 3.7 5.7 3.7 9s-1.2 6.3-3.7 9c-2.5-2.7-3.7-5.7-3.7-9S9.5 5.7 12 3z',
 heart:'M12 20s-7.5-4.6-7.5-10A4.5 4.5 0 0 1 12 7a4.5 4.5 0 0 1 7.5 3c0 5.4-7.5 10-7.5 10z',shield:'M12 3l7.5 3v6c0 4.6-3.2 8-7.5 9-4.3-1-7.5-4.4-7.5-9V6z',
 target:'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01',rocket:'M5 19c1-3 2.5-4.5 4-5M14.5 3.5c3 0 6 3 6 6 0 3.5-4.5 8-8.5 9.5L9 15.5C10.5 11.5 11 3.5 14.5 3.5zM15 9.5h.01',
 cart:'M3 4h2.5l2.4 11h10.6l2-8H7M10 20h.01M17 20h.01',mail:'M3 6h18v12H3zM3 7l9 7 9-7',phone:'M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 19h2',
 link:'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',play:'M7 4l13 8-13 8z',code:'M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16',
 brain:'M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3 3 3 0 0 0 3-3V7a3 3 0 0 0-3-3zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3 3 3 0 0 1-3-3'};
const icon=(name,size,color,sw)=>`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color||'currentColor'}" stroke-width="${sw||2}" stroke-linecap="round" stroke-linejoin="round"><path d="${ICON[name]||ICON.star}"/></svg>`;
const ICONS=Object.keys(ICON);
const pickIcon=s=>{s=String(s||'').toLowerCase();for(const k of ICONS)if(s.includes(k))return k;
  const m={answer:'chat',ask:'chat',question:'chat',search:'search',find:'search',data:'chart',grow:'chart',time:'clock',fast:'bolt',speed:'bolt',price:'money',pay:'money',sell:'money',
   team:'users',people:'users',safe:'shield',secure:'lock',idea:'bulb',goal:'target',launch:'rocket',file:'doc',docs:'doc',document:'doc',web:'globe',love:'heart',write:'doc',send:'mail',model:'brain',ai:'brain',video:'play',app:'phone'};
  for(const k in m)if(s.includes(k))return m[k];return 'star'};

/* ---------- stick figures + props (story) ---------- */
function figure(x,y,pose,col,shirt){         // y = feet; ~200 tall
  const sh=y-128,hip=y-62,hd=y-176;let arms;
  if(pose==='wave'||pose==='cheer')arms=`<path data-arm d="M${x} ${sh} L${x+44} ${sh-60} L${x+56} ${sh-112}"/>`+(pose==='cheer'?`<path d="M${x} ${sh} L${x-44} ${sh-60} L${x-56} ${sh-112}"/>`:`<path d="M${x} ${sh} L${x-30} ${sh+44} L${x-36} ${hip}"/>`);
  else if(pose==='point')arms=`<path d="M${x} ${sh} L${x+52} ${sh-6} L${x+96} ${sh-14}"/><path d="M${x} ${sh} L${x-30} ${sh+44} L${x-36} ${hip}"/>`;
  else if(pose==='sad')arms=`<path d="M${x} ${sh} L${x+22} ${sh+52} L${x+24} ${hip+6}"/><path d="M${x} ${sh} L${x-22} ${sh+52} L${x-24} ${hip+6}"/>`;
  else arms=`<path d="M${x} ${sh} L${x+30} ${sh+44} L${x+36} ${hip}"/><path d="M${x} ${sh} L${x-30} ${sh+44} L${x-36} ${hip}"/>`;
  const legs=pose==='walk'?`<path d="M${x} ${hip} L${x+34} ${y}"/><path d="M${x} ${hip} L${x-30} ${y}"/>`:`<path d="M${x} ${hip} L${x+22} ${y}"/><path d="M${x} ${hip} L${x-22} ${y}"/>`;
  const tilt=pose==='sad'?`transform="rotate(14 ${x} ${hd})"`:'';
  return `<g class="neon" style="color:${col}" stroke-width="9"><circle cx="${x}" cy="${hd}" r="24" ${tilt}/><path d="M${x} ${hd+24} L${x} ${hip}"/>${arms}${legs}</g>`+
    (shirt?`<path class="neon" style="color:${shirt}" stroke-width="13" d="M${x} ${sh-6} L${x} ${hip-8}"/>`:'')}
const PROP={car:(x,y)=>`<path d="M${x-130} ${y-26}h260v-40l-46-12-42-44h-104l-48 44-20 12z"/><circle cx="${x-76}" cy="${y-22}" r="24"/><circle cx="${x+76}" cy="${y-22}" r="24"/><path d="M${x-60} ${y-118}l-30 40h82v-40zM${x+4} ${y-118}v40h78l-30-40z"/>`,
 laptop:(x,y)=>`<path d="M${x-100} ${y-40}v-130h200v130zM${x-140} ${y-40}h280l-24 36h-232z"/>`,phone:(x,y)=>`<rect x="${x-46}" y="${y-190}" width="92" height="180" rx="16"/><path d="M${x-12} ${y-28}h24"/>`,
 box:(x,y)=>`<path d="M${x-90} ${y-150}h180v146h-180zM${x-90} ${y-150}l30-36h120l30 36M${x-20} ${y-150}v40h40v-40"/>`,doc:(x,y)=>`<path d="M${x-70} ${y-190}h100l40 40v146h-140zM${x+30} ${y-190}v40h40M${x-40} ${y-110}h80M${x-40} ${y-70}h80"/>`,
 house:(x,y)=>`<path d="M${x-100} ${y-6}v-110l100-80 100 80v110zM${x-26} ${y-6}v-60h52v60"/>`,money:(x,y)=>`<rect x="${x-110}" y="${y-110}" width="220" height="104" rx="12"/><circle cx="${x}" cy="${y-58}" r="26"/>`,
 chart:(x,y)=>`<path d="M${x-110} ${y-6}h220M${x-80} ${y-6}v-70M${x-20} ${y-6}v-120M${x+40} ${y-6}v-90M${x+100} ${y-6}v-160"/>`,
 desk:(x,y)=>`<path d="M${x-150} ${y-90}h300M${x-130} ${y-90}v84M${x+130} ${y-90}v84M${x-60} ${y-90}v-70h120v70"/>`};
const mark=(x,y,kind)=>kind==='check'?`<path class="neon" style="color:#5EE6B0" stroke-width="10" d="M${x-24} ${y} l18 18 l34 -38"/>`:kind==='x'?`<path class="neon" style="color:#FF5A4D" stroke-width="10" d="M${x-22} ${y-22} l44 44 M${x+22} ${y-22} l-44 44"/>`:'';

/* ---------- the cartoon host (presenter) — an original character ---------- */
function hostSVG(acc){return `<svg viewBox="0 0 600 760" width="600" height="760" style="position:absolute;left:240px;bottom:-20px;overflow:visible">
 <g stroke="#1E1E22" stroke-width="7" stroke-linejoin="round" stroke-linecap="round">
  <path data-h="body" d="M110 760 C120 600 180 520 300 520 C420 520 480 600 490 760Z" fill="${acc}"/>
  <path d="M250 520 L300 590 L350 520" fill="#fff"/>
  <g data-h="armL"><path d="M150 610 C110 660 100 700 120 760" fill="none" stroke-width="44" stroke="${acc}"/><path d="M150 610 C110 660 100 700 120 760" fill="none" stroke-width="7"/></g>
  <g data-h="armR" style="transform-origin:450px 610px"><path d="M450 610 C500 660 510 700 490 760" fill="none" stroke-width="44" stroke="${acc}"/><circle cx="490" cy="760" r="30" fill="#F4C9A4"/></g>
  <rect x="268" y="440" width="64" height="90" rx="20" fill="#F4C9A4"/>
  <g data-h="head"><ellipse cx="300" cy="330" rx="140" ry="150" fill="#F4C9A4"/>
   <path d="M164 300 C150 170 250 130 320 150 C400 140 460 210 440 300 C420 240 360 222 300 230 C230 236 190 260 164 300Z" fill="#2B2420"/>
   <circle cx="160" cy="345" r="22" fill="#F4C9A4"/><circle cx="440" cy="345" r="22" fill="#F4C9A4"/>
   <g data-h="eyes"><ellipse cx="248" cy="340" rx="14" ry="18" fill="#1E1E22" stroke="none"/><ellipse cx="352" cy="340" rx="14" ry="18" fill="#1E1E22" stroke="none"/></g>
   <path d="M222 300 q26 -14 52 0 M326 300 q26 -14 52 0" fill="none" stroke-width="8"/>
   <ellipse data-h="mouth" cx="300" cy="412" rx="34" ry="22" fill="#7A2A2A"/>
  </g></g></svg>`}
let HOSTEL=null;
window.hostInit=function(){if(!PLAN.host)return;hs.style.display='block';hs.innerHTML=hostSVG(getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#E3342F');
  HOSTEL={mouth:hs.querySelector('[data-h=mouth]'),eyes:hs.querySelector('[data-h=eyes]'),armR:hs.querySelector('[data-h=armR]'),head:hs.querySelector('[data-h=head]')}};
function talkAt(t){const T=PLAN.host&&PLAN.host.talk||[];for(const [a,z] of T){if(t>=a&&t<z+0.02)return [a,z]}return null}
function hostState(t){            // everything the host's picture depends on, relative to its own events
  if(!PLAN.host)return null;const w=talkAt(t);const m=w?0.25+0.75*Math.abs(Math.sin((t-w[0])*17)):0.12;
  const bt=(PLAN.beats||[]).find(b=>b.type!=='cta'&&IN(t,b.t0,b.t1));const cta=(PLAN.beats||[]).find(b=>b.type==='cta'&&IN(t,b.t0,b.t1));
  let arm=0;if(cta)arm=-70+12*Math.sin((t-cta.t0)*7);else if(bt){const u=P(t,bt.t0,0.4)*(1-P(t,bt.t0+1.4,0.4));arm=-58*eo(u)}
  const blink=w&&(Math.round((w[1]-w[0])*120)%5===0)&&(t-w[0])<0.12?1:0;
  return [Math.round(m*20)/20,Math.round(arm),blink,w?Math.round((t-w[0])*120):null,Math.round((bt?Math.sin((t-bt.t0)*1.3):0)*20)/20]}
window.hostDraw=function(t){if(!HOSTEL)return;const s=hostState(t);HOSTEL.mouth.setAttribute('ry',(4+24*s[0]).toFixed(1));
  HOSTEL.eyes.style.transform=s[2]?'scaleY(0.1)':'';HOSTEL.eyes.style.transformOrigin='300px 340px';
  HOSTEL.armR.style.transform=`rotate(${s[1]}deg)`;HOSTEL.head.style.transform=`rotate(${s[4]*2}deg)`;HOSTEL.head.style.transformOrigin='300px 470px'};
window.hostSig=t=>hostState(t);

Object.assign(COMP,{
/* ===== devices ===== */
phone:{full:1,build(b,el){const it=items(b);const mode=b.mode||(it.length?'list':'stats');
  const rows=mode==='chat'?it.map((x,i)=>`<div data-r style="align-self:${i%2?'flex-start':'flex-end'};max-width:78%;padding:14px 20px;border-radius:24px;font:600 26px/1.3 IT,LOC;background:${i%2?'rgba(255,255,255,.1)':'var(--acc)'};color:${i%2?'#fff':'var(--ink)'}">${esc(x.text)}</div>`).join('')
   :it.map((x,i)=>`<div data-r style="display:flex;align-items:center;gap:16px;padding:18px 20px;border-radius:20px;background:rgba(255,255,255,.06);font:600 27px IT,LOC"><span style="width:44px;height:44px;border-radius:12px;background:rgba(var(--accrgb),.18);display:grid;place-items:center;color:var(--acc)">${icon(pickIcon(x.text),26)}</span>${esc(x.text)}</div>`).join('');
  el.innerHTML=`<div class="scn"><div style="position:absolute;left:0;right:0;top:0;height:1000px;perspective:1800px">
   <div data-d class="dev" style="left:330px;top:40px;width:420px;height:870px"><div class="scr"><div class="isl"></div>
    <div class="sb"><span>9:41</span><span>●●● ▮</span></div>
    <div style="padding:46px 30px 0;font:800 40px IT,LOC">${esc(b.title||b.label||'')}</div>
    ${b.value!=null?`<div style="padding:18px 30px 0"><div data-n style="font:800 112px/1 IT;color:var(--acc);letter-spacing:-0.04em">0</div><div style="font:600 28px IT,LOC;opacity:.65;margin-top:8px">${esc(b.text||'')}</div></div>`:''}
    <div style="display:flex;flex-direction:column;gap:14px;padding:30px 24px">${rows}</div></div><div class="gloss"></div></div></div></div>`},
  draw(t,b,el){sIn(t,b,el);const d=el.querySelector('[data-d]');const e=eo(P(t,b.t0,0.9));
   d.style.transform=`rotateY(${-26+16*e+3*Math.sin((t-b.t0)*0.9)}deg) rotateX(${8-4*e}deg) translateY(${Math.sin((t-b.t0)*1.4)*10}px)`;
   const n=el.querySelector('[data-n]');if(n){const u=eo(P(t,kk(b,0),1));n.textContent=fmtN((b.value||0)*u,b)}
   el.querySelectorAll('[data-r]').forEach((r,i)=>{const [s,o]=pop(t,kk(b,i),0.35);setT(r,o,`translateX(${(1-o)*40}px) scale(${s})`)})}},
code:{full:1,build(b,el){const L=(b.lines||b.items||[]).slice(0,7);
  el.innerHTML=`<div class="scn"><div class="glass2" style="position:absolute;left:70px;top:150px;width:940px;padding:0 0 30px">
   <div style="display:flex;align-items:center;gap:12px;padding:22px 28px;border-bottom:1.5px solid rgba(255,255,255,.08)"><i style="width:16px;height:16px;border-radius:50%;background:#FF5F57"></i><i style="width:16px;height:16px;border-radius:50%;background:#FEBC2E"></i><i style="width:16px;height:16px;border-radius:50%;background:#28C840"></i>
    <span style="margin-left:16px;font:500 24px JB;opacity:.7">${esc(b.title||'main.py')}</span><span class="mono2" style="margin-left:auto">${esc(b.label||'')}</span></div>
   ${L.map((x,i)=>`<div data-l style="display:flex;gap:26px;padding:8px 28px;font:500 30px/1.45 JB;${i===(b.highlight??-1)?'background:rgba(var(--accrgb),.14);box-shadow:inset 4px 0 0 var(--acc)':''}"><span style="opacity:.3;width:34px;text-align:right">${i+1}</span><span data-x style="white-space:pre-wrap"></span></div>`).join('')}</div></div>`;
  el._L=L.map(x=>typeof x==='string'?x:(x.text||''))},
  draw(t,b,el){sIn(t,b,el,'tilt');el.querySelectorAll('[data-l]').forEach((r,i)=>{const txt=el._L[i]||'';const k=kk(b,i);const n=Math.max(0,Math.min(txt.length,Math.floor((GQ(t)-GQ(k))/4)));
   const xs=r.querySelector('[data-x]');const vis=[...txt].slice(0,n).join('');xs.innerHTML=esc(vis).replace(/(&quot;[^&]*&quot;|"[^"]*"|'[^']*')/g,'<span style="color:#FF8A65">$1</span>').replace(/\b(def|return|import|for|in|if|const|let|function|await|from)\b/g,'<span style="color:var(--acc)">$1</span>')+(n<txt.length&&n>0?'<span style="background:var(--acc)">&nbsp;</span>':'');
   r.style.opacity=GQ(t)>=GQ(k)-12?1:0})}},
timeline:{full:1,build(b,el){const it=items(b).slice(0,4);
  el.innerHTML=`<div class="scn"><div class="glass2" style="position:absolute;left:60px;top:200px;width:960px;height:560px;overflow:hidden">
   <div style="display:flex;justify-content:space-between;padding:22px 30px;font:500 24px JB;opacity:.75"><span>${esc(b.title||b.label||'timeline')}</span><span>frame <b data-f style="color:var(--acc)">0</b></span></div>
   <div style="position:absolute;left:30px;right:30px;top:80px;height:40px;display:flex;justify-content:space-between;font:500 18px JB;opacity:.4">${Array.from({length:9},(_,i)=>`<span>${i*24}</span>`).join('')}</div>
   ${it.map((x,i)=>`<div style="position:absolute;left:30px;right:30px;top:${150+i*95}px;height:72px;border-radius:14px;background:rgba(255,255,255,.04)"><div data-c style="position:absolute;left:${6+i*16}%;top:8px;height:56px;width:${40-i*4}%;border-radius:12px;background:linear-gradient(90deg,var(--acc),rgba(var(--accrgb),.55));display:flex;align-items:center;padding:0 18px;font:700 24px IT,LOC;color:var(--ink);transform-origin:left center">${esc(x.text)}</div></div>`).join('')}
   <div data-p style="position:absolute;top:70px;bottom:20px;width:3px;background:#fff;box-shadow:0 0 14px #fff"></div></div></div>`},
  draw(t,b,el){sIn(t,b,el);const u=P(t,b.t0+0.3,Math.max(1,b.t1-b.t0-0.6));el.querySelector('[data-p]').style.left=(30+u*900)+'px';el.querySelector('[data-f]').textContent=Math.round(u*192);
   el.querySelectorAll('[data-c]').forEach((c,i)=>{const e=eo(P(t,kk(b,i),0.4));c.style.transform=`scaleX(${e})`;c.style.opacity=e>0?1:0})}},
graph:{full:1,build(b,el){const W=700,H=440,cv=b.curve||'ease-out';
  const f={linear:u=>u,'ease-out':u=>1-Math.pow(1-u,3),'ease-in':u=>u*u*u,spring:u=>1-Math.exp(-6*u)*Math.cos(9*u),rise:u=>(Math.exp(3*u)-1)/(Math.exp(3)-1),drop:u=>1-(1-Math.pow(1-u,3))}[cv]||(u=>u);
  let d='';const pts=[];for(let i=0;i<=60;i++){const u=i/60,v=f(u);const x=80+u*W,y=40+H-v*H*0.86;d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1);if(i%8===0)pts.push([x,y])}
  el.innerHTML=`<div class="scn"><div class="glass2" style="position:absolute;left:110px;top:120px;width:860px;height:640px">
   <div style="position:absolute;left:30px;top:26px;display:flex;gap:12px"><span class="chip">${esc(b.label||'curve')}</span>${b.title?`<span class="chip acc">● ${esc(b.title)}</span>`:''}</div>
   <svg width="860" height="640" style="position:absolute;left:0;top:70px"><path d="M80 40 V${H+40} H${W+80}" stroke="rgba(255,255,255,.25)" stroke-width="2" fill="none"/>
    <path data-c d="${d}" stroke="var(--acc)" stroke-width="7" fill="none" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1" style="filter:drop-shadow(0 0 10px rgba(var(--accrgb),.6))"/>
    ${pts.map(p=>`<circle data-p cx="${p[0]}" cy="${p[1]}" r="9" fill="var(--acc)" opacity="0"/>`).join('')}
    <text x="${W+80}" y="${H+80}" text-anchor="end" style="font:500 20px JB;fill:rgba(255,255,255,.5);letter-spacing:.12em">${esc((b.x_label||'TIME').toUpperCase())} →</text>
    <text x="60" y="40" transform="rotate(-90 60 40)" text-anchor="end" style="font:500 20px JB;fill:rgba(255,255,255,.5);letter-spacing:.12em">${esc((b.y_label||'VALUE').toUpperCase())} →</text></svg>
   ${b.value!=null||b.text?`<div data-v class="chip acc" style="position:absolute;right:30px;top:26px">${esc(b.text||'')} ${b.value!=null?fmtN(b.value,b):''}</div>`:''}</div></div>`;el._n=pts.length},
  draw(t,b,el){sIn(t,b,el);const u=eio(P(t,kk(b,0),1.3));el.querySelector('[data-c]').style.strokeDashoffset=1-u;
   el.querySelectorAll('[data-p]').forEach((p,i)=>p.setAttribute('opacity',u>=i/(el._n-1)?1:0));const v=el.querySelector('[data-v]');if(v){const [s,o]=pop(t,kk(b,0)+1.2,0.4);setT(v,o,`scale(${s})`)}}},
glowword:{card:1,build(b,el){const c=hexrgb(b.color||getComputedStyle(document.documentElement).getPropertyValue('--acc').trim());
  el.innerHTML=`<div class="block" style="padding-bottom:var(--statPad)"><div data-t style="font:800 ${String(b.text||'').length>8?150:220}px/0.95 IT,LOC;letter-spacing:-0.05em;color:rgb(${c});text-shadow:0 1px 0 rgba(${c},.9),0 4px 0 rgba(120,10,10,.9),0 8px 0 rgba(90,8,8,.8),0 12px 0 rgba(60,6,6,.7),0 0 60px rgba(${c},.7),0 0 140px rgba(${c},.45)">${esc(b.text)}</div>${b.sub?`<div data-s style="margin-top:40px;font:800 60px IT,LOC;color:#fff">${esc(b.sub)}</div>`:''}</div>`},
  draw(t,b,el){const e=ent(t,b.t0,0.45),o=1-eo(P(t,b.t1-0.2,0.2));setT(el,e*o,`scale(${1.12-0.12*eb(P(t,b.t0,0.6))}) rotate(${(1-e)*-6}deg)`,(1-e)*14);
   const s=el.querySelector('[data-s]');if(s){const [k,op]=pop(t,kk(b,0)+0.2,0.4);setT(s,op,`scale(${k})`)}}},
commentcta:{full:1,build(b,el){el.innerHTML=`<div class="scn"><div style="position:absolute;left:0;right:0;top:60px;text-align:center"><div style="font:800 76px IT,LOC;color:var(--txt)">${esc(b.label&&b.label!=='COMMENT THE WORD'?b.label:'Comment')}</div>
   <div data-w style="font:800 200px/1 IT,LOC;letter-spacing:-0.05em;color:var(--acc);text-shadow:0 6px 0 rgba(0,0,0,.35),0 0 80px rgba(var(--accrgb),.55)">${esc(b.keyword||'')}</div></div>
   <div class="glass2" style="position:absolute;left:150px;top:420px;width:780px;height:460px"><div style="text-align:center;font:700 28px IT;padding:26px 0;border-bottom:1.5px solid rgba(255,255,255,.08)">Comments</div>
    <div style="position:absolute;left:0;right:0;top:170px;text-align:center;font:700 30px IT;opacity:.8">Be the first to comment</div>
    <div style="position:absolute;left:30px;right:30px;bottom:30px;height:90px;border-radius:45px;background:rgba(127,127,127,.14);display:flex;align-items:center;padding:0 16px 0 34px;gap:14px">
     <span data-x style="flex:1;font:800 38px IT,LOC"></span><span style="width:62px;height:62px;border-radius:50%;background:var(--acc);display:grid;place-items:center">${icon('play',26,'#fff')}</span></div></div></div>`},
  draw(t,b,el){sIn(t,b,el);const kw=b.keyword||'';const n=Math.max(0,Math.min(kw.length,Math.floor((GQ(t)-GQ(kk(b,0)+0.5))/12)));el.querySelector('[data-x]').textContent=kw.slice(0,n)+(n<kw.length?'|':'');
   const [s,o]=pop(t,b.t0+0.15,0.5);setT(el.querySelector('[data-w]'),o,`scale(${s})`)}},
/* ===== story ===== */
figures:{full:1,build(b,el){const side=(v,p)=>v&&typeof v==='object'?v:{label:v||'',pose:b[p+'_pose'],mark:b[p+'_mark']};const L=side(b.left,'left'),R=side(b.right,'right');const c1=L.color||'#EAF2FF',c2=R.color||'#EAF2FF';
  el.innerHTML=`<div class="scn">${b.text?`<div data-h style="position:absolute;left:0;right:0;top:40px;text-align:center;font:800 76px/1.05 IT,LOC;color:var(--acc);text-shadow:0 0 30px rgba(var(--accrgb),.5);letter-spacing:.01em;text-transform:uppercase">${esc(b.text)}</div>`:''}
   <div style="position:absolute;left:150px;top:240px;width:200px;text-align:center" class="mono2" data-l1>${esc(L.label||'')}</div><div style="position:absolute;left:730px;top:240px;width:200px;text-align:center" class="mono2" data-l2>${esc(R.label||'')}</div>
   <svg width="1080" height="1000" style="position:absolute;left:0;top:0;overflow:visible"><path d="M90 700 H990" stroke="rgba(255,255,255,.15)" stroke-width="3"/>
    <g data-f1>${figure(250,700,L.pose||'stand',c1,L.shirt)}</g><g data-f2>${figure(830,700,R.pose||'stand',c2,R.shirt)}</g>
    ${b.prop&&PROP[b.prop]?`<g data-pr class="neon" stroke-width="7" style="color:#9DB6D6">${PROP[b.prop](540,700)}</g>`:''}
    <g data-m1>${mark(250,400,L.mark)}</g><g data-m2>${mark(830,400,R.mark)}</g></svg></div>`},
  draw(t,b,el){sIn(t,b,el);const h=el.querySelector('[data-h]');if(h){const [s,o]=pop(t,b.t0+0.1,0.45);setT(h,o,`scale(${s})`)}
   [['[data-f1]',0.15],['[data-f2]',0.3],['[data-pr]',0.45]].forEach(([q,d])=>{const g=el.querySelector(q);if(g){const e=eo(P(t,b.t0+d,0.5));g.style.opacity=e;g.style.transform=`translateY(${(1-e)*30}px)`}});
   ['[data-m1]','[data-m2]'].forEach(q=>{const g=el.querySelector(q);const [s,o]=pop(t,kk(b,0),0.4);g.style.opacity=o;g.style.transformOrigin='center';g.style.transformBox='fill-box';g.style.transform=`scale(${s})`});
   const a=el.querySelector('[data-arm]');if(a){a.style.transformBox='fill-box';a.style.transformOrigin='0% 100%';a.style.transform=`rotate(${Math.sin((t-b.t0)*7)*10}deg)`}}},
tags:{full:1,build(b,el){const it=items(b);const pal=PLAN.palette||['var(--acc)'];const cols=it.length>3?2:1;
  el.innerHTML=`<div class="scn"><div class="mono2" style="position:absolute;left:0;right:0;top:60px;text-align:center;color:var(--acc);opacity:.9">${esc(b.label||'')}</div>
   <div style="position:absolute;left:${cols===2?80:240}px;right:${cols===2?80:240}px;top:140px;display:grid;grid-template-columns:repeat(${cols},1fr);gap:26px">
   ${it.map((x,i)=>{const c=pal[i%pal.length];return `<div data-g class="otag" style="--c:${c};--crgb:${c.startsWith('#')?hexrgb(c):'var(--accrgb)'};position:relative">${esc(x.text)}${x.strike?`<i data-s style="position:absolute;left:14px;right:14px;top:50%;height:6px;border-radius:3px;background:#FF5A4D;transform-origin:left;transform:scaleX(0);box-shadow:0 0 12px #FF5A4D"></i>`:''}</div>`}).join('')}</div></div>`},
  draw(t,b,el){sIn(t,b,el);el.querySelectorAll('[data-g]').forEach((g,i)=>{const [s,o]=pop(t,kk(b,i),0.35);setT(g,o,`scale(${s})`);const sk=g.querySelector('[data-s]');if(sk)sk.style.transform=`scaleX(${eo(P(t,kk(b,i)+0.6,0.35))})`})}},
speech:{full:1,build(b,el){const L=(b.lines||b.items||[]).slice(0,3);const side=b.who==='left'?'left':'right';const fx=side==='left'?260:820;
  el.innerHTML=`<div class="scn"><svg width="1080" height="1000" style="position:absolute;left:0;top:0;overflow:visible"><path d="M90 840 H990" stroke="rgba(255,255,255,.15)" stroke-width="3"/>${figure(fx,840,b.pose||'stand','#EAF2FF')}${b.other!==false?figure(side==='left'?820:260,840,'stand','#EAF2FF'):''}</svg>
   <div style="position:absolute;${side==='left'?'left:120px':'right:120px'};top:120px;display:flex;flex-direction:column;gap:22px;align-items:${side==='left'?'flex-start':'flex-end'}">
   ${L.map((x,i)=>`<div data-b style="max-width:640px;padding:24px 32px;border-radius:26px;border:3px solid var(--acc);color:#EAF2FF;background:rgba(8,14,26,.75);font:700 38px/1.3 IT,LOC;box-shadow:0 0 30px rgba(var(--accrgb),.3)">${esc(typeof x==='string'?x:x.text)}</div>`).join('')}</div></div>`},
  draw(t,b,el){sIn(t,b,el);el.querySelectorAll('[data-b]').forEach((g,i)=>{const [s,o]=pop(t,kk(b,i),0.35);g.style.transformOrigin=b.who==='left'?'left bottom':'right bottom';setT(g,o,`scale(${s})`)})}},
icons:{full:1,build(b,el){const it=items(b).slice(0,4);const pal=PLAN.palette||['var(--acc)'];
  el.innerHTML=`<div class="scn">${b.label?`<div class="mono2" style="position:absolute;left:0;right:0;top:70px;text-align:center;color:var(--acc)">${esc(b.label)}</div>`:''}
   <div style="position:absolute;left:60px;right:60px;top:200px;display:flex;justify-content:center;gap:34px;flex-wrap:wrap">
   ${it.map((x,i)=>{const c=pal[i%pal.length];return `<div data-g style="width:${it.length>3?210:260}px;display:flex;flex-direction:column;align-items:center;gap:24px"><div style="width:180px;height:180px;border-radius:40px;display:grid;place-items:center;border:3px solid ${c};color:${c};box-shadow:0 0 34px ${c}55,inset 0 0 24px ${c}22">${icon(x.icon&&ICON[x.icon]?x.icon:pickIcon(x.text),92,c,1.8)}</div><div style="font:700 34px/1.2 IT,LOC;text-align:center;color:var(--txt)">${esc(x.text)}</div></div>`}).join('')}</div></div>`},
  draw(t,b,el){sIn(t,b,el);el.querySelectorAll('[data-g]').forEach((g,i)=>{const [s,o]=pop(t,kk(b,i),0.4);setT(g,o,`translateY(${(1-o)*40}px) scale(${s})`)})}},
/* ===== editorial ===== */
notepad:{full:1,build(b,el){const words=String(b.text||'').split(/\s+/).filter(Boolean);const cw=String(b.circle||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
  el.innerHTML=`<div class="scn"><div data-p class="paper" style="position:absolute;left:190px;top:40px;width:700px;height:620px;clip-path:polygon(0 0,100% 0,100% 94%,96% 97%,92% 94%,88% 97%,84% 94%,80% 97%,76% 94%,72% 97%,68% 94%,64% 97%,60% 94%,56% 97%,52% 94%,48% 97%,44% 94%,40% 97%,36% 94%,32% 97%,28% 94%,24% 97%,20% 94%,16% 97%,12% 94%,8% 97%,4% 94%,0 97%);
    background:repeating-linear-gradient(#F8F6F0 0 76px,#C9D7EA 76px 78px);transform:rotate(-3deg)">
    <div style="position:absolute;left:84px;top:0;bottom:0;width:3px;background:#E8A0A0"></div>
    <div style="position:absolute;left:0;right:0;top:-6px;height:40px;display:flex;justify-content:space-around">${Array.from({length:10},()=>`<i style="width:22px;height:22px;border-radius:50%;background:#2A2A2A;margin-top:8px"></i>`).join('')}</div>
    <div class="hand" style="position:absolute;left:120px;right:50px;top:118px;line-height:78px">${words.map(w=>{const n=w.toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');return n&&n===cw?`<span style="position:relative;display:inline-block;font-style:normal;font-weight:700;font-family:IT">${esc(w)}<svg style="position:absolute;left:-26px;top:-12px;overflow:visible" width="1" height="1"><ellipse data-o cx="0" cy="0" rx="10" ry="10" fill="none" stroke="#C8202A" stroke-width="5" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg></span>`:esc(w)}).join(' ')}</div></div>
   ${b.big?`<div data-b style="position:absolute;left:0;right:0;top:700px;text-align:center"><span class="cond" style="color:#8E1515">${esc(b.big)}</span></div>`:''}
   <svg data-pen width="360" height="60" style="position:absolute;left:620px;top:660px;transform:rotate(-28deg)"><rect x="0" y="18" width="300" height="24" rx="12" fill="#1F1F22"/><path d="M300 18 L350 30 L300 42Z" fill="#B8B3A8"/><rect x="40" y="18" width="10" height="24" fill="#C9A227"/></svg></div>`},
  draw(t,b,el){sIn(t,b,el,'tilt');const o=el.querySelector('[data-o]');if(o){const sp=o.closest('span');const w=sp.offsetWidth;
    o.setAttribute('cx',w/2+26);o.setAttribute('cy',51);o.setAttribute('rx',w/2+24);o.setAttribute('ry',42);o.style.strokeDashoffset=1-eio(P(t,kk(b,0),0.5))}
   const g=el.querySelector('[data-b]');if(g){const e=eo(P(t,kk(b,0)+0.5,0.25));setT(g,C(e*3),`scale(${1.6-0.6*e}) rotate(-4deg)`)}
   const pen=el.querySelector('[data-pen]');pen.style.transform=`rotate(-28deg) translateX(${(1-eo(P(t,b.t0+0.2,0.7)))*200}px)`}},
bigtype:{card:1,build(b,el){el.innerHTML=`<div style="position:absolute;inset:0;background:inherit">
   <div style="position:absolute;left:70px;top:520px;width:46px;height:46px;border-left:5px solid #141414;border-top:5px solid #141414" data-c></div><div style="position:absolute;right:70px;top:1180px;width:46px;height:46px;border-right:5px solid #141414;border-bottom:5px solid #141414" data-c></div>
   <div data-t style="position:absolute;left:0;right:0;top:600px;text-align:center"><span class="cond" style="color:#8E1515;font-size:${String(b.text||'').length>9?150:210}px">${esc(b.text)}</span></div>
   <div data-u style="position:absolute;left:150px;right:150px;top:${String(b.text||'').length>9?850:930}px;height:14px;background:#D6262E;transform-origin:left;box-shadow:0 0 24px rgba(214,38,46,.6)"></div>
   ${b.sub?`<div data-s style="position:absolute;left:120px;right:120px;top:1000px;font:500 30px/1.5 JB;color:#3A3A3A"><b style="font-family:IT;font-size:34px;color:#141414">${esc(b.text)} —</b> ${esc(b.sub)}</div>`:''}</div>`},
  draw(t,b,el){const e=ent(t,b.t0,0.4),o=1-eo(P(t,b.t1-0.2,0.2));setT(el,e*o,'',(1-e)*10);const tt=el.querySelector('[data-t]');const s=eb(P(t,b.t0,0.5),1.4);tt.style.transform=`scale(${1.3-0.3*s})`;
   el.querySelector('[data-u]').style.transform=`scaleX(${eo(P(t,kk(b,0),0.4))})`;const sb=el.querySelector('[data-s]');if(sb){const u=ent(t,kk(b,0)+0.3,0.5);setT(sb,u,`translateY(${(1-u)*20}px)`)}
   el.querySelectorAll('[data-c]').forEach((c,i)=>{const u=eo(P(t,b.t0+0.2,0.5));c.style.transform=`translate(${(1-u)*(i?40:-40)}px,${(1-u)*(i?40:-40)}px)`;c.style.opacity=u})}},
magnify:{full:1,build(b,el){const R=String(b.reveal||'').trim();
  el.innerHTML=`<div class="scn"><div style="position:absolute;left:0;right:0;top:20px;text-align:center"><span class="cond" style="color:#8E1515;font-size:${String(b.text||'').length>9?120:160}px">${esc(b.text||'')}</span></div>
   <div style="position:absolute;left:90px;top:360px;width:900px;height:420px;display:grid;grid-template-columns:repeat(6,1fr);gap:12px">${Array.from({length:24},(_,i)=>`<i style="height:92px;border-radius:6px;background:${['#4A4A4F','#5B5B60','#3E3E42','#6A6A70'][(i*7)%4]};${i%6===0&&Math.floor(i/6)%2?'margin-left:-60px':''}"></i>`).join('')}</div>
   <div data-r style="position:absolute;left:300px;top:565px;width:480px;text-align:center;font:800 70px IT,LOC;color:#fff;text-shadow:0 4px 20px rgba(0,0,0,.6);opacity:0">${esc(R)}</div>
   <div data-m style="position:absolute;left:330px;top:400px;width:420px;height:420px"><div style="position:absolute;inset:0;border-radius:50%;border:26px solid #1C1C1E;box-shadow:0 30px 60px rgba(0,0,0,.4),inset 0 0 40px rgba(255,255,255,.4);background:radial-gradient(circle at 35% 30%,rgba(255,255,255,.35),rgba(255,255,255,.05) 60%)"></div>
    <div style="position:absolute;left:330px;top:330px;width:200px;height:56px;border-radius:28px;background:#1C1C1E;transform:rotate(45deg);transform-origin:left center"></div></div></div>`},
  draw(t,b,el){sIn(t,b,el);const u=eio(P(t,b.t0+0.2,Math.max(0.6,kk(b,0)-b.t0)));const m=el.querySelector('[data-m]');m.style.transform=`translate(${(1-u)*-260}px,${(1-u)*240}px) rotate(${(1-u)*-12}deg)`;
   const r=el.querySelector('[data-r]');const v=eo(P(t,kk(b,0),0.35));r.style.opacity=v;r.style.transform=`scale(${0.8+0.2*v})`}},
polaroids:{full:1,build(b,el){const it=items(b).slice(0,4);const pos=[[120,60,-7],[560,30,6],[160,470,5],[590,450,-5]];const imgs=PLAN.images||[];
  el.innerHTML=`<div class="scn">${it.map((x,i)=>{const p=pos[i];const im=x.image!=null&&imgs[x.image]?imgs[x.image]:(imgs[i]||null);return `<div data-p style="position:absolute;left:${p[0]}px;top:${p[1]}px;width:380px;padding:20px 20px 70px;background:#FBFAF6;box-shadow:0 24px 50px rgba(0,0,0,.25);transform:rotate(${p[2]}deg)">
    <div style="height:300px;background:${im?`url(${im}) center/cover`:`linear-gradient(135deg,${['#2B2B2E','#8E1515','#2F6BFF','#141414'][i%4]},#111)`};display:grid;place-items:center;color:#fff">${im?'':icon(pickIcon(x.text),120,'#fff',1.6)}</div>
    <div style="position:absolute;left:0;right:0;bottom:12px;text-align:center" class="hand"><span style="font-size:42px">${esc(x.text)}</span></div>
    <i style="position:absolute;left:50%;top:-14px;width:30px;height:30px;margin-left:-15px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#FF6B6B,#B3171C);box-shadow:0 6px 10px rgba(0,0,0,.3)"></i></div>`}).join('')}</div>`},
  draw(t,b,el){sIn(t,b,el);el.querySelectorAll('[data-p]').forEach((p,i)=>{const [s,o]=pop(t,kk(b,i),0.4);p.style.opacity=o;p.style.scale=s})}},
/* ===== presenter ===== */
window:{full:1,build(b,el){const kind=b.kind||((b.items||[]).length?'checklist':'prompt');const it=items(b);let body='';
  if(kind==='prompt')body=`<div style="padding:40px 36px"><div style="font:500 26px IT;color:#999;margin-bottom:22px">${esc(b.label||'What should we build?')}</div>
    <div style="border:2px solid #E3E3E8;border-radius:22px;padding:26px 28px;min-height:120px;font:600 36px/1.35 IT,LOC"><span data-x></span><span data-cur style="display:inline-block;width:4px;height:40px;background:var(--acc);vertical-align:-6px"></span></div>
    <div style="display:flex;justify-content:flex-end;margin-top:22px"><span data-go style="width:74px;height:74px;border-radius:50%;background:var(--acc);display:grid;place-items:center">${icon('play',30,'#fff')}</span></div></div>`;
  else if(kind==='folder')body=`<div style="height:420px;display:grid;place-items:center"><div data-fo style="display:flex;flex-direction:column;align-items:center;gap:20px"><svg width="220" height="170" viewBox="0 0 220 170"><path d="M10 30a14 14 0 0 1 14-14h60l18 20h94a14 14 0 0 1 14 14v100a14 14 0 0 1-14 14H24a14 14 0 0 1-14-14z" fill="#5AA9F7"/><path d="M10 64h200v86a14 14 0 0 1-14 14H24a14 14 0 0 1-14-14z" fill="#7CC0FF"/></svg><div style="font:700 34px IT,LOC">${esc(b.text||b.title||'folder')}</div></div>
    <svg data-cu width="44" height="56" viewBox="0 0 24 30" style="position:absolute;left:0;top:0"><path d="M2 2v22l6-6 4 9 4-2-4-9h8z" fill="#111" stroke="#fff" stroke-width="1.5"/></svg></div>`;
  else if(kind==='chat')body=`<div style="padding:30px;display:flex;flex-direction:column;gap:16px">${it.map((x,i)=>`<div data-r style="align-self:${i%2?'flex-start':'flex-end'};max-width:76%;padding:16px 24px;border-radius:26px;font:600 30px/1.3 IT,LOC;background:${i%2?'#F0F0F3':'var(--acc)'};color:${i%2?'#141414':'#fff'}">${esc(x.text)}</div>`).join('')}</div>`;
  else body=`<div style="padding:26px 30px;display:flex;flex-direction:column;gap:6px">${it.map(x=>`<div data-r style="display:flex;align-items:center;gap:20px;padding:16px 10px;font:600 32px IT,LOC"><span data-ck style="width:44px;height:44px;border-radius:50%;border:3px solid #D6D6DC;display:grid;place-items:center;flex:none"></span>${esc(x.text)}</div>`).join('')}</div>`;
  el.innerHTML=`<div class="scn"><div data-w class="win" style="left:110px;top:40px;width:860px"><div class="tb"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i><span style="margin-left:auto;margin-right:auto">${esc(b.title||'app')}</span></div>${body}</div>
   ${b.num?`<div data-n class="badge2" style="left:930px;top:0px">${esc(String(b.num))}</div>`:''}</div>`},
  draw(t,b,el){sIn(t,b,el);const n=el.querySelector('[data-n]');if(n){const [s,o]=pop(t,b.t0+0.25,0.4);setT(n,o,`scale(${s}) rotate(${(1-o)*20}deg)`)}
   const x=el.querySelector('[data-x]');if(x){const txt=b.text||'';const c=Math.max(0,Math.min(txt.length,Math.floor((GQ(t)-GQ(kk(b,0)))/5)));x.textContent=[...txt].slice(0,c).join('');
    el.querySelector('[data-cur]').style.opacity=(Math.floor((GQ(t)-GQ(b.t0))/48)%2||c<txt.length)?1:0;const [s]=pop(t,kk(b,0)+txt.length/24+0.2,0.3);el.querySelector('[data-go]').style.transform=`scale(${GQ(t)>=GQ(kk(b,0)+txt.length/24+0.2)?s:1})`}
   const cu=el.querySelector('[data-cu]');if(cu){const u=eio(P(t,b.t0+0.3,0.8));cu.style.transform=`translate(${700-280*u}px,${380-170*u}px)`;const f=el.querySelector('[data-fo]');const [s]=pop(t,b.t0+1.15,0.35);f.style.transform=`scale(${GQ(t)>=GQ(b.t0+1.15)?0.94+0.06*s:1})`}
   el.querySelectorAll('[data-r]').forEach((r,i)=>{const [s,o]=pop(t,kk(b,i),0.35);setT(r,o,`translateY(${(1-o)*16}px) scale(${s})`);const ck=r.querySelector('[data-ck]');
    if(ck){const on=GQ(t)>=GQ(kk(b,i)+0.35);ck.style.background=on?'var(--acc)':'';ck.style.borderColor=on?'var(--acc)':'#D6D6DC';ck.innerHTML=on?icon('check',28,'#fff',3):''}})}}
});
if(PLAN.ctaScene&&COMP[PLAN.ctaScene]&&COMP[PLAN.ctaScene]!==COMP.cta){const c=COMP[PLAN.ctaScene];COMP.cta={full:c.full,card:c.card,build:c.build,draw:c.draw}}
})();
