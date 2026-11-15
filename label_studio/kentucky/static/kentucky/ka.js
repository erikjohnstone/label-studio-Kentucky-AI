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
  const head = (kicker, title, accent, lede, actions) => h('div.pagehead', {}, h('div', {}, h('div.kicker', {}, kicker),
    h('div.display', { style: { marginTop: '8px' } }, title, accent ? h('span.c', {}, accent) : null), lede ? h('p.lede', {}, lede) : null),
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
  const NAV = { home: 'home', project: 'home', train: 'models', run: 'models', models: 'models', deployments: 'deployments', apikeys: 'apikeys', api: 'api', billing: 'billing', team: 'team' };
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('on', a.dataset.nav === NAV[page]));
  const setThemeLabel = () => { const l = document.getElementById('ka-theme-label'); if (l) l.textContent = document.documentElement.dataset.theme === 'dark' ? 'Light mode' : 'Dark mode'; };
  setThemeLabel();
  document.getElementById('ka-theme')?.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('ka-theme', next); } catch (e) { /* ignore */ }
    setThemeLabel();
  });

  const P = (KA.PAGES = {});
  function tile(k, v, d, good, onclick) {
    return h('div.tile' + (onclick ? '.click' : ''), { onclick }, h('div.key', {}, k), h('div.v' + (String(v).length > 7 ? '.sm' : ''), { style: good ? { color: 'var(--scan-ink)' } : {} }, v), h('div.d', {}, d));
  }

  // ================================================================== Datasets (home)
  P.home = async () => {
    const [ds, dash] = await Promise.all([api('datasets/'), api('dashboard/')]);
    setTop(['Datasets']);
    const st = [['01', 'Upload plans', ds.some((d) => d.sheets)], ['02', 'Label', ds.some((d) => d.objects)], ['03', 'Train', dash.models > 0], ['04', 'Check accuracy', dash.models > 0], ['05', 'Deploy', dash.deployments > 0]];
    const at = st.findIndex((x) => !x[2]);
    const progress = (d) => {
      const steps = [d.sheets > 0, d.objects > 0, d.objects > 0 && d.approved === d.objects, d.versions > 0];
      const i0 = steps.findIndex((x) => !x);
      return h('span.dots', { title: 'Upload · Label · Check · Train' }, steps.map((s, i) => h('i' + (s ? '.done' : i === i0 ? '.half' : ''))));
    };
    const card = (d) => h('a.dcard', { href: `/ka/projects/${d.id}/` },
      h('div.dthumb', { style: d.cover ? { backgroundImage: `url(${d.cover})` } : {} }),
      h('div.dbody', {}, h('div.t', {}, d.name), h('div.s', {}, `${d.sheets} sheet${d.sheets === 1 ? '' : 's'} · ${fmt.n(d.objects)} labeled · ${fmt.n(d.approved)} checked`),
        h('div.dfoot', {}, progress(d), h('span.cyan', { style: { fontWeight: 600, fontSize: '13.5px' } }, 'Open →'))));
    const add = h('button.dcard.add', { onclick: newDataset }, h('div', {}, h('div.plus', {}, '+'), h('div.t', {}, 'New dataset'), h('div.s', {}, 'Upload plans and pick what to find')));
    mount(
      head('Kentucky AI · Model studio', 'Datasets', null, 'Teach AI to read your drawings — upload plans, label what to find, train a private model, deploy it.', [h('button.btn.primary', { onclick: newDataset }, icon('plus', 16), 'New dataset')]),
      h('div.tiles', {}, tile('Datasets', fmt.n(ds.length), 'plan sets'), tile('Labeled items', fmt.n(dash.objects_approved + dash.objects_pending), `${fmt.n(dash.objects_approved)} checked`), tile('Models', fmt.n(dash.models), 'trained versions'), tile('Live APIs', fmt.n(dash.deployments), 'deployed models')),
      h('div.steps', {}, st.map(([n, t, done], i) => h('div.step' + (done ? '.done' : i === at ? '.on' : ''), {}, h('b', {}, done ? `${n} · DONE` : i === at ? `${n} · NEXT` : n), t))),
      h('div.grid.g3.eq', {}, ds.map(card), add));
  };

  async function newDataset() {
    const name = h('input', { type: 'text', placeholder: 'e.g. Office buildings — architectural plans' });
    const picks = new Set(['wall', 'door', 'window', 'room']);
    const opts = [['wall', 'Walls'], ['door', 'Doors'], ['window', 'Windows'], ['room', 'Rooms'], ['floor_finish', 'Flooring'], ['ceiling', 'Ceilings'], ['duct', 'Ductwork'], ['diffuser', 'Diffusers'], ['hvac_equipment', 'HVAC equipment'], ['electrical_device', 'Electrical devices'], ['plumbing_fixture', 'Plumbing fixtures'], ['structural_member', 'Structural']];
    const grid = h('div.row', { style: { gap: '8px' } }, opts.map(([k, l]) => {
      const b = h('button.chip' + (picks.has(k) ? '.cyan' : ''), { type: 'button', style: { cursor: 'pointer', border: 0, height: '34px', fontSize: '13.5px', padding: '0 14px' } }, l);
      b.onclick = () => { picks.has(k) ? picks.delete(k) : picks.add(k); b.classList.toggle('cyan'); };
      return b;
    }));
    const consent = h('input', { type: 'checkbox' });
    const ok = await dialog('New dataset', h('div.grid', { style: { gap: '20px' } },
      h('label.field', {}, h('span', {}, 'Name'), name),
      h('div', {}, h('div.key', { style: { marginBottom: '10px' } }, 'What should the AI find?'), grid, h('div.faint', { style: { fontSize: '13px', marginTop: '8px' } }, 'You can add more later.')),
      h('label.row', { style: { alignItems: 'flex-start', gap: '10px', fontSize: '13.5px', color: 'var(--ink-3)', flexWrap: 'nowrap' } }, consent, h('span', {}, 'Let Kentucky AI use these plans to improve its own models. Off by default — your data stays yours.'))),
    [{ label: 'Create dataset', primary: true }], 'Step 01');
    if (!ok) return;
    if (!name.value.trim()) return toast('Give the dataset a name', 'warn');
    const d = await guard(() => api('datasets/', { method: 'POST', body: { name: name.value.trim(), classes: [...picks], allow_ka_model_training: consent.checked } }));
    location.href = `/ka/projects/${d.id}/`;
  }

  // ================================================================== Dataset
  P.project = async () => {
    const id = PK;
    const [d, sheets, ready, jobs, props, pending] = await Promise.all([api(`datasets/${id}/`), api(`datasets/${id}/sheets/`), api(`datasets/${id}/readiness/`), api(`jobs/?dataset=${id}`), api(`datasets/${id}/proposals/?status=pending&kind=cv_object`), api(`datasets/${id}/objects/?status=pending`)]);
    const st = ready.stats;
    const cvClasses = d.taxonomy.filter((c) => c.kind === 'cv' && c.name !== 'unknown');
    const best = jobs.filter((j) => j.status === 'COMPLETED' && j.report).sort((a, b) => b.report.score - a.report.score)[0];
    const lastJob = best || jobs[0];
    const firstToLabel = sheets.find((s) => !s.objects) || sheets[0];
    const canTrain = !!ready.ready_for.semantic_segmentation;
    setTop([['Datasets', '/ka/'], d.name]);
    const counts = st.class_counts;
    const enough = cvClasses.filter((c) => (counts[c.name] || 0) >= 3).length;
    const labeledSheets = sheets.filter((x) => x.objects > 0).length;
    const checks = [
      { done: sheets.length > 0, t: 'Upload plan sheets', s: sheets.length ? `${sheets.length} sheet${sheets.length > 1 ? 's' : ''} ready` : 'PDF, scans or CAD (DXF)', fix: ['Upload', '#upload'] },
      { done: st.objects_total > 0, t: 'Label what the AI should find', s: st.objects_total ? `${fmt.n(st.objects_total)} items on ${labeledSheets} sheets` : 'Outline items, or let AI suggest', fix: ['Label', firstToLabel ? `/ka/markup/${firstToLabel.id}/` : '#upload'] },
      { done: st.objects_total > 0 && st.pending === 0, t: 'Check the labels', s: st.pending ? `${st.pending} waiting for a second look` : `${fmt.n(st.approved)} checked`, fix: ['Review', '#review'] },
      { done: canTrain, t: 'Enough examples', s: canTrain ? 'Ready to train' : `${enough} of ${cvClasses.length} items have 3+ examples`, fix: ['See counts', '#examples'] },
      { done: !!lastJob && lastJob.status === 'COMPLETED', t: 'Train your model', s: lastJob ? `${(STATUS[lastJob.status] || [lastJob.status])[0]} · ${fmt.ago(lastJob.created_at)}` : 'Cost shown before it runs', fix: ['Train', `/ka/train/?dataset=${id}`] },
    ];
    const doneN = checks.filter((c) => c.done).length;
    const nextI = checks.findIndex((c) => !c.done);
    const checklist = h('div.card', {}, h('div.card-h', {}, h('div.h3', {}, 'Before you can train'), h('span.muted', {}, `${doneN} of ${checks.length}`)),
      h('div.meter', { style: { marginBottom: '6px' } }, h('i', { style: { width: (doneN / checks.length) * 100 + '%' } })),
      checks.map((c, i) => h('div.check', {}, h('span.mark' + (c.done ? '.done' : i === nextI ? '.now' : '')), h('div', {}, h('div.t', {}, c.t), h('div.s', {}, c.s)),
        c.done ? h('span.faint', { style: { fontSize: '13px' } }, 'Done') : h('a.fix', { href: c.fix[1] }, c.fix[0], ' →'))));
    const examples = h('div.card', { id: 'examples' }, h('div.card-h', {}, h('div.h3', {}, 'Examples per item'), h('span.muted', {}, 'aim for 30+')),
      (() => { const withEx = cvClasses.filter((c) => counts[c.name]); const zero = cvClasses.filter((c) => !counts[c.name]); return withEx.concat(zero.slice(0, Math.max(0, 6 - withEx.length))); })().map((c) => {
        const n = counts[c.name] || 0;
        return h('div.bar-row', {}, h('span.row', { style: { gap: '10px', flexWrap: 'nowrap' } }, h('span.swatch', { style: { background: c.color } }), cap(c.name)),
          h('div.meter' + (n < 3 ? '.warn' : ''), {}, h('i', { style: { width: Math.max(2, Math.min(1, n / 30) * 100) + '%' } })), h('span.mono.muted', { style: { fontSize: '12.5px', textAlign: 'right' } }, n >= 30 ? `${n} ✓` : `${n}/30`));
      }), (() => { const shown = Math.max(cvClasses.filter((c) => counts[c.name]).length, 6); const more = cvClasses.length - shown; return more > 0 ? h('div.faint', { style: { fontSize: '13px', paddingTop: '8px' } }, `+${more} more item types with no examples yet`) : null; })());
    const review = pending.length ? h('div.banner', { id: 'review' }, h('span.mark.now'), h('div', {}, h('b', {}, `${pending.length} labels need a second look`), h('span.muted', {}, ' — only checked labels are used for training.')),
      h('div.row.right', {}, h('button.btn.sm', { onclick: async () => { await guard(() => api(`datasets/${id}/objects/review/`, { method: 'POST', body: { ids: pending.map((o) => o.id), status: 'rejected' } })); P.project(); } }, 'Reject all'),
        h('button.btn.sm.primary', { onclick: async () => { await guard(() => api(`datasets/${id}/objects/review/`, { method: 'POST', body: { ids: pending.map((o) => o.id), status: 'approved' } }), `${pending.length} labels checked`); P.project(); } }, 'Approve all'))) : null;
    const sheetCard = (s) => h('a.dcard', { href: `/ka/markup/${s.id}/` }, h('div.dthumb', { style: { backgroundImage: `url(${s.image_url})` } }),
      h('div.dbody', {}, h('div.t', { title: s.name }, nice(s.name)), h('div.s', {}, s.has_vector ? 'Vector drawing' : 'Scan'),
        h('div.dfoot', {}, s.objects ? chip(`${s.objects} labeled`, 'cyan') : chip('Not labeled'), h('span.cyan', { style: { fontWeight: 600, fontSize: '13.5px' } }, 'Label →'))));
    mount(
      head(`Dataset · ${sheets.length} sheets`, d.name, null, `Finds ${(cvClasses.filter((c) => counts[c.name]).length ? cvClasses.filter((c) => counts[c.name]) : cvClasses.slice(0, 4)).map((c) => cap(c.name).toLowerCase() + 's').join(', ')}`,
        [firstToLabel ? h('a.btn', { href: `/ka/markup/${firstToLabel.id}/` }, icon('pen', 16), 'Label plans') : null,
          h(canTrain ? 'a.btn.primary' : 'a.btn', { href: canTrain ? `/ka/train/?dataset=${id}` : '#examples', title: canTrain ? '' : 'Needs more checked examples' }, icon('spark', 16), 'Train model')]),
      h('div.tiles', {},
        tile('Plan sheets', fmt.n(st.sheets), `${st.vector_sheets} vector · ${st.raster_sheets} scanned`),
        tile('Labeled items', fmt.n(st.objects_total), `${fmt.n(st.approved)} checked`),
        tile('AI suggestions', fmt.n(props.length), props.length ? 'waiting for keep / dismiss' : 'none waiting'),
        tile('Best model', lastJob?.report ? lastJob.report.grade : lastJob ? (STATUS[lastJob.status] || [''])[0] : '—', lastJob?.report ? (lastJob.report.ready_to_use ? 'ready to deploy' : 'needs more examples') : 'not trained yet', !!lastJob?.report?.ready_to_use, lastJob ? () => (location.href = `/ka/runs/${lastJob.id}/`) : null)),
      review,
      h('div.grid.g2.eq', {}, checklist, examples),
      h('div.section-h', {}, h('span.kicker', {}, `Plan sheets · ${sheets.length}`)),
      h('div.grid.g4.eq', {}, sheets.map(sheetCard), uploadCard(id)));
    if (location.hash) document.querySelector(location.hash)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  function uploadCard(id) {
    const input = h('input', { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.dxf', style: { display: 'none' } });
    const box = h('button.dcard.add', { id: 'upload', onclick: () => input.click() }, h('div', {}, icon('upload', 28), h('div.t', {}, 'Add plans'), h('div.s', {}, 'Drop PDF, scans or DXF here')), input);
    const go = async (files) => {
      if (!files.length) return;
      const fd = new FormData(); [...files].forEach((f) => fd.append('file', f));
      box.classList.add('over'); box.querySelector('.t').textContent = `Reading ${files.length} file${files.length > 1 ? 's' : ''}…`;
      try {
        const res = await api(`datasets/${id}/documents/`, { method: 'POST', body: fd });
        res.forEach((r) => toast(r.status === 'ready' ? `${r.filename} — ${r.sheets.length} sheet${r.sheets.length > 1 ? 's' : ''} ready` : `${r.filename}: ${r.error}`, r.status === 'ready' ? 'pos' : 'danger'));
      } catch (e) { toast(e.message, 'danger'); }
      P.project();
    };
    input.onchange = () => go(input.files);
    box.ondragover = (e) => { e.preventDefault(); box.classList.add('over'); };
    box.ondragleave = () => box.classList.remove('over');
    box.ondrop = (e) => { e.preventDefault(); go(e.dataTransfer.files); };
    return box;
  }

  // ================================================================== Train
  P.train = async () => {
    const qs = new URLSearchParams(location.search);
    const ds = await api('datasets/');
    let pick = qs.get('dataset') || (ds[0] && String(ds[0].id));
    let goal = 'outlines', speed = 'cpu-local';
    setTop([['Models', '/ka/models/'], 'Train a model']);
    const area = h('div.grid', { style: { gap: '20px' } });
    const opt = (on, onclick, t, s) => h('div.choice' + (on ? '.on' : ''), { onclick }, h('span.radio'), h('div', {}, h('b', {}, t), h('span', {}, s)));
    const render = () => {
      const d = ds.find((x) => String(x.id) === String(pick));
      area.replaceChildren(
        h('div.grid.g3.eq', {},
          h('div.card', {}, h('div.key', { style: { marginBottom: '12px' } }, '01 · Plans to learn from'), h('div.grid', { style: { gap: '10px' } }, ds.map((x) => opt(String(x.id) === String(pick), () => { pick = String(x.id); render(); }, x.name, `${x.sheets} sheets · ${fmt.n(x.approved)} checked labels`)))),
          h('div.card', {}, h('div.key', { style: { marginBottom: '12px' } }, '02 · What it should do'), h('div.grid', { style: { gap: '10px' } },
            opt(goal === 'outlines', () => { goal = 'outlines'; render(); }, 'Outline items on any plan', 'Vector PDFs and scans'),
            opt(goal === 'structure', () => { goal = 'structure'; render(); }, 'Read the drawing line by line', 'Vector PDFs and CAD'))),
          h('div.card', {}, h('div.key', { style: { marginBottom: '12px' } }, '03 · Speed'), h('div.grid', { style: { gap: '10px' } },
            opt(speed === 'cpu-local', () => { speed = 'cpu-local'; render(); }, 'Standard', 'Included · minutes to hours'),
            opt(speed === 'nvidia-t4', () => { speed = 'nvidia-t4'; render(); }, 'Fast', 'Cloud GPU · by the minute'),
            opt(speed === 'nvidia-a10g', () => { speed = 'nvidia-a10g'; render(); }, 'Fastest', 'Large GPU · big datasets')))),
        h('div.banner', {}, h('div', {}, h('b', {}, d ? d.name : 'Pick a dataset'), h('span.muted', {}, ` · ${goal === 'outlines' ? 'Outline items' : 'Line by line'} · ${speed === 'cpu-local' ? 'Standard' : speed === 'nvidia-t4' ? 'Fast' : 'Fastest'}`)),
          h('span.muted.right', {}, 'Nothing runs or gets charged until you approve.'), h('button.btn.primary', { disabled: !d, onclick: () => start(d) }, 'Check & see cost ', arrow())));
    };
    async function start(d) {
      const r = await guard(() => api(`datasets/${d.id}/train/`, { method: 'POST', body: { goal, gpu_type: speed } }));
      if (!r.ready) {
        const tips = [...(r.readiness.blockers || []).map((b) => b.message), ...(r.readiness.warnings || []).filter((w) => w.code === 'pending_review' || w.code === 'graphs_pending_review').map((w) => w.message)];
        return dialog('Not quite ready', h('div.grid', { style: { gap: '10px' } }, h('div.muted', {}, goal === 'structure' ? 'Line-by-line models need at least 2 sheets labeled and approved in “Line by line”.' : 'The model needs at least 2 labeled sheets and 3 checked examples of each item.'),
          tips.map((t) => h('div.notice', {}, t)), h('a.btn.primary', { href: `/ka/projects/${d.id}/` }, 'Open the dataset ', arrow())), []);
      }
      const j = r.job;
      if (j.status === 'FAILED') return toast(j.error, 'danger');
      const e = j.estimate;
      const free = Number(e.customer_cost_high) === 0;
      const confirm = h('input', { type: 'checkbox', checked: free });
      const ok = await dialog('Ready to train', h('div.grid', { style: { gap: '16px' } },
        h('div.tiles', { style: { gridTemplateColumns: '1fr 1fr' } }, tile('Time', `${fmt.dur(e.seconds_low)}–${fmt.dur(e.seconds_high)}`, 'estimate'), tile('Cost', free ? 'Included' : `${fmt.usd(e.customer_cost_low)}–${fmt.usd(e.customer_cost_high)}`, free ? 'standard servers' : `max ${fmt.usd(e.max_charge_at_runtime_limit)}`)),
        j.init === 'checkpoint' ? h('div.notice.info', {}, 'It keeps learning from your last model instead of starting over.') : null,
        e.pricing_is_placeholder && !free ? h('div.notice', {}, 'Prices shown are placeholders during setup.') : null,
        free ? null : h('label.row', { style: { gap: '10px' } }, confirm, h('span', {}, `I approve up to ${fmt.usd(e.max_charge_at_runtime_limit)}`))),
      [{ label: 'Start training', primary: true }], 'Step 03 · Train');
      if (!ok) return;
      if (!confirm.checked) return toast('Tick the box to approve', 'warn');
      await guard(() => api(`jobs/${j.id}/authorize/`, { method: 'POST', body: { confirm: true } }));
      location.href = `/ka/runs/${j.id}/`;
    }
    mount(head('Step 03 · Train', 'Train a model', null, 'Pick the plans and the job. We show the time and cost before anything runs.'), ds.length ? area : empty('No datasets yet', 'Upload and label some plans first.', h('a.btn.primary', { href: '/ka/' }, 'Go to datasets')));
    render();
  };

  // ================================================================== Training run (progress + accuracy)
  P.run = async () => {
    const j = await api(`jobs/${PK}/`);
    const active = ACTIVE.includes(j.status) || j.status === 'VALIDATING';
    const title = `${LABEL[j.task] || 'Model'} · run #${j.id}`;
    setTop([['Models', '/ka/models/'], title]);
    const hist = j.metrics_history.filter((m) => m.epoch);
    const total = j.config?.epochs || 1;
    const ep = hist.length ? hist[hist.length - 1].epoch : 0;
    if (active) {
      const stage = { QUEUED: 'Waiting for a free server', PROVISIONING: 'Starting a server', PREPARING: 'Reading your plans and labels', TRAINING: `Studying your examples — pass ${ep} of ${total}`, EVALUATING: 'Testing on plans it has never seen', SAVING: 'Saving your model' }[j.status] || 'Working…';
      const pct = j.status === 'TRAINING' ? Math.max(6, (ep / total) * 86) : { QUEUED: 2, PROVISIONING: 3, PREPARING: 5, EVALUATING: 92, SAVING: 97 }[j.status] || 1;
      const steps = ['Get ready', 'Learn', 'Test', 'Save'];
      const si = { QUEUED: 0, PROVISIONING: 0, PREPARING: 0, VALIDATING: 0, TRAINING: 1, EVALUATING: 2, SAVING: 3 }[j.status];
      mount(head('Step 03 · Training', title, null, `Started ${fmt.ago(j.started_at || j.created_at)} · you can leave this page — training keeps going.`,
        [h('button.btn.danger', { onclick: async () => { if (await dialog('Stop training?', h('div.muted', {}, 'You only pay for the time used so far.'), [{ label: 'Stop', danger: true }])) { await guard(() => api(`jobs/${j.id}/cancel/`, { method: 'POST', body: {} })); P.run(); } } }, 'Stop')]),
      h('div.card', { style: { padding: '28px' } }, h('div.card-h', {}, h('div.h3', {}, stage), jobChip(j.status)), h('div.progress-big', { style: { margin: '6px 0 20px' } }, h('i', { style: { width: pct + '%' } })),
        h('div.steps', {}, steps.map((s, i) => h('div.step' + (i < si ? '.done' : i === si ? '.on' : ''), {}, h('b', {}, String(i + 1).padStart(2, '0')), s)))));
      setTimeout(() => { if (document.body.dataset.page === 'run') P.run(); }, 2500);
      return;
    }
    if (j.status !== 'COMPLETED') {
      const why = j.status === 'CREATED' ? 'This run is waiting for your approval.' : (j.error || '').split('\n')[0];
      mount(head('Training', title), h('div.card', {}, empty(STATUS[j.status][0], why, h('div.row', {}, h('a.btn.primary', { href: `/ka/train/?dataset=${j.dataset_id}` }, 'Try again'), h('a.btn', { href: `/ka/projects/${j.dataset_id}/` }, 'Open dataset')), false)), techDetails(j));
      return;
    }
    const rc = j.report;
    const tone = { great: '', good: '', fair: '.warn', weak: '.danger' };
    const deployBtn = j.model_version && rc?.ready_to_use ? h('button.btn.primary', { onclick: () => deployDialog(j.model_version, `${LABEL[j.task]} model`) }, 'Deploy ', arrow()) : null;
    mount(
      head('Step 04 · Accuracy report', title, null, `Learned in ${fmt.dur(j.runtime_s)} · tested on ${rc?.checked_on || 'held-back plans'}.`,
        [h('a.btn', { href: `/ka/projects/${j.dataset_id}/` }, 'Add more examples'), deployBtn]),
      h('div.grid.g2.eq', {},
        h('div.card.mcard', {},
          h('div.row', { style: { gap: '14px', flexWrap: 'nowrap', marginBottom: '6px' } }, h('div.grade' + (rc && rc.grade.length > 1 ? '.dim' : ''), {}, rc ? rc.grade : '—'),
            h('div', {}, h('div.h3', {}, rc && rc.ready_to_use ? 'Ready to put to work' : 'Needs more examples'), h('div.muted', { style: { fontSize: '14px' } }, rc ? rc.advice : ''))),
          h('div.key', { style: { margin: '6px 0 4px' } }, 'How often it finds each item'),
          (rc?.items || []).map((i) => h('div.bar-row', {}, h('span', {}, cap(i.name)), h('div.meter' + (tone[i.level] || ''), {}, h('i', { style: { width: Math.round(i.score * 100) + '%' } })), h('span.mono.muted', { style: { fontSize: '12.5px', textAlign: 'right' } }, `${Math.round(i.score * 10)}/10`))),
          h('div.strip', {}, [['Learned in', fmt.dur(j.runtime_s)], ['Tested on', rc?.checked_on?.startsWith('plans') ? 'new buildings' : 'held-back plans'], ['Version', `run #${j.id}`]].map(([k, v]) => h('div', {}, h('div.key', {}, k), h('div', { style: { fontWeight: 600, marginTop: '4px' } }, v))))),
        j.model_version ? h('div.card', {}, h('div.card-h', {}, h('div.h3', {}, 'On your plans'), h('span.muted', { style: { fontSize: '13px' } }, 'What it finds')), KA.predictionViewer(j.model_version, j.dataset_id)) : h('div')),
      techDetails(j));
  };
  function techDetails(j) {
    const fm = j.final_metrics || {};
    return h('details.tech', {}, h('summary', {}, 'Technical details'), h('div', {},
      h('dl.kv', {}, [['Architecture', j.catalog_id], ['Starting point', j.init], ['Passes (epochs)', j.config?.epochs], ['Best pass', fm.best_epoch], ['Headline', JSON.stringify(fm.headline || {})], ['Code version', j.code_version], ['Seed', j.seed], ['Run', j.id]].map(([k, v]) => [h('dt', {}, k), h('dd.mono', {}, String(v ?? '—'))])),
      h('pre.code', { style: { marginTop: '14px', maxHeight: '320px' } }, JSON.stringify({ config: j.config, test: fm.test, val: fm.val }, null, 1)),
      j.error ? h('pre.code', { style: { marginTop: '10px', whiteSpace: 'pre-wrap' } }, j.error) : null));
  }

  KA.predictionViewer = function (mvId, datasetId) {
    const wrap = h('div', {});
    const COL = { wall: '#1c9aa5', door: '#e39a1d', window: '#5b7cff', room: '#4f9f6b', room_tag: '#4f9f6b', other: '#848e8b' };
    const view = h('div.pv', {}, h('div.skeleton', { style: { height: '300px' } }));
    const legend = h('div.row', { style: { marginTop: '10px', gap: '8px' } });
    const go = async (s) => {
      view.replaceChildren(h('div.skeleton', { style: { height: '300px' } }));
      try {
        const r = await api(`model-versions/${mvId}/predict/`, { method: 'POST', body: { sheet_id: s.id, allow_raster_inferred: true } });
        const svg = svgEl('svg', { viewBox: `0 0 ${s.width} ${s.height}`, preserveAspectRatio: 'xMidYMid meet', style: { width: '100%', height: '320px', background: '#fff', borderRadius: '10px', display: 'block', border: '1px solid var(--rule)' } }, svgEl('image', { href: s.image_url, x: 0, y: 0, width: s.width, height: s.height }));
        (r.predictions || []).forEach((p) => svg.appendChild(svgEl('polygon', { class: 'overlay-poly', points: p.polygon.map((q) => q.join(',')).join(' '), fill: COL[p.label] || '#c3a6ff', stroke: COL[p.label] || '#c3a6ff' })));
        (r.nodes || []).forEach((n) => { if (!n.bbox || n.label === 'other') return; const [x0, y0, x1, y1] = n.bbox; svg.appendChild(svgEl('rect', { x: x0 - 1, y: y0 - 1, width: Math.max(2, x1 - x0 + 2), height: Math.max(2, y1 - y0 + 2), fill: 'none', stroke: COL[n.label] || '#c3a6ff', 'stroke-width': 2.2, 'vector-effect': 'non-scaling-stroke' })); });
        const counts = {}; (r.predictions || r.nodes || []).forEach((p) => (counts[p.label] = (counts[p.label] || 0) + 1));
        view.replaceChildren(svg);
        legend.replaceChildren(...Object.entries(counts).filter(([k]) => k !== 'other').map(([k, v]) => h('span.chip', {}, h('span.swatch', { style: { background: COL[k] || '#c3a6ff' } }), `${v} ${cap(k).toLowerCase()}${v > 1 ? 's' : ''}`)));
      } catch (e) { view.replaceChildren(h('div.notice.err', {}, e.message)); }
    };
    api(`datasets/${datasetId}/sheets/`).then((sheets) => {
      const sel = h('select', { style: { width: 'auto', minHeight: '36px', marginBottom: '10px' }, onchange: (e) => go(sheets.find((s) => String(s.id) === e.target.value)) }, sheets.map((s) => h('option', { value: s.id }, nice(s.name))));
      wrap.replaceChildren(sel, view, legend);
      if (sheets[0]) go(sheets[0]);
    });
    wrap.append(view);
    return wrap;
  };

  async function deployDialog(mvId, name) {
    const n = h('input', { type: 'text', value: name });
    const ok = await dialog('Deploy this model', h('div.grid', { style: { gap: '16px' } },
      h('div.muted', {}, 'Your software sends a plan sheet to a private API endpoint and gets back everything the model finds. Only requests with your API key are accepted.'),
      h('label.field', {}, h('span', {}, 'Name'), n)), [{ label: 'Deploy', primary: true }], 'Step 05 · Deploy');
    if (!ok) return;
    await guard(() => api('deployments/', { method: 'POST', body: { model_version_id: mvId, name: n.value, confirm: true } }), 'Deployed — it is live');
    location.href = '/ka/deployments/';
  }

  // ================================================================== Models
  P.models = async () => {
    const [ms, jobs] = await Promise.all([api('models/'), api('jobs/')]);
    setTop(['Models']);
    const running = jobs.filter((j) => ACTIVE.includes(j.status));
    const all = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m })));
    const versions = ms.map((m) => m.versions.map((v) => ({ ...v, m, count: m.versions.length })).sort((a, b) => (b.report?.score || 0) - (a.report?.score || 0) || b.version - a.version)[0]).filter(Boolean)
      .sort((a, b) => (b.report?.score || 0) - (a.report?.score || 0));
    const card = (v) => h('div.card.mcard', {},
      h('div.card-h', {}, h('span.key', {}, `${LABEL[v.task] || v.task} · v${v.version}${v.count > 1 ? ` of ${v.count}` : ''}`), v.status === 'archived' ? chip('Archived') : v.report?.ready_to_use ? chip('Ready', 'pos') : chip('Needs work', 'warn')),
      h('div.row', { style: { gap: '14px', flexWrap: 'nowrap' } }, h('div.grade' + (!v.report || v.report.grade.length > 1 ? '.dim' : ''), {}, v.report && v.report.grade.length === 1 ? v.report.grade : '–'),
        h('div', { style: { minWidth: 0 } }, h('div.h3', { style: { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, v.m.name.replace(/-(seg|gnn|inst)-.*/, '')), h('div.muted', { style: { fontSize: '13px' } }, `Trained ${fmt.date(v.created_at)}`))),
      h('div.mlist', {}, (v.report?.items || []).filter((i) => !/unrelated|other/.test(i.name)).slice(0, 3).map((i) => h('div.bar-row', {}, h('span', {}, cap(i.name)), h('div.meter' + ({ fair: '.warn', weak: '.danger' }[i.level] || ''), {}, h('i', { style: { width: Math.round(i.score * 100) + '%' } })), h('span.mono.muted', { style: { fontSize: '12px', textAlign: 'right' } }, `${Math.round(i.score * 10)}/10`)))),
      h('div.mfoot', {}, h('a.btn.sm', { href: `/ka/runs/${v.training_job}/` }, 'Report'),
        v.license.commercially_deployable && v.status === 'ready' ? h('button.btn.sm' + (v.report?.ready_to_use ? '.primary' : ''), { onclick: () => deployDialog(v.id, v.m.name.replace(/-(seg|gnn|inst)-.*/, '')) }, 'Deploy') : null,
        v.downloadable ? h('button.btn.sm.ghost', { onclick: async () => { const r = await guard(() => api(`model-versions/${v.id}/download/`)); location.href = r.url; } }, 'Download') : null));
    mount(head('Your models', 'Models', null, 'Every training run makes a new version. Deploy the one you like — roll back any time.', [h('a.btn.primary', { href: '/ka/train/' }, icon('spark', 16), 'Train a model')]),
      running.length ? h('div.list', {}, running.map((j) => h('a.item.click', { href: `/ka/runs/${j.id}/`, style: { textDecoration: 'none', color: 'inherit' } }, h('span.avatar', {}, icon('spark', 18)), h('div', {}, h('div.t', {}, `${LABEL[j.task] || 'Model'} · run #${j.id}`), h('div.s', {}, `Started ${fmt.ago(j.created_at)}`)), jobChip(j.status)))) : null,
      versions.length ? h('div.grid.eq.' + ({ 1: 'g3', 2: 'g2', 4: 'g2' }[versions.length] || 'g3'), {}, versions.map(card)) : (running.length ? null : h('div.card', {}, empty('No models yet', 'Label a few plans, then train your first model. It takes one click.', h('a.btn.primary', { href: '/ka/' }, 'Go to datasets'), false))),
      jobs.length ? h('details.tech', {}, h('summary', {}, `All training runs · ${jobs.length}`), h('div', {}, h('table.table', {}, h('thead', {}, h('tr', {}, ['Run', 'Status', 'Accuracy', 'Time', 'Started'].map((x) => h('th', {}, x)))),
        h('tbody', {}, jobs.map((j) => h('tr', {}, h('td', {}, h('a', { href: `/ka/runs/${j.id}/` }, `${LABEL[j.task] || 'Model'} · run #${j.id}`)), h('td', {}, jobChip(j.status)), h('td', {}, j.report ? j.report.grade : '—'), h('td.n', {}, fmt.dur(j.runtime_s)), h('td', {}, fmt.ago(j.created_at)))))))) : null);
  };

  // ================================================================== Deployments
  P.deployments = async () => {
    const [deps, ms] = await Promise.all([api('deployments/'), api('models/')]);
    setTop(['Deployments'], [h('a.btn', { href: '/ka/api-keys/' }, icon('key', 16), 'API keys')]);
    const curl = (d) => `curl -X POST ${location.origin}${d.endpoint} \\\n  -H "Authorization: Bearer $KA_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"image": "<base64 PNG of a plan sheet>"}'`;
    mount(head('Step 05 · Deploy', 'Send a drawing. ', 'Get back everything on it.', 'Each deployment is a private API endpoint for one of your models. Your software sends a plan sheet; it returns walls, doors, windows and rooms with their exact positions.'),
      deps.length ? deps.map((d) => {
        const versions = (ms.find((m) => m.id === d.model_id)?.versions || []).filter((v) => v.license.commercially_deployable && v.status === 'ready');
        const act = async (a, body) => { await guard(() => api(`deployments/${d.id}/${a}/`, { method: 'POST', body: body || {} }), 'Updated'); P.deployments(); };
        return sheetFrame([h('div.row', {}, h('div.h2', {}, d.name), d.status === 'active' ? chip('Live', 'pos', true) : chip('Paused', 'warn')),
          h('div.tiles', { style: { marginTop: '18px' } }, tile('Requests', fmt.n(d.request_count), d.last_request_at ? `last ${fmt.ago(d.last_request_at)}` : 'none yet'), tile('Errors', fmt.n(d.error_count), 'rejected requests'), tile('Version', `v${d.active_version_number}`, 'serving now'), tile('Limit', `${d.rate_limit_per_minute}/min`, 'requests')),
          h('div.key', { style: { marginTop: '22px' } }, 'API endpoint'), h('pre.code', { style: { marginTop: '8px' } }, `POST ${location.origin}${d.endpoint}`),
          h('details.tech', { style: { marginTop: '14px' } }, h('summary', {}, 'Example request'), h('div', {}, h('pre.code', {}, curl(d)))),
          h('div.row', { style: { marginTop: '18px' } },
            versions.length > 1 ? h('select', { style: { width: 'auto' }, onchange: (e) => act('set-version', { model_version_id: Number(e.target.value) }) }, versions.map((v) => h('option', { value: v.id, selected: v.id === d.active_version }, `Serve v${v.version}`))) : null,
            d.history.length > 1 ? h('button.btn.sm', { onclick: () => act('rollback') }, 'Roll back') : null,
            h('button.btn.sm', { onclick: () => act(d.status === 'active' ? 'pause' : 'resume') }, d.status === 'active' ? 'Pause' : 'Resume'),
            h('button.btn.sm.danger', { onclick: async () => { if (await dialog('Delete this deployment?', h('div.muted', {}, 'The endpoint stops answering right away. The model itself is kept.'), [{ label: 'Delete', danger: true }])) act('delete'); } }, 'Delete'))],
        { rows: [['Model', LABEL[d.task] || d.task], ['Created', fmt.date(d.created_at)]], no: `KA-5${String(d.id).padStart(2, '0')}` });
      }) : empty('Nothing deployed yet', 'Train a model, check its accuracy, then deploy it from the accuracy report.', h('a.btn.primary', { href: '/ka/models/' }, 'See your models ', arrow())));
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
  const run = P[page];
  if (run) run().catch((e) => { console.error(e); mount(empty('Something went wrong', e.message, h('button.btn', { onclick: () => location.reload() }, 'Try again'))); });
})();
