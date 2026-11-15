/* Kentucky AI — Model registry, Experiments, Deployments, API keys, API docs, Billing, Team (v5 design).
   All data comes from /api/ka; user data is inserted as text, never as HTML. */
(function () {
  'use strict';
  const KA = window.KA;
  const { api, h, svgEl, toast, dialog, guard, fmt, mount, setTop, nice, PAGES: P } = KA;
  const lbl = (t, cy) => h('span.lbl' + (cy ? '.cy' : ''), {}, t);
  const plural = (n, w, pl) => `${fmt.n(n)} ${n === 1 ? w : pl || w + 's'}`;
  const TASK = { semantic_segmentation: 'Outline areas', instance_segmentation: 'Item by item', node_classification: 'Name every line', edge_classification: 'Connections' };
  const head = (title, dim, actions) => h('div.headrow', {}, h('h1.h1', {}, title, dim ? [h('br'), h('span.dim', {}, dim)] : null), actions ? h('div.row', { style: { gap: '10px' } }, actions) : null);
  const pct = (v) => (v == null ? '—' : Math.round(v * 100) + '%');
  const from = (init, base) => (init === 'checkpoint' ? `Your v${base ?? '?'}` : init === 'pretrained' ? 'Public checkpoint' : init === 'scratch' ? 'From zero' : init || '—');
  const STATUS = { COMPLETED: ['Done', 'ok'], FAILED: ['Failed', 'warn'], CANCELLED: ['Stopped', 'mute'], TIMED_OUT: ['Timed out', 'warn'], CREATED: ['Waiting for OK', 'mute'] };
  const statusPill = (s) => { const [t, c] = STATUS[s] || [KA.STATUS[s]?.[0] || s, 'cy']; return h('span.pill.' + c, {}, c === 'cy' ? h('span.dot') : null, t); };
  const meter = (v) => h('div.mtr', {}, h('i', { style: { width: Math.round((v || 0) * 100) + '%' } }));
  const copyBtn = (text, label = 'Copy') => h('button.btn.sm', { onclick: () => { navigator.clipboard?.writeText(text); toast('Copied', 'pos'); } }, label);

  // ================================================================== Model registry
  P.models = async () => {
    const [ms, deps] = await Promise.all([api('models/'), api('deployments/')]);
    setTop(['Models']);
    const live = (v) => deps.find((d) => d.active_version === v.id && d.status === 'active');
    const all = ms.flatMap((m) => m.versions);
    const nLive = all.filter(live).length;
    const cards = ms.filter((m) => m.versions.length).map((m) => {
      const vs = [...m.versions].sort((a, b) => b.version - a.version);
      const top = vs[0];
      const deployable = vs.some((v) => v.license?.commercially_deployable);
      const row = (v) => {
        const act = async (path, body, msg) => { await guard(() => api(`model-versions/${v.id}/${path}/`, { method: 'POST', body }), msg); P.models(); };
        return h('tr', {}, h('td', {}, h('b', {}, `v${v.version}`), live(v) ? h('span.pill.ok', { style: { marginLeft: '8px' } }, h('span.dot'), 'Live') : v.status === 'archived' ? h('span.pill.mute', { style: { marginLeft: '8px' } }, 'Archived') : null),
          h('td', {}, v.dataset_name || '—', h('div.sub', {}, v.dataset_version ? `data v${v.dataset_version}` : '')),
          h('td', {}, from(v.init, v.base_version)),
          h('td', { style: { width: '200px' } }, v.report ? h('div.row', { style: { gap: '10px', flexWrap: 'nowrap' } }, meter(v.report.score), h('span.mono.small', {}, pct(v.report.score))) : h('span.faint', {}, 'No test score')),
          h('td.faint', { style: { whiteSpace: 'nowrap' } }, fmt.date(v.created_at)),
          h('td.acts', {}, v.training_job ? h('a.btn.sm', { href: `/ka/runs/${v.training_job}/` }, 'Results') : null,
            v.downloadable ? h('button.btn.sm', { onclick: async () => { const r = await guard(() => api(`model-versions/${v.id}/download/`)); location.href = r.url; } }, 'Download') : null,
            !live(v) && v.status === 'ready' && v.license?.commercially_deployable ? h('button.btn.sm.primary', { onclick: () => KA.deployDialog(v.id, `${v.dataset_name || 'Plan'} model`) }, 'Deploy') : null,
            !live(v) ? h('button.btn.sm.ghost', { onclick: () => act('archive', { archive: v.status !== 'archived' }, v.status === 'archived' ? 'Restored' : 'Archived') }, v.status === 'archived' ? 'Restore' : 'Archive') : null));
      };
      return h('section.regcard', {}, h('div.reghead', {},
        h('div', {}, h('div.h2', {}, `${top.dataset_name || 'Model'} · ${TASK[m.task] || m.task}`), h('div.sub', {}, `${top.architecture} · ${plural(vs.length, 'version')}`)),
        h('div.row', { style: { gap: '6px' } }, h('span.pill.' + (deployable ? 'ok' : 'warn'), {}, deployable ? 'OK to deploy commercially' : 'Not deployable — license review'), h('span.pill.mute', {}, m.catalog_id))),
      h('table.rtable', {}, h('thead', {}, h('tr', {}, ['Version', 'Trained on', 'Started from', 'Items found on test', 'Trained', ''].map((x) => h('th', {}, x)))), h('tbody', {}, vs.map(row))));
    });
    mount(head('Models.', `${plural(all.length, 'version')} · ${nLive} live.`, [h('a.btn', { href: '/ka/experiments/' }, 'Experiments'), h('a.btn.primary', { href: '/ka/train/' }, 'Train a model →')]),
      cards.length ? cards : h('div.emptyc', {}, h('b', {}, 'No models yet'), 'Check a few sheets, then train your first model.', h('a.btn.primary', { href: '/ka/' }, 'Go to plan sets')));
  };

  // ================================================================== Experiments
  P.experiments = async () => {
    const jobs = await api('jobs/');
    setTop([['Models', '/ka/models/'], 'Experiments']);
    const sel = new Set();
    const cmpBtn = h('button.btn.primary', { disabled: true, onclick: () => compare([...sel]) }, 'Compare');
    const out = h('div');
    const key = (j) => { const hl = j.headline || {}; const k = ['mean_iou', 'macro_f1', 'mask_map50', 'box_map50', 'map50', 'map', 'mask_map'].find((x) => typeof hl[x] === 'number'); return k ? [k, hl[k]] : null; };
    const rows = jobs.map((j) => {
      const cb = h('input', { type: 'checkbox', onchange: (e) => { e.target.checked ? sel.add(j.id) : sel.delete(j.id); cmpBtn.disabled = sel.size < 2; cmpBtn.textContent = sel.size >= 2 ? `Compare ${sel.size}` : 'Compare'; } });
      const k = key(j);
      return h('tr', {}, h('td', {}, cb), h('td', {}, h('a', { href: `/ka/runs/${j.id}/` }, h('b', {}, `Run ${j.id}`)), h('div.sub', {}, TASK[j.task] || j.task)),
        h('td', {}, j.dataset_name, h('div.sub', {}, `data v${j.dataset_version}`)), h('td', {}, j.architecture),
        h('td', {}, from(j.init, j.base_version)), h('td', {}, statusPill(j.status)),
        h('td.mono.small', {}, k ? `${k[0].replace(/_/g, ' ')} ${k[1].toFixed(3)}` : '—'),
        h('td.faint', {}, fmt.dur(j.runtime_s)), h('td.mono.small', {}, j.gpu_type), h('td', {}, j.deployed ? h('span.pill.ok', {}, h('span.dot'), 'Live') : j.model_version ? h('span.pill.mute', {}, 'Registered') : ''));
    });
    async function compare(ids) {
      const [cmp, ...full] = await Promise.all([api(`jobs/compare/?ids=${ids.join(',')}`), ...ids.map((i) => api(`jobs/${i}/`))]);
      const COLORS = ['#0e8f99', '#d98a00', '#5468d4', '#2f9a5b', '#c2341d'];
      const chart = (metric, title) => {
        const series = full.map((j) => (j.metrics_history || []).filter((m) => m.epoch && m[metric] != null).map((m) => [m.epoch, m[metric]]));
        const all = series.flat(); if (!all.length) return null;
        const mx = Math.max(...all.map((p) => p[0])), lo = Math.min(...all.map((p) => p[1])), hi = Math.max(...all.map((p) => p[1]));
        const X = (e) => 40 + ((e - 1) / Math.max(mx - 1, 1)) * 540, Y = (v) => 170 - ((v - lo) / Math.max(hi - lo, 1e-9)) * 150;
        return h('div.cmpchart', {}, lbl(title), svgEl('svg', { viewBox: '0 0 600 190' },
          [0, 0.5, 1].map((t) => svgEl('line', { x1: 40, x2: 580, y1: 170 - t * 150, y2: 170 - t * 150, stroke: 'var(--line)' })),
          [0, 1].map((t) => svgEl('text', { x: 4, y: 174 - t * 150, 'font-size': 10, fill: 'var(--ink-4)', 'font-family': 'Space Mono' }, (lo + t * (hi - lo)).toFixed(2))),
          series.map((s, i) => svgEl('path', { d: s.map((p, k) => `${k ? 'L' : 'M'}${X(p[0])} ${Y(p[1])}`).join(' '), fill: 'none', stroke: COLORS[i % 5], 'stroke-width': 2 }))));
      };
      const metric = ['val_mean_iou', 'val_macro_f1', 'val_map50', 'val_map'].find((m) => full.some((j) => (j.metrics_history || []).some((x) => x[m] != null)));
      out.replaceChildren(h('section.regcard', {}, h('div.reghead', {}, h('div.h2', {}, 'Side by side'), h('div.row', { style: { gap: '12px' } }, full.map((j, i) => h('span.row', { style: { gap: '6px' } }, h('i', { style: { width: '10px', height: '10px', borderRadius: '3px', background: COLORS[i % 5], display: 'inline-block' } }), `Run ${j.id}`)))),
        h('div.cmpgrid', {}, metric ? chart(metric, `${metric.replace('val_', '').replace(/_/g, ' ')} on the check sheet, per round`) : null, chart('val_loss', 'Check-sheet loss, per round') || chart('train_loss', 'Training loss, per round')),
        h('table.rtable', {}, h('thead', {}, h('tr', {}, h('th', {}, 'Setting'), full.map((j) => h('th', {}, `Run ${j.id}`)))),
          h('tbody', {}, [['Plan set · data', (j) => `${j.dataset_name} · v${j.dataset_version}`], ['Architecture', (j) => j.architecture], ['Started from', (j) => from(j.init, j.base_version)],
            ['Seed', (j) => j.seed], ['Code version', (j) => (j.code_version || '').slice(0, 12)], ['Hardware', (j) => j.gpu_type], ['Runtime', (j) => fmt.dur(j.runtime_s)],
            ...Object.keys(cmp.config_differences || {}).map((k) => [k, (j) => JSON.stringify(j.config?.[k])]),
            ...Object.keys(full[0].headline || {}).map((k) => [`Result: ${k.replace(/_/g, ' ')}`, (j) => (typeof j.headline?.[k] === 'number' ? j.headline[k].toFixed(3) : '—')])]
            .map(([k, f]) => h('tr', {}, h('td', {}, k), full.map((j) => h('td.mono.small', {}, String(f(j) ?? '—')))))))));
      out.scrollIntoView({ behavior: 'smooth' });
    }
    mount(head('Experiments.', 'Every training run, and exactly how it was made.', [cmpBtn]),
      jobs.length ? h('section.regcard', {}, h('table.rtable', {}, h('thead', {}, h('tr', {}, ['', 'Run', 'Plan set', 'Architecture', 'Started from', 'Status', 'Result', 'Time', 'Hardware', ''].map((x) => h('th', {}, x)))), h('tbody', {}, rows)))
        : h('div.emptyc', {}, h('b', {}, 'No training runs yet'), h('a.btn.primary', { href: '/ka/train/' }, 'Train a model')), out);
  };

  // ================================================================== Deployments
  P.deployments = async () => {
    const [deps, ms] = await Promise.all([api('deployments/'), api('models/')]);
    setTop(['Deployments']);
    const active = deps.filter((d) => d.status !== 'deleted');
    const nc = document.getElementById('nc-deployments'); if (nc) nc.textContent = active.filter((d) => d.status === 'active').length || '';
    const curl = (d) => `curl -X POST ${location.origin}${d.endpoint} \\\n  -H "Authorization: Bearer $KA_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"image": "<base64 PNG of a plan sheet>"}'`;
    const card = (d) => {
      const versions = (ms.find((m) => m.id === d.model_id)?.versions || []).filter((v) => v.license?.commercially_deployable && v.status === 'ready');
      const act = async (a, body) => { await guard(() => api(`deployments/${d.id}/${a}/`, { method: 'POST', body: body || {} }), 'Updated'); P.deployments(); };
      const input = h('input', { type: 'file', accept: '.png,.jpg,.jpeg', style: { display: 'none' } });
      const view = h('div.dpanel.ticks.trybox', { onclick: () => input.click() }, h('div.trycta', {}, h('b', {}, 'Try it'), h('span', {}, 'Drop a plan image (PNG or JPG) — runs on v' + d.active_version_number)), input);
      const run = async (f) => {
        view.replaceChildren(h('div.trycta', {}, h('b', {}, 'Reading…')), input);
        const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1]); r.readAsDataURL(f); });
        try {
          const r = await api(`model-versions/${d.active_version}/predict/`, { method: 'POST', body: { image: b64 } });
          const [W, H] = r.image_size;
          const c = {}; (r.predictions || []).forEach((p) => (c[p.label] = (c[p.label] || 0) + 1));
          const svg = svgEl('svg', { class: 'plan', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'xMidYMid meet' }, svgEl('image', { class: 'planimg', href: URL.createObjectURL(f), x: 0, y: 0, width: W, height: H, opacity: 0.55 }),
            (r.predictions || []).filter((p) => p.polygon).map((p) => svgEl('polygon', { class: `k k-${p.label} drawin`, points: p.polygon.map((q) => q.join(',')).join(' ') })));
          view.replaceChildren(svg, h('div.ptop', {}, Object.entries(c).map(([k, n]) => h('span.dchip', {}, `${n} ${k}${n > 1 ? 's' : ''}`))), input);
        } catch (e) { view.replaceChildren(h('div.trycta', {}, h('b', {}, 'Could not read that image'), h('span', {}, e.message)), input); }
      };
      input.onchange = () => input.files[0] && run(input.files[0]);
      view.ondragover = (e) => { e.preventDefault(); view.classList.add('over'); }; view.ondragleave = () => view.classList.remove('over');
      view.ondrop = (e) => { e.preventDefault(); view.classList.remove('over'); e.dataTransfer.files[0] && run(e.dataTransfer.files[0]); };
      return h('section.depcard', {}, h('div.depinfo', {},
        h('div.row', { style: { gap: '8px' } }, d.status === 'active' ? h('span.pill.ok', {}, h('span.dot'), 'Live') : h('span.pill.warn', {}, 'Paused'), lbl(`${TASK[d.task] || d.task} · v${d.active_version_number}`)),
        h('div.h2', { style: { marginTop: '10px' } }, d.name),
        h('div.endpoint', {}, h('code', {}, `POST ${location.origin}${d.endpoint}`), copyBtn(`${location.origin}${d.endpoint}`)),
        h('div.dstats', {}, [['Requests', fmt.n(d.request_count)], ['Errors', fmt.n(d.error_count)], ['Last request', fmt.ago(d.last_request_at)], ['Limit', `${d.rate_limit_per_minute}/min`]].map(([k, v]) => h('div', {}, h('b', {}, v), lbl(k)))),
        h('div.row', { style: { gap: '8px', marginTop: '16px', flexWrap: 'wrap' } }, h('button.btn.sm.primary', { onclick: () => { navigator.clipboard?.writeText(curl(d)); toast('Example request copied', 'pos'); } }, 'Copy example request'),
          versions.length > 1 ? h('select.sm', { onchange: (e) => act('set-version', { model_version_id: Number(e.target.value) }) }, versions.map((v) => h('option', { value: v.id, selected: v.id === d.active_version }, `Serve v${v.version}`))) : null,
          d.history.length > 1 ? h('button.btn.sm', { onclick: () => act('rollback') }, 'Roll back') : null,
          h('button.btn.sm', { onclick: () => act(d.status === 'active' ? 'pause' : 'resume') }, d.status === 'active' ? 'Pause' : 'Resume'),
          h('button.btn.sm.ghost', { onclick: async () => { if (await dialog('Delete this deployment?', h('p.muted', {}, 'The endpoint stops answering right away. The model is kept.'), [{ label: 'Delete', danger: true }])) act('delete'); } }, 'Delete')),
        h('div.hist2', {}, lbl('History'), [...d.history].reverse().slice(0, 4).map((x) => h('div', {}, h('span.mono.small', {}, `v${x.version}`), ` ${x.action} · ${fmt.ago(x.at)}`)))), view);
    };
    mount(head('Deployments.', active.length ? `${plural(active.filter((d) => d.status === 'active').length, 'private API')} live.` : 'Turn a model into a private API your software can call.', [h('a.btn', { href: '/ka/api-keys/' }, 'API keys'), h('a.btn', { href: '/ka/api/' }, 'API docs')]),
      active.length ? active.map(card) : h('div.emptyc', {}, h('b', {}, 'Nothing deployed yet'), 'Open a model and choose Deploy. You get an endpoint and a usage meter.', h('a.btn.primary', { href: '/ka/models/' }, 'See models')));
  };

  // ================================================================== API keys
  P.apikeys = async () => {
    const keys = await api('api-keys/');
    const show = (r) => dialog('Copy your API key', h('div.grid', { style: { gap: '12px' } }, h('div.notice', {}, 'You will only see this once. We keep a fingerprint, never the key.'),
      h('pre.code', { style: { userSelect: 'all', whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '14px' } }, r.key), copyBtn(r.key, 'Copy key')), [{ label: 'Done', primary: true }]).then(() => P.apikeys());
    const create = async () => { const n = h('input', { type: 'text', placeholder: 'e.g. Estimating software' }); if (!(await dialog('New API key', h('label.field', {}, h('span', {}, 'What will use it?'), n), [{ label: 'Create key', primary: true }]))) return; show(await guard(() => api('api-keys/', { method: 'POST', body: { name: n.value || 'API key' } }))); };
    setTop(['API keys']);
    const active = keys.filter((k) => !k.revoked_at), off = keys.filter((k) => k.revoked_at);
    const row = (k) => h('tr', {}, h('td', {}, h('b', {}, k.name)), h('td.mono.small', {}, `${k.prefix}••••••••`), h('td.faint', {}, fmt.date(k.created_at)), h('td.faint', {}, fmt.ago(k.last_used_at)),
      h('td.acts', {}, h('button.btn.sm', { onclick: async () => show(await guard(() => api(`api-keys/${k.id}/rotate/`, { method: 'POST', body: {} }))) }, 'Replace'),
        h('button.btn.sm.ghost', { onclick: async () => { if (await dialog(`Turn off “${k.name}”?`, h('p.muted', {}, 'Anything using this key stops working immediately.'), [{ label: 'Turn off', danger: true }])) { await guard(() => api(`api-keys/${k.id}/revoke/`, { method: 'POST', body: {} })); P.apikeys(); } } }, 'Turn off')));
    mount(head('API keys.', 'Your software uses a key to call your deployments.', [h('button.btn.primary', { onclick: create }, '＋ New API key')]),
      active.length ? h('section.regcard', {}, h('table.rtable', {}, h('thead', {}, h('tr', {}, ['Name', 'Key', 'Created', 'Last used', ''].map((x) => h('th', {}, x)))), h('tbody', {}, active.map(row))))
        : h('div.emptyc', {}, h('b', {}, 'No API keys yet'), 'Create one when you are ready to connect your software.', h('button.btn.primary', { onclick: create }, 'New API key')),
      h('div.tips3', {}, [['Keep it secret', 'Store keys in your server’s settings, never in a web page or app people download.'], ['One per tool', 'Make a key for each piece of software, so you can turn one off without breaking the others.'], ['Replace any time', 'Replace makes a new key and turns the old one off at once.']].map(([t, b]) => h('div', {}, h('b', {}, t), h('p', {}, b)))),
      off.length ? h('details.tech', {}, h('summary', {}, `Turned off · ${off.length}`), h('div', {}, off.map((k) => h('div.muted.mono', { style: { fontSize: '12.5px', padding: '4px 0' } }, `${k.name} · ${k.prefix}… · off since ${fmt.date(k.revoked_at)}`)))) : null);
  };

  // ================================================================== API docs
  P.api = async () => {
    setTop(['API docs']);
    const deps = await api('deployments/').catch(() => []);
    const slug = deps.find((d) => d.status === 'active')?.slug || '<deployment>';
    const url = `${location.origin}/api/ka/v1/deployments/${slug}/predict`;
    const ex = {
      curl: `curl -X POST ${url} \\\n  -H "Authorization: Bearer $KA_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -H "Idempotency-Key: sheet-A101-v1" \\\n  -d "{\\"image\\": \\"$(base64 -w0 A-101.png)\\"}"`,
      Python: `import base64, requests\n\nplan = base64.b64encode(open("A-101.png", "rb").read()).decode()\nr = requests.post(\n    "${url}",\n    headers={"Authorization": "Bearer <API key>"},\n    json={"image": plan},\n)\nfor item in r.json()["predictions"]:\n    print(item["label"], item["confidence"], item["bbox"])`,
      JavaScript: `const image = (await fs.promises.readFile("A-101.png")).toString("base64");\nconst r = await fetch("${url}", {\n  method: "POST",\n  headers: { Authorization: "Bearer " + process.env.KA_API_KEY, "Content-Type": "application/json" },\n  body: JSON.stringify({ image }),\n});\nconst { predictions } = await r.json();`,
    };
    let lang = 'curl';
    const code = h('pre.code');
    const tabs = h('div.segl');
    const draw = () => { code.textContent = ex[lang]; tabs.replaceChildren(...Object.keys(ex).map((k) => h('button' + (k === lang ? '.on' : ''), { onclick: () => { lang = k; draw(); } }, k))); };
    draw();
    const step = (n, t, b, el) => h('div.dstep', {}, h('span.n', {}, String(n)), h('div', {}, h('b', {}, t), h('p', {}, b), el || null));
    mount(head('API docs.', 'One endpoint per deployment. Send a sheet; get every item back.'),
      h('div.docgrid', {}, h('div', {},
        step(1, 'Create an API key', 'Keys are per organization and can be replaced or turned off at any time.', h('a.btn.sm', { href: '/ka/api-keys/' }, 'API keys →')),
        step(2, 'Deploy a model', 'Each deployment gets its own endpoint, usage meter and rate limit.', h('a.btn.sm', { href: '/ka/deployments/' }, 'Deployments →')),
        step(3, 'Send a plan sheet', 'A PNG or JPEG as base64, or the id of a sheet already uploaded. Retries with the same Idempotency-Key are billed once.'),
        h('dl.kv', { style: { marginTop: '18px' } }, [['Errors', '400 bad input · 401 bad API key · 404 unknown deployment · 409 paused · 429 too many requests'], ['Coordinates', 'bbox and polygon in image pixels; polygon_source in original PDF points when you send sheet_id'], ['Full reference', 'OpenAPI schema at /docs/api/schema/swagger-ui/']].map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))),
      h('div', {}, h('div.row', { style: { justifyContent: 'space-between', marginBottom: '10px' } }, tabs, copyBtn(ex[lang])), code,
        lbl('Response', false), h('pre.code', { style: { marginTop: '8px' } }, '{\n  "predictions": [\n    { "label": "door", "confidence": 0.94,\n      "bbox": [812, 440, 61, 58],\n      "polygon": [[812,440], [873,440], ...],\n      "polygon_source": [[401.2, 220.5], ...] }\n  ],\n  "model": { "name": "...", "version": 5 }\n}'))));
  };

  // ================================================================== Billing
  P.billing = async () => {
    const b = await api('billing/');
    const a = b.account, u = b.usage;
    setTop(['Billing']);
    const cap = Number(a.monthly_spend_cap_usd), used = Number(u.month_to_date) + Number(u.reserved_for_active_jobs);
    const NAMES = { training_compute: 'Training time', training_platform_fee: 'Training runs', inference: 'API requests', hosting: 'Hosting', storage: 'Storage' };
    const capIn = h('input', { type: 'number', step: '10', value: cap.toFixed(0), style: { width: '120px' } });
    const tiers = b.pricing.compute_tiers;
    mount(head('Billing.', 'Pay as you go. Nothing runs on paid hardware without your OK.'),
      h('div.stat4', {}, [['This month', fmt.usd(u.month_to_date), 'so far'], ['Reserved', fmt.usd(u.reserved_for_active_jobs), 'for training running now'],
        ['Monthly limit', fmt.usd(cap), `${Math.round((used / Math.max(cap, 0.01)) * 100)}% used`], ['Payment', a.payment_method_status === 'none' ? 'Not set' : 'Card on file', a.stripe_mode === 'not_configured' ? 'Payments not connected yet' : `Stripe ${a.stripe_mode}`]]
        .map(([k, v, s]) => h('div', {}, lbl(k), h('b', {}, v), h('small', {}, s)))),
      h('div.bgrid', {},
        h('section.regcard.pad', {}, h('div.h2', {}, 'Monthly limit'), h('p.muted.small', {}, 'New training is refused before it could go over this. Running jobs stop at their approved maximum.'),
          meter(Math.min(1, used / Math.max(cap, 0.01))), h('div.row', { style: { marginTop: '14px', gap: '8px' } }, h('span.muted', {}, '$'), capIn, h('button.btn', { onclick: async () => { await guard(() => api('billing/', { method: 'PATCH', body: { monthly_spend_cap_usd: capIn.value } }), 'Limit saved'); P.billing(); } }, 'Save'))),
        h('section.regcard.pad', {}, h('div.h2', {}, 'Last 30 days'), Object.keys(u.by_kind).length ? Object.entries(u.by_kind).map(([k, v]) => h('div.brow', {}, h('span', {}, NAMES[k] || k), meter(Number(v.charge) / Math.max(Number(u.total_charge), 0.01)), h('span.mono.small', {}, fmt.usd(v.charge)))) : h('p.muted', {}, 'Nothing billed yet.')),
        h('section.regcard.pad', {}, h('div.h2', {}, 'Prices'), h('table.rtable.compact', {}, h('tbody', {},
          Object.entries(tiers).map(([k, t]) => h('tr', {}, h('td', {}, k === 'cpu-local' ? 'Standard training' : k), h('td.mono.small', {}, Number(t.customer_per_hour) ? `${fmt.usd(t.customer_per_hour)}/hr` : 'Included'))),
          h('tr', {}, h('td', {}, 'API requests (outlines)'), h('td.mono.small', {}, `${fmt.usd(b.pricing.inference_per_1k.semantic_segmentation)}/1k`)),
          h('tr', {}, h('td', {}, 'API requests (item by item)'), h('td.mono.small', {}, `${fmt.usd(b.pricing.inference_per_1k.instance_segmentation)}/1k`)))),
        b.pricing.placeholder ? h('p.small.warn', { style: { marginTop: '10px' } }, 'Placeholder prices while payments are set up. Nothing is charged until payments are connected.') : null)),
      b.history.length ? h('section.regcard', {}, h('table.rtable', {}, h('thead', {}, h('tr', {}, ['Date', 'What', 'Quantity', 'Amount'].map((x) => h('th', {}, x)))),
        h('tbody', {}, b.history.slice(0, 40).map((e) => h('tr', {}, h('td.faint', {}, fmt.date(e.created_at)), h('td', {}, e.description || NAMES[e.kind] || e.kind), h('td.mono.small', {}, `${Number(e.quantity).toFixed(2)} ${e.unit}`), h('td.mono.small', {}, fmt.usd(e.customer_charge_usd))))))) : null);
  };

  // ================================================================== Team & data
  P.team = async () => {
    const [o, ds, logs] = await Promise.all([api('org/'), api('datasets/'), api('audit/')]);
    setTop(['Team']);
    const sw = (on, onchange) => h('label.switch', {}, h('input', { type: 'checkbox', checked: on, onchange }), h('i'));
    mount(head(`${o.title}.`, `${plural(o.members.length, 'person', 'people')} · your plans stay private.`),
      h('div.bgrid2', {},
        h('section.regcard.pad', {}, h('div.h2', {}, 'People'), h('div.people', {}, o.members.map((m) => h('div.person', {}, h('span.avatar', {}, m.email.slice(0, 1).toUpperCase()), h('div', {}, h('b', {}, m.email), h('small', {}, m.is_owner ? 'Owner' : 'Member')))))),
        h('section.regcard.pad', {}, h('div.h2', {}, 'Your data'), h('p.muted.small', {}, 'Plans, labels and models belong to your company. Kentucky AI never learns from them unless you switch it on for a plan set.'),
          ds.map((d) => h('div.datarow', {}, h('div', {}, h('b', {}, d.name), h('small', {}, `${plural(d.sheets, 'sheet')} · ${plural(d.objects, 'label')}`)),
            h('div.row', { style: { gap: '10px' } }, h('span.small.faint', {}, 'Help improve Kentucky AI'), sw(d.allow_ka_model_training, async (e) => { await guard(() => api(`datasets/${d.id}/`, { method: 'PATCH', body: { allow_ka_model_training: e.target.checked } }), 'Saved'); }),
              h('button.btn.sm.ghost', { onclick: async () => { if (await dialog(`Delete “${d.name}”?`, h('p.muted', {}, 'Deletes its plans, labels and exports for good. Trained models are kept until you archive them.'), [{ label: 'Delete for good', danger: true }])) { await guard(() => api(`datasets/${d.id}/`, { method: 'DELETE' }), 'Deleted'); P.team(); } } }, 'Delete')))))),
      h('section.regcard', {}, h('div.reghead', {}, h('div.h2', {}, 'Activity'), lbl('Every change is recorded')), h('table.rtable', {}, h('tbody', {}, logs.slice(0, 25).map((a) => h('tr', {}, h('td.faint', { style: { whiteSpace: 'nowrap' } }, fmt.ago(a.created_at)), h('td.mono.small', {}, a.action), h('td', {}, a.actor || a.api_key || '—')))))));
  };
})();
