/* Kentucky AI platform UI. Vanilla JS; all user/drawing data is inserted as text nodes (never innerHTML). */
(function () {
  'use strict';
  const KA = (window.KA = {});
  const $root = () => document.getElementById('ka-root');
  const page = document.body.dataset.page;
  const PK = document.body.dataset.pk;

  // ------------------------------------------------------------------ core
  function cookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }
  async function api(path, opts = {}) {
    const o = { method: opts.method || 'GET', headers: { 'X-CSRFToken': cookie('csrftoken') }, credentials: 'same-origin' };
    if (opts.body instanceof FormData) o.body = opts.body;
    else if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; }
    const r = await fetch('/api/ka/' + path, o);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      const msg = data ? (data.detail || data.error?.message || Object.entries(data).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : (typeof v === 'object' ? JSON.stringify(v) : v)}`).join('; ')) : r.statusText;
      const err = new Error(msg); err.status = r.status; err.data = data; throw err;
    }
    return data;
  }
  function h(tag, attrs, ...kids) {
    const [t, ...cls] = tag.split('.');
    const el = t === 'svg' || attrs?.svg ? document.createElementNS('http://www.w3.org/2000/svg', t) : document.createElement(t || 'div');
    if (cls.length) el.setAttribute('class', cls.join(' '));
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false || k === 'svg') continue;
      if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.setAttribute('class', (el.getAttribute('class') ? el.getAttribute('class') + ' ' : '') + v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const k of kids.flat(Infinity)) {
      if (k === null || k === undefined || k === false) continue;
      el.appendChild(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  function svgEl(tag, attrs, ...kids) { return h(tag, { ...attrs, svg: true }, ...kids); }
  function toast(msg, tone) {
    const t = h('div.ot-toast' + (tone ? '.is-' + tone : ''), {}, msg);
    document.getElementById('ka-toasts').appendChild(t);
    setTimeout(() => t.remove(), tone === 'danger' ? 8000 : 4000);
  }
  function dialog(title, body, actions) {
    return new Promise((resolve) => {
      const close = (v) => { scrim.remove(); resolve(v); };
      const scrim = h('div.ot-scrim', { onclick: (e) => { if (e.target === scrim) close(null); } },
        h('div.ot-dialog', { role: 'dialog', 'aria-modal': 'true' }, h('h2', {}, title), body,
          h('div.row', { style: { justifyContent: 'flex-end' } },
            h('button.ot-btn.ghost', { onclick: () => close(null) }, 'Cancel'),
            ...(actions || []).map((a) => h('button.ot-btn' + (a.primary ? '.primary' : '') + (a.danger ? '.danger' : ''), { onclick: () => close(a.value ?? true) }, a.label)))));
      document.body.appendChild(scrim);
      scrim.querySelector('input,select,textarea,button.primary')?.focus();
    });
  }
  async function guard(fn, okMsg) {
    try { const r = await fn(); if (okMsg) toast(okMsg, 'positive'); return r; } catch (e) { toast(e.message || String(e), 'danger'); throw e; }
  }
  const fmt = {
    n: (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
    pct: (v) => (v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%'),
    usd: (v) => (v === null || v === undefined ? '—' : '$' + Number(v).toFixed(Number(v) < 1 && Number(v) > 0 ? 4 : 2)),
    date: (v) => (v ? new Date(v).toLocaleString() : '—'),
    ago: (v) => { if (!v) return '—'; const s = (Date.now() - new Date(v)) / 1000; return s < 60 ? Math.round(s) + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : s < 86400 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; },
    dur: (s) => (s === null || s === undefined ? '—' : s < 60 ? s.toFixed(0) + 's' : s < 3600 ? (s / 60).toFixed(1) + 'm' : (s / 3600).toFixed(2) + 'h'),
  };
  const STATUS_TONE = { COMPLETED: 'pos', FAILED: 'danger', TIMED_OUT: 'danger', CANCELLED: 'warn', CREATED: 'warn', approved: 'pos', rejected: 'danger', pending: 'warn', ready: 'pos', active: 'pos', paused: 'warn', accepted: 'pos', modified: 'pos' };
  const chip = (s, tone) => h('span.chip' + ((tone || STATUS_TONE[s]) ? '.' + (tone || STATUS_TONE[s]) : (['TRAINING', 'EVALUATING', 'PREPARING', 'PROVISIONING', 'QUEUED', 'SAVING', 'VALIDATING'].includes(s) ? '.accent' : '')), {}, h('span.dot'), s);
  function titleBlock(lead, cells, actions) {
    return h('div.set-tb', {}, h('div.lead', {}, h('div.caption', {}, lead[0]), h('div.v', {}, lead[1])),
      ...cells.map(([k, v]) => h('div', {}, h('div.caption', {}, k), h('div.v', {}, v))), actions ? h('div.actions', {}, actions) : null);
  }
  const section = (t, ...extra) => h('div.set-h', {}, h('span.caption', {}, t), ...extra);
  function empty(title, body, action, tone) {
    return h('div.empty', { 'data-tone': tone || '' },
      svgEl('svg', { viewBox: '0 0 168 104' }, svgEl('rect', { x: 14, y: 10, width: 140, height: 84, rx: 2 }), svgEl('path', { d: 'M14 70h46V36h44v34h50M60 36V10M104 52h50' }),
        svgEl('path', { class: 'accent', d: 'M30 86 L60 56 L88 70 L138 24' })),
      h('div.t', {}, title), body ? h('div.b', {}, body) : null, action || null);
  }
  function table(cols, rows, opts = {}) {
    if (!rows.length) return opts.empty || empty('Nothing here yet', opts.emptyBody);
    return h('div.table-wrap', {}, h('table.set-table', {}, h('thead', {}, h('tr', {}, cols.map((c) => h('th', {}, c[0])))),
      h('tbody', {}, rows.map((r) => h('tr', opts.onRow ? { style: { cursor: 'pointer' }, onclick: () => opts.onRow(r) } : {},
        cols.map((c) => { const v = c[1](r); return h('td' + (c[2] ? '.' + c[2] : ''), {}, v); }))))));
  }
  function lineChart(series, opts = {}) {
    // series: [{name, color, points:[[x,y]]}]
    const W = 640, H = 220, P = { l: 44, r: 12, t: 12, b: 26 };
    const pts = series.flatMap((s) => s.points).filter((p) => p[1] !== null && p[1] !== undefined && Number.isFinite(p[1]));
    const svg = svgEl('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': opts.label || 'chart' });
    if (!pts.length) { svg.appendChild(svgEl('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }, 'No data yet')); return svg; }
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1), y0 = Math.min(0, ...ys), y1 = Math.max(...ys) * 1.05 || 1;
    const X = (x) => P.l + ((x - x0) / (x1 - x0)) * (W - P.l - P.r), Y = (y) => H - P.b - ((y - y0) / (y1 - y0)) * (H - P.t - P.b);
    svg.appendChild(svgEl('line', { class: 'axis', x1: P.l, y1: H - P.b, x2: W - P.r, y2: H - P.b }));
    svg.appendChild(svgEl('line', { class: 'axis', x1: P.l, y1: P.t, x2: P.l, y2: H - P.b }));
    for (let i = 0; i <= 4; i++) { const v = y0 + (i / 4) * (y1 - y0); svg.appendChild(svgEl('text', { x: P.l - 6, y: Y(v) + 3, 'text-anchor': 'end' }, v.toFixed(v < 1 ? 2 : 1))); }
    svg.appendChild(svgEl('text', { x: W - P.r, y: H - 6, 'text-anchor': 'end' }, opts.xlabel || 'epoch'));
    series.forEach((s) => {
      const p = s.points.filter((q) => q[1] !== null && q[1] !== undefined && Number.isFinite(q[1]));
      if (!p.length) return;
      svg.appendChild(svgEl('polyline', { points: p.map((q) => `${X(q[0])},${Y(q[1])}`).join(' '), fill: 'none', stroke: s.color, 'stroke-width': 1.6, 'vector-effect': 'non-scaling-stroke' }));
    });
    return h('div', {}, svg, h('div.row', { style: { gap: '14px', fontSize: '12px' } }, series.map((s) => h('span.row', { style: { gap: '6px' } }, h('span.swatch', { style: { background: s.color } }), s.name))));
  }
  function bars(items) { // [{label, value, max, text}]
    const max = Math.max(...items.map((i) => i.max ?? i.value), 1e-9);
    return h('div.grid', { style: { gap: '8px' } }, items.map((i) => h('div.pf-bar-row', {}, h('span.soft', {}, i.label), h('div.pf-bar', {}, h('i', { style: { width: Math.max(0, Math.min(100, (i.value / max) * 100)) + '%' } })), h('span.mono.num', { style: { textAlign: 'right', fontSize: '12px' } }, i.text ?? fmt.n(i.value, 2)))));
  }
  function confusion(m, classes) {
    if (!m || !m.length) return null;
    const max = Math.max(...m.flat(), 1);
    return h('div.table-wrap', {}, h('table.cm', { style: { borderCollapse: 'collapse' } },
      h('tr', {}, h('td', {}, 'gt\\pred'), classes.map((c) => h('td', { title: c }, c.slice(0, 6)))),
      m.map((row, i) => h('tr', {}, h('td', { title: classes[i] }, classes[i].slice(0, 8)), row.map((v, j) => h('td', { style: { background: `rgba(98,212,220,${(v / max) * 0.7})`, color: i === j ? 'var(--ink)' : 'var(--ink-soft)' } }, v))))));
  }
  Object.assign(KA, { api, h, svgEl, toast, dialog, guard, fmt, chip, table, titleBlock, section, empty, lineChart, bars, confusion });

  // ------------------------------------------------------------------ shell
  document.querySelectorAll('[data-nav]').forEach((a) => { if (a.dataset.nav === page || (page === 'dataset' && a.dataset.nav === 'datasets') || (page === 'experiment' && a.dataset.nav === 'experiments')) a.classList.add('active'); });
  document.getElementById('ka-theme')?.addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('ka-theme', next); } catch (e) { /* ignore */ }
  });
  function mount(...nodes) { const r = $root(); r.replaceChildren(...nodes.flat()); }
  KA.mount = mount;

  // ------------------------------------------------------------------ pages
  const PAGES = {};
  KA.PAGES = PAGES;

  PAGES.dashboard = async () => {
    const d = await api('dashboard/');
    const flow = [['Upload', d.sheets, 'sheets', '/ka/datasets/'], ['Label', d.objects_pending + d.objects_approved, 'objects', '/ka/datasets/'], ['Review', d.objects_pending, 'pending', '/ka/datasets/'],
      ['Agent', d.proposals_pending, 'proposals', '/ka/datasets/'], ['Train', d.jobs_active, 'active jobs', '/ka/training/'], ['Evaluate', d.jobs.length, 'recent runs', '/ka/experiments/'],
      ['Register', d.models, 'model versions', '/ka/models/'], ['Deploy', d.deployments, 'live endpoints', '/ka/deployments/']];
    mount(
      titleBlock(['Kentucky AI', 'Construction model platform'], [['Datasets', fmt.n(d.datasets)], ['Approved objects', fmt.n(d.objects_approved)], ['Month to date', fmt.usd(d.usage.month_to_date)]],
        [h('a.ot-btn', { href: '/ka/datasets/' }, 'Upload drawings'), h('a.ot-btn.primary', { href: '/ka/training/' }, 'Train a model')]),
      section('Workflow'),
      h('div.flow', {}, flow.map(([t, n, sub, href]) => h('a', { href }, h('div.mlabel', {}, t), h('div.n', {}, fmt.n(n)), h('div.muted', { style: { fontSize: '12px' } }, sub)))),
      h('div.grid.g2', {},
        h('div.card', {}, h('div.row', {}, h('h2', {}, 'Recent training'), h('a.right', { href: '/ka/experiments/' }, 'All experiments')),
          h('div', { style: { marginTop: '12px' } }, table([['Run', (j) => h('a', { href: `/ka/experiments/${j.id}/` }, j.name)], ['Status', (j) => chip(j.status)], ['Headline', (j) => headline(j.headline)]], d.jobs,
            { empty: empty('No training runs yet', 'Version a dataset, then start a run in the Training Center.', h('a.ot-btn.primary', { href: '/ka/training/' }, 'Open Training Center')) }))),
        h('div.card', {}, h('h2', {}, 'Drawings by type'), h('div', { style: { marginTop: '12px' } }, bars(Object.entries(d.documents_by_kind).map(([k, v]) => ({ label: k.replace('_', ' '), value: v, text: String(v) })))),
          h('div.mlabel', { style: { marginTop: '16px' } }, 'Usage (30 days)'), h('div', { style: { marginTop: '8px' } }, bars(Object.entries(d.usage.by_kind).map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: Number(v.charge), text: fmt.usd(v.charge) })))))),
    );
  };
  function headline(hl) {
    if (!hl) return '—';
    const [k, v] = Object.entries(hl).find(([k]) => k !== 'split' && k !== 'accuracy') || [];
    return k ? h('span.mono', {}, `${k} ${v === null ? '—' : Number(v).toFixed(3)} `, h('span.faint', {}, hl.split || '')) : '—';
  }
  KA.headline = headline;

  PAGES.datasets = async () => {
    const ds = await api('datasets/');
    const create = async () => {
      const name = h('input', { type: 'text', placeholder: 'e.g. Riverside medical office - floor plans' });
      const desc = h('textarea', { rows: 3, placeholder: 'Optional description' });
      const consent = h('input', { type: 'checkbox' });
      const ok = await dialog('New dataset', h('div.grid', {}, h('label.field', {}, h('span.caption', {}, 'Name'), name), h('label.field', {}, h('span.caption', {}, 'Description'), desc),
        h('label.row', {}, consent, h('span.soft', {}, 'Allow Kentucky AI to use this dataset to improve Kentucky AI models (off by default; recorded with timestamp).'))), [{ label: 'Create dataset', primary: true }]);
      if (!ok) return;
      const d = await guard(() => api('datasets/', { method: 'POST', body: { name: name.value, description: desc.value, allow_ka_model_training: consent.checked } }));
      location.href = `/ka/datasets/${d.id}/`;
    };
    mount(titleBlock(['Dataset Center', 'Datasets'], [['Datasets', ds.length], ['Sheets', ds.reduce((a, d) => a + d.sheets, 0)], ['Approved', ds.reduce((a, d) => a + d.approved, 0)]], [h('button.ot-btn.primary', { onclick: create }, 'New dataset')]),
      ds.length ? h('div.grid.g3', {}, ds.map((d) => h('div.card.click', { onclick: () => (location.href = `/ka/datasets/${d.id}/`) },
        h('div.row', {}, h('h2', {}, d.name), h('span.tag.right', {}, 'tax v' + d.taxonomy_version)), h('div.muted', { style: { margin: '6px 0 12px' } }, d.description || '—'),
        h('div.grid.g4', { style: { gap: '8px' } }, [['Docs', d.documents], ['Sheets', d.sheets], ['Objects', d.objects], ['Versions', d.versions]].map(([k, v]) => h('div', {}, h('div.mlabel', {}, k), h('div.mono', {}, v)))),
        h('div.pf-bar', { style: { marginTop: '12px' } }, h('i', { style: { width: (d.sheets ? (d.labeled_sheets / d.sheets) * 100 : 0) + '%' } })),
        h('div.faint', { style: { fontSize: '12px', marginTop: '4px' } }, `${d.labeled_sheets}/${d.sheets} sheets labeled · ${d.approved} approved objects`))))
        : empty('No datasets yet', 'Create a dataset, upload vector PDFs, DXF, or scanned plans, and start labeling.', h('button.ot-btn.primary', { onclick: create }, 'New dataset')));
  };

  PAGES.labeling = async () => {
    const ds = await api('datasets/');
    mount(titleBlock(['Labeling Studio', 'CV segmentation labeling'], [['Engine', 'Label Studio editor'], ['Tools', 'polygon · box · brush · keypoint']]),
      h('div.notice.info', {}, 'Segmentation labeling uses the Label Studio editor (zoom, pan, precise polygons with vertex editing, brush masks, boxes, keypoints). Agent proposals appear in the editor as predictions you accept, edit, or reject. After labeling, sync to the Dataset Center for review and versioning.'),
      table([['Dataset', (d) => d.name], ['Sheets', (d) => d.sheets, 'num'], ['Labeled', (d) => d.labeled_sheets, 'num'],
        ['Label', (d) => d.project_id ? h('a.ot-btn.sm.primary', { href: `/projects/${d.project_id}/data` }, 'Open in Label Studio') : '—'],
        ['Review', (d) => h('a.ot-btn.sm', { href: `/ka/datasets/${d.id}/#review` }, 'Review queue')]], ds));
  };

  // ------------------------------------------------------------------ dataset detail
  PAGES.dataset = async () => {
    const id = PK;
    const d = await api(`datasets/${id}/`);
    const tabs = ['sheets', 'review', 'assistant', 'quality', 'versions', 'taxonomy'];
    let cur = (location.hash || '#sheets').slice(1);
    if (!tabs.includes(cur)) cur = 'sheets';
    const body = h('div.grid', {});
    const tabEls = tabs.map((t) => h('button.tab' + (t === cur ? '.on' : ''), { onclick: () => { location.hash = t; cur = t; tabEls.forEach((x) => x.classList.toggle('on', x.textContent.toLowerCase() === t)); render(); } }, t[0].toUpperCase() + t.slice(1)));
    async function render() {
      body.replaceChildren(h('div.skeleton', { style: { height: '80px' } }));
      try { body.replaceChildren(...[].concat(await DS_TABS[cur](d, id))); } catch (e) { body.replaceChildren(empty('Could not load', e.message, null, 'error')); }
    }
    mount(titleBlock(['Dataset', d.name], [['Sheets', d.sheets], ['Objects', d.objects], ['Approved', d.approved], ['Versions', d.versions]],
      [d.label_studio_url ? h('a.ot-btn', { href: d.label_studio_url }, 'Label in Label Studio') : null, h('a.ot-btn.primary', { href: `/ka/training/?dataset=${id}` }, 'Train')]),
    h('div.tabs', {}, tabEls), body);
    render();
  };
  const DS_TABS = {};
  DS_TABS.sheets = async (d, id) => {
    const [docs, sheets] = await Promise.all([api(`datasets/${id}/documents/`), api(`datasets/${id}/sheets/`)]);
    const input = h('input', { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.dxf', style: { display: 'none' } });
    const group = h('input', { type: 'text', placeholder: 'Building / project (for leak-free splits)' });
    const drop = h('div.drop', { onclick: () => input.click() }, h('div', {}, h('b', {}, 'Drop drawings here'), ' or click to choose'), h('div.faint', { style: { fontSize: '12px', marginTop: '4px' } }, 'Vector PDF · scanned PDF · PNG · JPG · DXF (ASCII). DWG / IFC are not supported yet. Max 200 MB.'));
    const upload = async (files) => {
      if (!files.length) return;
      const fd = new FormData(); [...files].forEach((f) => fd.append('file', f)); fd.append('split_group', group.value);
      drop.classList.add('over'); drop.firstChild.textContent = `Processing ${files.length} file(s)…`;
      try {
        const res = await api(`datasets/${id}/documents/`, { method: 'POST', body: fd });
        res.forEach((r) => toast(`${r.filename}: ${r.status}${r.error ? ' — ' + r.error : ''}`, r.status === 'ready' ? 'positive' : 'danger'));
      } catch (e) { toast(e.message, 'danger'); }
      KA.PAGES.dataset();
    };
    input.addEventListener('change', () => upload(input.files));
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); upload(e.dataTransfer.files); });
    return [h('div.grid.g2', {}, h('div.grid', { style: { gap: '8px' } }, drop, input), h('div.card', {}, h('div.caption', {}, 'Split group'), h('div.faint', { style: { fontSize: '12px', margin: '4px 0 8px' } }, 'Sheets in the same group always land in the same train/val/test split.'), group)),
      section('Sheets', h('span.faint', {}, `${sheets.length}`)),
      sheets.length ? h('div.grid.g4', {}, sheets.map((s) => h('div.card', {},
        h('img.thumb', { src: s.image_url, loading: 'lazy', alt: s.name }),
        h('div', { style: { margin: '8px 0 4px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: s.name }, s.name),
        h('div.row.gap4', {}, h('span.tag', { style: { color: s.has_vector ? 'var(--accent)' : 'var(--warn)' } }, s.has_vector ? 'vector' : 'raster-inferred'), h('span.tag', {}, s.document_kind), h('span.tag', {}, s.labeling_status)),
        h('div.faint.mono', { style: { fontSize: '11px', margin: '6px 0' } }, `${s.width}×${s.height}px · ${s.primitive_count} prims · ${s.text_count} text · rot ${s.rotation}° · ${s.objects} obj`),
        h('div.row.gap4', {}, h('a.ot-btn.sm.primary', { href: `/ka/graph/${s.id}/` }, 'Graph Studio'), s.ls_task_id ? h('a.ot-btn.sm', { href: `/projects/${d.project_id}/data?task=${s.ls_task_id}` }, 'Label CV') : null))))
        : empty('No sheets yet', 'Upload drawings to extract pages, vector geometry and text.'),
      section('Documents'), table([['File', (x) => x.filename], ['Type', (x) => x.kind || '—'], ['Status', (x) => chip(x.status, x.status === 'ready' ? 'pos' : x.status === 'failed' || x.status === 'rejected' ? 'danger' : '')], ['Group', (x) => x.split_group], ['Sheets', (x) => x.sheets, 'num'], ['Error', (x) => h('span.danger', {}, x.error)]], docs)];
  };
  DS_TABS.review = async (d, id) => {
    const filter = h('select', {}, ['pending', 'approved', 'rejected', ''].map((s) => h('option', { value: s }, s || 'all')));
    const list = h('div', {});
    const load = async () => {
      const objs = await api(`datasets/${id}/objects/${filter.value ? '?status=' + filter.value : ''}`);
      const sel = new Set();
      const review = async (status) => { if (!sel.size) return toast('Select objects first', 'warn'); await guard(() => api(`datasets/${id}/objects/review/`, { method: 'POST', body: { ids: [...sel], status } }), `${sel.size} marked ${status}`); load(); };
      list.replaceChildren(h('div.row', { style: { marginBottom: '8px' } }, h('button.ot-btn.sm', { onclick: () => { list.querySelectorAll('input[type=checkbox]').forEach((c) => { c.checked = true; sel.add(Number(c.value)); }); } }, 'Select all'),
        h('button.ot-btn.sm.primary', { onclick: () => review('approved') }, 'Approve'), h('button.ot-btn.sm.danger', { onclick: () => review('rejected') }, 'Reject'), h('span.faint', {}, `${objs.length} objects`)),
      table([['', (o) => h('input', { type: 'checkbox', value: o.id, onchange: (e) => (e.target.checked ? sel.add(o.id) : sel.delete(o.id)) })], ['Object', (o) => h('span.mono', {}, o.uid)], ['Sheet', (o) => o.sheet_id, 'num'], ['Label', (o) => o.label],
        ['Geometry', (o) => o.geometry_type], ['Provenance', (o) => h('span.tag', { style: { color: o.provenance === 'human' ? 'var(--ink-soft)' : 'var(--accent)' } }, o.provenance)], ['Review', (o) => chip(o.review_status)], ['Annotator', (o) => o.annotator || '—']], objs,
      { empty: empty('Nothing to review', 'Sync annotations from Label Studio, or accept agent proposals.') }));
    };
    filter.addEventListener('change', load);
    await load();
    return [h('div.row', {}, h('button.ot-btn', { onclick: async () => { const r = await guard(() => api(`datasets/${id}/sync/`, { method: 'POST', body: {} })); toast(`Synced: ${r.created} new, ${r.updated} updated, ${r.deleted} removed`, 'positive'); load(); } }, 'Sync from Label Studio'), filter,
      h('span.faint', {}, 'Only approved objects become ground truth. Edits after review reset an object to pending.')), list];
  };
  DS_TABS.assistant = async (d, id) => {
    const sheets = await api(`datasets/${id}/sheets/`);
    const sheetSel = h('select', {}, sheets.map((s) => h('option', { value: s.id }, s.name)));
    const out = h('div', {});
    const run = async (action, needsSheet) => { await guard(() => api(`datasets/${id}/agent/${action}/`, { method: 'POST', body: needsSheet ? { sheet_id: Number(sheetSel.value) } : {} }), 'Agent finished'); refresh(); };
    const refresh = async () => {
      const [props, summary] = await Promise.all([api(`datasets/${id}/proposals/?status=pending`), api(`datasets/${id}/agent/summary/`, { method: 'POST', body: {} })]);
      out.replaceChildren(
        h('div.card', {}, h('div.row', {}, h('h2', {}, 'Dataset summary'), h('span.tag.right', {}, summary.generated_by)), h('ul', {}, summary.recommendations.map((r) => h('li', {}, r))), summary.recommendations.length ? null : h('div.muted', {}, 'No recommendations.')),
        section('Pending proposals', h('span.faint', {}, String(props.length))),
        table([['Kind', (p) => h('span.tag', {}, p.kind)], ['Agent', (p) => h('span.mono', { style: { fontSize: '12px' } }, `${p.agent}@${p.agent_version}`)], ['Sheet', (p) => p.sheet_id ?? '—', 'num'], ['Suggestion', (p) => p.payload.label || p.payload.class || p.payload.issue || '—'],
          ['Conf.', (p) => (p.confidence ?? 0).toFixed(2), 'num'], ['Why', (p) => h('span.soft', { style: { fontSize: '12px' } }, p.explanation)],
          ['', (p) => h('div.row.gap4', {}, h('button.ot-btn.sm.primary', { onclick: async () => { await guard(() => api(`proposals/${p.id}/review/`, { method: 'POST', body: { action: p.kind === 'quality_flag' ? 'dismiss' : 'accept' } }), 'Accepted'); refresh(); } }, p.kind === 'quality_flag' ? 'Resolve' : 'Accept'),
            h('button.ot-btn.sm', { onclick: async () => { await guard(() => api(`proposals/${p.id}/review/`, { method: 'POST', body: { action: 'reject' } }), 'Rejected'); refresh(); } }, 'Reject'))]], props.slice(0, 300),
        { empty: empty('No pending proposals', 'Run an agent action above. Proposals never become ground truth until a person accepts them.') }));
    };
    await refresh();
    return [h('div.notice.info', {}, 'The labeling assistant is rule-based (construction geometry + text rules) plus model-in-the-loop when you have a trained model. It never writes ground truth itself: every suggestion is a proposal with provenance, evidence, and confidence. Drawing text is treated as data, never as instructions.'),
      h('div.card', {}, h('div.row', {}, h('button.ot-btn', { onclick: () => run('suggest-classes') }, 'Suggest classes from drawing text'), h('button.ot-btn', { onclick: () => run('quality-review') }, 'Quality review (missing / wrong / invalid)')),
        h('div.row', { style: { marginTop: '10px' } }, sheetSel, h('button.ot-btn', { onclick: () => run('propose-graph', true) }, 'Propose graph labels'), h('button.ot-btn', { onclick: () => run('propose-cv', true) }, 'Propose CV polygons → Label Studio'))), out];
  };
  DS_TABS.quality = async (d, id) => {
    const r = await api(`datasets/${id}/readiness/`);
    const st = r.stats;
    const list = (items, cls) => items.map((i) => h('div.notice' + cls, {}, h('b', {}, i.code), ' — ', i.message));
    return [h('div.grid.g4', {}, Object.entries(r.ready_for).map(([t, ok]) => h('div.card', {}, h('div.caption', {}, t.replace(/_/g, ' ')), h('div', { style: { marginTop: '8px' } }, chip(ok ? 'ready' : 'not ready', ok ? 'pos' : 'warn'))))),
      h('div.grid.g2', {}, h('div.card', {}, h('h2', {}, 'CV class balance (approved)'), h('div', { style: { marginTop: '10px' } }, bars(Object.entries(st.class_counts).map(([k, v]) => ({ label: k, value: v, text: String(v) }))))),
        h('div.card', {}, h('h2', {}, 'Graph labels (verified)'), h('div', { style: { marginTop: '10px' } }, bars(Object.entries(st.node_label_counts).map(([k, v]) => ({ label: 'node · ' + k, value: v, text: String(v) })).concat(Object.entries(st.edge_label_counts).map(([k, v]) => ({ label: 'edge · ' + k, value: v, text: String(v) }))))))),
      h('dl.kv.card', {}, Object.entries(st).filter(([, v]) => typeof v !== 'object').map(([k, v]) => [h('dt', {}, k.replace(/_/g, ' ')), h('dd.mono', {}, String(v))])),
      ...list(r.blockers, '.err'), ...list(r.warnings, ''), ...list(r.info, '.info')];
  };
  DS_TABS.versions = async (d, id) => {
    const vs = await api(`datasets/${id}/versions/`);
    const create = async () => {
      const strat = h('select', {}, ['group', 'document', 'sheet'].map((s) => h('option', { value: s }, s)));
      const seed = h('input', { type: 'number', value: 0 }); const notes = h('input', { type: 'text', placeholder: 'Notes' });
      const ok = await dialog('Create immutable dataset version', h('div.grid', {}, h('div.muted', {}, 'Snapshots approved objects, approved graphs, the taxonomy (which becomes frozen) and leak-free splits.'),
        h('label.field', {}, h('span.caption', {}, 'Split strategy'), strat), h('label.field', {}, h('span.caption', {}, 'Seed'), seed), notes), [{ label: 'Create version', primary: true }]);
      if (!ok) return;
      await guard(() => api(`datasets/${id}/versions/`, { method: 'POST', body: { strategy: strat.value, seed: Number(seed.value), notes: notes.value } }), 'Version created');
      KA.PAGES.dataset();
    };
    const exportV = async (v) => { const r = await guard(() => api(`versions/${v.id}/export/`, { method: 'POST', body: {} })); location.href = r.url; };
    return [h('div.row', {}, h('button.ot-btn.primary', { onclick: create }, 'Create version'), h('span.faint', {}, 'Exports: COCO detection + instance segmentation, semantic masks, graph JSON, PyTorch Geometric.')),
      table([['Version', (v) => 'v' + v.version], ['Created', (v) => fmt.date(v.created_at)], ['Objects', (v) => v.objects, 'num'], ['Graphs', (v) => v.graphs, 'num'],
        ['Splits (sheets)', (v) => h('span.mono', {}, `${v.splits.train.length}/${v.splits.val.length}/${v.splits.test.length}`)], ['Strategy', (v) => v.strategy],
        ['Ready for', (v) => h('div.row.gap4', {}, Object.entries(v.readiness.ready_for || {}).filter(([, ok]) => ok).map(([t]) => h('span.tag', {}, t.split('_')[0])))], ['Hash', (v) => h('span.mono.faint', {}, v.content_hash.slice(0, 10))],
        ['', (v) => h('div.row.gap4', {}, h('button.ot-btn.sm', { onclick: () => exportV(v) }, 'Export'), h('a.ot-btn.sm.primary', { href: `/ka/training/?version=${v.id}` }, 'Train'))]], vs,
      { empty: empty('No versions yet', 'Approve annotations, then create an immutable version to train on.') })];
  };
  DS_TABS.taxonomy = async (d, id) => {
    const t = await api(`datasets/${id}/taxonomy/`);
    const ta = h('textarea', { rows: 18, class: 'w100' }); ta.value = JSON.stringify(t.classes, null, 1);
    const save = async () => { let classes; try { classes = JSON.parse(ta.value); } catch (e) { return toast('Invalid JSON', 'danger'); } await guard(() => api(`datasets/${id}/taxonomy/`, { method: 'POST', body: { classes } }), 'New taxonomy version saved'); KA.PAGES.dataset(); };
    return [h('div.row', {}, h('span.chip.accent', {}, 'v' + t.version + (t.frozen ? ' · frozen (used by a version)' : '')), h('button.ot-btn.primary.right', { onclick: save }, 'Save as new version')),
      h('div.grid.g2', {}, h('div', {}, ta), h('div.grid', { style: { alignContent: 'start' } }, ['cv', 'node', 'edge'].map((k) => h('div.card', {}, h('div.caption', {}, { cv: 'CV classes (segmentation)', node: 'Graph node classes', edge: 'Graph relation classes' }[k]),
        h('div.row.gap4', { style: { marginTop: '8px' } }, t.classes.filter((c) => c.kind === k).map((c) => h('span.chip', { title: (c.aliases || []).join(', ') }, h('span.swatch', { style: { background: c.color } }), c.name))))))),
      section('History'), table([['Version', (x) => 'v' + x.version], ['Frozen', (x) => (x.frozen ? 'yes' : 'no')], ['Created', (x) => fmt.date(x.created_at)]], t.history)];
  };

  // ------------------------------------------------------------------ catalog
  PAGES.catalog = async () => {
    const c = await api('catalog/');
    const lic = (i) => h('dl.kv', { style: { fontSize: '12px' } }, [['Checkpoint license', i.checkpoint_license], ['Commercial use', String(i.commercial_use)], ['Deployable', String(i.commercially_deployable)], ['Fine-tuning', String(i.fine_tuning_allowed)], ['Redistribution', i.redistribution], ['Hosting', i.hosting_restrictions], ['Attribution', i.attribution], ['Revision', i.revision || '—'], ['Checksum', i.checksum || 'n/a']].map(([k, v]) => [h('dt', {}, k), h('dd', {}, v ?? '—')]));
    mount(titleBlock(['Model Catalog', 'Approved training templates'], [['Kentucky AI models', c.kentucky_models.length], ['Open models', c.open_models.length]]),
      h('div.notice', {}, c.kentucky_models_note),
      section('Open, commercially permissible architectures'),
      h('div.grid.g2', {}, c.open_models.map((m) => h('div.card', {}, h('div.row', {}, h('h2', {}, m.name), h('span.tag.right', {}, m.task.replace(/_/g, ' '))), h('div.muted', { style: { margin: '6px 0' } }, m.description),
        h('dl.kv', { style: { fontSize: '12px' } }, [['Architecture', m.architecture], ['Implementation', `${m.implementation} (${m.implementation_license})`], ['Version', m.version], ['Compute', m.gpu_recommended], ['Source', m.source]].map(([k, v]) => [h('dt', {}, k), h('dd.mono', {}, v)])),
        h('div.caption', { style: { marginTop: '10px' } }, 'Starting points'), ...m.inits.map((i) => h('details', { style: { marginTop: '6px' } }, h('summary', {}, i.label, ' ', chip(i.commercially_deployable === true ? 'deployable' : 'review required', i.commercially_deployable === true ? 'pos' : 'warn')), lic(i), i.note ? h('div.faint', { style: { fontSize: '12px' } }, i.note) : null)),
        (m.excluded_checkpoints || []).map((x) => h('div.notice', { style: { marginTop: '8px' } }, 'Excluded: ', h('b', {}, x.id), ' — ', x.reason)),
        h('a.ot-btn.sm.primary', { href: `/ka/training/?model=${m.id}`, style: { marginTop: '10px' } }, 'Train with this model')))),
      section('Assisted labeling'), table([['Tool', (x) => x.name], ['Code license', (x) => x.implementation_license], ['Weights license', (x) => x.checkpoint_license], ['Status', (x) => x.status]], c.segmentation_assist));
  };

  // ------------------------------------------------------------------ training wizard
  PAGES.training = async () => {
    const qs = new URLSearchParams(location.search);
    const [datasets, cat, models] = await Promise.all([api('datasets/'), api('catalog/'), api('models/')]);
    const state = { dataset: qs.get('dataset'), version: qs.get('version'), task: null, model: qs.get('model'), init: 'scratch', base: null, mode: 'recommended', overrides: {}, gpu: 'cpu-local' };
    const steps = ['Dataset', 'Readiness', 'Task', 'Architecture', 'Checkpoint', 'Config', 'Estimate', 'Authorize', 'Monitor', 'Deploy'];
    const stepBar = h('div.steps', {});
    const content = h('div.grid', {});
    const setStep = (n) => stepBar.replaceChildren(...steps.map((s, i) => h('div.st' + (i < n ? '.done' : i === n ? '.on' : ''), {}, h('b', {}, String(i + 1).padStart(2, '0')), s)));
    let version = null, rec = null;
    if (state.version && !state.dataset) {
      for (const d of datasets) { const vs = await api(`datasets/${d.id}/versions/`); const v = vs.find((x) => String(x.id) === state.version); if (v) { state.dataset = String(d.id); break; } }
    }
    async function render() {
      content.replaceChildren();
      // 1 dataset
      const dsSel = h('select', { onchange: (e) => { state.dataset = e.target.value; state.version = null; render(); } }, h('option', { value: '' }, 'Choose dataset…'), datasets.map((d) => h('option', { value: d.id, selected: String(d.id) === state.dataset }, d.name)));
      content.append(h('div.card', {}, h('div.caption', {}, '1 · Dataset'), h('div.row', { style: { marginTop: '8px' } }, dsSel)));
      if (!state.dataset) return setStep(0);
      const vs = await api(`datasets/${state.dataset}/versions/`);
      if (!vs.length) { content.append(empty('No dataset versions', 'Create an immutable version in the Dataset Center first.', h('a.ot-btn.primary', { href: `/ka/datasets/${state.dataset}/#versions` }, 'Create version'))); return setStep(0); }
      if (!state.version) state.version = String(vs[0].id);
      version = vs.find((v) => String(v.id) === state.version) || vs[0];
      const vSel = h('select', { onchange: (e) => { state.version = e.target.value; state.task = null; render(); } }, vs.map((v) => h('option', { value: v.id, selected: v.id === version.id }, `v${v.version} · ${fmt.date(v.created_at)}`)));
      // 2 readiness
      const r = version.readiness;
      content.append(h('div.card', {}, h('div.caption', {}, '2 · Validate labels & readiness'), h('div.row', { style: { marginTop: '8px' } }, vSel, ...Object.entries(r.ready_for).map(([t, ok]) => chip(t.replace(/_/g, ' '), ok ? 'pos' : 'warn'))),
        r.blockers.length ? r.blockers.map((b) => h('div.notice.err', { style: { marginTop: '8px' } }, b.message)) : null, r.warnings.slice(0, 4).map((w) => h('div.notice', { style: { marginTop: '8px' } }, w.message))));
      rec = await api(`training/recommend/?dataset_version=${version.id}`);
      const readyTasks = Object.entries(r.ready_for).filter(([, ok]) => ok).map(([t]) => t);
      if (!readyTasks.length) { content.append(empty('Not ready for training', 'Resolve readiness issues (approve labels, approve graphs) and create a new version.')); return setStep(1); }
      // 3 task
      if (!state.task || !readyTasks.includes(state.task)) state.task = (state.model && cat.open_models.find((m) => m.id === state.model)?.task) || readyTasks[0];
      content.append(h('div.card', {}, h('div.caption', {}, '3 · ML task'), h('div.row', { style: { marginTop: '8px' } }, readyTasks.map((t) => h('button.ot-btn' + (t === state.task ? '.primary' : ''), { onclick: () => { state.task = t; state.model = null; render(); } }, t.replace(/_/g, ' '))))));
      // 4 architecture
      const options = cat.open_models.filter((m) => m.task === state.task);
      const recT = rec.tasks.find((t) => t.task === state.task);
      if (!state.model || !options.find((m) => m.id === state.model)) state.model = recT?.catalog_id || options[0].id;
      const model = options.find((m) => m.id === state.model);
      content.append(h('div.card', {}, h('div.row', {}, h('div.caption', {}, '4 · Architecture'), h('span.tag.right', {}, rec.advisor)), recT ? h('div.notice.info', { style: { margin: '8px 0' } }, h('b', {}, 'Recommended: ' + recT.catalog_id + '. '), recT.why) : null,
        h('div.grid.g3', { style: { marginTop: '8px' } }, options.map((m) => h('div.card.click' + (m.id === state.model ? '.hot' : ''), { onclick: () => { state.model = m.id; state.init = 'scratch'; render(); } }, h('b', {}, m.name), h('div.faint', { style: { fontSize: '12px', marginTop: '4px' } }, m.architecture), h('div.muted', { style: { fontSize: '12px', marginTop: '4px' } }, m.gpu_recommended))))));
      // 5 checkpoint
      const own = models.flatMap((rm) => rm.versions).filter((mv) => mv.catalog_id === state.model && mv.status === 'ready');
      const inits = model.inits.map((i) => ({ id: i.id, label: i.label, deployable: i.commercially_deployable === true, note: i.note })).concat(own.length ? [{ id: 'checkpoint', label: 'Your registered model version (fine-tune)', deployable: 'inherits' }] : []);
      const baseSel = h('select', { onchange: (e) => { state.base = e.target.value; } }, own.map((mv) => h('option', { value: mv.id, selected: String(mv.id) === String(state.base) }, `${mv.model_name} v${mv.version} · ${headline(mv.headline).textContent || ''}`)));
      if (state.init === 'checkpoint' && !state.base && own[0]) state.base = String(own[0].id);
      content.append(h('div.card', {}, h('div.caption', {}, '5 · Starting checkpoint'), h('div.notice', { style: { margin: '8px 0' } }, cat.kentucky_models_note),
        h('div.grid', { style: { gap: '6px' } }, inits.map((i) => h('label.row', {}, h('input', { type: 'radio', name: 'init', checked: state.init === i.id, onchange: () => { state.init = i.id; render(); } }), h('span', {}, i.label), chip(i.deployable === true ? 'deployable' : i.deployable === 'inherits' ? 'inherits license' : 'not deployable (license review)', i.deployable === true ? 'pos' : i.deployable === 'inherits' ? '' : 'warn'), i.id === 'scratch' ? h('span.faint', { style: { fontSize: '12px' } }, 'needs more labeled data and compute') : null))),
        state.init === 'checkpoint' ? h('div.row', { style: { marginTop: '8px' } }, baseSel) : null, recT ? h('div.faint', { style: { fontSize: '12px', marginTop: '8px' } }, recT.init_why) : null));
      // 6 config
      const defaults = rec.configs[state.model] || {};
      const cfgBox = h('div.grid.g4', {});
      if (state.mode === 'advanced') {
        Object.entries(defaults).forEach(([k, v]) => {
          if (typeof v === 'object') return;
          const inp = h('input', { type: typeof v === 'number' ? 'number' : 'text', value: state.overrides[k] ?? v, step: 'any', onchange: (e) => { state.overrides[k] = typeof v === 'number' ? Number(e.target.value) : e.target.value; } });
          cfgBox.append(h('label.field', {}, h('span.caption', {}, k), inp));
        });
      } else {
        cfgBox.append(...Object.entries(defaults).filter(([, v]) => typeof v !== 'object').map(([k, v]) => h('div', {}, h('div.mlabel', {}, k), h('div.mono', {}, String(v)))));
      }
      const gpuSel = h('select', { onchange: (e) => { state.gpu = e.target.value; render(); } }, ['cpu-local', 'cpu-4', 'nvidia-t4', 'nvidia-a10g', 'nvidia-a100-40gb'].map((g) => h('option', { value: g, selected: g === state.gpu }, g)));
      content.append(h('div.card', {}, h('div.row', {}, h('div.caption', {}, '6 · Configuration'), h('div.row.right', {}, ['recommended', 'advanced'].map((m) => h('button.ot-btn.sm' + (state.mode === m ? '.primary' : ''), { onclick: () => { state.mode = m; if (m === 'recommended') state.overrides = {}; render(); } }, m)))),
        h('div', { style: { marginTop: '10px' } }, cfgBox), h('div.row', { style: { marginTop: '10px' } }, h('span.caption', {}, 'Compute'), gpuSel, h('span.faint', { style: { fontSize: '12px' } }, 'Paid GPU tiers require an operator to enable paid compute and a payment method.'))));
      // 7-8 estimate + authorize
      const create = h('button.ot-btn.primary', {}, 'Validate & estimate');
      const area = h('div', {});
      create.addEventListener('click', async () => {
        const job = await guard(() => api('jobs/', { method: 'POST', body: { dataset_version_id: version.id, catalog_id: state.model, init: state.init, base_model_version_id: state.init === 'checkpoint' ? Number(state.base) : null, config: state.overrides, gpu_type: state.gpu } }));
        if (job.status === 'FAILED') { area.replaceChildren(h('div.notice.err', {}, job.error)); setStep(5); return; }
        const e = job.estimate; setStep(7);
        const confirm = h('input', { type: 'checkbox' }); const maxc = h('input', { type: 'number', step: '0.01', value: e.max_charge_at_runtime_limit });
        area.replaceChildren(h('div.card.hot', {}, h('div.caption', {}, '7 · Estimated cost'), h('div.grid.g4', { style: { marginTop: '10px' } },
          [['Runtime', `${fmt.dur(e.seconds_low)} – ${fmt.dur(e.seconds_high)}`], ['Customer cost', `${fmt.usd(e.customer_cost_low)} – ${fmt.usd(e.customer_cost_high)}`], ['Max at runtime limit', fmt.usd(e.max_charge_at_runtime_limit)], ['Compute', `${e.gpu_type} · ${e.provider}`]].map(([k, v]) => h('div.stat', {}, h('div.caption', {}, k), h('div.v', { style: { fontSize: '20px' } }, v)))),
          e.pricing_is_placeholder ? h('div.notice', { style: { marginTop: '10px' } }, 'Pricing uses development placeholder rates; configure KA_PRICING before charging customers.') : null,
          h('div.caption', { style: { marginTop: '14px' } }, '8 · Authorize'), h('div.row', { style: { marginTop: '8px' } }, h('label.row', {}, confirm, h('span', {}, 'I authorize this training run and compute spend up to')), maxc),
          h('div.row', { style: { marginTop: '10px' } }, h('button.ot-btn.primary', { onclick: async () => {
            if (!confirm.checked) return toast('Tick the authorization box first', 'warn');
            await guard(() => api(`jobs/${job.id}/authorize/`, { method: 'POST', body: { confirm: true, max_cost_usd: maxc.value } }), 'Queued');
            location.href = `/ka/experiments/${job.id}/`;
          } }, 'Authorize & start'), h('span.faint', {}, `Job #${job.id} validated · config is stored exactly for reproducibility`))));
      });
      content.append(h('div.card', {}, h('div.caption', {}, '7 · Estimate'), h('div.row', { style: { marginTop: '8px' } }, create)), area);
      setStep(5);
    }
    mount(titleBlock(['Training Center', 'Train a construction model'], [['Path', 'Select → Train → Evaluate → Deploy']]), stepBar, content);
    render();
  };

  // ------------------------------------------------------------------ experiments
  PAGES.experiments = async () => {
    const jobs = await api('jobs/');
    const sel = new Set();
    const cmpOut = h('div', {});
    const compare = async () => {
      if (sel.size < 2) return toast('Select at least two runs', 'warn');
      const c = await api(`jobs/compare/?ids=${[...sel].join(',')}`);
      cmpOut.replaceChildren(section('Comparison'), table([['Run', (r) => h('a', { href: `/ka/experiments/${r.job}/` }, `#${r.job} ${r.name}`)], ['Model', (r) => r.catalog_id], ['Init', (r) => r.init], ['Data', (r) => 'v' + r.dataset_version], ['Headline', (r) => headline(r.headline)], ['Runtime', (r) => fmt.dur(r.runtime_s), 'num']], c.rows),
        h('div.card', { style: { marginTop: '10px' } }, h('div.caption', {}, 'Config differences'), Object.keys(c.config_differences).length ? h('dl.kv', { style: { marginTop: '8px' } }, Object.entries(c.config_differences).map(([k, v]) => [h('dt', {}, k), h('dd.mono', {}, v.map(String).join('  |  '))])) : h('div.muted', {}, 'Identical configurations.')));
    };
    mount(titleBlock(['Experiments', 'Training runs'], [['Runs', jobs.length], ['Completed', jobs.filter((j) => j.status === 'COMPLETED').length], ['Active', jobs.filter((j) => !['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'CREATED'].includes(j.status)).length]], [h('button.ot-btn', { onclick: compare }, 'Compare selected'), h('a.ot-btn.primary', { href: '/ka/training/' }, 'New run')]),
      table([['', (j) => h('input', { type: 'checkbox', onchange: (e) => (e.target.checked ? sel.add(j.id) : sel.delete(j.id)) })], ['Run', (j) => h('a', { href: `/ka/experiments/${j.id}/` }, `#${j.id} ${j.name}`)], ['Task', (j) => j.task.replace(/_/g, ' ')], ['Model', (j) => h('span.mono', { style: { fontSize: '12px' } }, j.catalog_id)], ['Init', (j) => j.init],
        ['Data', (j) => 'v' + j.dataset_version], ['Status', (j) => chip(j.status)], ['Headline', (j) => headline(j.headline)], ['Runtime', (j) => fmt.dur(j.runtime_s), 'num'], ['Compute', (j) => j.gpu_type]], jobs,
      { empty: empty('No experiments yet', 'Start a training run from the Training Center.', h('a.ot-btn.primary', { href: '/ka/training/' }, 'Open Training Center')) }), cmpOut);
  };

  PAGES.experiment = async () => {
    const j = await api(`jobs/${PK}/`);
    const active = !['COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'].includes(j.status);
    const hist = j.metrics_history.filter((m) => m.epoch !== undefined);
    const logs = j.metrics_history.filter((m) => m.log);
    const series = [{ name: 'train loss', color: 'var(--accent)', points: hist.map((m) => [m.epoch, m.train_loss]) }, { name: 'val loss', color: 'var(--warn)', points: hist.map((m) => [m.epoch, m.val_loss]) }];
    const valKey = hist.length ? Object.keys(hist[hist.length - 1]).find((k) => k.startsWith('val_') && k !== 'val_loss') : null;
    const fm = j.final_metrics || {};
    const split = fm.test && (fm.test.n || fm.test.per_class) ? fm.test : fm.val;
    const splitName = split === fm.test ? 'test (held-out building)' : 'validation';
    const per = split?.per_class || {};
    const diag = j.status === 'COMPLETED' ? await api(`jobs/${j.id}/diagnose/`) : null;
    const deployBtn = j.model_version ? h('a.ot-btn.primary', { href: `/ka/models/?version=${j.model_version}` }, 'Review & deploy') : null;
    mount(titleBlock([`Run #${j.id}`, j.name], [['Status', chip(j.status)], ['Model', j.catalog_id], ['Init', j.init], ['Data', 'v' + j.dataset_version], ['Runtime', fmt.dur(j.runtime_s)], ['Compute', `${j.gpu_type} · ${j.provider}`]],
      [active && j.status !== 'CREATED' ? h('button.ot-btn.danger', { onclick: async () => { await guard(() => api(`jobs/${j.id}/cancel/`, { method: 'POST', body: {} }), 'Cancellation requested'); } }, 'Cancel') : null, deployBtn]),
    h('div.steps', {}, ['CREATED', 'QUEUED', 'PROVISIONING', 'PREPARING', 'TRAINING', 'EVALUATING', 'SAVING', 'COMPLETED'].map((s, i) => { const seen = j.status_history.some((x) => x.status === s); return h('div.st' + (s === j.status ? '.on' : seen ? '.done' : ''), {}, h('b', {}, String(i + 1).padStart(2, '0')), s.toLowerCase()); })),
    j.error ? h('div.notice.err', {}, h('pre.code', { style: { whiteSpace: 'pre-wrap' } }, j.error)) : null,
    h('div.grid.g2', {}, h('div.card', {}, h('h2', {}, 'Loss'), lineChart(series)),
      h('div.card', {}, h('h2', {}, valKey ? valKey.replace(/_/g, ' ') : 'Validation metric'), lineChart(valKey ? [{ name: valKey, color: 'var(--pos)', points: hist.map((m) => [m.epoch, m[valKey]]) }] : []))),
    j.status === 'COMPLETED' ? [section(`Evaluation — ${splitName}`),
      h('div.grid.g4', {}, Object.entries(split || {}).filter(([k, v]) => typeof v === 'number').slice(0, 8).map(([k, v]) => h('div.card.stat', {}, h('div.caption', {}, k.replace(/_/g, ' ')), h('div.v', {}, Number(v).toFixed(3))))),
      h('div.grid.g2', {}, h('div.card', {}, h('h2', {}, 'Per class'), h('div', { style: { marginTop: '10px' } }, table([['Class', (r) => r[0]], ...(Object.values(per)[0]?.iou !== undefined ? [['IoU', (r) => fmt.n(r[1].iou, 3), 'num'], ['Dice', (r) => fmt.n(r[1].dice, 3), 'num'], ['Prec.', (r) => fmt.n(r[1].precision, 3), 'num'], ['Recall', (r) => fmt.n(r[1].recall, 3), 'num']] : [['F1', (r) => fmt.n(r[1].f1, 3), 'num'], ['Prec.', (r) => fmt.n(r[1].precision, 3), 'num'], ['Recall', (r) => fmt.n(r[1].recall, 3), 'num'], ['Support', (r) => r[1].support, 'num']])], Object.entries(per).filter(([, v]) => (v.support ?? v.gt_pixels ?? 1) > 0)))),
        h('div.card', {}, h('h2', {}, 'Confusion matrix'), h('div', { style: { marginTop: '10px' } }, confusion(split?.confusion_matrix, split?.classes || []) || h('div.muted', {}, 'Not available for this task (see AP / counts).')),
          split?.objects ? h('div', { style: { marginTop: '12px' } }, h('div.caption', {}, 'Construction metrics'), table([['Class', (r) => r[0]], ['GT objects', (r) => r[1].gt_count, 'num'], ['Pred comps', (r) => r[1].pred_components, 'num'], ['Count err', (r) => r[1].count_error, 'num'], ['Missing', (r) => fmt.pct(r[1].missing_rate), 'num']], Object.entries(split.objects))) : null,
          split?.per_class_pr ? h('div', { style: { marginTop: '12px' } }, h('div.caption', {}, 'Mask AP@50 per class'), table([['Class', (r) => r[0]], ['AP', (r) => fmt.n(r[1], 3), 'num']], Object.entries(split.per_class_ap || {}))) : null,
          split?.graph_consistency ? h('dl.kv', { style: { marginTop: '12px' } }, Object.entries(split.graph_consistency).map(([k, v]) => [h('dt', {}, k.replace(/_/g, ' ')), h('dd.mono', {}, String(v))])) : null)),
      diag ? h('div.card', {}, h('div.row', {}, h('h2', {}, 'Training assistant'), h('span.tag.right', {}, diag.advisor)), diag.findings.length ? h('ul', {}, diag.findings.map((f) => h('li', {}, h('b', {}, f.code.replace(/_/g, ' ') + ': '), f.message, f.suggestion ? ' ' + f.suggestion : ''))) : h('div.muted', {}, 'No issues detected.')) : null,
      j.model_version ? h('div.card', {}, h('h2', {}, 'Predictions over source drawing'), h('div.muted', { style: { margin: '6px 0 10px' } }, 'Run the trained model on a sheet of this dataset; predictions are drawn in their original coordinates.'), KA.predictionViewer(j.model_version, j.dataset_id, j.task)) : null] : null,
    h('details.card', {}, h('summary', {}, 'Reproducibility — exact configuration, seed, code version'), h('pre.code', { style: { marginTop: '10px' } }, JSON.stringify({ config: j.config, seed: j.seed, code_version: j.code_version, dataset_version_id: j.dataset_version_id, catalog_id: j.catalog_id, init: j.init, base_model_version: j.base_model_version, provider_job_id: j.provider_job_id, resource_usage: j.resource_usage }, null, 1))),
    h('details.card', {}, h('summary', {}, `Logs & status history (${logs.length + j.status_history.length})`), h('pre.code', { style: { marginTop: '10px' } }, [...j.status_history.map((s) => `${s.at}  ${s.status}${s.reason ? '  — ' + s.reason : ''}`), ...logs.map((l) => `+${l.t}s  ${l.log}`)].join('\n'))));
    if (active) setTimeout(() => { if (document.body.dataset.page === 'experiment') PAGES.experiment(); }, 4000);
  };

  KA.predictionViewer = function (mvId, datasetId, task) {
    const wrap = h('div.grid', {});
    const go = async (sheetId, sheets) => {
      const s = sheets.find((x) => String(x.id) === String(sheetId));
      wrap.lastChild?.remove();
      const box = h('div', { style: { position: 'relative' } }, h('div.skeleton', { style: { height: '300px' } }));
      wrap.append(box);
      try {
        const r = await api(`model-versions/${mvId}/predict/`, { method: 'POST', body: { sheet_id: Number(sheetId), allow_raster_inferred: true } });
        const svg = svgEl('svg', { viewBox: `0 0 ${s.width} ${s.height}`, style: { width: '100%', background: '#fff', borderRadius: '4px' } }, svgEl('image', { href: s.image_url, x: 0, y: 0, width: s.width, height: s.height }));
        const colors = { wall: '#62d4dc', door: '#f0b24a', window: '#8fa8ff', room_tag: '#4f9f6b', other: '#848e8b', same_object: '#62d4dc', hosted_by: '#f0b24a', none: '#848e8b' };
        if (r.predictions) r.predictions.forEach((p) => svg.appendChild(svgEl('polygon', { class: 'overlay-poly', points: p.polygon.map((q) => q.join(',')).join(' '), fill: colors[p.label] || '#c3a6ff', stroke: colors[p.label] || '#c3a6ff' }, svgEl('title', {}, `${p.label} ${p.confidence}`))));
        if (r.nodes) r.nodes.forEach((n) => { if (!n.bbox) return; const [x0, y0, x1, y1] = n.bbox; svg.appendChild(svgEl('rect', { x: x0 - 1, y: y0 - 1, width: Math.max(2, x1 - x0 + 2), height: Math.max(2, y1 - y0 + 2), fill: 'none', stroke: colors[n.label] || '#c3a6ff', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', opacity: 0.4 + 0.6 * n.confidence }, svgEl('title', {}, `${n.label} ${n.confidence}`))); });
        const counts = {}; (r.predictions || r.nodes || r.edges || []).forEach((p) => (counts[p.label] = (counts[p.label] || 0) + 1));
        box.replaceChildren(svg, h('div.row', { style: { marginTop: '8px' } }, Object.entries(counts).map(([k, v]) => h('span.chip', {}, h('span.swatch', { style: { background: colors[k] || '#c3a6ff' } }), `${k} · ${v}`)), r.edges ? h('span.faint', {}, 'Edge predictions: open Graph Studio to compare relations.') : null));
      } catch (e) { box.replaceChildren(h('div.notice.err', {}, e.message)); }
    };
    api(`datasets/${datasetId}/sheets/`).then((sheets) => {
      const sel = h('select', { onchange: (e) => go(e.target.value, sheets) }, sheets.map((s) => h('option', { value: s.id }, `${s.name}${s.has_vector ? '' : ' (raster)'}`)));
      wrap.append(h('div.row', {}, sel, h('button.ot-btn', { onclick: () => go(sel.value, sheets) }, 'Run prediction')));
    });
    return wrap;
  };

  // ------------------------------------------------------------------ registry
  PAGES.models = async () => {
    const ms = await api('models/');
    const focus = new URLSearchParams(location.search).get('version');
    const deploy = async (mv) => {
      const name = h('input', { type: 'text', value: mv.model_name }); const rl = h('input', { type: 'number', value: 60 }); const ok = h('input', { type: 'checkbox' });
      const res = await dialog('Deploy model version', h('div.grid', {}, h('div.muted', {}, 'Creates an authenticated HTTPS endpoint. Calls require an organization API key and are metered.'), h('label.field', {}, h('span.caption', {}, 'Name'), name), h('label.field', {}, h('span.caption', {}, 'Rate limit / min'), rl),
        h('label.row', {}, ok, h('span', {}, 'I authorize exposing this model through the Kentucky AI API'))), [{ label: 'Deploy', primary: true }]);
      if (!res) return;
      await guard(() => api('deployments/', { method: 'POST', body: { model_version_id: mv.id, name: name.value, rate_limit_per_minute: Number(rl.value), confirm: ok.checked } }), 'Deployed');
      location.href = '/ka/deployments/';
    };
    mount(titleBlock(['Model Registry', 'Your models'], [['Models', ms.length], ['Versions', ms.reduce((a, m) => a + m.versions.length, 0)]]),
      ms.length ? ms.map((m) => h('div.card', {}, h('div.row', {}, h('h2', {}, m.name), h('span.tag', {}, m.task.replace(/_/g, ' ')), h('span.mono.faint.right', { style: { fontSize: '12px' } }, m.catalog_id)),
        h('div', { style: { marginTop: '10px' } }, table([['Version', (v) => h('b', { style: { color: String(v.id) === focus ? 'var(--accent)' : '' } }, 'v' + v.version)], ['Created', (v) => fmt.date(v.created_at)], ['Trained on', (v) => `dataset ${v.dataset_id} v${v.dataset_version}`], ['Headline', (v) => headline(v.headline)],
          ['Classes', (v) => h('span.faint', { style: { fontSize: '12px' } }, v.classes.join(', '))], ['License', (v) => chip(v.license.commercially_deployable ? 'deployable' : 'not deployable', v.license.commercially_deployable ? 'pos' : 'warn')], ['Status', (v) => chip(v.status)],
          ['', (v) => h('div.row.gap4', {}, h('a.ot-btn.sm', { href: `/ka/experiments/${v.training_job}/` }, 'Run'), h('button.ot-btn.sm', { onclick: async () => { const r = await guard(() => api(`model-versions/${v.id}/download/`)); location.href = r.url; } }, 'Download'),
            h('a.ot-btn.sm', { href: `/ka/training/?version=&model=${m.catalog_id}` }, 'Fine-tune'), h('button.ot-btn.sm', { onclick: async () => { await guard(() => api(`model-versions/${v.id}/archive/`, { method: 'POST', body: { archive: v.status !== 'archived' } }), 'Updated'); PAGES.models(); } }, v.status === 'archived' ? 'Restore' : 'Archive'),
            h('button.ot-btn.sm.primary', { disabled: !v.license.commercially_deployable || v.status !== 'ready', title: v.license.reason, onclick: () => deploy(v) }, 'Deploy'))]], m.versions))))
        : empty('No models yet', 'Completed training runs register a model version here automatically.'));
  };

  // ------------------------------------------------------------------ deployments
  PAGES.deployments = async () => {
    const [deps, models] = await Promise.all([api('deployments/'), api('models/')]);
    const curl = (d) => `curl -X POST ${location.origin}${d.endpoint} \\\n  -H "Authorization: Bearer $KA_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '${d.task.includes('segmentation') ? '{"image": "<base64 PNG>"}' : '{"graph": {"nodes": [...], "edges": [...]}}'}'`;
    mount(titleBlock(['Deployments', 'Hosted inference'], [['Endpoints', deps.length], ['Active', deps.filter((d) => d.status === 'active').length], ['Requests', deps.reduce((a, d) => a + d.request_count, 0)]], [h('a.ot-btn', { href: '/ka/keys/' }, 'API keys'), h('a.ot-btn.primary', { href: '/ka/models/' }, 'Deploy a model')]),
      deps.length ? deps.map((d) => {
        const versions = (models.find((m) => m.id === d.model_id)?.versions || []).filter((v) => v.license.commercially_deployable && v.status === 'ready');
        const vsel = h('select', {}, versions.map((v) => h('option', { value: v.id, selected: v.id === d.active_version }, 'v' + v.version)));
        const act = async (a, body) => { await guard(() => api(`deployments/${d.id}/${a}/`, { method: 'POST', body: body || {} }), 'Updated'); PAGES.deployments(); };
        return h('div.card', {}, h('div.row', {}, h('h2', {}, d.name), chip(d.status), h('span.tag', {}, d.task.replace(/_/g, ' ')), h('span.mono.faint.right', { style: { fontSize: '12px' } }, d.endpoint)),
          h('div.grid.g4', { style: { margin: '12px 0' } }, [['Serving', `v${d.active_version_number}`], ['Requests', fmt.n(d.request_count)], ['Errors', fmt.n(d.error_count)], ['Rate limit', `${d.rate_limit_per_minute}/min`]].map(([k, v]) => h('div', {}, h('div.mlabel', {}, k), h('div.mono', {}, v)))),
          h('div.row', {}, vsel, h('button.ot-btn.sm', { onclick: () => act('set-version', { model_version_id: Number(vsel.value) }) }, 'Set version'), h('button.ot-btn.sm', { onclick: () => act('rollback') }, 'Roll back'),
            h('button.ot-btn.sm', { onclick: () => act(d.status === 'active' ? 'pause' : 'resume') }, d.status === 'active' ? 'Pause' : 'Resume'), h('button.ot-btn.sm.danger', { onclick: async () => { if (await dialog('Delete deployment?', h('div.muted', {}, 'The endpoint stops accepting requests immediately.'), [{ label: 'Delete', danger: true }])) act('delete'); } }, 'Delete')),
          h('details', { style: { marginTop: '10px' } }, h('summary', {}, 'Example request'), h('pre.code', { style: { marginTop: '8px' } }, curl(d))),
          h('details', {}, h('summary', {}, `Version history (${d.history.length})`), h('pre.code', { style: { marginTop: '8px' } }, d.history.map((x) => `${x.at}  ${x.action}  v${x.version}`).join('\n'))));
      }) : empty('No deployments', 'Deploy a registered model version to get an authenticated API endpoint.', h('a.ot-btn.primary', { href: '/ka/models/' }, 'Model Registry')));
  };

  // ------------------------------------------------------------------ keys
  PAGES.keys = async () => {
    const keys = await api('api-keys/');
    const show = (r) => dialog('Copy your API key', h('div.grid', {}, h('div.notice', {}, 'This key is shown once. Kentucky AI stores only a SHA-256 hash.'), h('pre.code', { style: { userSelect: 'all', whiteSpace: 'pre-wrap', wordBreak: 'break-all' } }, r.key)), [{ label: 'Done', primary: true }]).then(() => PAGES.keys());
    const create = async () => { const n = h('input', { type: 'text', placeholder: 'e.g. takeoff-service-prod' }); if (!(await dialog('New API key', h('label.field', {}, h('span.caption', {}, 'Name'), n), [{ label: 'Create', primary: true }]))) return; show(await guard(() => api('api-keys/', { method: 'POST', body: { name: n.value, scopes: ['inference'] } }))); };
    mount(titleBlock(['API Keys', 'Organization keys'], [['Active', keys.filter((k) => !k.revoked_at).length], ['Revoked', keys.filter((k) => k.revoked_at).length]], [h('button.ot-btn.primary', { onclick: create }, 'New key')]),
      table([['Name', (k) => k.name], ['Prefix', (k) => h('span.mono', {}, k.prefix + '…')], ['Scopes', (k) => k.scopes.join(', ')], ['Created', (k) => fmt.date(k.created_at)], ['Last used', (k) => fmt.ago(k.last_used_at)], ['Status', (k) => chip(k.revoked_at ? 'revoked' : 'active', k.revoked_at ? 'danger' : 'pos')],
        ['', (k) => (k.revoked_at ? '' : h('div.row.gap4', {}, h('button.ot-btn.sm', { onclick: async () => show(await guard(() => api(`api-keys/${k.id}/rotate/`, { method: 'POST', body: {} }))) }, 'Rotate'), h('button.ot-btn.sm.danger', { onclick: async () => { await guard(() => api(`api-keys/${k.id}/revoke/`, { method: 'POST', body: {} }), 'Revoked'); PAGES.keys(); } }, 'Revoke')))]], keys,
      { empty: empty('No API keys', 'Create a key to call your deployments.', h('button.ot-btn.primary', { onclick: create }, 'New key')) }));
  };

  // ------------------------------------------------------------------ billing
  PAGES.billing = async () => {
    const b = await api('billing/');
    const a = b.account, u = b.usage;
    const cap = h('input', { type: 'number', step: '1', value: a.monthly_spend_cap_usd });
    const used = Number(u.month_to_date) + Number(u.reserved_for_active_jobs);
    mount(titleBlock(['Usage & Billing', 'Pay as you go'], [['Month to date', fmt.usd(u.month_to_date)], ['Reserved (active jobs)', fmt.usd(u.reserved_for_active_jobs)], ['Spend cap', fmt.usd(a.monthly_spend_cap_usd)], ['Stripe', a.stripe_mode]]),
      a.stripe_mode !== 'test' && a.stripe_mode !== 'live' ? h('div.notice', {}, 'Stripe is not configured: charges are recorded in the idempotent ledger only; no payment is initiated. Set KA_STRIPE_SECRET_KEY (sk_test_…) to submit invoice items in test mode.') : null,
      b.pricing.placeholder ? h('div.notice', {}, 'Rates shown are development placeholders, not provider quotes.') : null,
      h('div.grid.g3', {},
        h('div.card', {}, h('h2', {}, 'Spend cap'), h('div.pf-bar', { style: { margin: '12px 0 6px' } }, h('i', { style: { width: Math.min(100, (used / Math.max(Number(a.monthly_spend_cap_usd), 1e-9)) * 100) + '%' } })),
          h('div.faint', { style: { fontSize: '12px' } }, `${fmt.usd(used)} of ${fmt.usd(a.monthly_spend_cap_usd)} used or reserved`), h('div.row', { style: { marginTop: '10px' } }, cap, h('button.ot-btn', { onclick: async () => { await guard(() => api('billing/', { method: 'PATCH', body: { monthly_spend_cap_usd: cap.value } }), 'Cap updated'); PAGES.billing(); } }, 'Save'))),
        h('div.card', {}, h('h2', {}, 'Payment method'), h('div', { style: { margin: '10px 0' } }, chip(a.payment_method_status, a.payment_method_status === 'none' ? 'warn' : 'pos')),
          h('div.row', {}, a.payment_method_status === 'none' ? h('button.ot-btn', { onclick: async () => { await guard(() => api('billing/', { method: 'PATCH', body: { payment_method: 'test_card' } }), 'Test payment method added'); PAGES.billing(); } }, 'Add test card') : h('button.ot-btn', { onclick: async () => { await guard(() => api('billing/', { method: 'PATCH', body: { payment_method: 'remove' } })); PAGES.billing(); } }, 'Remove'))),
        h('div.card', {}, h('h2', {}, 'Last 30 days'), h('div', { style: { marginTop: '10px' } }, bars(Object.entries(u.by_kind).map(([k, v]) => ({ label: k.replace(/_/g, ' '), value: Number(v.charge), text: fmt.usd(v.charge) })))),
          h('div.faint', { style: { fontSize: '12px', marginTop: '8px' } }, `Customer charges ${fmt.usd(u.total_charge)} · infrastructure cost ${fmt.usd(u.total_infra)}`))),
      section('Rates'), h('div.table-wrap', {}, h('table.set-table', {}, h('thead', {}, h('tr', {}, ['Compute tier', 'Provider', 'Infra $/h', 'Customer $/h'].map((x) => h('th', {}, x)))), h('tbody', {}, Object.entries(b.pricing.compute_tiers).map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v.provider), h('td.num', {}, v.infra_per_hour), h('td.num', {}, v.customer_per_hour)))))),
      section('Billing history'), table([['When', (e) => fmt.date(e.created_at)], ['Kind', (e) => h('span.tag', {}, e.kind)], ['Description', (e) => e.description], ['Qty', (e) => `${Number(e.quantity).toFixed(4)} ${e.unit}`, 'num'], ['Infra', (e) => fmt.usd(e.infra_cost_usd), 'num'], ['Charge', (e) => fmt.usd(e.customer_charge_usd), 'num'], ['Stripe', (e) => h('span.faint', {}, e.stripe_status)], ['Key', (e) => h('span.mono.faint', { style: { fontSize: '11px' } }, e.idempotency_key)]], b.history));
  };

  // ------------------------------------------------------------------ settings
  PAGES.settings = async () => {
    const [o, logs, ds] = await Promise.all([api('org/'), api('audit/'), api('datasets/')]);
    mount(titleBlock(['Organization', o.title], [['Members', o.members.length], ['Paid compute', o.paid_compute_enabled ? 'enabled' : 'disabled'], ['Stripe', o.stripe_mode], ['Graph features', o.feature_spec]]),
      h('div.grid.g2', {}, h('div.card', {}, h('h2', {}, 'Members'), h('div', { style: { marginTop: '10px' } }, table([['Email', (m) => m.email], ['Role', (m) => (m.is_owner ? 'owner' : 'member')]], o.members)), h('a.ot-btn.sm', { href: '/organization/', style: { marginTop: '10px' } }, 'Invite via Label Studio organization')),
        h('div.card', {}, h('h2', {}, 'Data use consent'), h('div.muted', { style: { margin: '6px 0 10px', fontSize: '13px' } }, 'Customer data is never used to train Kentucky AI models unless you opt in per dataset. Changes are timestamped and kept.'),
          table([['Dataset', (d) => d.name], ['Allow Kentucky AI training', (d) => h('input', { type: 'checkbox', checked: d.allow_ka_model_training, onchange: async (e) => { await guard(() => api(`datasets/${d.id}/`, { method: 'PATCH', body: { allow_ka_model_training: e.target.checked } }), 'Consent recorded'); } })],
            ['', (d) => h('button.ot-btn.sm.danger', { onclick: async () => { if (await dialog(`Delete "${d.name}"?`, h('div.muted', {}, 'Permanently deletes originals, derived sheets, annotations, graphs and exports. Trained models are kept until you archive them.'), [{ label: 'Delete permanently', danger: true }])) { await guard(() => api(`datasets/${d.id}/`, { method: 'DELETE' }), 'Deleted'); PAGES.settings(); } } }, 'Delete data')]], ds))),
      h('div.card', {}, h('h2', {}, 'Security boundaries'), h('ul', { style: { color: 'var(--ink-soft)', fontSize: '13px' } }, ['All datasets, sheets, models, jobs, deployments and keys are scoped to this organization.', 'Storage is private; downloads use signed URLs that expire in 5 minutes.', 'API keys are stored as SHA-256 hashes and can be rotated or revoked at any time.', 'Training runs approved templates only — no customer-supplied code.', `Storage: ${o.storage}`].map((x) => h('li', {}, x)))),
      section('Audit log'), table([['When', (a) => fmt.date(a.created_at)], ['Action', (a) => h('span.mono', {}, a.action)], ['Actor', (a) => a.actor || (a.api_key ? 'key ' + a.api_key : '—')], ['Target', (a) => a.target], ['IP', (a) => a.ip]], logs));
  };

  // ------------------------------------------------------------------ API docs
  PAGES.apidocs = async () => {
    const ex = {
      seg: `import base64, requests\nimg = base64.b64encode(open("sheet.png", "rb").read()).decode()\nr = requests.post(\n    "${location.origin}/api/ka/v1/deployments/<slug>/predict",\n    headers={"Authorization": "Bearer " + KA_API_KEY, "Idempotency-Key": "req-123"},\n    json={"image": img},\n)\nfor p in r.json()["predictions"]:\n    print(p["label"], p["confidence"], p["bbox"])  # image px; polygon_source when sheet_id is used`,
      gnn: `r = requests.post(url, headers=hdrs, json={"graph": graph})  # ka graph JSON (feature_spec ka-graph-features-1)\nfor n in r.json()["nodes"]:\n    print(n["id"], n["label"], n["confidence"], n["primitive_ids"])`,
      sheet: `# Inference on a sheet already ingested in your organization (maps back to PDF points / CAD units):\nrequests.post(url, headers=hdrs, json={"sheet_id": 42})`,
    };
    mount(titleBlock(['API Reference', 'Kentucky AI inference API'], [['Base', '/api/ka/v1'], ['Auth', 'Bearer ka_…']]),
      h('div.card', {}, h('h2', {}, 'POST /api/ka/v1/deployments/{slug}/predict'), h('dl.kv', { style: { marginTop: '10px' } }, [['Auth', 'Authorization: Bearer <organization API key with inference scope>'], ['Idempotency', 'Optional Idempotency-Key header: retried requests with the same key are billed once'], ['Rate limit', 'Per deployment, sliding 60 s window → 429 with Retry-After'], ['Inputs (CV)', '{"image": base64 PNG/JPEG} or {"sheet_id": int}'], ['Inputs (graph)', '{"graph": {...}} or {"sheet_id": int} (vector sheets; allow_raster_inferred=true for scans)'], ['Outputs (CV)', 'predictions[]: label, confidence, bbox [x,y,w,h], polygon (image px), polygon_source (PDF pt / CAD units), page'], ['Outputs (graph)', 'nodes[] / edges[] with label, confidence, probabilities, primitive_ids'], ['Errors', '{"error": {"code", "message"}} with 400 / 401 / 404 / 409 / 429 / 500']].map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))),
      h('div.grid.g2', {}, h('div.card', {}, h('div.caption', {}, 'Segmentation (Python)'), h('pre.code', { style: { marginTop: '8px' } }, ex.seg)), h('div.card', {}, h('div.caption', {}, 'Graph + sheet inference'), h('pre.code', { style: { marginTop: '8px' } }, ex.gnn + '\n\n' + ex.sheet))),
      h('div.card', {}, h('h2', {}, 'Platform API'), h('div.muted', { style: { margin: '6px 0' } }, 'Session-authenticated endpoints under /api/ka/ cover datasets, uploads, sheets, graphs, proposals, versions, exports, training jobs, models, deployments, keys and billing. OpenAPI schema: '), h('a', { href: '/docs/api/schema/swagger-ui/' }, 'Swagger UI')));
  };

  // ------------------------------------------------------------------ boot
  const run = PAGES[page];
  if (run && page !== 'graph') {
    run().catch((e) => mount(empty('Something went wrong', e.message, h('button.ot-btn', { onclick: () => location.reload() }, 'Retry'), 'error')));
  }
})();
