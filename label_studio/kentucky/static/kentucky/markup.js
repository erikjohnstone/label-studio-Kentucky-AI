/* Label a plan sheet — Kentucky AI page wrapping the embedded labeling engine (Label Studio editor library, Apache-2.0). */
(function () {
  'use strict';
  const { api, h, toast, dialog, guard, chip, nice, cap } = window.KA;
  const SHEET = Number(document.body.dataset.pk);
  const S = { dirty: false, engine: null, data: null, active: null };

  async function loadEngine() {
    if (window.LabelStudio) return;
    const html = await (await fetch('/ka/engine/index.html', { credentials: 'same-origin' })).text();
    const js = html.match(/src="([^"]+\.js)"/)[1];
    const css = html.match(/href="([^"]+\.css)"/)[1];
    document.head.appendChild(h('link', { rel: 'stylesheet', href: css }));
    document.head.appendChild(h('script', { type: 'module', src: js }));
    for (let i = 0; i < 200 && !window.LabelStudio; i++) await new Promise((r) => setTimeout(r, 50));
    if (!window.LabelStudio) throw new Error('The labeling engine did not load');
  }

  function counts() {
    const out = {};
    const ann = S.engine?.annotationStore?.selected;
    (ann?.regionStore?.regions || []).forEach((r) => { const l = r.labeling?.mainValue || r.labelName || (r.labels || [])[0]; if (l) out[l] = (out[l] || 0) + 1; });
    return out;
  }

  function render(d) {
    const classes = d.classes.filter((c) => c.name !== 'unknown');
    const pos = d.position;
    const saveBtn = h('button.btn.primary', { id: 'save', onclick: save }, 'Save');
    const status = h('span.s', { id: 'status' }, d.annotation ? 'Saved' : 'Nothing saved yet');
    const list = h('div', { id: 'conds' });
    const root = document.getElementById('ka-root');
    root.replaceChildren(h('div.canvas-page', {},
      h('div.canvas-top', {},
        h('a.icon-btn', { href: `/ka/projects/${d.dataset.id}/`, title: 'Back to dataset' }, '←'),
        h('div', {}, h('div.t', {}, nice(d.sheet.name)), h('div.s', {}, `${d.dataset.name} · sheet ${pos[0]} of ${pos[1]} · `, status)),
        h('div', { style: { flex: 1 } }),
        d.prev ? h('a.btn.sm.ghost', { href: `/ka/markup/${d.prev}/` }, '‹ Previous') : null,
        d.next ? h('a.btn.sm.ghost', { href: `/ka/markup/${d.next}/` }, 'Next sheet ›') : null,
        h('button.btn.sm', { onclick: suggest }, '✦ Suggest with AI'), saveBtn),
      h('div.canvas-body', {},
        h('div.canvas-stage', {}, h('div', { id: 'engine' }), h('div.hint', { id: 'hint' }, 'Pick an item on the right, then click around it. Double-click to finish.')),
        h('aside.canvas-side', {},
          h('section', {}, h('div.key', {}, 'What are you labeling?'), list),
          h('section', {}, h('div.key', {}, 'How'), h('div.soft', { style: { fontSize: '14px', lineHeight: 1.6 } },
            h('div', {}, h('b', {}, 'Outline: '), 'click each corner, double-click to close.'),
            h('div', {}, h('b', {}, 'Box: '), 'hold ', h('kbd', {}, 'Shift'), ' and drag (quick for doors, fixtures).'),
            h('div', {}, h('b', {}, 'Fix: '), 'click a shape to move corners. ', h('kbd', {}, 'Del'), ' removes it.'),
            h('div', {}, h('b', {}, 'Zoom: '), 'scroll · drag with ', h('kbd', {}, 'Space'), ' held.'))),
          h('section', { id: 'ai' }, h('div.key', {}, 'AI suggestions'),
            h('div.soft', { style: { fontSize: '14px' } }, h('span.legend-dash'), ' dashed = suggested. Keep what is right; delete what is wrong; save.'),
            d.predictions.length ? h('button.btn.sm', { onclick: () => startFromSuggestions(d.predictions[0]) }, `Start from AI suggestions (${(d.predictions[0].result || []).length})`) : h('button.btn.sm', { onclick: suggest }, '✦ Suggest with AI')),
          h('section', {}, h('div.key', {}, 'Tip'), h('div.muted', { style: { fontSize: '13.5px' } }, 'Tight outlines teach the model best. Label every wall, door and window on the sheet — what you skip, it learns to skip.'))))));
    S.list = list;
    S.classes = classes;
    drawList();
  }

  function drawList() {
    const c = counts();
    S.list.replaceChildren(...S.classes.map((cl, i) => h('div.cond' + (S.active === cl.name ? '.on' : ''), { onclick: () => pick(cl.name) },
      h('span.swatch', { style: { background: cl.color } }), h('span', {}, cap(cl.name)), h('kbd', {}, String(i + 1)), h('span.n', {}, String(c[cl.name] || 0)))));
  }

  function pick(name) {
    S.active = name;
    // select the label in both tools (outline + box) so whichever tool is used gets this label
    const ann = S.engine?.annotationStore?.selected;
    ann?.names?.forEach((ctrl) => {
      if (!ctrl.children) return;
      ctrl.children.forEach((lab) => { if (lab.value === name && !lab.selected) lab.setSelected?.(true); else if (lab.value !== name && lab.selected) lab.setSelected?.(false); });
    });
    const tool = ann?.names?.get?.('polygonlabels');
    try { S.engine?.annotationStore?.selected?.toolsManager?.selectTool?.(tool?.tool || null, true); } catch (e) { /* engine keeps its own tool */ }
    document.getElementById('hint').textContent = `${cap(name)}: click each corner, double-click to finish. Shift-drag for a box.`;
    drawList();
  }

  function boot(d, initial, fromPrediction) {
    const el = document.getElementById('engine');
    el.replaceChildren();
    const task = { id: d.task.id, data: d.task.data, annotations: initial ? [{ id: 'k1', result: initial }] : [], predictions: [] };
    S.fromPrediction = fromPrediction || null;
    S.engine = new window.LabelStudio(el, {
      config: d.config, task, user: { id: d.user.id, pk: d.user.id, firstName: d.user.email.split('@')[0], email: d.user.email },
      interfaces: ['side-column', 'edit-history'],
      onLabelStudioLoad(ls) {
        if (!ls.annotationStore.annotations.length) {
          const a = ls.annotationStore.addAnnotation({ userGenerate: true });
          ls.annotationStore.selectAnnotation(a.id);
        }
        setTimeout(() => { if (S.classes[0]) pick(S.active || S.classes[0].name); }, 200);
      },
    });
    const watch = () => { drawList(); S.dirty = true; document.getElementById('status').textContent = 'Unsaved changes'; };
    el.addEventListener('mouseup', () => setTimeout(watch, 60));
    el.addEventListener('keyup', () => setTimeout(watch, 60));
  }

  async function save() {
    const ann = S.engine?.annotationStore?.selected;
    if (!ann) return;
    const result = ann.serializeAnnotation();
    const btn = document.getElementById('save');
    btn.disabled = true; btn.textContent = 'Saving…';
    try {
      const r = await api(`sheets/${SHEET}/markup/`, { method: 'POST', body: { result, from_suggestion: S.fromPrediction } });
      S.dirty = false;
      document.getElementById('status').textContent = `Saved · ${r.objects} items on this sheet`;
      toast(`Saved — ${r.objects} item${r.objects === 1 ? '' : 's'} on this sheet`, 'pos', S.data.next ? { label: 'Next sheet →', run: () => (location.href = `/ka/markup/${S.data.next}/`) } : null);
    } catch (e) { toast(e.message, 'danger'); }
    btn.disabled = false; btn.textContent = 'Save';
  }

  async function suggest() {
    if (S.dirty && !(await dialog('Save first?', h('div.muted', {}, 'AI suggestions will load over this sheet. Save your changes first so nothing is lost.'), [{ label: 'Continue without saving', primary: true }]))) return;
    const t = document.getElementById('hint');
    t.textContent = '✦ Reading the drawing for walls, doors and windows…';
    try {
      const r = await api(`datasets/${S.data.dataset.id}/agent/propose-cv/`, { method: 'POST', body: { sheet_id: SHEET } });
      const d = await api(`sheets/${SHEET}/markup/`);
      S.data = d;
      if (!r.created || !d.predictions.length) { t.textContent = 'No suggestions on this sheet — the drawing may be a scan. Label it by hand.'; return; }
      startFromSuggestions(d.predictions[0]);
      toast(`${r.created} suggestions added. Keep what is right, delete what is wrong, then Save.`, 'pos');
    } catch (e) { toast(e.message, 'danger'); t.textContent = 'Could not get suggestions.'; }
  }

  function startFromSuggestions(pred) {
    const mine = S.engine?.annotationStore?.selected?.serializeAnnotation() || [];
    const ids = new Set(mine.map((r) => r.id));
    const merged = mine.concat((pred.result || []).filter((r) => !ids.has(r.id)));
    boot(S.data, merged, pred.id);
    document.getElementById('hint').textContent = 'Suggestions loaded. Click one to fix it, Del to remove it, then Save.';
  }

  document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save(); }
    if (/^[1-9]$/.test(e.key) && S.classes?.[Number(e.key) - 1] && !e.ctrlKey && !e.metaKey) { pick(S.classes[Number(e.key) - 1].name); }
  });
  window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });

  (async () => {
    try {
      const [d] = await Promise.all([api(`sheets/${SHEET}/markup/`), loadEngine()]);
      S.data = d;
      document.title = `Label ${nice(d.sheet.name)} · Kentucky AI`;
      render(d);
      boot(d, d.annotation ? d.annotation.result : null, null);
    } catch (e) {
      document.getElementById('ka-root').replaceChildren(window.KA.empty('Could not open this sheet', e.message, h('a.btn', { href: '/ka/' }, 'Back to datasets')));
    }
  })();
})();
