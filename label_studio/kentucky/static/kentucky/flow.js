/* Kentucky AI — contractor flow: Plan sets → Plan set → Train → Training (live) → Results.
   Every number on these screens comes from the API; nothing is estimated unless it says so. */
(function () {
  'use strict';
  const KA = window.KA;
  const { api, h, svgEl, toast, dialog, guard, fmt, mount, setTop, nice, cap, PAGES: P } = KA;
  const plural = (n, w) => `${fmt.n(n)} ${w}${n === 1 ? '' : 's'}`;
  const NAME = { wall: 'Walls', door: 'Doors', window: 'Windows', room: 'Rooms', room_tag: 'Room names' };
  const nm = (k) => NAME[k] || cap(KA.niceItem(k)) + 's';
  const TASKS = { semantic_segmentation: 'Outline areas', instance_segmentation: 'Item by item', node_classification: 'Name every line', edge_classification: 'Connections between lines' };
  const TASKDESC = { semantic_segmentation: 'Paints every wall, door and window pixel. Fast; works on scans.', instance_segmentation: 'One shape per item — best for counts and review.', node_classification: 'Labels each vector line (graph network). Vector PDFs and CAD.', edge_classification: 'Learns which lines belong together.' };
  const SW = { wall: '#62d4dc', door: '#f0b24a', window: '#9db1ff', room: '#7fcf9c', room_tag: '#7fcf9c' };
  const sw = (k) => SW[k] || '#848e8b';
  const mark = '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>';

  // ------------------------------------------------------------------ drawing helpers
  // vb: [x, y, w, h] in image px (default: whole sheet). cls(item) -> extra class (e.g. 'k-miss')
  function plan(sheet, items, o = {}) {
    const vb = o.vb || [0, 0, sheet.width, sheet.height];
    const svg = svgEl('svg', { class: 'plan', viewBox: vb.join(' '), preserveAspectRatio: o.par || 'xMidYMid meet' },
      svgEl('image', { class: 'planimg', href: sheet.image_url, x: 0, y: 0, width: sheet.width, height: sheet.height, opacity: o.op ?? 0.45 }));
    (items || []).forEach((it, i) => {
      if (!it.polygon || it.polygon.length < 3) return;
      svg.appendChild(svgEl('polygon', { class: `k k-${it.label} ${o.cls ? o.cls(it) : ''} ${o.anim ? 'drawin' : ''}`, points: it.polygon.map((q) => q.join(',')).join(' '),
        style: o.anim ? `animation-delay:${Math.min(i * 6, 900)}ms` : null }));
    });
    return svg;
  }
  // a crop around where the items are (so thumbnails show the building, not the margins)
  function focus(sheet, items, aspect) {
    const pts = (items || []).flatMap((i) => i.polygon || []);
    if (!pts.length) return null;
    let x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0])), y0 = Math.min(...pts.map((p) => p[1])), y1 = Math.max(...pts.map((p) => p[1]));
    const pad = Math.max(x1 - x0, y1 - y0) * 0.06;
    x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
    let w = x1 - x0, hh = y1 - y0;
    if (aspect) { if (w / hh < aspect) { const nw = hh * aspect; x0 -= (nw - w) / 2; w = nw; } else { const nh = w / aspect; y0 -= (nh - hh) / 2; hh = nh; } }
    return [x0, y0, w, hh];
  }
  const dchip = (k, n) => h('span.dchip', {}, h('span.dot', { style: { background: sw(k) } }), `${fmt.n(n)} ${nm(k)}`);
  const lbl = (t, cy) => h('span.lbl' + (cy ? '.cy' : ''), {}, t);
  const tone = (s) => ({ done: 'done', review: 'review', labeled: 'labeled' }[s] || '');
  const greet = () => { const hr = new Date().getHours(); return hr < 12 ? 'Good morning.' : hr < 18 ? 'Good afternoon.' : 'Good evening.'; };
  const sheetLabel = (i) => `Sheet ${String(i + 1).padStart(2, '0')}`;

  function dropCard(datasetId) {
    const input = h('input', { type: 'file', multiple: true, accept: '.pdf,.png,.jpg,.jpeg,.dxf', style: { display: 'none' } });
    const card = h('button.dropc', { onclick: () => input.click() },
      h('div.ic', {}, svgEl('svg', { viewBox: '0 0 24 24' }, svgEl('path', { d: 'M12 16V4M7 9l5-5 5 5M4 16v4h16v-4' }))),
      h('b.t', {}, datasetId ? 'Add sheets' : 'Drop a new plan set'), h('span', { style: { fontSize: '13px' } }, 'The AI marks it up for you to check.'),
      h('div.fmt', {}, ['PDF', 'DXF', 'SCAN', 'JPG'].map((x) => h('span', {}, x))), input);
    KA.wireDrop(card, input, datasetId);
    return card;
  }

  // ================================================================== Plan sets (home)
  P.home = async () => {
    const { plan_sets: ps, next } = await api('home/');
    setTop(['Plan sets']);
    const nc = document.getElementById('nc-home'); if (nc) nc.textContent = ps.length || '';
    const d = ps.find((x) => x.id === next.dataset) || ps[0];
    const SUB = { review: 'One plan set is waiting on you.', check: 'Check your sheets, then train.', label: 'Let the AI mark up your plans.', training: 'Your model is learning.',
      train: "You're ready to train.", deploy: 'Your model is ready to go live.', live: 'Your model is live.', upload: 'Drop your plans to get started.' };
    const head = h('div.headrow', {}, h('h1.h1', {}, greet(), h('br'), h('span.dim', {}, SUB[next.kind])),
      h('div.row', {}, ps.length ? h('button.btn.ink', { onclick: () => document.querySelector('.dropc input')?.click() }, '＋ Upload plans') : null));
    if (!ps.length) return mount(head, h('div', { style: { maxWidth: '520px' } }, dropCard(null)));
    // next-up hero
    const pct = d.sheets.length ? Math.round((d.done / d.sheets.length) * 100) : 0;
    let title, meta, actions;
    const cta = (t, href) => h('a.btn.primary.lg', { href }, t, ' →');
    const second = (t, href) => h('a.btn.lg.ghostd', { href }, t);
    if (next.kind === 'review') {
      title = 'Finish checking'; meta = `${plural(next.pending, 'AI suggestion')} left to check on sheet ${next.sheet_pos}. Keep what is right — about ${Math.max(1, Math.round(next.pending / 12))} min.`;
      actions = [cta('Continue checking', `/ka/markup/${next.sheet}/`), d.done ? second("Train with what's done", `/ka/train/?dataset=${d.id}`) : null];
    } else if (next.kind === 'check' || next.kind === 'label') {
      title = next.kind === 'label' ? 'Mark up your plans' : 'Check your sheets';
      meta = next.kind === 'label' ? 'Open a sheet and let the AI take the first pass. You just keep what is right.' : `${d.done} of ${d.sheets.length} sheets checked. Confirm the labels on each sheet so the model learns from them.`;
      actions = [cta(next.kind === 'label' ? 'Start' : 'Continue checking', `/ka/markup/${next.sheet}/`), d.done >= 2 ? second("Train with what's done", `/ka/train/?dataset=${d.id}`) : null];
    } else if (next.kind === 'training') {
      title = 'Your model is learning'; meta = 'Training on the sheets you checked. You can keep working while it runs.';
      actions = [cta('Watch it learn', `/ka/runs/${next.job}/`)];
    } else if (next.kind === 'train') {
      title = 'Ready to train'; meta = `${d.done} sheets checked with ${plural(d.objects, 'item')}. Teach your model what to find.`;
      actions = [cta('Train your model', `/ka/train/?dataset=${d.id}`)];
    } else if (next.kind === 'deploy') {
      title = 'Put your model to work'; meta = `Model v${d.model.version} passed its test. Turn it into an API your software can call.`;
      actions = [cta('See results', `/ka/runs/${d.model.job}/`)];
    } else {
      title = next.kind === 'live' ? 'Your model is live' : 'Add your plans'; meta = next.kind === 'live' ? 'It is answering requests from your software.' : 'PDF, scans or DXF.';
      actions = [cta(next.kind === 'live' ? 'Open deployment' : 'Upload plans', next.kind === 'live' ? '/ka/deployments/' : '/ka/')];
    }
    const right = h('div.r');
    if (d.cover) {
      const fv = focus(d.cover, d.cover.items, 1.6);
      right.append(plan(d.cover, d.cover.items, { vb: fv, par: 'xMidYMid slice', anim: true, op: 0.5 }), h('div.glow'),
        h('div.chips', {}, Object.entries(d.counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => dchip(k, n))));
    }
    const hero = h('section.dpanel.ticks.nexthero', {},
      h('div.l', {}, lbl('● Next up', true), h('div.t', {}, title, h('br'), h('span.dim', {}, d.name)), h('div.meta', {}, meta),
        h('div', { style: { marginTop: 'auto' } }, h('div.track', { style: { marginTop: '22px' } }, h('i', { style: { width: pct + '%' } })),
          h('div.row', { style: { justifyContent: 'space-between', margin: '9px 0 18px' } }, lbl(`${d.done} of ${d.sheets.length} sheets checked`), lbl(pct + '%', true)),
          h('div.row', { style: { gap: '10px' } }, actions))), right);
    // plan set cards
    const cards = ps.map((x) => {
      const th = h('div.dpanel.ticks.th', {}, x.cover ? lbl(nice(x.cover.name)) : null);
      if (x.cover) th.append(plan(x.cover, x.cover.items, { vb: focus(x.cover, x.cover.items, 1.55) || undefined, par: 'xMidYMid slice', op: 0.75 }));
      const pill = x.training ? h('span.pill.cy', {}, h('span.dot'), 'Learning')
        : x.pending ? h('span.pill.cy', {}, h('span.dot'), `Checking · ${x.done} of ${x.sheets.length}`)
          : x.model && x.model.ready ? h('span.pill.ok', {}, `✓ Model v${x.model.version} ready`)
            : x.done === x.sheets.length && x.sheets.length ? h('span.pill.ok', {}, '✓ All checked')
              : h('span.pill.mute', {}, `${x.done} of ${x.sheets.length} checked`);
      return h('a.ps', { href: `/ka/projects/${x.id}/` }, th, h('div.b', {}, h('div.n', {}, x.name),
        h('div.m', {}, `${plural(x.sheets.length, 'sheet')} · ${plural(x.objects, 'item')} marked`),
        h('div.f', {}, pill, h('div.sbars', {}, x.sheets.map((s) => h('i.' + (tone(s.state) || 'x'), { title: s.state }))))));
    });
    const sheetsTotal = ps.reduce((a, x) => a + x.sheets.length, 0);
    mount(head, hero, h('div.secrow', {}, h('div.h2', {}, 'Your plan sets'), lbl(`${plural(ps.length, 'set')} · ${plural(sheetsTotal, 'sheet')}`)),
      h('div.psgrid', {}, cards, dropCard(null)));
  };

  // ================================================================== Plan set
  P.project = async () => {
    const id = Number(document.body.dataset.pk);
    const [{ plan_sets: ps }, sheets, objs] = await Promise.all([api('home/'), api(`datasets/${id}/sheets/`), api(`datasets/${id}/objects/`)]);
    const d = ps.find((x) => x.id === id);
    setTop([['Plan sets', '/ka/'], d.name]);
    const by = {}; objs.forEach((o) => { if (o.geometry.polygon) (by[o.sheet_id] = by[o.sheet_id] || []).push({ label: o.label, polygon: o.geometry.polygon }); });
    const st = Object.fromEntries(d.sheets.map((s) => [s.id, s]));
    const firstOpen = d.sheets.find((s) => s.state !== 'done') || d.sheets[0];
    const canTrain = d.done >= 2;
    const PILL = { done: () => h('span.pill.ok', {}, '✓ Checked'), review: (s) => h('span.pill.cy', {}, h('span.dot'), `${s.pending} to check`), labeled: () => h('span.pill.mute', {}, 'Not checked'), empty: () => h('span.pill.mute', {}, 'Not marked up') };
    const cards = sheets.map((s, i) => {
      const th = h('div.dpanel.ticks.th', {}, lbl(sheetLabel(i)));
      th.append(plan(s, by[s.id] || [], { vb: focus(s, by[s.id], 1.4) || undefined, par: 'xMidYMid slice', op: 0.8 }));
      const x = st[s.id] || { state: 'empty' };
      return h('a.ps', { href: `/ka/markup/${s.id}/` }, th, h('div.b', {}, h('div.n', { title: s.name }, nice(s.name)),
        h('div.f', { style: { marginTop: '8px' } }, PILL[x.state](x), h('span.lbl', {}, `${(by[s.id] || []).length} items`))));
    });
    let msg, act;
    if (!sheets.length) { msg = ['Add sheets to get started.', 'PDF, scans or DXF.']; act = null; }
    else if (d.pending) { msg = [`${plural(d.pending, 'AI suggestion')} to check.`, 'Keep what is right — it takes a few minutes.']; act = h('a.btn.primary', { href: `/ka/markup/${(d.sheets.find((s) => s.pending) || firstOpen).id}/` }, 'Continue checking →'); }
    else if (d.done < d.sheets.length && !canTrain) { msg = [`${d.done} of ${d.sheets.length} sheets checked.`, 'Check at least 2 sheets to train a model.']; act = h('a.btn.primary', { href: `/ka/markup/${firstOpen.id}/` }, 'Check next sheet →'); }
    else { msg = ['Ready to train.', `${d.done} checked sheets · ${plural(d.objects, 'item')}.`]; act = h('a.btn.primary', { href: `/ka/train/?dataset=${id}` }, 'Train model →'); }
    mount(
      h('div.headrow', {}, h('h1.h1', {}, d.name, h('br'), h('span.dim', {}, `${plural(sheets.length, 'sheet')} · ${d.done} checked`)),
        h('div.totals', {}, Object.entries(d.counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => h('div', {}, h('b', {}, fmt.n(n)), lbl(nm(k)))),
          h('div', {}, h('b', { style: { color: 'var(--teal)' } }, `${d.done}/${d.sheets.length}`), lbl('Sheets done')))),
      h('div.statusbar', {}, h('div', {}, h('b', {}, msg[0]), h('div.s', {}, msg[1])), h('div.grow'), canTrain && act && !/train/.test(act.href) ? h('a.btn', { href: `/ka/train/?dataset=${id}` }, 'Train with what\'s done') : null, act),
      h('div.sheetgrid', {}, cards, dropCard(id)));
  };

  // ================================================================== Train
  P.train = async () => {
    const qs = new URLSearchParams(location.search);
    const ds = await api('datasets/');
    if (!ds.length) return mount(KA.empty('No plan sets yet', 'Add and check some plans first.', h('a.btn.primary', { href: '/ka/' }, 'Add plans')));
    const id = Number(qs.get('dataset') || ds[0].id);
    const d = ds.find((x) => x.id === id) || ds[0];
    let [{ plan_sets: ps }, rd, est, ms, cat] = await Promise.all([api('home/'), api(`datasets/${d.id}/readiness/`), api(`datasets/${d.id}/estimate/?goal=outlines`), api('models/'), api('catalog/')]);
    let adv = null; // advanced choice: { task, catalog_id, init, base_model_version_id, config, label }
    const hp = ps.find((x) => x.id === d.id);
    setTop([['Plan sets', '/ka/'], [d.name, `/ka/projects/${d.id}/`], 'Train']);
    const counts = (rd.stats && rd.stats.class_counts) || hp.counts;
    const versions = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m }))).filter((v) => v.dataset_id === d.id && v.task === 'semantic_segmentation' && v.report).sort((a, b) => (a.created_at < b.created_at ? -1 : 1)); // in training order, across architectures
    const prev = versions[versions.length - 1];
    let speed = 'cpu-local';
    const isReady = () => !!rd.ready_for?.[adv ? adv.task : 'semantic_segmentation'];
    const cover = hp.cover;
    const classes = [...new Set(['wall', 'door', 'window', ...Object.keys(counts)])].filter((k) => k !== 'unknown').slice(0, 4);
    if (classes.length < 4) classes.push('room');
    const tile = (k) => {
      const n = counts[k] || 0, ok = n >= 3;
      const pv = h('div.dpanel.pv');
      const its = (cover?.items || []).filter((i) => i.label === k);
      if (cover && its.length) { const f = focus(cover, its.slice(0, 6), 1.5); pv.append(plan(cover, its, { vb: f, par: 'xMidYMid slice', op: 0.45 })); }
      else pv.append(h('div', { style: { height: '100%', display: 'grid', placeItems: 'center' } }, lbl(ok ? '' : 'Not enough yet')));
      return h('div.cls' + (ok ? '.on' : '.off'), {}, pv, h('div.nm', {}, nm(k), h('span.ck', {}, ok ? '✓' : '')),
        h('div.ex', {}, ok ? `${fmt.n(n)} examples · ${n >= 30 ? 'plenty' : 'enough'}` : n ? `${n} examples · need ${3 - n} more` : 'No examples yet'),
        h('div.bar', {}, h('i', { style: { width: Math.min(100, (n / 30) * 100) + '%', background: ok ? '' : 'var(--ink-4)' } })));
    };
    const SPEEDS = [['cpu-local', 'Standard', 'Runs on our servers. Included in your plan.'], ['nvidia-t4', 'Fast', 'A cloud GPU. Pay only for the minutes used.'], ['nvidia-a10g', 'Fastest', 'A bigger cloud GPU for large plan sets.']];
    const mid = (e) => (e.seconds_low + e.seconds_high) / 2;
    const cost = (e) => (Number(e.customer_cost_high) === 0 ? 'Included' : '~' + fmt.usd((Number(e.customer_cost_low) + Number(e.customer_cost_high)) / 2));
    const speedRow = h('div.speedgrid');
    const panel = h('aside.dpanel.ticks.readyp');
    const checklist = () => {
      const blockers = rd.blockers || [];
      const items = [
        [hp.done >= 2 ? 'ok' : 'no', `${hp.done} sheet${hp.done === 1 ? '' : 's'} checked`, hp.done >= 2 ? 'Every label on them confirmed' : 'Check at least 2 sheets'],
        [isReady() ? 'ok' : 'no', `${fmt.n(Object.values(counts).reduce((a, b) => a + b, 0))} examples`, isReady() ? 'Enough of each item to learn from' : (blockers[0]?.message || (adv && !rd.ready_for?.[adv.task] ? `Not enough labels yet for ${TASKS[adv.task]}` : 'Not enough examples yet'))],
        adv ? ['ok', adv.label, adv.detail] : prev ? ['ok', `Builds on Model v${prev.version}`, 'Starts from what it already knows'] : ['ok', 'First model for this plan set', 'Starts fresh'],
      ];
      const open = hp.sheets.length - hp.done;
      if (open) items.push(['w', `${plural(open, 'sheet')} not checked yet`, "They'll be skipped — check them for a better model"]);
      return items.map(([t, a, b]) => h('div.ci', {}, h('span.i.' + t, {}, t === 'ok' ? '✓' : t === 'w' ? '!' : '×'), h('div', {}, a, h('small', {}, b))));
    };
    const render = () => {
      speedRow.replaceChildren(...SPEEDS.map(([k, t, desc]) => {
        const e = est[k];
        return h('button.sp' + (speed === k ? '.on' : ''), { onclick: () => { speed = k; render(); } }, h('div.tt', {}, t, k === 'cpu-local' ? h('span.pill.cy', {}, 'Recommended') : null), h('div.d', {}, desc),
          h('div.nums', {}, h('div', {}, h('b', {}, e ? '~' + fmt.dur(mid(e)) : '—'), lbl('Time')), h('div', {}, h('b', {}, e ? cost(e) : '—'), lbl('Cost'))));
      }));
      const e = est[speed];
      const ready = isReady();
      panel.replaceChildren(lbl(ready ? '● Ready to train' : '● Not ready yet', ready), h('div.t', {}, `Model v${(() => { if (!adv) return prev ? prev.version + 1 : 1; const vs = ms.flatMap((m) => m.versions).filter((v) => v.catalog_id === adv.catalog_id && v.dataset_id === d.id); return vs.length ? Math.max(...vs.map((v) => v.version)) + 1 : 1; })()} for`, h('br'), h('span.dim', {}, d.name)),
        h('div', { style: { marginTop: '18px' } }, checklist()),
        h('div.est3', {}, h('div', {}, h('b', {}, e ? '~' + fmt.dur(mid(e)) : '—'), lbl('Time')), h('div', {}, h('b', {}, e ? cost(e) : '—'), lbl('Cost')), h('div', {}, h('b', {}, '1+'), lbl('Test sheet'))),
        h('button.btn.primary.lg.go', { disabled: !ready || !e, onclick: () => start(e) }, 'Start training →'),
        h('button.btn.lg.go.ghostd', { onclick: customize }, adv ? 'Change model & settings' : 'Customize model & settings'),
        h('div.fine', {}, 'We test it on a sheet it never saw and tell you how it did.'));
    };
    async function start(e) {
      if (Number(e.customer_cost_high) > 0 && !(await dialog('Approve the cost', h('p.muted', {}, `This uses a cloud GPU. You pay for the minutes used — never more than ${fmt.usd(e.max_charge_at_runtime_limit)}.`), [{ label: `Approve up to ${fmt.usd(e.max_charge_at_runtime_limit)}`, primary: true }]))) return;
      const body = { goal: 'outlines', gpu_type: speed };
      if (adv) Object.assign(body, { catalog_id: adv.catalog_id, init: adv.init, base_model_version_id: adv.base_model_version_id, config: adv.config });
      const r = await guard(() => api(`datasets/${d.id}/train/`, { method: 'POST', body }));
      if (!r.ready) return toast('Not ready yet — check at least 2 sheets with 3 examples of each item.', 'danger');
      if (r.job.status === 'FAILED') return toast(r.job.error, 'danger');
      await guard(() => api(`jobs/${r.job.id}/authorize/`, { method: 'POST', body: { confirm: true } }));
      location.href = `/ka/runs/${r.job.id}/`;
    }
    // ---------------- advanced: task → architecture → starting point → settings (validated server-side)
    async function customize() {
      const TASKLIST = Object.keys(TASKS);
      let task = adv ? adv.task : 'semantic_segmentation';
      let cid = adv ? adv.catalog_id : null, init = adv ? adv.init : null, base = adv ? adv.base_model_version_id : null, cfg = adv ? { ...adv.fullConfig } : null, defaults = null, schema = {}, enums = {};
      const own = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m }))).filter((v) => v.status === 'ready');
      const body = h('div.adv-body');
      const close = () => scrim.remove();
      const scrim = h('div.scrim', { onclick: (e) => { if (e.target === scrim) close(); } }, h('div.dialog.advdlg', { role: 'dialog', 'aria-modal': 'true' },
        h('div.row', { style: { justifyContent: 'space-between' } }, h('div', {}, lbl('Training center · advanced'), h('div.h2', { style: { marginTop: '6px' } }, 'Choose the model and how it learns')), h('button.btn.sm.ghost', { onclick: close }, 'Close')), body));
      document.body.appendChild(scrim);
      const loadDefaults = async () => { const r = await api(`training/defaults/?catalog_id=${cid}&train_items=${Math.max(1, hp.done)}`); defaults = r.config; schema = r.schema; enums = r.enums; if (!cfg || cfg._cid !== cid) cfg = { ...r.config, _cid: cid }; };
      const arches = () => cat.open_models.filter((m) => m.task === task);
      const draw = async () => {
        if (!cid || !arches().some((a) => a.id === cid)) { const kind = hp.scanned * 2 > hp.sheets.length ? 'scan' : 'vector'; cid = (arches().find((a) => a.best_for === kind && !(a.min_sheets > hp.done)) || arches().find((a) => a.recommended) || arches().find((a) => a.cpu_trainable && !(a.min_sheets > hp.done)) || arches()[0])?.id; init = null; cfg = null; }
        if (cid && (!cfg || cfg._cid !== cid)) await loadDefaults();
        const arch = arches().find((a) => a.id === cid);
        const inits = arch ? arch.inits.filter((i) => i.id !== 'checkpoint') : [];
        const mine = own.filter((v) => v.catalog_id === cid).sort((a, b) => (b.dataset_id === d.id) - (a.dataset_id === d.id)); // this plan set's first
        if (!init) init = mine.length ? 'checkpoint' : 'scratch';
        if (init === 'checkpoint' && !base && mine[0]) base = mine[0].id;
        const step = (n, t, ...kids) => h('section.advstep', {}, h('div.stepl', {}, h('span.n', {}, String(n)), h('b', {}, t)), ...kids);
        const opt = (on, onclick, title, sub, chips, disabled) => h('button.advopt' + (on ? '.on' : '') + (disabled ? '.off' : ''), { onclick: disabled ? null : onclick, disabled: !!disabled }, h('div', {}, h('b', {}, title), sub ? h('small', {}, sub) : null), chips ? h('div.chips2', {}, chips) : null);
        const lic = (txt, ok) => h('span.pill.' + (ok ? 'ok' : ok === false ? 'warn' : 'mute'), {}, txt);
        const fields = cfg ? Object.keys(schema).filter((k) => ['epochs', 'batch_size', 'lr', 'weight_decay', 'crop_size', 'crops_per_sheet', 'training_scale', 'hidden', 'layers', 'heads', 'dropout', 'early_stopping_patience', 'seed', 'max_runtime_s'].includes(k)) : [];
        body.replaceChildren(
          step(1, 'What should it learn?', h('div.advgrid', {}, TASKLIST.map((t) => opt(task === t, () => { task = t; cid = null; draw(); }, TASKS[t], TASKDESC[t], [rd.ready_for?.[t] ? lic('Your labels are ready', true) : lic('Needs more labels')])))),
          step(2, 'Model architecture', h('div.advgrid', {}, arches().map((a) => opt(cid === a.id, () => { cid = a.id; init = null; base = null; cfg = null; draw(); }, a.name, a.description,
            [lic(`Code: ${a.implementation_license}`, true), a.inits.some((i) => i.id === 'pretrained' && i.commercially_deployable) ? lic('Pretrained · OK to deploy', true) : null, a.badge ? h('span.pill.cy', {}, a.badge) : null, a.experimental ? lic('Experimental', false) : null, lic(a.cpu_trainable ? 'Trains on our servers' : `Needs GPU (${a.gpu_recommended})`, a.cpu_trainable ? true : null)].filter(Boolean))))),
          step(3, 'Starting point', h('div.advgrid', {},
            opt(false, null, 'Kentucky AI model', cat.kentucky_models_note || 'Coming soon', [lic('Not available yet')], true),
            inits.map((i) => opt(init === i.id, () => { init = i.id; base = null; draw(); }, i.id === 'scratch' ? 'Start from zero' : i.label, i.note || i.checkpoint_license,
              [lic(i.commercially_deployable === true ? 'OK to deploy commercially' : 'Legal review pending — can’t deploy', i.commercially_deployable === true ? true : false)])),
            mine.map((v) => opt(init === 'checkpoint' && base === v.id, () => { init = 'checkpoint'; base = v.id; draw(); }, `Your model v${v.version} · ${v.dataset_name || 'plan set'}`, `${v.report ? Math.round(v.report.score * 100) + '% on its test · ' : ''}trained ${fmt.date(v.created_at)}`, [lic('Yours to deploy', true)])))),
          cfg ? step(4, 'Settings', h('p.muted.small', { style: { margin: '-4px 0 10px' } }, 'Pre-filled with what we recommend for this model. Every value is checked before training starts.' + (init === 'checkpoint' ? ' Continuing from your model uses 0.3× this learning rate unless you change it, and keeps your model if training does not beat it.' : '')),
            h('div.advfields', {}, fields.map((k) => h('label.field', {}, h('span', {}, (FIELD_LABEL[k] || k.replace(/_/g, ' '))),
              h('input', { type: 'number', value: cfg[k], step: schema[k].type === 'float' ? 'any' : '1', min: schema[k].min, max: schema[k].max, oninput: (e) => { cfg[k] = schema[k].type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value); } }),
              defaults[k] !== cfg[k] ? h('small.cy', {}, `recommended ${defaults[k]}`) : null)),
            Object.keys(enums).map((k) => h('label.field', {}, h('span', {}, FIELD_LABEL[k] || k.replace(/_/g, ' ')), h('select', { onchange: (e) => { cfg[k] = e.target.value; } }, enums[k].map((o) => h('option', { value: o, selected: cfg[k] === o }, o))))))) : null,
          h('div.row', { style: { justifyContent: 'flex-end', gap: '10px', marginTop: '6px' } },
            h('button.btn', { onclick: () => { adv = null; close(); refresh(); } }, 'Use recommended'),
            h('button.btn.primary', { onclick: apply }, 'Use these settings')));
      };
      async function apply() {
        const arch = arches().find((a) => a.id === cid);
        const over = {}; Object.keys(defaults).forEach((k) => { if (JSON.stringify(defaults[k]) !== JSON.stringify(cfg[k])) over[k] = cfg[k]; });
        try { await api(`datasets/${d.id}/estimate/?catalog_id=${cid}` + (over.epochs ? `&epochs=${over.epochs}` : '') + (over.batch_size ? `&batch_size=${over.batch_size}` : '')); } catch (e) { return toast(e.message, 'danger'); }
        const i = arch.inits.find((x) => x.id === init);
        const bv = own.find((v) => v.id === base);
        adv = { task, catalog_id: cid, init, base_model_version_id: init === 'checkpoint' ? base : null, config: over, fullConfig: { ...cfg },
          label: arch.name, detail: init === 'checkpoint' ? `Fine-tunes your model v${bv?.version} (${bv?.dataset_name || 'plan set'})` : init === 'scratch' ? 'Starts from zero' : `Starts from ${i?.label}` + (Object.keys(over).length ? ` · ${Object.keys(over).length} custom setting${Object.keys(over).length > 1 ? 's' : ''}` : '') };
        close(); refresh();
      }
      draw();
    }
    async function refresh() {
      const q = adv ? `catalog_id=${adv.catalog_id}` + (adv.config.epochs ? `&epochs=${adv.config.epochs}` : '') + (adv.config.batch_size ? `&batch_size=${adv.config.batch_size}` : '') : 'goal=outlines';
      try { est = await api(`datasets/${d.id}/estimate/?${q}`); } catch (e) { toast(e.message, 'danger'); }
      render();
    }
    // history (measured scores only)
    const hist = h('div.hist', {}, versions.slice(-2).flatMap((v, i) => [i ? h('span.harrow') : null,
      h('div.hv', { title: `${v.m.name} v${v.version}` }, lbl(`Run ${versions.indexOf(v) + 1} · ${fmt.date(v.created_at).replace(/, \d{4}$/, '')}`), h('b', {}, Math.round(v.report.score * 100) + '%'), h('small', {}, 'items found on test sheet'))]),
    versions.length ? h('span.harrow') : null, h('div.hv.next', {}, lbl(`Run ${versions.length + 1} · today`, true), h('b', {}, '?'), h('small', {}, `Find out in ~${fmt.dur(mid(est['cpu-local']))}`)),
    (() => { const pts = versions.slice(-4).map((v) => v.report.score); if (!pts.length) return null; const xs = pts.map((_, i) => (i / Math.max(pts.length, 1)) * 300); const y = (s) => 64 - s * 56;
      return svgEl('svg', { viewBox: '0 0 300 70', preserveAspectRatio: 'none' }, svgEl('path', { d: pts.map((s, i) => `${i ? 'L' : 'M'}${xs[i]} ${y(s)}`).join(' '), stroke: 'var(--ink)', 'stroke-width': 2, fill: 'none' }),
        svgEl('path', { d: `M${xs[xs.length - 1]} ${y(pts[pts.length - 1])} L300 ${y(Math.min(1, pts[pts.length - 1] + 0.05))}`, stroke: 'var(--teal)', 'stroke-width': 2, 'stroke-dasharray': '5 5', fill: 'none' }),
        pts.map((s, i) => svgEl('circle', { cx: xs[i], cy: y(s), r: 4, fill: 'var(--ink)' })), svgEl('circle', { cx: 300, cy: y(Math.min(1, pts[pts.length - 1] + 0.05)), r: 5, fill: '#62d4dc', stroke: 'var(--teal)', 'stroke-width': 2 })); })());
    render();
    mount(h('div.trainwrap', {}, h('div', {},
      h('h1.h1', {}, 'Teach your model.', h('br'), h('span.dim', {}, 'It learns from the sheets you checked.')),
      h('div.step', {}, h('div.stepl', {}, h('span.n', {}, '1'), h('b', {}, 'What it will learn to find'), lbl(`From ${plural(hp.done, 'checked sheet')}`)), h('div.clsgrid', {}, classes.map(tile))),
      h('div.step', {}, h('div.stepl', {}, h('span.n', {}, '2'), h('b', {}, 'How fast?')), speedRow),
      h('div.step', {}, h('div.stepl', {}, h('span.n', {}, '3'), h('b', {}, "How it's improving"), lbl('Share of items found on its test sheet')), hist)), panel));
  };

  const FIELD_LABEL = { lr: 'Learning rate', batch_size: 'Batch size', weight_decay: 'Weight decay', crop_size: 'Crop size (px)', crops_per_sheet: 'Crops per sheet',
    training_scale: 'Image scale', hidden: 'Hidden size', layers: 'Layers', heads: 'Attention heads', early_stopping_patience: 'Stop after rounds without progress',
    max_runtime_s: 'Time limit (seconds)', optimizer: 'Optimizer', scheduler: 'Learning-rate schedule' };
  // ================================================================== Training run: live → results
  const STEP = [['PREPARING', 'Got your checked sheets ready'], ['TRAINING', 'Learning to find each item'], ['EVALUATING', "Testing on a sheet it hasn't seen"], ['SAVING', 'Saving the model']];
  const ORDER = ['CREATED', 'VALIDATING', 'QUEUED', 'PROVISIONING', 'PREPARING', 'TRAINING', 'EVALUATING', 'SAVING', 'COMPLETED'];
  P.run = async () => {
    const j = await api(`jobs/${document.body.dataset.pk}/`);
    const sheets = await api(`datasets/${j.dataset_id}/sheets/`);
    const ds = await api(`datasets/${j.dataset_id}/`);
    const test = sheets.find((s) => (j.eval_sheets || []).includes(s.id)) || sheets[0];
    const live = KA.ACTIVE.includes(j.status) || ['VALIDATING', 'QUEUED', 'CREATED'].includes(j.status);
    setTop([['Plan sets', '/ka/'], [ds.name, `/ka/projects/${ds.id}/`], live ? 'Training' : 'Results']);
    if (live) return runLive(j, test);
    if (j.status !== 'COMPLETED') {
      return mount(h('div.headrow', {}, h('h1.h1', {}, (KA.STATUS[j.status] || [j.status])[0] + '.', h('br'), h('span.dim', {}, j.status === 'CANCELLED' ? 'You stopped this run. Nothing more is charged.' : 'Something went wrong while training.'))),
        h('div.note', {}, (j.error || '').split('\n')[0] || 'No details.'), h('div.row', {}, h('a.btn.primary', { href: `/ka/train/?dataset=${j.dataset_id}` }, 'Try again →')), KA.techDetails(j));
    }
    return runResults(j, test, sheets, ds);
  };

  function runLive(j, test) {
    const hist = (j.metrics_history || []).filter((m) => m.epoch);
    const total = j.config?.epochs || 1, ep = hist.length ? hist[hist.length - 1].epoch : 0;
    const key = ['val_mean_iou', 'val_macro_f1', 'val_map50', 'val_map'].find((k) => hist.some((m) => m[k] != null));
    const series = key ? hist.filter((m) => m[key] != null).map((m) => m[key]) : [];
    const pct = j.status === 'TRAINING' ? Math.max(4, Math.round((ep / total) * 100)) : { EVALUATING: 96, SAVING: 99 }[j.status] || 2;
    const left = j.started_at && pct > 8 && j.status === 'TRAINING' ? ((Date.now() - new Date(j.started_at)) / 1000) * (100 / pct - 1) : null;
    const at = (s) => (j.status_history || []).find((x) => x.status === s)?.at;
    const idx = ORDER.indexOf(j.status);
    const steps = STEP.map(([s, t]) => {
      const i = ORDER.indexOf(s), state = idx > i ? 'ok' : idx === i ? 'on' : 'wait';
      const nxt = ORDER[i + 1]; const dur = at(s) && (at(nxt) || state === 'on') ? ((at(nxt) ? new Date(at(nxt)) : new Date()) - new Date(at(s))) / 1000 : null;
      return h('div.st' + (state === 'wait' ? '.dim' : ''), {}, h('span.i.' + state, {}, state === 'ok' ? '✓' : ''), state === 'on' ? h('b', { style: { fontWeight: 600 } }, t) : t, dur != null ? h('span.r', {}, fmt.dur(dur)) : null);
    });
    const view = h('div.dpanel.ticks', {}, plan(test, [], { op: 0.55 }), h('div.scanl'),
      h('div.ptop', {}, h('span.dchip', {}, 'Test sheet · ', nice(test.name)), h('span.dchip', { style: { marginLeft: 'auto' } }, 'Results appear when it finishes')),
      h('div.pbot', {}, h('span.dchip', {}, `Round ${ep} / ${total}`), h('div.ticksrow', {}, Array.from({ length: Math.min(total, 60) }, (_, i) => h('i.' + (i < Math.round((ep / total) * Math.min(total, 60)) - 1 ? 'd' : i === Math.round((ep / total) * Math.min(total, 60)) - 1 ? 'c' : 'x')))), h('span.dchip', { style: { color: '#62d4dc' } }, pct + '%')));
    const spark = series.length > 1 ? (() => { const mx = Math.max(...series, 0.01); const pts = series.map((v, i) => [(i / (series.length - 1)) * 300, 60 - (v / mx) * 52]);
      return svgEl('svg', { viewBox: '0 0 300 64', preserveAspectRatio: 'none' }, svgEl('path', { d: pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${p[1]}`).join(' ') + ' V64 H0Z', fill: 'rgba(98,212,220,.14)' }),
        svgEl('path', { d: pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${p[1]}`).join(' '), fill: 'none', stroke: 'var(--ink)', 'stroke-width': 2 }), svgEl('circle', { cx: pts[pts.length - 1][0], cy: pts[pts.length - 1][1], r: 4.5, fill: '#62d4dc', stroke: 'var(--teal)', 'stroke-width': 2 })); })() : null;
    mount(h('div.headrow', {}, h('div', {}, h('span.livetag', {}, h('i'), j.status === 'TRAINING' ? `Training · round ${ep} of ${total}` : (KA.STATUS[j.status] || [j.status])[0]),
      h('h1.h1', {}, 'Your model is learning.', h('br'), h('span.dim', {}, left ? `About ${fmt.dur(left)} left.` : 'Getting started…'))),
    h('button.btn', { onclick: async () => { if (await dialog('Stop training?', h('p.muted', {}, 'You only pay for the time used so far.'), [{ label: 'Stop', danger: true }])) { await guard(() => api(`jobs/${j.id}/cancel/`, { method: 'POST', body: {} })); P.run(); } } }, 'Stop training')),
    h('div.runwrap', {}, view, h('div.runcol', {},
      h('div.bigstat', {}, lbl('How closely it matches your labels'), h('div.n', {}, series.length ? Math.round(series[series.length - 1] * 100) + '%' : '—', h('span', {}, series.length ? ' on the check sheet' : '')),
        h('div.s', {}, series.length > 1 ? `Started at ${Math.round(series[0] * 100)}%. ${series[series.length - 1] >= series[series.length - 2] ? 'Still climbing.' : 'Settling in.'}` : 'Measured after each round.'), spark),
      h('div.steps', {}, steps),
      h('div.note', {}, 'You can keep working on other plan sets. This page updates by itself.'))));
    setTimeout(() => { if (document.body.dataset.page === 'run') P.run(); }, 2500);
  }

  // match predictions to the user's labels on the test sheet: a label counts as found when a prediction of the same
  // item covers its centre or overlaps its box by ≥ 30% (same rule for outline and instance models)
  function matchUp(gt, pred) {
    const bb = (p) => { const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; };
    const iou = (a, b) => { const iw = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])), ih = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1])); const i = iw * ih; const u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i; return u > 0 ? i / u : 0; };
    const inside = (pt, poly) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c; } return c; };
    const P2 = pred.map((p) => ({ ...p, b: bb(p.polygon), used: false }));
    const found = [], missed = [];
    gt.forEach((g) => {
      const b = bb(g.polygon), c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
      const m = P2.filter((p) => p.label === g.label && (iou(p.b, b) >= 0.3 || (c[0] >= p.b[0] && c[0] <= p.b[2] && c[1] >= p.b[1] && c[1] <= p.b[3] && inside(c, p.polygon))));
      if (m.length) { m.forEach((p) => (p.used = true)); found.push(g); } else missed.push(g);
    });
    return { found, missed, pred: P2, extra: P2.filter((p) => !p.used) };
  }

  async function runResults(j, test, sheets, ds) {
    const rc = j.report || { items: [], advice: '', sentence: '' };
    const ms = await api('models/');
    const all = ms.flatMap((m) => m.versions.map((v) => ({ ...v, m })));
    const mv = all.find((v) => v.id === j.model_version);
    const prev = mv && all.filter((v) => v.model_id === mv.model_id && v.version < mv.version && v.report).sort((a, b) => b.version - a.version)[0];
    const items = rc.items.filter((i) => !/unrelated|other|background/.test(i.name));
    const lead = items.find((i) => i.key === 'door') || items[0];
    const view = h('div.dpanel.ticks', {}, h('div.ptop', {}, h('span.dchip', {}, 'Loading the test sheet…')));
    const deployable = mv && rc.ready_to_use && mv.license?.commercially_deployable;
    const card = (i) => {
      const p = prev?.report?.items.find((x) => x.key === i.key);
      const delta = p ? Math.round((i.score - p.score) * 100) : null;
      return h('div.itemcard', {}, h('div.r1', {}, h('i.sw', { style: { background: sw(i.key) } }), h('span.nm', {}, nm(i.key)), h('span.pc', {}, Math.round(i.score * 100) + '%')),
        h('div.s', {}, i.total != null ? `Found ${i.found} of ${i.total} ${i.name}` : i.sentence),
        h('div.cmp', {}, h('i.new', { style: { width: Math.round(i.score * 100) + '%' } }), p ? h('i.old', { style: { left: Math.round(p.score * 100) + '%' } }) : null),
        h('div.cl', {}, lbl(p ? `v${prev.version} was ${Math.round(p.score * 100)}%` : 'First version'), delta == null ? h('span') : Math.abs(delta) < 2 ? lbl('About the same') : h('span.' + (delta > 0 ? 'up' : 'down'), {}, `${delta > 0 ? '▲' : '▼'} ${Math.abs(delta)} POINTS`)));
    };
    const hl = j.final_metrics?.headline || {};
    mount(
      h('div.headrow', {}, h('div', {}, h('span.stamp', {}, h('i'), `Model v${mv ? mv.version : '?'} · tested · ${fmt.date(j.finished_at)}`),
        h('h1.h1', {}, lead ? `Model v${mv?.version ?? ''} finds ${Math.round(lead.score * 10)} of every 10 ${lead.name}.` : 'Training finished.', h('br'), h('span.dim', {}, lead ? `Tested on ${nice(test.name)} — a sheet it never saw.` : 'But there was nothing checked to test it on.'))),
      h('div.row', { style: { gap: '10px' } }, h('a.btn', { href: `/ka/projects/${ds.id}/` }, 'Add more examples'),
        deployable ? h('button.btn.primary', { onclick: () => KA.deployDialog(mv.id, `${ds.name} model`) }, 'Use this model →') : h('span.pill.warn', {}, 'Not ready to use yet'))),
      h('div.runwrap', {}, view, h('div.runcol', {}, items.slice(0, 3).map(card),
        h('div.adv', {}, h('span', { html: '' }, svgEl('svg', { viewBox: '0 0 24 24' }, svgEl('path', { d: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z' }))),
          h('div', {}, h('b', {}, rc.ready_to_use ? 'What would make it better' : 'What it needs'), j.final_metrics?.kept_starting_model ? h('p', {}, h('b', {}, 'This round did not beat the model it started from, so it kept that model’s skills. ')) : null, h('p', {}, rc.advice || 'There were no checked items on its test sheet to score against. Check one or two more sheets, then train again — we hold one back to test on.'))))),
      h('div.engfoot', {}, lbl('For engineers'), h('span', {}, Object.entries(hl).filter(([, v]) => typeof v === 'number').map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.toFixed(2)}`).join(' · ') || 'no test score', ` · ${j.catalog_id} · ${fmt.dur(j.runtime_s)}`)),
      KA.techDetails(j));
    // the test sheet: what it found vs your labels
    try {
      const [gtObjs, pr] = await Promise.all([api(`datasets/${ds.id}/objects/?sheet=${test.id}`), api(`model-versions/${j.model_version}/predict/`, { method: 'POST', body: { sheet_id: test.id, allow_raster_inferred: true } })]);
      const gt = gtObjs.filter((o) => o.geometry.polygon && !o.is_negative).map((o) => ({ label: o.label, polygon: o.geometry.polygon }));
      const pred = (pr.predictions || []).filter((p) => p.polygon && p.polygon.length > 2);
      const m = matchUp(gt, pred);
      let mode = 'found';
      const draw = () => {
        const svg = mode === 'found' ? plan(test, [...m.pred, ...m.missed.map((x) => ({ ...x, label: 'miss' }))], { op: 0.45, anim: true })
          : plan(test, gt, { op: 0.45 });
        const seg = h('div.segd', {}, [['found', 'What it found'], ['yours', 'Your labels']].map(([k, t]) => h('button' + (mode === k ? '.on' : ''), { onclick: () => { mode = k; draw(); } }, t)));
        view.replaceChildren(svg, h('div.ptop', {}, mode === 'found' ? [h('span.dchip', {}, 'What it drew'), h('span.dchip', {}, h('span.dot', { style: { background: '#ff6b6b' } }), 'Dashed = your labels it missed')] : h('span.dchip', {}, `${gt.length} items you labeled`), seg),
          h('div.pbot', {}, h('span.dchip', {}, `${nice(test.name)} · test sheet · not used in training`)));
      };
      draw();
    } catch (e) { view.replaceChildren(h('div.ptop', {}, h('span.dchip', {}, 'Could not draw the test sheet: ' + e.message))); }
  }
})();
