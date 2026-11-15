/* Kentucky AI model studio — UI. Vanilla JS; every piece of user/drawing data is inserted as text (never innerHTML). */
(function () {
  'use strict';
  const KA = (window.KA = {});
  const page = document.body.dataset.page;
  const PK = document.body.dataset.pk;

  // ------------------------------------------------------------------ core
  const cookie = (n) => (document.cookie.match(new RegExp('(?:^|; )' + n + '=([^;]*)')) || [])[1] || '';
  async function api(path, opts = {}) {
    const o = { method: opts.method || 'GET', headers: { 'X-CSRFToken': decodeURIComponent(cookie('csrftoken')) }, credentials: 'same-origin' };
    if (opts.body instanceof FormData) o.body = opts.body;
    else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; }
    const r = await fetch('/api/ka/' + path, o);
    let data = null;
    try { data = await r.json(); } catch (e) { /* empty */ }
    if (!r.ok) {
      const msg = data ? (data.detail || data.error?.message || Object.values(data).flat().join(' ')) : r.statusText;
      const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)); err.status = r.status; err.data = data; throw err;
    }
    return data;
  }
  const SVG_TAGS = ['svg', 'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'g', 'text', 'image', 'title', 'defs', 'pattern'];
  function h(tag, attrs, ...kids) {
    const [t, ...cls] = tag.split('.');
    const svg = SVG_TAGS.includes(t) || attrs?.svg;
    const el = svg ? document.createElementNS('http://www.w3.org/2000/svg', t) : document.createElement(t || 'div');
    if (cls.length) el.setAttribute('class', cls.join(' '));
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false || k === 'svg') continue;
      if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.setAttribute('class', ((el.getAttribute('class') || '') + ' ' + v).trim());
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const k of kids.flat(Infinity)) if (k !== null && k !== undefined && k !== false) el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    return el;
  }
  const svgEl = (t, a, ...k) => h(t, { ...a, svg: true }, ...k);
  function toast(msg, tone, action) {
    const t = h('div.toast' + (tone ? '.' + tone : ''), {}, h('span', { style: { flex: 1 } }, msg), action ? h('button.btn.sm', { onclick: () => { action.run(); t.remove(); } }, action.label) : null);
    document.getElementById('ka-toasts').appendChild(t);
    setTimeout(() => t.remove(), tone === 'danger' ? 9000 : 6000);
  }
  function dialog(title, body, actions, kicker) {
    return new Promise((resolve) => {
      const close = (v) => { s.remove(); document.removeEventListener('keydown', key); resolve(v); };
      const key = (e) => { if (e.key === 'Escape') close(null); };
      document.addEventListener('keydown', key);
      const s = h('div.scrim', { onclick: (e) => { if (e.target === s) close(null); } },
        h('div.dialog', { role: 'dialog', 'aria-modal': 'true' }, kicker ? h('div.kicker', {}, kicker) : null, h('div.h2', {}, title), body,
          h('div.row', { style: { justifyContent: 'flex-end', marginTop: '6px' } }, h('button.btn.ghost', { onclick: () => close(null) }, actions && actions.length ? 'Cancel' : 'Close'),
            ...(actions || []).map((a) => h('button.btn' + (a.primary ? '.primary' : '') + (a.danger ? '.danger' : ''), { onclick: () => close(a.value ?? true) }, a.label)))));
      document.body.appendChild(s);
      s.querySelector('input,select,textarea')?.focus();
    });
  }
  async function guard(fn, ok) { try { const r = await fn(); if (ok) toast(ok, 'pos'); return r; } catch (e) { toast(e.message || String(e), 'danger'); throw e; } }
  const fmt = {
    n: (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
    usd: (v) => (v === null || v === undefined ? '—' : '$' + Number(v).toFixed(2)),
    date: (v) => (v ? new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'),
    ago: (v) => { if (!v) return 'never'; const s = (Date.now() - new Date(v)) / 1000; return s < 60 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : s < 86400 ? Math.round(s / 3600) + ' h ago' : Math.round(s / 86400) + ' d ago'; },
    dur: (s) => (s === null || s === undefined ? '—' : s < 60 ? Math.round(s) + ' sec' : s < 3600 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1) + ' h'),
  };
  const ICON = {
    upload: 'M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3',
    spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z',
    pen: 'M4 20l4-1 11-11-3-3L5 16zM14 6l3 3',
    plus: 'M12 5v14M5 12h14',
    key: 'M15 7a4 4 0 1 1-3.5 6L5 19.5V22H2.5v-2.5L9 13a4 4 0 0 1 6-6zM16 8h.01',
  };
  const icon = (n, size = 18) => svgEl('svg', { viewBox: '0 0 24 24', width: size, height: size, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, svgEl('path', { d: ICON[n] }));
  const arrow = () => h('span.arrow', {}, '→');
  const chip = (text, tone, pulse) => h('span.chip' + (tone ? '.' + tone : '') + (pulse ? '.pulse' : ''), {}, h('span.dot'), text);
  function sheetFrame(content, tb) {
    return h('section.sheet', {}, h('span.ticks', {}, h('i'), h('i'), h('i'), h('i')), h('div.sheet-in', {}, h('div', {}, content),
      h('aside.titleblock', {}, h('div.grid', { style: { gap: '16px' } }, tb.rows.map(([k, v]) => h('div.key', {}, k, h('b', {}, v)))), h('div.sheet-no', {}, tb.no))));
  }
  function empty(title, body, action, drawing = true) {
    return h('div.empty', {}, drawing ? svgEl('svg', { viewBox: '0 0 200 120' }, svgEl('rect', { x: 10, y: 10, width: 180, height: 100, rx: 2 }),
      svgEl('path', { d: 'M10 78h58V40h56v38h66M68 40V10M124 58h66M96 78v32' }), svgEl('path', { class: 'a', d: 'M68 40h56v38H68z' })) : null,
    h('div.t', {}, title), body ? h('div.b', {}, body) : null, action || null);
  }
  function setTop(crumbs, actions) {
    const c = document.getElementById('ka-crumbs');
    if (c) c.replaceChildren(...crumbs.flatMap((x, i) => [i ? h('span.faint', {}, '/') : null, typeof x === 'string' ? h('b', {}, x) : h('a', { href: x[1] }, x[0])]).filter(Boolean));
    const a = document.getElementById('ka-top-actions');
    if (a) a.replaceChildren(...(actions || []).filter(Boolean));
  }
  const mount = (...n) => document.getElementById('ka-root').replaceChildren(...n.flat().filter(Boolean));
  const head = (kicker, title, accent, lede, actions) => h('div.pagehead', {}, h('div', {}, h('h1.h1', {}, title, accent || ''), lede ? h('p.lede', {}, lede) : null),
    actions ? h('div.actions', {}, actions) : null);
  const LABEL = { semantic_segmentation: 'Plan outlines', instance_segmentation: 'Item outlines', node_classification: 'Line by line', edge_classification: 'Connections' };
  const STATUS = {
    CREATED: ['Waiting for your OK', 'warn'], VALIDATING: ['Checking', 'cyan'], QUEUED: ['In line', 'cyan'], PROVISIONING: ['Starting up', 'cyan'], PREPARING: ['Getting ready', 'cyan'],
    TRAINING: ['Learning', 'cyan'], EVALUATING: ['Testing', 'cyan'], SAVING: ['Saving', 'cyan'], COMPLETED: ['Ready', 'pos'], FAILED: ['Stopped — error', 'danger'],
    CANCELLED: ['Cancelled', 'warn'], TIMED_OUT: ['Ran out of time', 'danger'],
  };
  const ACTIVE = ['TRAINING', 'EVALUATING', 'PREPARING', 'PROVISIONING', 'QUEUED', 'SAVING'];
  const jobChip = (s) => chip((STATUS[s] || [s])[0], (STATUS[s] || [])[1], ACTIVE.includes(s));
  const nice = (s) => (s || '').replace(/\.(pdf|png|jpe?g|dxf)/i, '').replace(/ - Page (\d+)$/, ' · p$1').replace(/ - Model space$/, '').replace(/ - Image$/, '');
  const cap = (s) => s[0].toUpperCase() + s.slice(1).replace(/_/g, ' ');
  Object.assign(KA, { api, h, svgEl, toast, dialog, guard, fmt, chip, empty, mount, icon, setTop, sheetFrame, jobChip, LABEL, nice, cap });

  // nav + theme
  const NAV = { markup: 'home', home: 'home', project: 'home', train: 'home', run: 'models', models: 'models', deployments: 'deployments', apikeys: 'apikeys', api: 'api', billing: 'billing', team: 'team' };
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('on', a.dataset.nav === NAV[page]));
  // theme: Light / Dark (remembered per browser); the review canvas follows it too
  KA.setTheme = (t) => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('ka-theme', t); } catch (e) { /* ignore */ }
    document.querySelectorAll('[data-t]').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
  };
  KA.theme = () => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  document.querySelectorAll('#ka-theme [data-t]').forEach((b) => b.addEventListener('click', () => KA.setTheme(b.dataset.t)));
  KA.setTheme(KA.theme());

  const P = (KA.PAGES = {});
  function tile(k, v, d, good, onclick) {
    return h('div.tile' + (onclick ? '.click' : ''), { onclick }, h('div.key', {}, k), h('div.v' + (String(v).length > 7 ? '.sm' : ''), { style: good ? { color: 'var(--scan-ink)' } : {} }, v), h('div.d', {}, d));
  }

  // ================================================================== shared visual pieces
  const COLORS = { wall: '#62d4dc', door: '#f0b24a', window: '#8fa8ff', room: '#7fcf9c', room_tag: '#7fcf9c', other: '#848e8b' };
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  const niceItem = (k) => ({ room_tag: 'room name', hvac_equipment: 'HVAC unit', electrical_device: 'electrical device', plumbing_fixture: 'plumbing fixture', structural_member: 'structural member', floor_finish: 'flooring area' }[k] || k.replace(/_/g, ' '));
  // graphite drawing panel with crop marks + title strip; overlays model predictions with a scan + draw-in
  function darkDrawing(sheet, preds, strip) {
    const panel = h('div.panel-dark', {}, h('span.crop', {}, h('i'), h('i'), h('i'), h('i')), strip ? h('div.titlestrip', {}, strip) : null);
    if (!sheet) return panel;
    const svg = svgEl('svg', { viewBox: `0 0 ${sheet.width} ${sheet.height}`, preserveAspectRatio: 'xMidYMid meet' },
      svgEl('image', { class: 'sheet-img', href: sheet.image_url, x: 0, y: 0, width: sheet.width, height: sheet.height }));
    (preds || []).forEach((p, i) => svg.appendChild(svgEl('polygon', { class: 'pred', points: p.polygon.map((q) => q.join(',')).join(' '), fill: COLORS[p.label] || '#62d4dc', stroke: COLORS[p.label] || '#62d4dc', style: `animation-delay:${Math.min(i * 15, 900)}ms` })));
    panel.append(h('div.drawing', {}, svg));
    if (preds && preds.length) panel.append(h('div.scanline'));
    return panel;
  }
  function headx(title, lede, actions, kicker) {
    return h('div.pagehead', {}, h('div', {}, kicker ? h('div.kicker', { style: { marginBottom: '8px' } }, kicker) : null, h('h1.h1', {}, title), lede ? h('p.lede', {}, lede) : null),
      actions ? h('div.actions', {}, actions) : null);
  }

  // ================================================================== Plan sets (home)
  P.home = async () => {
    const [ds, dash, ms, deps] = await Promise.all([api('datasets/'), api('dashboard/'), api('models/'), api('deployments/')]);
    setTop(['Plan sets']);
    if (!ds.length) return firstRun();
    const best = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m }))).filter((v) => v.report && v.task === 'semantic_segmentation').sort((a, b) => b.report.score - a.report.score)[0];
    const d0 = ds[0];
    const sheets = await api(`datasets/${(best?.dataset_id) || d0.id}/sheets/`);
    const sheet = sheets[0];
    // what's next
    let title, lede, action;
    const live = deps.find((x) => x.status === 'active');
    if (live) { title = 'Your model is live.'; lede = `${live.name} is answering requests. ${fmt.n(live.request_count)} so far.`; action = h('a.btn.primary.lg', { href: '/ka/deployments/' }, 'Open deployment ', arrow()); }
    else if (best?.report?.ready_to_use) { title = 'Your model is ready to go live.'; lede = best.report.sentence; action = h('button.btn.primary.lg', { onclick: () => deployDialog(best.id, `${niceItem(best.report.items[0].key)} model`) }, 'Put it to work ', arrow()); }
    else if (dash.objects_approved > 0) { title = 'Ready to train your first model.'; lede = `${fmt.n(dash.objects_approved)} checked labels across your plans.`; action = h('a.btn.primary.lg', { href: `/ka/train/?dataset=${d0.id}` }, 'Train model ', arrow()); }
    else if (dash.sheets > 0) { title = 'Show the AI what to find.'; lede = 'Outline walls, doors and windows on a couple of sheets — or let AI take a first pass and you keep what is right.'; action = h('a.btn.primary.lg', { href: `/ka/markup/${sheet?.id}/` }, 'Start labeling ', arrow()); }
    else { title = 'Add your plans.'; lede = 'Drop PDFs, scans or DXF into a plan set.'; action = h('a.btn.primary.lg', { href: `/ka/projects/${d0.id}/` }, 'Add plans ', arrow()); }
    const panel = darkDrawing(sheet, [], sheet ? `${nice(sheet.name)} · ${best ? 'Model v' + best.version : 'Plan'}` : null);
    const hero = h('section.hero', {}, h('div.hero-copy', {}, h('h1.h1', {}, title), h('p.lede', {}, lede), h('div.actions', {}, action, best ? h('a.btn.ghost', { href: `/ka/runs/${best.training_job}/` }, 'See accuracy') : null)), panel);
    if (best && sheet) api(`model-versions/${best.id}/predict/`, { method: 'POST', body: { sheet_id: sheet.id } }).then((r) => panel.replaceWith(darkDrawing(sheet, r.predictions, `${nice(sheet.name)} · model v${best.version}`))).catch(() => {});
    const cards = ds.map((d) => {
      const steps = [d.sheets > 0, d.objects > 0, d.objects > 0 && d.approved === d.objects, d.versions > 0];
      return h('a.pcard', { href: `/ka/projects/${d.id}/` }, h('div.pthumb', { style: d.cover ? { backgroundImage: `url(${d.cover})` } : {} }),
        h('div.pbody', {}, h('div.t', {}, d.name), h('div.s', {}, `${plural(d.sheets, 'sheet')} · ${d.approved === d.objects && d.objects ? 'ready to train' : d.objects ? `${fmt.n(d.objects - d.approved)} to check` : 'not labeled yet'}`),
          h('div.pfoot', {}, h('span.minibar', { title: 'Upload · Label · Check · Train' }, steps.map((s) => h('i' + (s ? '.on' : '')))), h('span.faint.small', {}, fmt.ago(d.updated_at || d.created_at)))));
    });
    mount(hero, h('div.section-h', {}, h('div.h2', {}, 'Plan sets'), h('span.faint', {}, plural(ds.length, 'set'))), h('div.grid.g3', {}, cards, dropCard()));
  };
  function dropCard(datasetId) {
    const input = h('input', { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.dxf', style: { display: 'none' } });
    const card = h('button.pcard.ghost', { onclick: () => input.click() }, h('div', {}, svgEl('svg', { viewBox: '0 0 24 24' }, svgEl('path', { d: 'M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3' })),
      h('div.t', {}, datasetId ? 'Add plans' : 'New plan set'), h('div.s', {}, 'Drop PDFs, scans or DXF')), input);
    wireDrop(card, input, datasetId);
    return card;
  }
  function wireDrop(el, input, datasetId) {
    const go = async (files) => {
      if (!files.length) return;
      el.classList.add('over');
      const t = el.querySelector('.t'); if (t) t.textContent = `Reading ${plural(files.length, 'file')}…`;
      let id = datasetId;
      try {
        if (!id) { const d = await api('datasets/', { method: 'POST', body: { name: files[0].name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' '), classes: ['wall', 'door', 'window', 'room'] } }); id = d.id; }
        const fd = new FormData(); [...files].forEach((f) => fd.append('file', f));
        const res = await api(`datasets/${id}/documents/`, { method: 'POST', body: fd });
        const bad = res.filter((r) => r.status !== 'ready');
        bad.forEach((r) => toast(`${r.filename}: ${r.error}`, 'danger'));
        if (!datasetId) { location.href = `/ka/projects/${id}/`; return; }
        toast(`${plural(res.reduce((a, r) => a + (r.sheets?.length || 0), 0), 'sheet')} added`, 'pos');
      } catch (e) { toast(e.message, 'danger'); }
      P[page]();
    };
    input.onchange = () => go(input.files);
    el.ondragover = (e) => { e.preventDefault(); el.classList.add('over'); };
    el.ondragleave = () => el.classList.remove('over');
    el.ondrop = (e) => { e.preventDefault(); go(e.dataTransfer.files); };
  }
  function firstRun() {
    const input = h('input', { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.dxf', style: { display: 'none' } });
    const zone = h('div.drop-all', { onclick: () => input.click() }, h('div', {}, svgEl('svg', { viewBox: '0 0 200 120', width: 200, height: 120, style: 'stroke:var(--ink-3);stroke-width:1.4;fill:none' }, svgEl('rect', { x: 10, y: 10, width: 180, height: 100, rx: 2 }), svgEl('path', { d: 'M10 78h58V40h56v38h66M68 40V10M124 58h66' }), svgEl('path', { d: 'M68 40h56v38H68z', style: 'stroke:var(--teal)' })),
      h('h1.h1', { style: { marginTop: '18px' } }, 'Drop your plans to start'), h('p.lede', { style: { margin: '8px auto 20px' } }, 'PDF, scans or DXF. We read every page, find the lines and text, and get it ready to label.'), h('span.btn.primary.lg', {}, 'Choose files')), input);
    wireDrop(zone, input, null);
    mount(zone);
  }

  // ================================================================== Plan set (dataset)
  P.project = async () => {
    const id = PK;
    const [d, sheets, ready, jobs, pending] = await Promise.all([api(`datasets/${id}/`), api(`datasets/${id}/sheets/`), api(`datasets/${id}/readiness/`), api(`jobs/?dataset=${id}`), api(`datasets/${id}/objects/?status=pending`)]);
    const st = ready.stats, counts = st.class_counts;
    const cv = d.taxonomy.filter((c) => c.kind === 'cv' && c.name !== 'unknown');
    const used = cv.filter((c) => counts[c.name]);
    const canTrain = !!ready.ready_for.semantic_segmentation;
    setTop([['Plan sets', '/ka/'], d.name]);
    const pendingBy = {}; pending.forEach((o) => (pendingBy[o.sheet_id] = (pendingBy[o.sheet_id] || 0) + 1));
    const firstToLabel = sheets.find((s) => !s.objects) || sheets[0];
    const chips = (used.length ? used : cv.slice(0, 4)).map((c) => h('span.chip', {}, h('span.swatch', { style: { background: c.color } }), `${cap(niceItem(c.name))}s ${fmt.n(counts[c.name] || 0)}`));
    const sheetCards = sheets.map((s) => h('a.pcard', { href: `/ka/markup/${s.id}/` }, h('div.pthumb.sq', { style: { backgroundImage: `url(${s.image_url})` } }),
      h('span.corner', {}, pendingBy[s.id] ? chip(`${pendingBy[s.id]} to review`, 'warn') : s.objects ? chip('✓ labeled', 'pos') : chip('not labeled')),
      h('div.pbody', {}, h('div.t', { title: s.name }, nice(s.name)), h('div.s', {}, `${s.has_vector ? 'Vector' : 'Scan'} · ${plural(s.objects, 'label')}`))));
    // readiness bar
    const short = used.filter((c) => (counts[c.name] || 0) < 3);
    let msg, act;
    if (!sheets.length) { msg = [h('b', {}, 'Add plans to get started.')]; act = null; }
    else if (!st.objects_total) { msg = [h('b', {}, 'Label a couple of sheets.'), h('span.m', {}, ' Outline items, or let AI take a first pass.')]; act = h('a.btn.primary', { href: `/ka/markup/${firstToLabel.id}/` }, 'Start labeling ', arrow()); }
    else if (pending.length) { msg = [h('b', {}, `${plural(pending.length, 'label')} to check.`), h('span.m', {}, ' Only checked labels are used to train.')]; act = h('button.btn.primary', { onclick: async () => { await guard(() => api(`datasets/${id}/objects/review/`, { method: 'POST', body: { ids: pending.map((o) => o.id), status: 'approved' } }), 'Labels checked'); P.project(); } }, 'Approve all ', arrow()); }
    else if (!canTrain) { msg = [h('b', {}, 'Almost ready.'), h('span.m', {}, short.length ? ` Add ${short.map((c) => `${3 - (counts[c.name] || 0)} more ${niceItem(c.name)}s`).join(', ')} — or label one more sheet.` : ' Label at least 2 sheets.')]; act = h('a.btn.primary', { href: `/ka/markup/${firstToLabel.id}/` }, 'Keep labeling ', arrow()); }
    else { msg = [h('b', {}, 'Ready to train.'), h('span.m', {}, ` ${fmt.n(st.approved)} checked labels on ${plural(sheets.filter((s) => s.objects).length, 'sheet')}.`)]; act = h('a.btn.primary', { href: `/ka/train/?dataset=${id}` }, 'Train model ', arrow()); }
    const pct = Math.round((Math.min(st.approved, 60) / 60) * 100);
    const ring = svgEl('svg', { class: 'ring', viewBox: '0 0 36 36' }, svgEl('circle', { cx: 18, cy: 18, r: 15, fill: 'none', stroke: 'rgba(236,238,233,.15)', 'stroke-width': 4 }),
      svgEl('circle', { cx: 18, cy: 18, r: 15, fill: 'none', stroke: '#62d4dc', 'stroke-width': 4, 'stroke-dasharray': `${(canTrain ? 100 : pct) * 0.94} 100`, transform: 'rotate(-90 18 18)', 'stroke-linecap': 'round' }));
    mount(
      headx(d.name, null, [firstToLabel ? h('a.btn', { href: `/ka/markup/${firstToLabel.id}/` }, 'Label') : null, h(canTrain ? 'a.btn.primary' : 'a.btn', { href: canTrain ? `/ka/train/?dataset=${id}` : '#' }, 'Train model')]),
      h('div.chips', { style: { marginTop: '-16px' } }, chips, cv.length > used.length && used.length ? h('span.chip', { title: cv.filter((c) => !counts[c.name]).map((c) => c.name).join(', ') }, `+${cv.length - used.length} more types`) : null),
      h('div.grid.g4', {}, sheetCards, dropCard(id)),
      h('div.readybar', {}, ring, h('div', {}, msg), h('div.right', {}, act)));
  };

  // ================================================================== Train (one decision, cost up front)
  P.train = async () => {
    const qs = new URLSearchParams(location.search);
    const ds = await api('datasets/');
    let pick = qs.get('dataset') || (ds[0] && String(ds[0].id));
    let goal = 'outlines', speed = 'cpu-local', est = null;
    setTop([['Models', '/ka/models/'], 'Train']);
    const root = h('div.narrow');
    const ill = (kind) => svgEl('svg', { viewBox: '0 0 48 34' }, kind === 'outlines'
      ? [svgEl('rect', { x: 4, y: 4, width: 40, height: 26, fill: 'none', stroke: '#2b373c' }), svgEl('rect', { x: 8, y: 8, width: 14, height: 18, fill: 'rgba(98,212,220,.2)', stroke: '#62d4dc' }), svgEl('rect', { x: 26, y: 14, width: 10, height: 8, fill: 'rgba(240,178,74,.25)', stroke: '#f0b24a' })]
      : [svgEl('path', { d: 'M6 28V6h36v22M6 17h16M22 6v22', fill: 'none', stroke: '#62d4dc', 'stroke-width': 1.5 }), svgEl('circle', { cx: 22, cy: 17, r: 2, fill: '#f0b24a' }), svgEl('circle', { cx: 6, cy: 17, r: 2, fill: '#f0b24a' })]);
    const render = async () => {
      const d = ds.find((x) => String(x.id) === String(pick));
      if (!est || est._k !== `${pick}:${goal}`) { try { est = await api(`datasets/${pick}/estimate/?goal=${goal}`); est._k = `${pick}:${goal}`; } catch (e) { est = null; } }
      const e = est?.[speed];
      const free = e && Number(e.customer_cost_high) === 0;
      const sel = h('select', { style: { width: 'auto', height: '30px', display: 'inline-block', marginLeft: '6px' }, onchange: (ev) => { pick = ev.target.value; render(); } }, ds.map((x) => h('option', { value: x.id, selected: String(x.id) === String(pick) }, x.name)));
      root.replaceChildren(
        h('div', {}, h('h1.h1', {}, 'Train a model'), h('p.lede', {}, 'Training on', sel)),
        h('div', {}, h('div.h3', { style: { marginBottom: '12px' } }, 'What should it find?'), h('div.grid', { style: { gap: '12px' } },
          h('button.choice' + (goal === 'outlines' ? '.on' : ''), { onclick: () => { goal = 'outlines'; render(); } }, h('span.ill', {}, ill('outlines')), h('div', {}, h('b', {}, 'Outline walls, doors & windows'), h('span', {}, 'Works on vector PDFs and scans'))),
          h('button.choice' + (goal === 'structure' ? '.on' : ''), { onclick: () => { goal = 'structure'; render(); } }, h('span.ill', {}, ill('structure')), h('div', {}, h('b', {}, 'Trace every line'), h('span', {}, 'Names each line on vector PDFs and CAD'))))),
        h('div', {}, h('div.h3', { style: { marginBottom: '12px' } }, 'How fast?'), h('div.seg', {}, [['cpu-local', 'Standard'], ['nvidia-t4', 'Fast'], ['nvidia-a10g', 'Fastest']].map(([k, t]) => {
          const x = est?.[k];
          return h('button' + (speed === k ? '.on' : ''), { onclick: () => { speed = k; render(); } }, h('b', {}, t), h('small', {}, x ? `${Number(x.customer_cost_high) === 0 ? 'Included' : '~' + fmt.usd((Number(x.customer_cost_low) + Number(x.customer_cost_high)) / 2)} · ~${fmt.dur((x.seconds_low + x.seconds_high) / 2)}` : '…'));
        }))),
        h('div', {}, h('button.btn.primary.lg.w100', { disabled: !d || !e, onclick: () => start(d, e) }, e ? `Start training · ~${fmt.dur((e.seconds_low + e.seconds_high) / 2)} · ${free ? '$0' : 'up to ' + fmt.usd(e.max_charge_at_runtime_limit)}` : 'Start training'),
          h('p.faint.small', { style: { textAlign: 'center', marginTop: '10px' } }, free ? 'Included in your plan. You can leave while it trains.' : 'Billed by the minute. You approve the maximum before it starts.')));
    };
    async function start(d, e) {
      if (Number(e.customer_cost_high) > 0 && !(await dialog('Approve the cost', h('p.muted', {}, `This run uses a cloud GPU. You will be charged for the time used, never more than ${fmt.usd(e.max_charge_at_runtime_limit)}.`), [{ label: `Approve up to ${fmt.usd(e.max_charge_at_runtime_limit)}`, primary: true }]))) return;
      const r = await guard(() => api(`datasets/${d.id}/train/`, { method: 'POST', body: { goal, gpu_type: speed } }));
      if (!r.ready) return dialog('Not quite ready', h('div.grid', { style: { gap: '12px' } }, h('p.muted', { style: { margin: 0 } }, goal === 'structure' ? 'Line tracing needs at least 2 sheets labeled and approved line by line.' : 'The model needs at least 2 labeled sheets and 3 checked examples of each item.'), h('a.btn.primary', { href: `/ka/projects/${d.id}/` }, 'Open the plan set')), []);
      if (r.job.status === 'FAILED') return toast(r.job.error, 'danger');
      await guard(() => api(`jobs/${r.job.id}/authorize/`, { method: 'POST', body: { confirm: true } }));
      location.href = `/ka/runs/${r.job.id}/`;
    }
    mount(ds.length ? root : empty('No plan sets yet', 'Add and label some plans first.', h('a.btn.primary', { href: '/ka/' }, 'Add plans')));
    if (ds.length) render();
  };

  // ================================================================== Training run → accuracy
  P.run = async () => {
    const j = await api(`jobs/${PK}/`);
    const active = ACTIVE.includes(j.status) || j.status === 'VALIDATING';
    const name = `${LABEL[j.task] || 'Model'} · run ${j.id}`;
    setTop([['Models', '/ka/models/'], name]);
    if (active) {
      const hist = j.metrics_history.filter((m) => m.epoch);
      const total = j.config?.epochs || 1, ep = hist.length ? hist[hist.length - 1].epoch : 0;
      const stage = { QUEUED: 'Waiting for a server', PROVISIONING: 'Starting a server', PREPARING: 'Reading your plans and labels', TRAINING: 'Studying your examples', EVALUATING: 'Testing on plans it has never seen', SAVING: 'Saving your model' }[j.status] || 'Getting ready';
      const pct = j.status === 'TRAINING' ? Math.max(6, (ep / total) * 86) : { EVALUATING: 92, SAVING: 97 }[j.status] || 3;
      const left = j.started_at && pct > 8 ? ((Date.now() - new Date(j.started_at)) / 1000) * (100 / pct - 1) : null;
      mount(h('section.hero', {}, h('div.hero-copy', {}, h('div.kicker', {}, 'Training'), h('h1.h1', { style: { marginTop: '6px' } }, stage),
        h('p.lede', {}, left ? `About ${fmt.dur(left)} left. You can leave — it keeps going.` : 'You can leave — it keeps going.'), h('div.progress-big', { style: { marginTop: '22px' } }, h('i', { style: { width: pct + '%' } })),
        h('div.actions', {}, h('button.btn.ghost', { onclick: async () => { if (await dialog('Stop training?', h('p.muted', {}, 'You only pay for the time used so far.'), [{ label: 'Stop', danger: true }])) { await guard(() => api(`jobs/${j.id}/cancel/`, { method: 'POST', body: {} })); P.run(); } } }, 'Stop'))),
      darkDrawing(null, [], `Run ${j.id} · ${ep}/${total}`)));
      setTimeout(() => { if (document.body.dataset.page === 'run') P.run(); }, 2500);
      return;
    }
    if (j.status !== 'COMPLETED') {
      mount(headx(name), h('div.card', {}, empty(STATUS[j.status][0], j.status === 'CREATED' ? 'This run is waiting for your approval.' : (j.error || '').split('\n')[0], h('a.btn.primary', { href: `/ka/train/?dataset=${j.dataset_id}` }, 'Try again'), false)), techDetails(j));
      return;
    }
    const rc = j.report || { items: [], sentence: '' };
    const items = rc.items.filter((i) => !/unrelated|other/.test(i.name)).slice(0, 3);
    const deploy = j.model_version && rc.ready_to_use ? h('button.btn.primary.lg', { onclick: () => deployDialog(j.model_version, `${cap(items.map((i) => i.name).join(' & '))} model`) }, 'Put it to work ', arrow()) : null;
    mount(
      headx(rc.ready_to_use ? 'Ready to put to work.' : 'Not ready yet.', `${rc.sentence} Tested on plans it never saw while learning.`, [h('a.btn', { href: `/ka/projects/${j.dataset_id}/` }, 'Add examples'), deploy]),
      j.model_version ? compareView(j) : null,
      h('div.stats3', {}, items.map((i) => h('div.stat', {}, h('div', {}, h('span.big', {}, i.found ?? Math.round(i.score * 10)), h('span.of', {}, ` / ${i.total ?? 10}`)), h('div.what', {}, `${cap(i.name)} found`),
        h('div.meter' + ({ fair: '.warn', weak: '.danger' }[i.level] || ''), {}, h('i', { style: { width: Math.round(i.score * 100) + '%' } }))))),
      techDetails(j));
  };
  function compareView(j) {
    const box = h('div.compare', {}, h('div.skeleton', { style: { position: 'absolute', inset: 0, opacity: .1 } }));
    (async () => {
      const sheets = await api(`datasets/${j.dataset_id}/sheets/`);
      const order = (j.eval_sheets || []).map((id) => sheets.find((s) => s.id === id)).filter(Boolean).concat(sheets);
      const show = async (s) => {
        const [objs, pred] = await Promise.all([api(`datasets/${j.dataset_id}/objects/?sheet=${s.id}&status=approved`), api(`model-versions/${j.model_version}/predict/`, { method: 'POST', body: { sheet_id: s.id, allow_raster_inferred: true } })]);
        const layer = (polys, cls) => h('div.layer' + cls, {}, svgEl('svg', { viewBox: `0 0 ${s.width} ${s.height}`, preserveAspectRatio: 'xMidYMid meet' },
          svgEl('image', { href: s.image_url, x: 0, y: 0, width: s.width, height: s.height, style: 'filter:invert(1) hue-rotate(180deg) brightness(.9);opacity:.55' }),
          polys.map((p, i) => svgEl('polygon', { class: 'pred', points: p.polygon.map((q) => q.join(',')).join(' '), fill: COLORS[p.label] || '#62d4dc', stroke: COLORS[p.label] || '#62d4dc', style: `animation-delay:${Math.min(i * 12, 700)}ms` }))));
        const before = layer(objs.filter((o) => o.geometry.polygon).map((o) => ({ polygon: o.geometry.polygon, label: o.label })), '.before');
        const after = layer(pred.predictions || [], '.after');
        const handle = h('div.handle');
        const sel = h('select', { onchange: (e) => show(order.find((x) => String(x.id) === e.target.value)) }, [...new Map(order.map((x) => [x.id, x])).values()].map((x) => h('option', { value: x.id, selected: x.id === s.id }, `${nice(x.name)}${(j.eval_sheets || []).includes(x.id) ? ' · never seen' : ''}`)));
        box.replaceChildren(before, after, h('span.lab.l', {}, 'Your labels'), h('span.lab.r', {}, 'Model found'), handle, sel);
        const move = (x) => { const r = box.getBoundingClientRect(); const f = Math.min(1, Math.max(0, (x - r.left) / r.width)); after.style.clipPath = `inset(0 0 0 ${f * 100}%)`; handle.style.left = f * 100 + '%'; };
        let drag = false;
        box.onmousedown = (e) => { drag = true; move(e.clientX); }; window.addEventListener('mouseup', () => (drag = false)); box.onmousemove = (e) => drag && move(e.clientX);
        box.ontouchmove = (e) => move(e.touches[0].clientX);
      };
      if (order[0]) show(order[0]);
    })().catch((e) => box.replaceChildren(h('div.notice.err', { style: { margin: '20px' } }, e.message)));
    return box;
  }
  function techDetails(j) {
    const fm = j.final_metrics || {};
    return h('details.tech', {}, h('summary', {}, 'Technical details'), h('div', {},
      h('dl.kv', {}, [['Architecture', j.catalog_id], ['Starting point', j.init], ['Passes (epochs)', j.config?.epochs], ['Best pass', fm.best_epoch], ['Headline', JSON.stringify(fm.headline || {})], ['Runtime', fmt.dur(j.runtime_s)], ['Code version', j.code_version], ['Seed', j.seed]].map(([k, v]) => [h('dt', {}, k), h('dd.mono', {}, String(v ?? '—'))])),
      h('pre.code', { style: { marginTop: '14px', maxHeight: '300px' } }, JSON.stringify({ config: j.config, test: fm.test, val: fm.val }, null, 1))));
  }
  KA.predictionViewer = (mvId, datasetId) => compareView({ model_version: mvId, dataset_id: datasetId, eval_sheets: [] });

  async function deployDialog(mvId, name) {
    const n = h('input', { type: 'text', value: name });
    const ok = await dialog('Put this model to work', h('div.grid', { style: { gap: '16px' } },
      h('p.muted', { style: { margin: 0 } }, 'You get a private API endpoint. Your software sends a plan sheet and gets back every item with its outline. Only requests with your API key are accepted.'),
      h('label.field', {}, h('span', {}, 'Name'), n)), [{ label: 'Deploy', primary: true }]);
    if (!ok) return;
    await guard(() => api('deployments/', { method: 'POST', body: { model_version_id: mvId, name: n.value, confirm: true } }));
    location.href = '/ka/deployments/?new=1';
  }

  // ================================================================== Models (best live + version table)
  P.models = async () => {
    const [ms, jobs, deps] = await Promise.all([api('models/'), api('jobs/'), api('deployments/')]);
    setTop(['Models']);
    const running = jobs.filter((j) => ACTIVE.includes(j.status));
    const all = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m }))).filter((v) => v.report);
    const best = [...all].sort((a, b) => b.report.score - a.report.score)[0];
    const liveFor = (v) => deps.find((d) => d.active_version === v.id && d.status === 'active');
    const finds = (v) => v.report.items.filter((i) => !/unrelated|other/.test(i.name)).map((i) => i.name);
    const jobName = (v) => cap(finds(v).slice(0, 2).join(' & '));
    const hero = best ? h('section.hero', {}, h('div.hero-copy', {}, h('div.row', { style: { gap: '8px' } }, liveFor(best) ? h('span.chip.pos', {}, h('span.dot'), 'Live') : h('span.chip.cyan', {}, h('span.dot'), 'Best version'), h('span.faint.small', {}, `${LABEL[best.task]} · v${best.version}`)),
      h('h1.h1', { style: { marginTop: '10px' } }, jobName(best)), h('p.lede', {}, best.m.name.replace(/-(seg|gnn|inst)-.*/, '')),
      h('div.grid.g3', { style: { gap: '12px', marginTop: '18px' } }, best.report.items.filter((i) => !/unrelated|other/.test(i.name)).slice(0, 3).map((i) => h('div', {}, h('div', {}, h('span.mono', { style: { fontSize: '24px', fontWeight: 500 } }, i.found ?? Math.round(i.score * 10)), h('span.faint.mono', {}, ` / ${i.total ?? 10}`)), h('div.faint.small', {}, `${i.name} found`)))),
      h('div.actions', {}, liveFor(best) ? h('a.btn.lg', { href: '/ka/deployments/' }, 'Live since ' + fmt.date(liveFor(best).created_at)) : h('button.btn.primary.lg', { onclick: () => deployDialog(best.id, `${jobName(best)} model`) }, 'Put it to work ', arrow()), h('a.btn.ghost', { href: `/ka/runs/${best.training_job}/` }, 'Accuracy'))),
    darkDrawing(null, [], `Model v${best.version}`)) : null;
    if (best) api(`datasets/${best.dataset_id}/sheets/`).then(async (ss) => { const s = ss[0]; const r = await api(`model-versions/${best.id}/predict/`, { method: 'POST', body: { sheet_id: s.id } }); hero.lastChild.replaceWith(darkDrawing(s, r.predictions || [], `${nice(s.name)} · v${best.version}`)); }).catch(() => {});
    const rows = [...all].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    mount(headx('Models', null, [h('a.btn.primary', { href: '/ka/train/' }, 'Train a model')]),
      running.length ? h('div.list', {}, running.map((j) => h('a.item.click', { href: `/ka/runs/${j.id}/`, style: { textDecoration: 'none', color: 'inherit' } }, h('span.livedot'), h('div', {}, h('div.t', {}, `${LABEL[j.task]} · training`), h('div.s', {}, `Started ${fmt.ago(j.created_at)}`)), jobChip(j.status)))) : null,
      hero || h('div.card', {}, empty('No models yet', 'Label a few plans, then train your first model.', h('a.btn.primary', { href: '/ka/' }, 'Go to plan sets'), false)),
      rows.length ? h('div', {}, h('div.section-h', { style: { marginBottom: '12px' } }, h('div.h2', {}, 'All versions'), h('span.faint', {}, plural(rows.length, 'version'))),
        h('div.tablewrap', {}, h('table.table', {}, h('thead', {}, h('tr', {}, ['Model', 'Finds', 'Found', 'Trained', ''].map((x) => h('th', {}, x)))),
          h('tbody', {}, rows.map((v) => h('tr', {}, h('td', {}, h('div', { style: { fontWeight: 600 } }, `${jobName(v)} · v${v.version}`), h('div.faint.small', {}, LABEL[v.task])),
            h('td', {}, finds(v).slice(0, 3).join(', ')),
            h('td', { style: { width: '220px' } }, h('div.row', { style: { gap: '10px', flexWrap: 'nowrap' } }, h('div.meter' + (v.report.ready_to_use ? '' : '.warn'), { style: { flex: 1 } }, h('i', { style: { width: Math.round(v.report.score * 100) + '%' } })), h('span.mono.small', {}, `${Math.round(v.report.score * 100)}%`))),
            h('td.faint', { style: { whiteSpace: 'nowrap' } }, fmt.date(v.created_at)),
            h('td', { style: { textAlign: 'right', whiteSpace: 'nowrap' } }, liveFor(v) ? h('span.chip.pos', {}, h('span.dot'), 'Live') : null, h('a.btn.sm.ghost', { href: `/ka/runs/${v.training_job}/` }, 'Report'),
              v.license.commercially_deployable && v.status === 'ready' && !liveFor(v) ? h('button.btn.sm' + (v.report.ready_to_use ? '' : '.ghost'), { onclick: () => deployDialog(v.id, `${jobName(v)} model`) }, 'Deploy') : null))))))) : null);
  };

  // ================================================================== Deployments (live panel + try it)
  P.deployments = async () => {
    const [deps, ms] = await Promise.all([api('deployments/'), api('models/')]);
    setTop(['Deployments']);
    const active = deps.filter((d) => d.status !== 'deleted');
    const curl = (d) => `curl -X POST ${location.origin}${d.endpoint} \\\n  -H "Authorization: Bearer $KA_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"image": "<base64 PNG of a plan sheet>"}'`;
    const card = (d) => {
      const versions = (ms.find((m) => m.id === d.model_id)?.versions || []).filter((v) => v.license.commercially_deployable && v.status === 'ready');
      const act = async (a, body) => { await guard(() => api(`deployments/${d.id}/${a}/`, { method: 'POST', body: body || {} }), 'Updated'); P.deployments(); };
      const input = h('input', { type: 'file', accept: '.png,.jpg,.jpeg', style: { display: 'none' } });
      const out = h('div');
      const drop = h('div.trydrop', { onclick: () => input.click() }, h('b', { style: { color: '#eceee9' } }, 'Try it: drop a plan image here'), h('div.small', {}, 'PNG or JPG · runs against v' + d.active_version_number), input);
      const run = async (f) => {
        drop.classList.add('over'); out.replaceChildren(h('div.small.muted', {}, 'Reading…'));
        const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(f); });
        try {
          const r = await api(`model-versions/${d.active_version}/predict/`, { method: 'POST', body: { image: b64 } });
          const c = {}; (r.predictions || []).forEach((p) => (c[p.label] = (c[p.label] || 0) + 1));
          const url = URL.createObjectURL(f);
          const [W, H] = r.image_size;
          const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, style: { width: '100%', maxHeight: '320px', marginTop: '12px', borderRadius: '8px', background: '#fff' } }, svgEl('image', { href: url, x: 0, y: 0, width: W, height: H }),
            (r.predictions || []).map((p) => svgEl('polygon', { class: 'overlay-poly', points: p.polygon.map((q) => q.join(',')).join(' '), fill: COLORS[p.label] || '#62d4dc', stroke: COLORS[p.label] || '#62d4dc' })));
          out.replaceChildren(h('div.row', { style: { marginTop: '12px' } }, Object.entries(c).map(([k, v]) => h('span.chip', {}, h('span.swatch', { style: { background: COLORS[k] || '#62d4dc' } }), `${v} ${niceItem(k)}${v > 1 ? 's' : ''}`))), svg);
        } catch (e) { out.replaceChildren(h('div.notice.err', {}, e.message)); }
        drop.classList.remove('over');
      };
      input.onchange = () => input.files[0] && run(input.files[0]);
      drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
      drop.ondrop = (e) => { e.preventDefault(); e.dataTransfer.files[0] && run(e.dataTransfer.files[0]); };
      return h('section.live', {}, h('span.tri'),
        h('div.row', {}, d.status === 'active' ? h('span.row', { style: { gap: '8px' } }, h('span.livedot'), h('span.small', { style: { color: 'var(--cyan)', fontWeight: 600 } }, 'Live')) : h('span.chip.warn', {}, 'Paused'), h('span.muted.small', {}, `${LABEL[d.task]} · v${d.active_version_number} · ${fmt.n(d.request_count)} requests`)),
        h('div.display', { style: { marginTop: '12px' } }, d.status === 'active' ? h('span', {}, d.name, h('span.c', {}, ' is live.')) : `${d.name} is paused.`),
        h('div.grid.g2', { style: { marginTop: '24px', alignItems: 'start' } },
          h('div', {}, h('div.small.muted', { style: { marginBottom: '8px' } }, 'Endpoint'), h('pre.code', {}, `POST ${location.origin}${d.endpoint}`),
            h('div.row', { style: { marginTop: '14px' } }, h('button.btn.primary', { onclick: () => { navigator.clipboard?.writeText(curl(d)); toast('Example request copied', 'pos'); } }, 'Copy example request'), h('a.btn', { href: '/ka/api-keys/' }, 'API keys'),
              versions.length > 1 ? h('select', { style: { width: 'auto', height: '36px', background: 'transparent', color: '#eceee9', borderColor: 'rgba(236,238,233,.25)' }, onchange: (e) => act('set-version', { model_version_id: Number(e.target.value) }) }, versions.map((v) => h('option', { value: v.id, selected: v.id === d.active_version }, `v${v.version}`))) : null),
            h('div.row', { style: { marginTop: '10px' } }, d.history.length > 1 ? h('button.btn.sm', { onclick: () => act('rollback') }, 'Roll back') : null, h('button.btn.sm', { onclick: () => act(d.status === 'active' ? 'pause' : 'resume') }, d.status === 'active' ? 'Pause' : 'Resume'),
              h('button.btn.sm', { onclick: async () => { if (await dialog('Delete this deployment?', h('p.muted', {}, 'The endpoint stops answering right away. The model is kept.'), [{ label: 'Delete', danger: true }])) act('delete'); } }, 'Delete'))),
          h('div', {}, drop, out)));
    };
    mount(headx('Deployments', active.length ? null : 'A deployment turns a model into a private API your software can call.'), active.length ? active.map(card) : h('div.card', {}, empty('Nothing deployed yet', 'Open a model and choose “Put it to work”.', h('a.btn.primary', { href: '/ka/models/' }, 'See models'), false)));
  };

  // ================================================================== API keys
  P.apikeys = async () => {
    const keys = await api('api-keys/');
    const show = (r) => dialog('Copy your API key', h('div.grid', { style: { gap: '12px' } }, h('div.notice', {}, 'You will only see this once. We store a fingerprint, not the key.'),
      h('pre.code', { style: { userSelect: 'all', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '14px' } }, r.key),
      h('button.btn', { onclick: () => { navigator.clipboard?.writeText(r.key); toast('Copied', 'pos'); } }, 'Copy')), [{ label: 'Done', primary: true }]).then(() => P.apikeys());
    const create = async () => { const n = h('input', { type: 'text', placeholder: 'e.g. Estimating software' }); if (!(await dialog('New API key', h('label.field', {}, h('span', {}, 'What will use it?'), n), [{ label: 'Create key', primary: true }]))) return; show(await guard(() => api('api-keys/', { method: 'POST', body: { name: n.value || 'API key' } }))); };
    setTop(['API keys'], [h('button.btn.primary', { onclick: create }, icon('plus', 16), 'New API key')]);
    const active = keys.filter((k) => !k.revoked_at);
    mount(head('Security', 'API keys', null, 'Your software uses an API key to call your deployments. Keep them private; replace or turn one off any time.'),
      active.length ? h('div.list', {}, active.map((k) => h('div.item', {}, h('span.avatar', {}, icon('key', 18)), h('div', {}, h('div.t', {}, k.name), h('div.s.mono', {}, `${k.prefix}•••••••• · created ${fmt.date(k.created_at)} · last used ${fmt.ago(k.last_used_at)}`)),
        h('div.row', {}, h('button.btn.sm', { onclick: async () => show(await guard(() => api(`api-keys/${k.id}/rotate/`, { method: 'POST', body: {} }))) }, 'Replace'), h('button.btn.sm.danger', { onclick: async () => { if (await dialog(`Turn off “${k.name}”?`, h('div.muted', {}, 'Anything using this key stops working immediately.'), [{ label: 'Turn off', danger: true }])) { await guard(() => api(`api-keys/${k.id}/revoke/`, { method: 'POST', body: {} })); P.apikeys(); } } }, 'Turn off')))))
        : empty('No API keys yet', 'Create one when you are ready to connect your software.', h('button.btn.primary', { onclick: create }, 'New API key')),
      keys.length > active.length ? h('details.tech', {}, h('summary', {}, `Turned off · ${keys.length - active.length}`), h('div', {}, keys.filter((k) => k.revoked_at).map((k) => h('div.muted.mono', { style: { fontSize: '12.5px', padding: '4px 0' } }, `${k.name} · ${k.prefix}… · off since ${fmt.date(k.revoked_at)}`)))) : null);
  };

  // ================================================================== API docs
  P.api = async () => {
    setTop(['API docs']);
    const ex = `import base64, requests\n\nplan = base64.b64encode(open("A-101.png", "rb").read()).decode()\nr = requests.post(\n    "${location.origin}/api/ka/v1/deployments/<deployment>/predict",\n    headers={"Authorization": "Bearer <API key>"},\n    json={"image": plan},\n)\nfor item in r.json()["predictions"]:\n    print(item["label"], item["confidence"], item["bbox"])`;
    mount(head('Developers', 'API docs', null, 'One endpoint per deployment. Send a plan sheet; get back every item with its outline and position.'),
      sheetFrame([h('div.key', {}, 'Request'), h('pre.code', { style: { marginTop: '8px' } }, 'POST /api/ka/v1/deployments/{deployment}/predict\nAuthorization: Bearer <API key>\nContent-Type: application/json\n\n{ "image": "<base64 PNG or JPEG>" }        or        { "sheet_id": 42 }'),
        h('div.key', { style: { marginTop: '22px' } }, 'Response'), h('pre.code', { style: { marginTop: '8px' } }, '{\n  "predictions": [\n    { "label": "door", "confidence": 0.94,\n      "bbox": [812, 440, 61, 58],               // x, y, width, height (image pixels)\n      "polygon": [[812,440], [873,440], ...],\n      "polygon_source": [[401.2, 220.5], ...]   // original PDF points (with sheet_id)\n    }\n  ]\n}'),
        h('div.key', { style: { marginTop: '22px' } }, 'Python'), h('pre.code', { style: { marginTop: '8px' } }, ex),
        h('dl.kv', { style: { marginTop: '24px' } }, [['Errors', '400 bad input · 401 bad API key · 404 unknown deployment · 409 paused · 429 too many requests'], ['Retries', 'Send an Idempotency-Key header — a retried request is billed once'], ['Full reference', 'OpenAPI schema at /docs/api/schema/swagger-ui/']].map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))],
      { rows: [['Auth', 'Bearer API key'], ['Format', 'JSON']], no: 'KA-600' }));
  };

  // ================================================================== Billing
  P.billing = async () => {
    const b = await api('billing/');
    const a = b.account, u = b.usage;
    setTop(['Billing']);
    const capIn = h('input', { type: 'number', step: '10', value: Number(a.monthly_spend_cap_usd).toFixed(0), style: { width: '140px' } });
    const used = Number(u.month_to_date) + Number(u.reserved_for_active_jobs);
    const NAMES = { training_compute: 'Training time', training_platform_fee: 'Training runs', inference: 'API requests', hosting: 'Hosting', storage: 'Storage' };
    mount(head('Pay as you go', 'Billing'),
      h('div.tiles', {}, tile('This month', fmt.usd(u.month_to_date), 'so far'), tile('Monthly limit', fmt.usd(a.monthly_spend_cap_usd), `${Math.round((used / Math.max(Number(a.monthly_spend_cap_usd), 0.01)) * 100)}% used`), tile('Payment', a.payment_method_status === 'none' ? 'Not set' : 'Card on file', a.stripe_mode === 'not_configured' ? 'payments not connected yet' : a.stripe_mode)),
      h('div.grid.g2', {}, h('div.card', {}, h('div.h3', {}, 'Monthly limit'), h('div.muted', { style: { fontSize: '14px', margin: '6px 0 14px' } }, 'New training stops before you go over this.'),
        h('div.meter', {}, h('i', { style: { width: Math.min(100, (used / Math.max(Number(a.monthly_spend_cap_usd), 0.01)) * 100) + '%' } })),
        h('div.row', { style: { marginTop: '16px' } }, h('span.muted', {}, '$'), capIn, h('button.btn', { onclick: async () => { await guard(() => api('billing/', { method: 'PATCH', body: { monthly_spend_cap_usd: capIn.value } }), 'Limit saved'); P.billing(); } }, 'Save'))),
      h('div.card', {}, h('div.h3', {}, 'What you used'), h('div', { style: { marginTop: '10px' } }, Object.keys(u.by_kind).length ? Object.entries(u.by_kind).map(([k, v]) => h('div.bar-row', {}, h('span', {}, NAMES[k] || k), h('div.meter', {}, h('i', { style: { width: Math.min(100, (Number(v.charge) / Math.max(Number(u.total_charge), 0.01)) * 100) + '%' } })), h('span.mono', {}, fmt.usd(v.charge)))) : h('div.muted', {}, 'Nothing billed yet.')))),
      b.history.length ? h('div.list', {}, h('table.table', {}, h('thead', {}, h('tr', {}, ['Date', 'What', 'Amount'].map((x) => h('th', {}, x)))), h('tbody', {}, b.history.slice(0, 50).map((e) => h('tr', {}, h('td', {}, fmt.date(e.created_at)), h('td', {}, e.description || NAMES[e.kind]), h('td.n', {}, fmt.usd(e.customer_charge_usd))))))) : null,
      b.pricing.placeholder ? h('div.notice', {}, 'Prices are placeholders while payments are being set up. Nothing is charged until payments are connected.') : null);
  };

  // ================================================================== Team & settings
  P.team = async () => {
    const [o, ds, logs] = await Promise.all([api('org/'), api('datasets/'), api('audit/')]);
    setTop(['Team & settings']);
    mount(head(o.title, 'Team & settings'),
      h('div.grid.g2', { style: { alignItems: 'start' } },
        h('div.card', {}, h('div.h3', {}, 'Team'), h('div.list', { style: { marginTop: '14px' } }, o.members.map((m) => h('div.item', {}, h('span.avatar', {}, m.email.slice(0, 2).toUpperCase()), h('div', {}, h('div.t', {}, m.email), h('div.s', {}, m.is_owner ? 'Owner' : 'Member')), h('span'))))),
        h('div.card', {}, h('div.h3', {}, 'Your data'), h('div.muted', { style: { fontSize: '14px', margin: '6px 0 14px' } }, 'Your plans are private to your company. Kentucky AI never uses them to train its own models unless you turn it on for a dataset.'),
          ds.map((d) => h('div.check', {}, h('input', { type: 'checkbox', checked: d.allow_ka_model_training, onchange: async (e) => { await guard(() => api(`datasets/${d.id}/`, { method: 'PATCH', body: { allow_ka_model_training: e.target.checked } }), 'Saved'); } }),
            h('div', {}, h('div.t', {}, d.name), h('div.s', {}, 'Allow Kentucky AI to learn from this dataset')),
            h('button.btn.sm.danger', { onclick: async () => { if (await dialog(`Delete “${d.name}”?`, h('div.muted', {}, 'Deletes the plans, labels and exports for good. Trained models are kept until you archive them.'), [{ label: 'Delete for good', danger: true }])) { await guard(() => api(`datasets/${d.id}/`, { method: 'DELETE' }), 'Deleted'); P.team(); } } }, 'Delete'))))),
      h('details.tech', {}, h('summary', {}, 'Activity log'), h('div', {}, h('table.table', {}, h('tbody', {}, logs.slice(0, 80).map((a) => h('tr', {}, h('td', {}, fmt.ago(a.created_at)), h('td.n', {}, a.action), h('td', {}, a.actor || a.api_key || '—'))))))));
  };

  // ------------------------------------------------------------------ boot
  Object.assign(KA, { wireDrop, deployDialog, compareView, techDetails, COLORS, niceItem, plural, arrow, headx, ACTIVE, STATUS });
  // boot after every page script has registered (flow.js overrides some pages)
  setTimeout(() => {
    const run = P[page];
    if (run) run().catch((e) => { console.error(e); mount(empty('Something went wrong', e.message, h('button.btn', { onclick: () => location.reload() }, 'Try again'))); });
  }, 0);
})();
