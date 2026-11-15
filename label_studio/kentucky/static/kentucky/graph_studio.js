/* Graph Studio: GNN annotation over vector blueprints. Requires ka.js (window.KA). */
(function () {
  'use strict';
  if (document.body.dataset.page !== 'graph') return;
  const { api, h, svgEl, toast, dialog, guard, chip, empty, mount } = window.KA;
  const SHEET = Number(document.body.dataset.pk);
  const S = { sel: new Set(), showEdges: 'selection', dirty: false, filter: null, compare: null, colors: {} };
  const FALLBACK = ['#62d4dc', '#f0b24a', '#8fa8ff', '#4f9f6b', '#c3a6ff', '#f2b45a', '#ff7b63', '#97e6eb', '#3b40d2', '#f05cc8'];

  async function load() {
    const [sheet, prims, gr] = await Promise.all([api(`sheets/${SHEET}/`), api(`sheets/${SHEET}/primitives/`), api(`sheets/${SHEET}/graph/`)]);
    const [tax, props, versions, models] = await Promise.all([api(`datasets/${sheet.dataset_id}/taxonomy/`), api(`datasets/${sheet.dataset_id}/proposals/?sheet=${SHEET}&status=pending`), api(`sheets/${SHEET}/graph/versions/`), api('models/')]);
    Object.assign(S, { sheet, prims: prims.primitives, gr, graph: gr.graph, tax, props, versions, models });
    tax.classes.filter((c) => c.kind === 'node' || c.kind === 'edge').forEach((c, i) => (S.colors[c.kind + ':' + c.name] = c.color || FALLBACK[i % FALLBACK.length]));
    S.primById = Object.fromEntries(S.prims.map((p) => [p.id, p]));
    reindex();
    render();
  }
  function reindex() {
    S.nodeById = Object.fromEntries(S.graph.nodes.map((n) => [n.id, n]));
    S.adj = {};
    S.graph.edges.forEach((e) => { (S.adj[e.source] ||= []).push(e); (S.adj[e.target] ||= []).push(e); });
    S.nodeOfPrim = {};
    S.graph.nodes.forEach((n) => (n.primitive_ids || [n.id]).forEach((p) => (S.nodeOfPrim[p] = n.id)));
  }
  const nodeColor = (n) => (n.label ? S.colors['node:' + n.label] || '#c3a6ff' : 'var(--faint)');
  const center = (n) => { const b = n.bbox; return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]; };
  function markHuman(item) { item.provenance = 'human'; item.review = 'approved'; item.confidence = null; S.dirty = true; }

  // ------------------------------------------------------------------ layout
  let svg, gPrims, gEdges, gOverlay, panel, mini, vb;
  function render() {
    const { sheet } = S;
    vb = { x: 0, y: 0, w: sheet.width, h: sheet.height };
    svg = svgEl('svg', { class: 'plan', viewBox: `0 0 ${sheet.width} ${sheet.height}`, preserveAspectRatio: 'xMidYMid meet' });
    svg.appendChild(svgEl('rect', { x: 0, y: 0, width: sheet.width, height: sheet.height, fill: '#ffffff' }));
    svg.appendChild(svgEl('image', { href: sheet.image_url, x: 0, y: 0, width: sheet.width, height: sheet.height, opacity: 0.35 }));
    gPrims = svgEl('g', {}); gEdges = svgEl('g', {}); gOverlay = svgEl('g', {});
    svg.append(gEdges, gPrims, gOverlay);
    S.prims.forEach((p) => {
      const pts = p.pts_px.map((q) => q.join(',')).join(' ');
      let el;
      if (p.type === 'text') { const [x0, y0, x1, y1] = p.bbox; el = svgEl('rect', { x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0), class: 'prim prim-text' }); }
      else if (p.closed || p.type === 'rect' || p.type === 'circle') el = svgEl('polygon', { points: pts, class: 'prim' });
      else el = svgEl('polyline', { points: pts, class: 'prim' });
      el.dataset.pid = p.id;
      el.appendChild(svgEl('title', {}, `${p.id} · ${p.type}${p.text ? ' · ' + p.text : ''}${p.layer ? ' · layer ' + p.layer : ''}`));
      p._el = el;
      gPrims.appendChild(el);
    });
    svg.addEventListener('click', onClick);
    enablePanZoom();
    const toolbar = h('div.toolbar', {},
      h('button.ot-btn.sm', { onclick: () => { vb = { x: 0, y: 0, w: S.sheet.width, h: S.sheet.height }; applyVB(); } }, 'Fit'),
      h('select', { onchange: (e) => { S.showEdges = e.target.value; drawEdges(); } }, [['selection', 'Edges: selection'], ['labeled', 'Edges: labeled'], ['all', 'Edges: all candidates'], ['none', 'Edges: hidden']].map(([v, t]) => h('option', { value: v }, t))),
      h('a.ot-btn.sm', { href: `/ka/projects/${S.sheet.dataset_id}/` }, '← Plan set'));
    const legend = h('div.legend', {});
    mini = h('canvas.minigraph', { width: 600, height: 420, title: 'Object graph (click a node to select its primitives)' });
    mini.addEventListener('click', onMiniClick);
    panel = h('div.panel', {});
    const wrap = h('div.canvas-wrap', {}, svg, toolbar, legend, mini);
    const root = document.getElementById('ka-root');
    root.style.maxWidth = 'none';
    const body = document.getElementById('ka-body'); if (body) body.style.padding = '0';
    mount(h('div.studio', {}, wrap, panel));
    S.legend = legend;
    paint();
    renderPanel();
    document.addEventListener('keydown', onKey);
    window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });
  }
  function applyVB() { svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); }
  function enablePanZoom() {
    let drag = null;
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = svg.getBoundingClientRect(); const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      const scale = Math.max(vb.w / r.width, vb.h / r.height);
      const mx = vb.x + (e.clientX - r.left - (r.width - vb.w / scale) / 2) * scale, my = vb.y + (e.clientY - r.top - (r.height - vb.h / scale) / 2) * scale;
      vb = { x: mx - (mx - vb.x) * k, y: my - (my - vb.y) * k, w: vb.w * k, h: vb.h * k }; applyVB();
    }, { passive: false });
    svg.addEventListener('mousedown', (e) => { if (e.button !== 0) return; drag = { x: e.clientX, y: e.clientY, vb: { ...vb }, moved: false }; });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return; const r = svg.getBoundingClientRect(); const scale = Math.max(vb.w / r.width, vb.h / r.height);
      const dx = (e.clientX - drag.x) * scale, dy = (e.clientY - drag.y) * scale;
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 3) { drag.moved = true; svg.classList.add('panning'); }
      if (drag.moved) { vb = { ...drag.vb, x: drag.vb.x - dx, y: drag.vb.y - dy }; applyVB(); }
    });
    window.addEventListener('mouseup', () => { if (drag?.moved) svg.dataset.justPanned = '1'; drag = null; svg.classList.remove('panning'); });
  }

  // ------------------------------------------------------------------ painting
  function paint() {
    const counts = {};
    S.graph.nodes.forEach((n) => (counts[n.label || 'unlabeled'] = (counts[n.label || 'unlabeled'] || 0) + 1));
    S.prims.forEach((p) => {
      const n = S.nodeById[S.nodeOfPrim[p.id]];
      const el = p._el;
      if (!n) { el.style.stroke = '#bbb'; el.classList.add('dim'); return; }
      let c = nodeColor(n);
      if (S.compare && S.compare[n.id] && n.label && S.compare[n.id].label !== n.label) c = '#ff2d2d';
      el.style.stroke = c; if (n.type === 'text') el.style.fill = c;
      el.classList.toggle('sel', S.sel.has(n.id));
      el.classList.toggle('dim', !!S.filter && (n.label || 'unlabeled') !== S.filter);
      el.style.strokeDasharray = n.provenance === 'raster_inferred' ? '4 3' : (n.provenance === 'agent' ? '2 2' : '');
    });
    S.legend.replaceChildren(...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => h('span.chip' + (S.filter === k ? '.accent' : ''), { onclick: () => { S.filter = S.filter === k ? null : k; paint(); } },
      h('span.swatch', { style: { background: k === 'unlabeled' ? 'var(--faint)' : S.colors['node:' + k] || '#c3a6ff' } }), `${k} · ${v}`)),
    ...(S.compare ? [h('span.chip.danger', {}, h('span.swatch', { style: { background: '#ff2d2d' } }), 'prediction ≠ label')] : []));
    drawEdges();
    drawMini();
  }
  function drawEdges() {
    gEdges.replaceChildren();
    let es = [];
    if (S.showEdges === 'all') es = S.graph.edges;
    else if (S.showEdges === 'labeled') es = S.graph.edges.filter((e) => e.label && e.label !== 'none');
    else if (S.showEdges === 'selection') es = [...S.sel].flatMap((id) => S.adj[id] || []);
    es.slice(0, 6000).forEach((e) => {
      const a = S.nodeById[e.source], b = S.nodeById[e.target]; if (!a || !b) return;
      const [x1, y1] = center(a), [x2, y2] = center(b);
      gEdges.appendChild(svgEl('line', { x1, y1, x2, y2, class: 'edge-line', stroke: e.label ? S.colors['edge:' + e.label] || '#c3a6ff' : '#9ba4a1', 'stroke-dasharray': e.label ? '' : '3 3' }));
    });
  }
  // object-level graph: groups (object_uid) or single labeled nodes become graph nodes; labeled relations become links
  function objectGraph() {
    const key = (n) => n.object_uid || n.id;
    const objs = {};
    S.graph.nodes.forEach((n) => { if (!n.label || n.label === 'other') return; const k = key(n); (objs[k] ||= { id: k, label: n.label, members: [], x: 0, y: 0 }).members.push(n.id); });
    const links = {};
    S.graph.edges.forEach((e) => {
      if (!e.label || e.label === 'none' || e.label === 'same_object') return;
      const a = S.nodeById[e.source], b = S.nodeById[e.target]; if (!a || !b) return;
      const ka = key(a), kb = key(b); if (ka === kb || !objs[ka] || !objs[kb]) return;
      links[[ka, kb].sort().join('|') + e.label] = { a: ka, b: kb, label: e.label };
    });
    const list = Object.values(objs);
    list.forEach((o) => { const cs = o.members.map((m) => center(S.nodeById[m])); o.x = cs.reduce((s, c) => s + c[0], 0) / cs.length; o.y = cs.reduce((s, c) => s + c[1], 0) / cs.length; });
    return { objs: list, links: Object.values(links) };
  }
  function drawMini() {
    const ctx = mini.getContext('2d');
    const W = mini.width, H = mini.height;
    ctx.clearRect(0, 0, W, H);
    const { objs, links } = objectGraph();
    S.mini = objs;
    if (!objs.length) { ctx.fillStyle = '#9ba4a1'; ctx.font = '22px Inter Tight, sans-serif'; ctx.fillText('Label & group nodes to see the object graph', 20, H / 2); return; }
    // geometry-anchored layout (keeps drawing ↔ graph orientation), then light repulsion
    const sx = (W - 40) / S.sheet.width, sy = (H - 40) / S.sheet.height, s = Math.min(sx, sy);
    objs.forEach((o) => { o.px = 20 + o.x * s; o.py = 20 + o.y * s; });
    for (let it = 0; it < 30; it++) for (let i = 0; i < objs.length; i++) for (let j = i + 1; j < objs.length; j++) {
      const a = objs[i], b = objs[j]; const dx = b.px - a.px, dy = b.py - a.py, d = Math.hypot(dx, dy) || 1;
      if (d < 14) { const f = (14 - d) / 2 / d; a.px -= dx * f; a.py -= dy * f; b.px += dx * f; b.py += dy * f; }
    }
    const byId = Object.fromEntries(objs.map((o) => [o.id, o]));
    links.forEach((l) => { const a = byId[l.a], b = byId[l.b]; ctx.strokeStyle = S.colors['edge:' + l.label] || '#c3a6ff'; ctx.globalAlpha = 0.7; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py); ctx.stroke(); });
    ctx.globalAlpha = 1;
    objs.forEach((o) => {
      const on = o.members.some((m) => S.sel.has(m));
      ctx.fillStyle = S.colors['node:' + o.label] || '#c3a6ff'; ctx.beginPath(); ctx.arc(o.px, o.py, on ? 9 : 5, 0, Math.PI * 2); ctx.fill();
      if (on) { ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 3; ctx.stroke(); }
    });
    ctx.fillStyle = '#9ba4a1'; ctx.font = '20px Space Mono, monospace'; ctx.fillText(`${objs.length} objects · ${links.length} relations`, 14, H - 12);
  }
  function onMiniClick(e) {
    const r = mini.getBoundingClientRect(); const x = ((e.clientX - r.left) / r.width) * mini.width, y = ((e.clientY - r.top) / r.height) * mini.height;
    let best = null, bd = 400;
    (S.mini || []).forEach((o) => { const d = (o.px - x) ** 2 + (o.py - y) ** 2; if (d < bd) { bd = d; best = o; } });
    if (!best) return;
    if (!e.shiftKey) S.sel.clear();
    best.members.forEach((m) => S.sel.add(m));
    paint(); renderPanel();
  }

  // ------------------------------------------------------------------ interaction
  function onClick(e) {
    if (svg.dataset.justPanned) { delete svg.dataset.justPanned; return; }
    const pid = e.target?.dataset?.pid;
    if (!pid) { if (!e.shiftKey) { S.sel.clear(); paint(); renderPanel(); } return; }
    const nid = S.nodeOfPrim[pid]; if (!nid) return;
    const n = S.nodeById[nid];
    if (e.altKey && n.object_uid) { // select whole object
      if (!e.shiftKey) S.sel.clear();
      S.graph.nodes.filter((m) => m.object_uid === n.object_uid).forEach((m) => S.sel.add(m.id));
    } else if (e.shiftKey) { S.sel.has(nid) ? S.sel.delete(nid) : S.sel.add(nid); }
    else { S.sel.clear(); S.sel.add(nid); }
    paint(); renderPanel();
  }
  function onKey(e) {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
    const nodeClasses = S.gr.node_classes;
    if (/^[1-9]$/.test(e.key) && nodeClasses[Number(e.key) - 1]) { setLabel(nodeClasses[Number(e.key) - 1]); e.preventDefault(); }
    else if (e.key === 'g') groupSel();
    else if (e.key === 'u') ungroupSel();
    else if (e.key === 'Delete' || e.key === 'Backspace') { deleteSel(); e.preventDefault(); }
    else if (e.key === 'Escape') { S.sel.clear(); paint(); renderPanel(); }
    else if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(); }
  }
  function setLabel(label) {
    if (!S.sel.size) return toast('Select nodes first (click; shift-click to add; alt-click selects an object)', 'warn');
    S.sel.forEach((id) => { const n = S.nodeById[id]; n.label = label; markHuman(n); });
    paint(); renderPanel();
  }
  function groupSel() {
    if (S.sel.size < 1) return;
    const uid = 'obj_' + Math.random().toString(36).slice(2, 10);
    const ids = [...S.sel];
    ids.forEach((id) => { S.nodeById[id].object_uid = uid; markHuman(S.nodeById[id]); });
    // candidate edges inside the group become same_object
    S.graph.edges.forEach((e) => { if (S.sel.has(e.source) && S.sel.has(e.target)) { e.label = 'same_object'; markHuman(e); } });
    toast(`Grouped ${ids.length} primitives into ${uid}`, 'positive');
    paint(); renderPanel();
  }
  function ungroupSel() {
    S.sel.forEach((id) => { const n = S.nodeById[id]; n.object_uid = null; markHuman(n); });
    S.graph.edges.forEach((e) => { if ((S.sel.has(e.source) || S.sel.has(e.target)) && e.label === 'same_object') { e.label = 'none'; markHuman(e); } });
    paint(); renderPanel();
  }
  function deleteSel() {
    if (!S.sel.size) return;
    const kill = new Set(S.sel);
    S.graph.nodes = S.graph.nodes.filter((n) => !kill.has(n.id));
    S.graph.edges = S.graph.edges.filter((e) => !kill.has(e.source) && !kill.has(e.target));
    S.sel.clear(); S.dirty = true; reindex(); paint(); renderPanel();
    toast(`Removed ${kill.size} node(s) from the graph (source geometry is unchanged)`, 'warn');
  }
  function addEdge(label) {
    const ids = [...S.sel]; if (ids.length !== 2) return toast('Select exactly two nodes', 'warn');
    const [a, b] = ids;
    let e = S.graph.edges.find((x) => (x.source === a && x.target === b) || (x.source === b && x.target === a));
    if (!e) { e = { id: 'eh' + Date.now().toString(36), source: a, target: b, type: 'near', label, directed: false, features: [0, 0, 0, 1, 0, 0, 0, 0, 0], provenance: 'human', review: 'approved', confidence: null }; S.graph.edges.push(e); }
    e.label = label; markHuman(e); reindex(); paint(); renderPanel();
  }
  function addNode() {
    if (!S.sel.size) return toast('Select the primitives the new semantic node should reference', 'warn');
    const members = [...S.sel].map((id) => S.nodeById[id]);
    const bb = members.reduce((b, n) => [Math.min(b[0], n.bbox[0]), Math.min(b[1], n.bbox[1]), Math.max(b[2], n.bbox[2]), Math.max(b[3], n.bbox[3])], [Infinity, Infinity, -Infinity, -Infinity]);
    const id = 'sem_' + Math.random().toString(36).slice(2, 9);
    const feat = new Array(members[0].features.length).fill(0); feat[3] = 1;
    S.graph.nodes.push({ id, type: 'polyline', label: members[0].label, primitive_ids: members.flatMap((m) => m.primitive_ids || [m.id]), object_uid: members[0].object_uid, bbox: bb, features: feat, provenance: 'human', review: 'approved', semantic: true });
    members.forEach((m) => S.graph.edges.push({ id: 'eh' + Math.random().toString(36).slice(2, 9), source: id, target: m.id, type: 'near', label: 'contained_in', directed: true, features: [0, 0, 0, 1, 0, 0, 0, 0, 0], provenance: 'human', review: 'approved' }));
    S.dirty = true; reindex(); S.sel = new Set([id]); paint(); renderPanel();
  }
  async function save() {
    const msg = h('input', { type: 'text', placeholder: 'What changed?' });
    if (!(await dialog(`Save graph as v${S.gr.version + 1}`, h('label.field', {}, h('span.caption', {}, 'Message'), msg), [{ label: 'Save version', primary: true }]))) return;
    try {
      const r = await api(`sheets/${SHEET}/graph/`, { method: 'POST', body: { graph: S.graph, base_version: S.gr.version, message: msg.value } });
      S.dirty = false; toast(`Saved v${r.version} (${r.stats.labeled_nodes} labeled nodes)`, 'positive'); load();
    } catch (e) {
      if (e.status === 400 && e.data?.issues) { S.issues = e.data.issues; renderPanel(); toast('Fix validation errors before saving', 'danger'); } else toast(e.message, 'danger');
    }
  }

  // ------------------------------------------------------------------ panel
  function renderPanel() {
    const nodeClasses = S.gr.node_classes, edgeClasses = S.gr.edge_classes;
    const sel = [...S.sel].map((id) => S.nodeById[id]).filter(Boolean);
    const one = sel.length === 1 ? sel[0] : null;
    const st = S.gr.stats;
    const issues = S.issues || S.gr.issues || [];
    panel.replaceChildren(
      h('section', {}, h('div.row', {}, h('h2', {}, S.sheet.name.slice(0, 40)), chip(S.gr.review_status)),
        h('div.faint.mono', { style: { fontSize: '11px' } }, `graph v${S.gr.version} · ${st.nodes} nodes · ${st.edges} edges · ${st.labeled_nodes} labeled · ${st.objects} objects`),
        S.sheet.has_vector ? null : h('div.notice', {}, 'Raster sheet: lines were inferred from pixels (dashed) and are NOT verified CAD geometry.'),
        h('div.row.gap4', {}, h('button.ot-btn.sm.primary', { onclick: save }, S.dirty ? 'Save version •' : 'Save version'),
          h('button.ot-btn.sm', { onclick: async () => { if (S.dirty) return toast('Save first', 'warn'); try { await api(`sheets/${SHEET}/graph/review/`, { method: 'POST', body: { status: 'approved' } }); toast('Graph approved for training', 'positive'); load(); } catch (e) { S.issues = e.data?.issues; renderPanel(); toast(e.message, 'danger'); } } }, 'Approve graph'),
          h('button.ot-btn.sm', { onclick: async () => { await guard(() => api(`sheets/${SHEET}/graph/review/`, { method: 'POST', body: { status: 'rejected' } }), 'Graph rejected'); load(); } }, 'Reject'))),
      h('section', {}, h('div.caption', {}, `Selection · ${sel.length}`),
        h('div.row.gap4.wrap', {}, nodeClasses.map((c, i) => h('button.ot-btn.sm', { onclick: () => setLabel(c), title: `key ${i + 1}` }, h('span.swatch', { style: { background: S.colors['node:' + c] } }), `${i + 1} ${c}`))),
        h('div.row.gap4.wrap', {}, h('button.ot-btn.sm', { onclick: groupSel }, 'Group (g)'), h('button.ot-btn.sm', { onclick: ungroupSel }, 'Ungroup (u)'), h('button.ot-btn.sm', { onclick: addNode }, 'Add semantic node'), h('button.ot-btn.sm.danger', { onclick: deleteSel }, 'Remove (Del)')),
        sel.length === 2 ? h('div.row.gap4.wrap', {}, h('span.faint', { style: { fontSize: '12px' } }, 'Add / set relation:'), edgeClasses.map((c) => h('button.ot-btn.sm', { onclick: () => addEdge(c) }, c))) : null,
        one ? inspector(one, edgeClasses) : sel.length ? h('div.faint', { style: { fontSize: '12px' } }, sel.map((n) => n.id).slice(0, 30).join(', ')) : h('div.faint', { style: { fontSize: '12px' } }, 'Click a primitive. Shift-click adds, alt-click selects its object, wheel zooms, drag pans. Keys 1–9 assign labels.')),
      h('section', {}, h('div.caption', {}, 'Bulk'), h('div.row.gap4.wrap', {},
        h('button.ot-btn.sm', { onclick: () => { let n = 0; S.graph.edges.forEach((e) => { const a = S.nodeById[e.source], b = S.nodeById[e.target]; if (a?.object_uid && a.object_uid === b?.object_uid && e.label !== 'same_object') { e.label = 'same_object'; markHuman(e); n++; } }); toast(`${n} edges → same_object`); paint(); } }, 'Group edges → same_object'),
        h('button.ot-btn.sm', { onclick: () => { let n = 0; S.graph.edges.forEach((e) => { if (!e.label) { e.label = 'none'; markHuman(e); n++; } }); toast(`${n} unlabeled candidate edges → none`); paint(); } }, 'Unlabeled edges → none'),
        h('button.ot-btn.sm', { onclick: () => { let n = 0; S.graph.nodes.forEach((x) => { if (!x.label) { x.label = 'other'; markHuman(x); n++; } }); toast(`${n} nodes → other`); paint(); renderPanel(); } }, 'Unlabeled nodes → other'))),
      h('section', {}, h('div.row', {}, h('div.caption', {}, `Agent proposals · ${S.props.filter((p) => ['node_label', 'group'].includes(p.kind)).length}`),
        h('button.ot-btn.sm.right', { onclick: async () => { if (S.dirty) return toast('Save first', 'warn'); await guard(() => api(`datasets/${S.sheet.dataset_id}/agent/propose-graph/`, { method: 'POST', body: { sheet_id: SHEET } }), 'Geometry agent proposed labels'); load(); } }, 'Run geometry agent')),
        proposalList()),
      h('section', {}, h('div.caption', {}, 'Compare with a model'), compareBox()),
      h('section', {}, h('div.caption', {}, `Validation · ${issues.length}`), issues.length ? issues.slice(0, 20).map((i) => h('div.notice' + (i.severity === 'error' ? '.err' : i.severity === 'info' ? '.info' : ''), { style: { cursor: i.ids?.length ? 'pointer' : 'default' }, onclick: () => { const ids = (i.ids || []).filter((x) => S.nodeById[x]); if (ids.length) { S.sel = new Set(ids); paint(); renderPanel(); } } }, h('b', {}, i.code), ' ', i.message)) : h('div.faint', {}, 'No issues.')),
      h('section', {}, h('div.caption', {}, 'Versions'), ...S.versions.slice(0, 12).map((v) => h('div.row', { style: { fontSize: '12px' } }, h('span.mono', {}, 'v' + v.version), h('span.tag', {}, v.source), chip(v.review_status), h('span.faint', {}, v.message || ''), h('span.faint.right', {}, KA.fmt.ago(v.created_at))))));
  }
  function inspector(n, edgeClasses) {
    const prim = S.primById[(n.primitive_ids || [])[0]];
    const edges = S.adj[n.id] || [];
    const featNames = ['line', 'curve', 'arc', 'polyline', 'rect', 'circle', 'text', 'length', 'sin2θ', 'cos2θ', 'bbox_w', 'bbox_h', 'stroke', 'closed', 'degree', 'raster', 'n_pts'];
    return h('div.grid', { style: { gap: '8px' } },
      h('dl.kv', {}, [['id', n.id], ['type', n.type], ['label', n.label || '—'], ['object', n.object_uid || '—'], ['provenance', n.provenance], ['review', n.review], ['confidence', n.confidence ?? '—'], ['text', n.text || prim?.text || '—'], ['layer', n.layer || prim?.layer || '—'],
        ['primitives', (n.primitive_ids || []).join(', ')], ['source pts', prim ? JSON.stringify(prim.pts.slice(0, 2)) + (prim.pts.length > 2 ? '…' : '') : '—']].map(([k, v]) => [h('dt', {}, k), h('dd.mono', { style: { fontSize: '11.5px' } }, String(v))])),
      h('details', {}, h('summary', { style: { fontSize: '12px' } }, 'Node features'), h('div.mono', { style: { fontSize: '11px' } }, n.features.map((f, i) => `${featNames[i] || i}=${Number(f).toFixed(2)}`).join('  '))),
      h('div.caption', {}, `Edges · ${edges.length}`),
      ...edges.slice(0, 40).map((e) => {
        const other = e.source === n.id ? e.target : e.source;
        const s = h('select', { style: { minHeight: '28px', padding: '2px 6px' }, onchange: (ev) => { e.label = ev.target.value || null; markHuman(e); paint(); } }, h('option', { value: '' }, '— unlabeled —'), edgeClasses.map((c) => h('option', { value: c, selected: e.label === c }, c)));
        return h('div.row.gap4', { style: { fontSize: '12px' } }, h('a', { href: '#', onclick: (ev) => { ev.preventDefault(); S.sel = new Set([other]); paint(); renderPanel(); } }, other), h('span.tag', {}, e.type), s,
          h('button.ot-btn.sm.ghost', { title: 'Remove edge', onclick: () => { S.graph.edges = S.graph.edges.filter((x) => x !== e); S.dirty = true; reindex(); paint(); renderPanel(); } }, '×'));
      }));
  }
  function proposalList() {
    const ps = S.props.filter((p) => ['node_label', 'group'].includes(p.kind));
    if (!ps.length) return h('div.faint', { style: { fontSize: '12px' } }, 'None pending. Proposals are suggestions only; accepted ones are recorded with provenance.');
    const minc = h('input', { type: 'number', step: '0.05', value: 0.7, style: { width: '80px' } });
    const byLabel = {}; ps.forEach((p) => (byLabel[p.payload.label] = (byLabel[p.payload.label] || 0) + 1));
    return h('div.grid', { style: { gap: '6px' } },
      h('div.row.gap4', {}, Object.entries(byLabel).map(([k, v]) => h('span.chip', {}, h('span.swatch', { style: { background: S.colors['node:' + k] } }), `${k} · ${v}`))),
      h('div.row.gap4', {}, h('span.faint', { style: { fontSize: '12px' } }, 'min confidence'), minc,
        h('button.ot-btn.sm.primary', { onclick: async () => { if (S.dirty) return toast('Save first', 'warn'); const r = await guard(() => api(`sheets/${SHEET}/proposals/apply/`, { method: 'POST', body: { min_confidence: Number(minc.value), accept: true } })); toast(`Applied ${r.applied} proposals → graph v${r.graph_version}`, 'positive'); load(); } }, 'Accept ≥'),
        h('button.ot-btn.sm', { onclick: async () => { const r = await guard(() => api(`sheets/${SHEET}/proposals/apply/`, { method: 'POST', body: { accept: false } })); toast(`Rejected ${r.applied}`); load(); } }, 'Reject all')),
      ...ps.slice(0, 25).map((p) => h('div.row.gap4', { style: { fontSize: '12px', cursor: 'pointer' }, onclick: () => { S.sel = new Set(p.payload.node_ids.filter((x) => S.nodeById[x])); paint(); renderPanel(); } },
        h('span.swatch', { style: { background: S.colors['node:' + p.payload.label] } }), h('b', {}, p.payload.label), h('span.faint', {}, `${p.payload.node_ids.length} · ${(p.confidence || 0).toFixed(2)} · ${p.evidence.rule || p.agent}`),
        h('button.ot-btn.sm.ghost.right', { onclick: async (ev) => { ev.stopPropagation(); if (S.dirty) return toast('Save first', 'warn'); await guard(() => api(`proposals/${p.id}/review/`, { method: 'POST', body: { action: 'accept' } })); load(); } }, '✓'),
        h('button.ot-btn.sm.ghost', { onclick: async (ev) => { ev.stopPropagation(); await guard(() => api(`proposals/${p.id}/review/`, { method: 'POST', body: { action: 'reject' } })); load(); } }, '×'))));
  }
  function compareBox() {
    const mvs = S.models.flatMap((m) => m.versions).filter((v) => v.task === 'node_classification' && v.status === 'ready');
    if (!mvs.length) return h('div.faint', { style: { fontSize: '12px' } }, 'Train a node-classification model to compare predictions with ground truth here.');
    const sel = h('select', {}, mvs.map((v) => h('option', { value: v.id }, `${v.model_name} v${v.version}`)));
    const out = h('div.faint', { style: { fontSize: '12px' } });
    return h('div.grid', { style: { gap: '6px' } }, h('div.row.gap4', {}, sel, h('button.ot-btn.sm', { onclick: async () => {
      const r = await guard(() => api(`model-versions/${sel.value}/predict/`, { method: 'POST', body: { graph: S.graph } }));
      S.compare = Object.fromEntries(r.nodes.map((n) => [n.id, n]));
      const labeled = S.graph.nodes.filter((n) => n.label && S.compare[n.id]); const ok = labeled.filter((n) => S.compare[n.id].label === n.label).length;
      out.textContent = `Agreement with current labels: ${ok}/${labeled.length} (${labeled.length ? ((ok / labeled.length) * 100).toFixed(1) : 0}%). Mismatches are red.`;
      paint();
    } }, 'Compare'), h('button.ot-btn.sm.ghost', { onclick: () => { S.compare = null; out.textContent = ''; paint(); } }, 'Clear')), out);
  }

  load().catch((e) => mount(empty('Could not open Graph Studio', e.message, null, 'error')));
})();
