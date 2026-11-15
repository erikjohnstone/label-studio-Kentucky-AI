const MARK='<svg viewBox="0 0 64 32"><defs><pattern id="scanm" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2.6" fill="#62d4dc"/></pattern></defs><path d="M4 30 L18 6 H30 L16 30 Z M22 30 L36 6 H62 L58 14 H45 L36 30 Z" fill="url(#scanm)"/></svg>';
function sidebar(on){
  const I={plans:'<path d="M4 5h16v14H4z"/><path d="M4 10h16M9 10v9"/>',models:'<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',deploy:'<path d="M4 12h12M12 6l6 6-6 6M20 4v16"/>',keys:'<circle cx="8" cy="15" r="4"/><path d="M11 12l8-8M16 7l3 3"/>',docs:'<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>',bill:'<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/>',team:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/>'};
  const n=(k,l,c)=>`<a class="nav ${on===k?'on':''}"><svg viewBox="0 0 24 24">${I[k]}</svg>${l}${c?`<span class="c">${c}</span>`:''}</a>`;
  document.getElementById('side').innerHTML=`<div class="brand"><span class="m">${MARK}</span>Kentucky AI</div>
  ${n('plans','Plan sets','3')}${n('models','Models','2')}${n('deploy','Deployments','1')}
  <div class="mono navlbl">Developers</div>${n('keys','API keys')}${n('docs','API docs')}
  <div class="mono navlbl">Account</div>${n('bill','Billing')}${n('team','Team')}
  <div class="grow"></div><div class="me"><span class="av">E</span>Erik · Kentucky AI</div>`;
}
const NS='http://www.w3.org/2000/svg',W=1855,H=2400,COL={wall:'#62d4dc',door:'#f0b24a',window:'#9db1ff'};
function el(n,a,p){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);p&&p.appendChild(e);return e}
// draw a sheet into svg. opts: img, items, vb, sw, opacity, filter(fn item->bool), dashed(fn), clipX (reveal fraction)
function plan(svg,o){
  svg.setAttribute('viewBox',(o.vb||[0,0,W,H]).join(' '));svg.setAttribute('preserveAspectRatio',o.par||'xMidYMid meet');
  el('image',{href:o.img||'s6.png',x:0,y:0,width:o.w||W,height:o.h||H,class:'planimg',opacity:o.opacity??.45},svg);
  const g=el('g',{},svg);
  (o.items||[]).forEach(i=>{if(o.filter&&!o.filter(i))return;const c=o.color?o.color(i):COL[i.c];
    const a={points:i.p.map(q=>q.join(',')).join(' '),stroke:c,'stroke-width':o.sw||4,'stroke-linejoin':'round',fill:c,'fill-opacity':o.fo??.16};
    if(o.dashed&&o.dashed(i))a['stroke-dasharray']='10 7';el('polygon',a,g);});
  return g;
}
