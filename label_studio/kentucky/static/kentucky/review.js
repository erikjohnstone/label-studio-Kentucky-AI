/* Check the AI's work — review-first labeling canvas.
   The sheet's labels are a Label Studio annotation (polygonlabels); this screen edits that list and autosaves it.
   AI suggestions are Proposals: Keep adds the region (id ka<proposal>) so provenance survives; Dismiss rejects it. */
(function () {
  'use strict';
  const { api, h, svgEl, toast, dialog, nice, cap } = window.KA;
  const SHEET = Number(document.body.dataset.pk);
  const NS = 'http://www.w3.org/2000/svg';
  const TOOLS = [
    ['select', 'Select', 'V', '<path d="M5 3l14 8-6 2-3 6z"/>'],
    ['wall', 'Wall', 'W', '<rect x="3" y="9" width="18" height="6"/>'],
    ['door', 'Door', 'O', '<path d="M5 20V5M5 5a14 14 0 0 1 14 14H5"/>'],
    ['window', 'Window', 'N', '<rect x="3" y="8" width="18" height="8"/><path d="M3 12h18"/>'],
    ['pan', 'Pan', 'H', '<path d="M8 11V5.5a1.5 1.5 0 0 1 3 0V10m0-5.5a1.5 1.5 0 0 1 3 0V10m0-3.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-2.7L3.6 14a1.5 1.5 0 0 1 2.4-1.8L8 14"/>'],
  ];
  const KEY = { v: 'select', w: 'wall', o: 'door', n: 'window', h: 'pan' };
  const NAME = { wall: 'Wall', door: 'Door', window: 'Window', room: 'Room', room_tag: 'Room name' };
  const nm = (k) => NAME[k] || cap(k);
  const PAT = { wall: 'background:color-mix(in srgb,var(--c-wall) 18%,transparent);box-shadow:inset 0 0 0 1.5px var(--c-wall)',
    door: 'background:color-mix(in srgb,var(--c-door) 16%,transparent);box-shadow:inset 0 0 0 1.5px var(--c-door)',
    window: 'background:repeating-linear-gradient(90deg,transparent 0 5px,color-mix(in srgb,var(--c-window) 55%,transparent) 5px 6px);box-shadow:inset 0 0 0 1.5px var(--c-window)' };
  const pat = (k) => h('i.pat', { style: PAT[k] || 'background:var(--sunken);box-shadow:inset 0 0 0 1.5px var(--c-other)' });
  const ccls = (k) => 'c-' + (['wall', 'door', 'window', 'room', 'room_tag'].includes(k) ? k : 'other');
  const S = { regions: [], extra: [], sugg: [], cur: 0, mode: 'review', tool: 'select', sel: null, hidden: new Set(), undo: [], view: null, dirty: false, saving: false };
  const el = (n, a, p) => { const e = document.createElementNS(NS, n); for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
  const bbox = (poly) => { const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; };
  const pts = (poly) => poly.map((p) => p.join(',')).join(' ');
  let D, W, H, stage, svg, world, crop;

  // ------------------------------------------------------------------ LS <-> regions
  function fromLS(r) {
    const v = r.value || {};
    const ow = r.original_width || W, oh = r.original_height || H;
    if (r.type === 'polygonlabels') return { id: r.id, label: (v.polygonlabels || [])[0], poly: (v.points || []).map(([x, y]) => [(x * ow) / 100, (y * oh) / 100]), raw: r };
    if (r.type === 'rectanglelabels' && !v.rotation) { const x = (v.x * ow) / 100, y = (v.y * oh) / 100, w = (v.width * ow) / 100, hh = (v.height * oh) / 100; return { id: r.id, label: (v.rectanglelabels || [])[0], poly: [[x, y], [x + w, y], [x + w, y + hh], [x, y + hh]], raw: r }; }
    return null;
  }
  function toLS(g) {
    if (g.raw && !g.changed) return g.raw;
    return { id: g.id, from_name: 'polygonlabels', to_name: 'image', type: 'polygonlabels', original_width: W, original_height: H, image_rotation: 0,
      value: { points: g.poly.map(([x, y]) => [(x / W) * 100, (y / H) * 100]), closed: true, polygonlabels: [g.label] } };
  }

  // ------------------------------------------------------------------ saving
  let saveT = null;
  const status = (t, cls) => { const s = document.getElementById('saved'); if (s) { s.textContent = t; s.className = 'rv-saved' + (cls ? ' ' + cls : ''); } };
  function dirty() { S.dirty = true; status('Saving…', 'busy'); clearTimeout(saveT); saveT = setTimeout(save, 700); }
  async function save(keepalive) {
    clearTimeout(saveT);
    if (!S.dirty) return;
    S.dirty = false; S.saving = true;
    const body = { result: S.regions.map(toLS).concat(S.extra) };
    try {
      if (keepalive) { await window.fetch(`/api/ka/sheets/${SHEET}/markup/`, { method: 'POST', keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent((document.cookie.match(/csrftoken=([^;]*)/) || [])[1] || '') }, body: JSON.stringify(body) }); }
      else await api(`sheets/${SHEET}/markup/`, { method: 'POST', body });
      status('Saved');
    } catch (e) { S.dirty = true; status('Not saved — retrying', 'err'); saveT = setTimeout(save, 3000); }
    S.saving = false;
  }
  window.addEventListener('beforeunload', () => { if (S.dirty) save(true); });

  // ------------------------------------------------------------------ camera
  const aspect = () => { const r = stage.getBoundingClientRect(); return r.height / Math.max(r.width, 1); };
  function setView(v) { S.view = v; svg.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.w * aspect()}`); placeTag(); const z = document.getElementById('zoomv'); if (z) z.textContent = Math.round(((S.fitW || v.w) / v.w) * 100) + '%'; }
  function fitView() {
    // fit the sheet in the area above the floating toolbar
    const r = stage.getBoundingClientRect(), a = aspect(), top = 64, bot = 100, side = 40;
    const sx = W / Math.max(r.width - side * 2, 100), sy = H / Math.max(r.height - top - bot, 100), k = Math.max(sx, sy);
    const w = r.width * k; S.fitW = w;
    return { x: W / 2 - w / 2, y: H / 2 - ((r.height - top - bot) / 2 + top) * k, w };
  }
  let anim = null;
  function camera(t, ms = 280) {
    cancelAnimationFrame(anim);
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return setView(t);
    const f = { ...S.view }, t0 = performance.now();
    const step = (now) => { const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3); setView({ x: f.x + (t.x - f.x) * e, y: f.y + (t.y - f.y) * e, w: f.w + (t.w - f.w) * e }); if (k < 1) anim = requestAnimationFrame(step); };
    anim = requestAnimationFrame(step);
  }
  function focusOn(poly) {
    const [x0, y0, x1, y1] = bbox(poly), a = aspect();
    const w = Math.max((x1 - x0) * 7, ((y1 - y0) * 7) / a, W * 0.3);
    camera({ x: (x0 + x1) / 2 - w / 2, y: (y0 + y1) / 2 - (w * a) / 2, w });
  }
  const toWorld = (cx, cy) => { const r = stage.getBoundingClientRect(), v = S.view; return [v.x + ((cx - r.left) / r.width) * v.w, v.y + ((cy - r.top) / r.height) * v.w * aspect()]; };
  const toScreen = (x, y) => { const r = stage.getBoundingClientRect(), v = S.view; return [((x - v.x) / v.w) * r.width, ((y - v.y) / (v.w * aspect())) * r.height]; };

  // ------------------------------------------------------------------ drawing the sheet
  function drawWorld() {
    world.replaceChildren();
    const cur = S.mode === 'review' ? S.sugg[S.cur] : null;
    S.regions.forEach((g) => {
      if (!g.poly || g.poly.length < 3) return;
      const p = el('polygon', { class: `rg ${ccls(g.label)}${S.sel === g.id ? ' sel' : ''}${S.hidden.has(g.label) ? ' hide' : ''}`, points: pts(g.poly), 'data-id': g.id }, world);
      p.addEventListener('mousedown', (e) => { if (S.tool !== 'select' || e.button !== 0) return; e.stopPropagation(); S.sel = g.id; S.mode = 'draw'; renderAll(); });
    });
    S.sugg.forEach((s, i) => {
      if (S.hidden.has(s.label)) return;
      const p = el('polygon', { class: `rg todo ${ccls(s.label)}${cur && cur.id === s.id ? ' cur' : ''}`, points: pts(s.polygon) }, world);
      p.addEventListener('mousedown', (e) => { if (S.tool !== 'select' || e.button !== 0) return; e.stopPropagation(); S.cur = i; S.mode = 'review'; S.sel = null; renderAll(); focusOn(s.polygon); });
    });
    if (cur) { // spotlight
      const [x0, y0, x1, y1] = bbox(cur.polygon), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, r = Math.max(x1 - x0, y1 - y0) * 0.9 + W * 0.02;
      const m = el('mask', { id: 'spot' }, world); el('rect', { x: -W, y: -H, width: W * 3, height: H * 3, fill: '#fff' }, m); el('circle', { cx, cy, r, fill: '#000' }, m);
      el('rect', { class: 'rv-dim', x: -W, y: -H, width: W * 3, height: H * 3, mask: 'url(#spot)' }, world);
      el('circle', { class: 'rv-ring', cx, cy, r, style: `stroke:var(--c-${['wall', 'door', 'window'].includes(cur.label) ? cur.label : 'other'})` }, world);
      el('circle', { class: 'rv-ring o', cx, cy, r: r * 1.1, style: `stroke:var(--c-${['wall', 'door', 'window'].includes(cur.label) ? cur.label : 'other'})` }, world);
    }
    placeTag();
  }
  function placeTag() {
    const tag = document.getElementById('tag'); if (!tag) return;
    const cur = S.mode === 'review' ? S.sugg[S.cur] : null;
    if (!cur || !S.view) { tag.style.display = 'none'; return; }
    const [x0, y0, x1, y1] = bbox(cur.polygon), r = Math.max(x1 - x0, y1 - y0) * 0.9 + W * 0.02;
    const [sx, sy] = toScreen((x0 + x1) / 2 + r * 0.72, (y0 + y1) / 2 - r * 0.72);
    tag.style.display = 'flex'; tag.style.left = sx + 10 + 'px'; tag.style.top = sy - 18 + 'px';
    const c = cur.confidence ?? 0;
    tag.replaceChildren(h('span.sw', { style: { background: `var(--c-${['wall', 'door', 'window'].includes(cur.label) ? cur.label : 'other'})` } }), `${nm(cur.label)} · `, h('em', { style: c >= 0.8 ? { color: 'var(--pos)' } : c >= 0.6 ? { color: 'var(--teal)' } : {} }, `${Math.round(c * 100)}% sure`));
  }

  // ------------------------------------------------------------------ panel
  const confCls = (c) => (c >= 0.8 ? 'hi' : c >= 0.6 ? 'mid' : 'lo');
  const confTxt = (c) => (c >= 0.8 ? 'Very likely' : c >= 0.6 ? 'Probably' : 'Look closely');
  function counts() { const k = {}, p = {}; S.regions.forEach((g) => (k[g.label] = (k[g.label] || 0) + 1)); S.sugg.forEach((s) => (p[s.label] = (p[s.label] || 0) + 1)); return { k, p }; }
  function mainClasses() { const names = D.classes.map((c) => c.name); const base = ['wall', 'door', 'window'].filter((x) => names.includes(x)); const { k, p } = counts(); const extra = [...new Set([...Object.keys(k), ...Object.keys(p)])].filter((x) => !base.includes(x)); return base.concat(extra); }
  function renderPanel() {
    const panel = document.getElementById('panel');
    const { k, p } = counts();
    const total = D.decided.kept + D.decided.dismissed + S.sugg.length + S.sessionKept + S.sessionDis;
    const kept = D.decided.kept + S.sessionKept, dis = D.decided.dismissed + S.sessionDis;
    const pct = total ? Math.round(((kept + dis) / total) * 100) : 100;
    const cur = S.sugg[S.cur];
    const head = h('div.rv-ph', {}, h('div.row1', {}, h('span.lbl', {}, S.mode === 'review' ? 'AI review' : 'Drawing'), h('span.lbl', {}, `[ Sheet ${String(D.position[0]).padStart(2, '0')} / ${String(D.position[1]).padStart(2, '0')} ]`)),
      total ? h('div.rv-h', {}, `AI found ${total} item${total === 1 ? '' : 's'}.`, h('br'), h('span', {}, S.sugg.length ? `${S.sugg.length} left to check.` : 'All checked.'))
        : h('div.rv-h', {}, `${S.regions.length} item${S.regions.length === 1 ? '' : 's'} marked.`, h('br'), h('span', {}, S.regions.length ? 'Look them over.' : 'Draw, or ask the AI.')),
      total ? [h('div.rv-bar', {}, h('i', { style: { width: (kept / total) * 100 + '%', background: 'var(--cyan)' } }), h('i', { style: { width: (dis / total) * 100 + '%', background: 'var(--ink-4)' } })),
        h('div.rv-barl', {}, h('span.lbl', {}, `${kept} kept · ${dis} dismissed`), h('span.lbl.cy', {}, pct + '%'))] : null);
    let card;
    if (S.mode === 'review' && cur) {
      const c = cur.confidence ?? 0;
      const others = mainClasses().filter((x) => x !== cur.label && ['wall', 'door', 'window'].includes(x));
      card = h('div.rv-card', {}, h('div.rv-crop', {}, (crop = svgEl('svg', {})), h('span.lbl', {}, cur.source === 'model' ? 'Suggested by your model' : "Found from the drawing's lines")),
        h('div.rv-cb', {}, h('div.rv-what', {}, h('span.sw', { style: PAT[cur.label] || '' }), h('b', {}, nm(cur.label)), h('span.rv-conf.' + confCls(c), {}, `${Math.round(c * 100)}% · ${confTxt(c)}`)),
          h('div.rv-sub', {}, `Is the highlighted outline a ${nm(cur.label).toLowerCase()}? Keep it if it's right.`),
          h('div.rv-acts', {}, h('button.rv-keep', { onclick: () => keep() }, 'Keep ', h('kbd', {}, 'K')), h('button.rv-dis', { onclick: dismiss }, `Not a ${nm(cur.label).toLowerCase()} `, h('kbd', {}, 'D'))),
          others.length ? h('div.rv-swap', {}, "It's actually a", others.map((o) => h('button', { onclick: () => keep(o) }, nm(o), h('kbd', {}, TOOLS.find((t) => t[0] === o)?.[2] || '')))) : null,
          h('div.rv-nav', {}, h('button', { onclick: () => go(-1) }, '← Previous'), h('span.lbl', {}, `${S.cur + 1} / ${S.sugg.length}`), h('button', { onclick: () => go(1) }, 'Skip →'))));
    } else if (S.mode === 'draw') {
      const g = S.regions.find((x) => x.id === S.sel);
      card = g ? h('div.rv-card', {}, h('div.rv-cb', {}, h('div.rv-what', {}, h('span.sw', { style: PAT[g.label] || '' }), h('b', {}, nm(g.label)), h('span.rv-conf.mid', {}, g.id.startsWith('ka') ? 'Kept from AI' : 'Yours')),
        h('div.rv-sub', {}, 'Change its type, or delete it.'), h('div.rv-swap', {}, 'Make it a', mainClasses().filter((x) => x !== g.label).map((o) => h('button', { onclick: () => relabel(g, o) }, nm(o)))),
        h('div.rv-acts', {}, h('button.rv-dis', { onclick: () => removeSel() }, 'Delete ', h('kbd', {}, 'Del')), h('button.rv-dis', { onclick: () => { S.sel = null; renderAll(); } }, 'Deselect ', h('kbd', {}, 'Esc')))))
        : h('div.rv-empty', {}, h('b', {}, S.tool === 'select' || S.tool === 'pan' ? 'Pick a tool to draw' : `Drawing ${nm(S.tool).toLowerCase()}s`), S.tool === 'select' || S.tool === 'pan' ? 'Wall, Door or Window in the toolbar — then drag a box around the item.' : 'Drag a box around each one. Click a shape with Select to change or delete it.');
    } else {
      card = h('div.rv-empty', {}, h('b', {}, S.regions.length ? 'Nothing left to check' : 'No AI suggestions yet'),
        S.regions.length ? 'Look over the sheet. Missed something? Draw it, or ask the AI to look again.' : D.can_find_more ? 'Let the AI take a first pass — you just keep what is right.' : 'This sheet is a scan. Draw the items, then train — your model will suggest on the next ones.',
        h('div', {}, D.can_find_more ? h('button.btn.primary', { onclick: findMore }, '✦ Find with AI') : h('button.btn', { onclick: () => setTool('wall') }, 'Start drawing')));
    }
    const layers = h('div.rv-sec', {}, h('div.lbl', { style: { marginBottom: '6px' } }, 'On this sheet'), mainClasses().map((c) => {
      const left = p[c] || 0, n = (k[c] || 0) + left;
      return h('div.rv-layer' + (S.hidden.has(c) ? '.off' : '') + (cur && cur.label === c && S.mode === 'review' ? '.on' : ''), { onclick: () => { S.hidden.has(c) ? S.hidden.delete(c) : S.hidden.add(c); renderAll(); }, title: 'Show / hide' }, pat(c), h('span.nm', {}, nm(c) + 's'),
        h('span.lst' + (!left && n ? '.done' : ''), {}, left ? `${left} of ${n} left` : n ? `✓ ${n} checked` : 'none'), svgEl('svg', { viewBox: '0 0 24 24' }, S.hidden.has(c) ? svgEl('path', { d: 'M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.3 4.2M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a9.6 9.6 0 0 0 5.4-1.6' }) : [svgEl('path', { d: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z' }), svgEl('circle', { cx: 12, cy: 12, r: 3 })]));
    }));
    const foot = h('div.rv-foot', {}, svgEl('svg', { viewBox: '0 0 24 24' }, svgEl('circle', { cx: 12, cy: 12, r: 9 }), svgEl('path', { d: 'M12 11v5M12 8h.01' })),
      h('span', {}, 'Everything you keep teaches your model. Anything you dismiss, it learns to ignore. ', h('a', { href: `?editor=1` }, 'Precise outline editor')));
    panel.replaceChildren(head, card, layers, foot);
    if (crop && cur && S.mode === 'review') drawCrop(cur);
  }
  function drawCrop(cur) {
    const [x0, y0, x1, y1] = bbox(cur.polygon), cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const r = crop.parentNode.getBoundingClientRect(), a = r.height / Math.max(r.width, 1);
    const w = Math.max((x1 - x0) * 3.2, ((y1 - y0) * 3.2) / a, W * 0.08);
    crop.setAttribute('viewBox', `${cx - w / 2} ${cy - (w * a) / 2} ${w} ${w * a}`);
    el('image', { class: 'rv-img', href: D.sheet.image_url, x: 0, y: 0, width: W, height: H }, crop);
    S.regions.forEach((g) => g.poly.length > 2 && el('polygon', { class: `rg ${ccls(g.label)}`, points: pts(g.poly), style: 'opacity:.5' }, crop));
    el('polygon', { class: `rg cur ${ccls(cur.label)}`, points: pts(cur.polygon) }, crop);
  }
  function renderLegend() {
    const { k, p } = counts();
    document.getElementById('legend').replaceChildren(...[...mainClasses().map((c) => h('button' + (S.hidden.has(c) ? '.off' : ''), { onclick: () => { S.hidden.has(c) ? S.hidden.delete(c) : S.hidden.add(c); renderAll(); } }, pat(c), nm(c) + 's', h('b', {}, String((k[c] || 0) + (p[c] || 0))))),
      S.sugg.length ? h('span', { style: { color: 'var(--ink-3)', cursor: 'default' } }, svgEl('svg', { width: 14, viewBox: '0 0 14 14' }, svgEl('rect', { x: 1, y: 1, width: 12, height: 12, rx: 2, fill: 'none', stroke: 'currentColor', 'stroke-dasharray': '2.5 2' })), 'Dashed = not checked yet') : null].filter(Boolean));
    document.getElementById('nleft').textContent = S.sugg.length || '';
    const { k: kk } = counts();
    document.getElementById('totals').replaceChildren(...['wall', 'door', 'window'].map((c) => h('div', {}, h('b', {}, String(kk[c] || 0)), h('span.lbl', {}, nm(c) + 's'))),
      h('div', {}, h('b', { style: { color: 'var(--teal)' } }, `${D.sheets.filter((s) => s.state === 'done').length} / ${D.sheets.length}`), h('span.lbl', {}, 'Sheets done')));
  }
  function renderAll() {
    stage.classList.toggle('draw', ['wall', 'door', 'window'].includes(S.tool));
    stage.classList.toggle('pan', S.tool === 'pan');
    document.querySelectorAll('.rv-tool').forEach((b) => b.classList.toggle('on', b.dataset.t === S.tool));
    document.querySelectorAll('.rv-seg button').forEach((b) => b.classList.toggle('on', b.dataset.m === S.mode));
    drawWorld(); renderPanel(); renderLegend();
  }

  // ------------------------------------------------------------------ actions
  function go(d) { if (!S.sugg.length) return; S.cur = (S.cur + d + S.sugg.length) % S.sugg.length; S.mode = 'review'; renderAll(); focusOn(S.sugg[S.cur].polygon); }
  function afterDecision() {
    if (S.cur >= S.sugg.length) S.cur = 0;
    renderAll();
    if (S.sugg.length) focusOn(S.sugg[S.cur].polygon);
    else { camera(fitView(), 420); toast('Every suggestion on this sheet is checked. Press Done when it looks right.', 'pos'); }
  }
  function keep(label) {
    const s = S.sugg[S.cur]; if (!s || S.mode !== 'review') return;
    const lab = label || s.label;
    S.regions.push({ id: 'ka' + s.id, label: lab, poly: s.polygon.map((p) => [...p]), changed: true });
    S.sugg.splice(S.cur, 1); S.sessionKept++;
    S.undo.push({ t: 'keep', s, i: S.cur });
    api(`sheets/${SHEET}/decide/`, { method: 'POST', body: { proposal_id: s.id, action: 'keep', label: lab } }).catch((e) => toast(e.message, 'danger'));
    dirty(); afterDecision();
  }
  function dismiss() {
    const s = S.sugg[S.cur]; if (!s || S.mode !== 'review') return;
    S.sugg.splice(S.cur, 1); S.sessionDis++;
    S.undo.push({ t: 'dismiss', s, i: S.cur });
    api(`sheets/${SHEET}/decide/`, { method: 'POST', body: { proposal_id: s.id, action: 'dismiss' } }).catch((e) => toast(e.message, 'danger'));
    afterDecision();
  }
  function relabel(g, lab) { S.undo.push({ t: 'relabel', id: g.id, from: g.label }); g.label = lab; g.changed = true; dirty(); renderAll(); }
  function removeSel() {
    const i = S.regions.findIndex((x) => x.id === S.sel); if (i < 0) return;
    S.undo.push({ t: 'delete', g: S.regions[i], i }); S.regions.splice(i, 1); S.sel = null; dirty(); renderAll();
  }
  function undo() {
    const u = S.undo.pop(); if (!u) return toast('Nothing to undo');
    if (u.t === 'keep' || u.t === 'dismiss') {
      if (u.t === 'keep') { S.regions = S.regions.filter((g) => g.id !== 'ka' + u.s.id); S.sessionKept--; dirty(); } else S.sessionDis--;
      S.sugg.splice(u.i, 0, u.s); S.cur = u.i; S.mode = 'review';
      api(`sheets/${SHEET}/decide/`, { method: 'POST', body: { proposal_id: u.s.id, action: 'undo' } }).catch(() => {});
      renderAll(); focusOn(u.s.polygon);
    } else if (u.t === 'add') { S.regions = S.regions.filter((g) => g.id !== u.id); dirty(); renderAll(); }
    else if (u.t === 'delete') { S.regions.splice(u.i, 0, u.g); dirty(); renderAll(); }
    else if (u.t === 'relabel') { const g = S.regions.find((x) => x.id === u.id); if (g) { g.label = u.from; g.changed = true; dirty(); renderAll(); } }
  }
  function setTool(t) { S.tool = t; if (t !== 'select' && t !== 'pan') { S.mode = 'draw'; S.sel = null; } renderAll(); }
  function setMode(m) { S.mode = m; S.sel = null; if (m === 'review') { S.tool = 'select'; if (S.sugg.length) { renderAll(); return focusOn(S.sugg[S.cur].polygon); } } renderAll(); }
  async function findMore() {
    const btn = document.getElementById('aibtn'); if (btn) btn.disabled = true;
    const scan = h('div.rv-scan'); stage.append(scan);
    const hint = h('div.rv-hint', {}, '✦ Reading the drawing for walls, doors and windows…'); stage.append(hint);
    try {
      await save();
      const r = await api(`sheets/${SHEET}/find-more/`, { method: 'POST', body: {} });
      const d = await api(`sheets/${SHEET}/review/`);
      S.sugg = d.suggestions; S.cur = 0; D.decided = d.decided; S.sessionKept = 0; S.sessionDis = 0;
      toast(r.created ? `The AI found ${r.created} item${r.created === 1 ? '' : 's'} to check${r.source === 'model' ? ` (using ${r.model})` : ''}.` : 'Nothing new found — everything it sees is already marked.', r.created ? 'pos' : null);
      setMode('review');
    } catch (e) { toast(e.message, 'danger'); }
    scan.remove(); hint.remove(); if (btn) btn.disabled = !D.can_find_more;
  }
  async function done() {
    if (S.sugg.length && !(await dialog(`${S.sugg.length} suggestion${S.sugg.length === 1 ? '' : 's'} not checked`, h('p.muted', {}, 'Finish anyway? Unchecked suggestions are dismissed — the model won’t learn from them.'), [{ label: 'Dismiss them and finish', primary: true }]))) return;
    await save();
    const r = await api(`sheets/${SHEET}/done/`, { method: 'POST', body: { dismiss_rest: true } });
    try { sessionStorage.setItem('ka-toast', `Sheet checked — ${r.approved ? r.approved + ' items ready to train on. ' : ''}${r.sheets_done} of ${r.sheets_total} sheets done.`); } catch (e) { /* ignore */ }
    location.href = r.next ? `/ka/markup/${r.next}/` : `/ka/projects/${D.dataset.id}/`;
  }
  function shortcuts() {
    const rows = [['K', 'Keep the suggestion'], ['D', 'Dismiss it'], ['→ / Tab', 'Skip to the next one'], ['←', 'Previous one'], ['V', 'Select'], ['W  O  N', 'Draw a wall, door or window'], ['H / hold Space', 'Pan'], ['Scroll', 'Zoom'], ['0', 'Fit the sheet'], ['Del', 'Delete the selected shape'], ['Ctrl Z', 'Undo'], ['Enter', 'Done · next sheet']];
    dialog('Keyboard shortcuts', h('div.keys', {}, rows.flatMap(([k, t]) => [h('kbd', {}, k), h('span', {}, t)])), []);
  }

  // ------------------------------------------------------------------ input
  function wire() {
    let drag = null, space = false;
    stage.addEventListener('wheel', (e) => {
      e.preventDefault();
      const [wx, wy] = toWorld(e.clientX, e.clientY), f = Math.exp(e.deltaY * 0.0015), v = S.view;
      const w = Math.min(Math.max(v.w * f, W * 0.02), W * 6);
      const r = stage.getBoundingClientRect();
      setView({ x: wx - ((e.clientX - r.left) / r.width) * w, y: wy - ((e.clientY - r.top) / r.height) * w * aspect(), w });
    }, { passive: false });
    stage.addEventListener('mousedown', (e) => {
      stage.focus();
      if (e.button === 1 || S.tool === 'pan' || space) { drag = { t: 'pan', x: e.clientX, y: e.clientY, v: { ...S.view } }; stage.classList.add('panning'); e.preventDefault(); return; }
      if (e.button !== 0) return;
      if (['wall', 'door', 'window'].includes(S.tool)) { const p = toWorld(e.clientX, e.clientY); drag = { t: 'draw', p, r: el('rect', { class: 'rv-draft', x: p[0], y: p[1], width: 0, height: 0, style: `fill:var(--c-${S.tool});stroke:var(--c-${S.tool})` }, world) }; return; }
      if (S.tool === 'select') { if (S.sel) { S.sel = null; renderAll(); } drag = { t: 'pan', x: e.clientX, y: e.clientY, v: { ...S.view }, soft: true }; }
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      if (drag.t === 'pan') { const r = stage.getBoundingClientRect(), k = drag.v.w / r.width; if (drag.soft && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) stage.classList.add('panning'); setView({ x: drag.v.x - (e.clientX - drag.x) * k, y: drag.v.y - (e.clientY - drag.y) * k, w: drag.v.w }); }
      else { const p = toWorld(e.clientX, e.clientY); const x = Math.min(p[0], drag.p[0]), y = Math.min(p[1], drag.p[1]); drag.r.setAttribute('x', x); drag.r.setAttribute('y', y); drag.r.setAttribute('width', Math.abs(p[0] - drag.p[0])); drag.r.setAttribute('height', Math.abs(p[1] - drag.p[1])); }
    });
    window.addEventListener('mouseup', (e) => {
      if (!drag) return;
      stage.classList.remove('panning');
      if (drag.t === 'draw') {
        const p = toWorld(e.clientX, e.clientY); drag.r.remove();
        const x0 = Math.max(0, Math.min(p[0], drag.p[0])), y0 = Math.max(0, Math.min(p[1], drag.p[1])), x1 = Math.min(W, Math.max(p[0], drag.p[0])), y1 = Math.min(H, Math.max(p[1], drag.p[1]));
        if (x1 - x0 > W * 0.002 && y1 - y0 > H * 0.002) {
          const id = 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
          S.regions.push({ id, label: S.tool, poly: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], changed: true });
          S.undo.push({ t: 'add', id }); dirty(); renderAll();
        }
      }
      drag = null;
    });
    window.addEventListener('resize', () => S.view && setView(S.view));
    document.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || document.querySelector('.scrim')) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); return undo(); }
      if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); return save(); }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (k === ' ') { space = true; stage.classList.add('pan'); e.preventDefault(); return; }
      if (k === 'k') return keep();
      if (k === 'd') return dismiss();
      if (k === 'arrowright' || k === 'tab') { e.preventDefault(); return go(1); }
      if (k === 'arrowleft') return go(-1);
      if (k === 'enter') return done();
      if (k === 'escape') { S.sel = null; return renderAll(); }
      if (k === 'delete' || k === 'backspace') return removeSel();
      if (k === '0') return camera(fitView());
      if (k === '?' || (k === '/' && e.shiftKey)) return shortcuts();
      if (k === '=' || k === '+' || k === '-') { const v = S.view, f = k === '-' ? 1.25 : 0.8, w = v.w * f; return camera({ x: v.x + (v.w - w) / 2, y: v.y + ((v.w - w) * aspect()) / 2, w }, 160); }
      if (KEY[k]) {
        const g = S.sel && S.regions.find((x) => x.id === S.sel);
        if (g && ['wall', 'door', 'window'].includes(KEY[k])) return relabel(g, KEY[k]);
        if (S.mode === 'review' && S.sugg[S.cur] && ['wall', 'door', 'window'].includes(KEY[k]) && KEY[k] !== S.sugg[S.cur].label) return keep(KEY[k]);
        return setTool(KEY[k]);
      }
    });
    document.addEventListener('keyup', (e) => { if (e.key === ' ') { space = false; stage.classList.toggle('pan', S.tool === 'pan'); } });
  }

  // ------------------------------------------------------------------ layout + boot
  function layout() {
    const markSvg = '<svg viewBox="0 0 64 32"><defs><pattern id="scanr" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2.6" fill="#62d4dc"/></pattern></defs><path d="M4 30 L18 6 H30 L16 30 Z M22 30 L36 6 H62 L58 14 H45 L36 30 Z" fill="url(#scanr)"/></svg>';
    const mark = h('a.rv-mark', { href: '/ka/', title: 'Plan sets' }); mark.innerHTML = markSvg; // static brand mark, no user data
    const themeBtn = h('button.rv-ib', { title: 'Light / Dark', onclick: () => { window.KA.setTheme(window.KA.theme() === 'dark' ? 'light' : 'dark'); themeIcon(); } });
    const themeIcon = () => themeBtn.replaceChildren(svgEl('svg', { viewBox: '0 0 24 24' }, window.KA.theme() === 'dark' ? [svgEl('circle', { cx: 12, cy: 12, r: 4 }), svgEl('path', { d: 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4' })] : svgEl('path', { d: 'M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z' })));
    themeIcon();
    const tools = h('div.rv-tools', {}, TOOLS.map(([t, label, key, path]) => { const b = h('button.rv-tool', { 'data-t': t, onclick: () => setTool(t), title: `${label} (${key})` }); const s = svgEl('svg', { viewBox: '0 0 24 24' }); s.innerHTML = path; b.append(s, label, h('span.k', {}, key)); return b; }),
      h('span.div'), h('button.rv-ai', { id: 'aibtn', onclick: findMore, disabled: !D.can_find_more, title: D.can_find_more ? 'Ask the AI to mark up this sheet' : 'Scans need a trained model first' }, svgEl('svg', { viewBox: '0 0 24 24' }, svgEl('path', { d: 'M12 2l2.2 6.6L21 11l-6.8 2.4L12 20l-2.2-6.6L3 11l6.8-2.4z' })), 'Find more with AI'));
    stage = h('section.rv-stage', { tabindex: 0 });
    svg = svgEl('svg', { preserveAspectRatio: 'none' });
    el('rect', { class: 'rv-sheet', x: 0, y: 0, width: W, height: H, 'vector-effect': 'non-scaling-stroke' }, svg);
    const t = Math.max(W, H) * 0.025, o = Math.max(W, H) * 0.012;
    [[-o, -o, 1, 1], [W + o, -o, -1, 1], [-o, H + o, 1, -1], [W + o, H + o, -1, -1]].forEach(([x, y, sx, sy]) => el('path', { class: 'rv-tick', d: `M${x} ${y + sy * t}V${y}H${x + sx * t}` }, svg));
    el('image', { class: 'rv-img', href: D.sheet.image_url, x: 0, y: 0, width: W, height: H }, svg);
    world = el('g', {}, svg);
    stage.append(svg, h('div.rv-legend', { id: 'legend' }), h('div.rv-zoom', {}, h('button', { onclick: () => { const v = S.view, w = v.w * 1.25; camera({ x: v.x - (w - v.w) / 2, y: v.y - ((w - v.w) * aspect()) / 2, w }, 160); }, title: 'Zoom out' }, '−'), h('span', { id: 'zoomv' }, '100%'),
      h('button', { onclick: () => { const v = S.view, w = v.w * 0.8; camera({ x: v.x + (v.w - w) / 2, y: v.y + ((v.w - w) * aspect()) / 2, w }, 160); }, title: 'Zoom in' }, '+'), h('button.fit', { onclick: () => camera(fitView()), title: 'Fit (0)' }, 'FIT')),
    h('div.rv-tag', { id: 'tag' }), tools);
    const thumbs = h('div.rv-thumbs', {}, D.sheets.map((s, i) => h('a.rv-th' + (s.id === SHEET ? '.on' : ''), { href: `/ka/markup/${s.id}/`, title: `${nice(s.name)}${s.pending ? ` · ${s.pending} to check` : ''}`, onclick: async (e) => { if (S.dirty) { e.preventDefault(); await save(); location.href = `/ka/markup/${s.id}/`; } } },
      h('img', { src: s.image_url, alt: '', loading: 'lazy' }), h('span.d.s-' + s.state), h('span.no', {}, `S-${String(i + 1).padStart(2, '0')}`))));
    document.getElementById('ka-root').replaceChildren(h('div.rv', {},
      h('header.rv-top', {}, h('a.rv-ib', { href: `/ka/projects/${D.dataset.id}/`, title: 'Back to the plan set' }, '←'), mark,
        h('div.rv-crumb', {}, h('b', {}, D.dataset.name), h('span', {}, `Sheet ${D.position[0]} of ${D.position[1]}`)), h('div.rv-chip', { title: D.sheet.name }, nice(D.sheet.name)),
        h('div.rv-seg', {}, h('button', { 'data-m': 'review', onclick: () => setMode('review') }, 'Review AI ', h('span.n', { id: 'nleft' })), h('button', { 'data-m': 'draw', onclick: () => setMode('draw') }, 'Draw')),
        h('div', { style: { flex: 1 } }), h('span.rv-saved', { id: 'saved' }, D.annotation ? 'Saved' : 'Nothing saved yet'), themeBtn, h('button.rv-ib', { onclick: shortcuts, title: 'Keyboard shortcuts' }, '?'),
        h('button.btn.primary', { onclick: done }, 'Done · Next sheet ', h('kbd', {}, '↵'))),
      stage, h('aside.rv-panel', { id: 'panel' }), h('footer.rv-film', {}, thumbs, h('div.rv-totals', { id: 'totals' }))));
  }

  (async () => {
    try {
      D = await api(`sheets/${SHEET}/review/`);
      W = D.sheet.width; H = D.sheet.height;
      document.title = `Check ${nice(D.sheet.name)} · Kentucky AI`;
      (D.annotation?.result || []).forEach((r) => { const g = fromLS(r); if (g && g.poly.length > 2) S.regions.push(g); else S.extra.push(r); });
      S.sugg = D.suggestions; S.sessionKept = 0; S.sessionDis = 0;
      S.mode = S.sugg.length ? 'review' : 'draw';
      layout(); wire();
      setView(fitView());
      renderAll();
      if (S.sugg.length) setTimeout(() => focusOn(S.sugg[0].polygon), 350);
      try { const m = sessionStorage.getItem('ka-toast'); if (m) { sessionStorage.removeItem('ka-toast'); toast(m, 'pos'); } } catch (e) { /* ignore */ }
    } catch (e) {
      console.error(e);
      document.getElementById('ka-root').replaceChildren(window.KA.empty('Could not open this sheet', e.message, h('a.btn', { href: '/ka/' }, 'Back to plan sets')));
    }
  })();
})();
