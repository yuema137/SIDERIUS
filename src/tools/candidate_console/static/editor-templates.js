/* "Start from a template": gallery, graph preview and one-click import into the draft.
 * Templates come only from GET /api/editor/templates (tools/workflow_authoring/templates.py,
 * the one template owner). Import asks the server for unsaved source that keeps the open
 * project's own task references, then hands it to the ordinary source Review through
 * window.workflowEditor.importSource. Nothing is written until the author saves. */
(() => {
  'use strict';
  const svgNs = 'http://www.w3.org/2000/svg';
  const $ = id => document.getElementById(id);
  let catalog = null, loading = null, chosen = null, busy = false;
  const BLANK = 'blank';
  const element = (tag, text, parent, className) => {
    const value = document.createElement(tag); value.textContent = text;
    if (className) value.className = className;
    if (parent) parent.append(value); return value;
  };
  const svgElement = (tag, attributes, parent) => {
    const value = document.createElementNS(svgNs, tag);
    for (const [name, item] of Object.entries(attributes)) value.setAttribute(name, item);
    parent.append(value); return value;
  };
  const label = capability => window.editorCapabilityPresentation?.label(capability) || capability;
  // Preview geometry (viewBox units). The preview is presentation only: the server positions
  // (one row on the canvas grid) give the step order; the editor canvas keeps them untouched.
  const VIEW_W = 1100, PAD = 40, NODE_H = 84, ROW_GAP = 180, MAX_GAP = 320, NODE_FONT = 22, MIN_FONT_PX = 13.5;
  const MAX_ASPECT = 2.6;

  /** Folded layout: up to three steps in one row; longer chains fold into two rows in snake
   * order (the second row runs right to left, its last step under the first), so a loop
   * from the last step back to the first closes the ring along the left column. */
  function foldedLayout(preview) {
    const order = [...preview.nodes].sort((a, b) => a.x - b.x || a.y - b.y).map(n => n.id);
    const cols = order.length <= 3 ? order.length : Math.ceil(order.length / 2);
    const nodeW = cols >= 3 ? 260 : 300;
    const gap = cols > 1 ? Math.min((VIEW_W - 2 * PAD - cols * nodeW) / (cols - 1), MAX_GAP) : 0;
    const left = (VIEW_W - cols * nodeW - (cols - 1) * gap) / 2;
    const rows = order.length > cols ? 2 : 1;
    const content = 2 * PAD + rows * NODE_H + (rows - 1) * ROW_GAP;
    const height = Math.max(content, VIEW_W / MAX_ASPECT), top = (height - content) / 2 + PAD;
    const cell = (col, row) => ({x: left + col * (nodeW + gap), y: top + row * (NODE_H + ROW_GAP), w: nodeW, h: NODE_H});
    const at = {};
    order.slice(0, cols).forEach((id, col) => { at[id] = cell(col, 0); });
    const rest = order.slice(cols);
    rest.forEach((id, index) => {
      // First under the last column, last under the first column, the others spread between.
      const col = rest.length === 1 ? cols - 1 : Math.round((cols - 1) * (1 - index / (rest.length - 1)));
      at[id] = cell(col, 1);
    });
    return {width: VIEW_W, height, at};
  }

  const center = r => ({x: r.x + r.w / 2, y: r.y + r.h / 2});
  /** Point where the ray from the centre of `r` towards `toward` leaves the rectangle. */
  function border(r, toward) {
    const c = center(r), dx = toward.x - c.x, dy = toward.y - c.y;
    const t = Math.min(dx ? (r.w / 2) / Math.abs(dx) : Infinity, dy ? (r.h / 2) / Math.abs(dy) : Infinity);
    return {x: c.x + t * dx, y: c.y + t * dy};
  }
  /** Whether the segment p-q passes through rectangle r (sampled; cards are large). */
  function crosses(p, q, r) {
    for (let i = 1; i < 40; i++) {
      const x = p.x + (q.x - p.x) * i / 40, y = p.y + (q.y - p.y) * i / 40;
      if (x > r.x + 2 && x < r.x + r.w - 2 && y > r.y + 2 && y < r.y + r.h - 2) return true;
    }
    return false;
  }

  /** Graph preview of a template (server preview: nodes, edges, loop), folded to a balanced
   * aspect. Every mark lies inside the viewBox; the loop label interrupts the dashed loop line. */
  function thumbnail(preview, large) {
    const {width, height, at} = foldedLayout(preview);
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('class', `template-thumbnail${large ? ' large' : ''}`);
    // Never shrink labels below MIN_FONT_PX; a frame narrower than that scrolls instead.
    if (large) svg.style.minWidth = `${Math.ceil(width * MIN_FONT_PX / NODE_FONT)}px`;
    svg.setAttribute('role', 'img');
    const steps = preview.nodes.map(n => label(n.capability)).join(' → ');
    svg.setAttribute('aria-label', preview.loop ? `${steps}, repeated up to ${preview.loop.final_iteration} time(s) from ${preview.loop.source} back to ${preview.loop.target}` : steps);
    const defs = svgElement('defs', {}, svg), marker = svgElement('marker', {id: `arrow-${large ? 'l' : 's'}`, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse'}, defs);
    svgElement('path', {d: 'M0 0 10 5 0 10z', class: 'template-arrow'}, marker);
    const arrow = `url(#arrow-${large ? 'l' : 's'})`;
    const rects = Object.values(at);
    // One line per connected pair; several arguments between the same nodes draw once.
    for (const pair of new Set(preview.edges.map(edge => `${edge.source}>${edge.target}`))) {
      const [source, target] = pair.split('>'), a = at[source], b = at[target];
      const p = border(a, center(b)), q = border(b, center(a));
      let d = `M${p.x} ${p.y} L${q.x} ${q.y}`;
      if (rects.some(r => r !== a && r !== b && crosses(p, q, r))) {
        // A same-row skip would pass through the cards between: arc outside the rows instead.
        const up = a.y === rects[0].y, y = up ? a.y : a.y + a.h, lift = up ? -40 : 40; // rises 30 < PAD
        d = `M${a.x + a.w / 2} ${y} C${a.x + a.w / 2} ${y + lift}, ${b.x + b.w / 2} ${y + lift}, ${b.x + b.w / 2} ${y}`;
      }
      svgElement('path', {d, class: 'template-edge', 'data-source': source, 'data-target': target, 'marker-end': arrow}, svg);
    }
    if (preview.loop) {
      const s = at[preview.loop.source], t = at[preview.loop.target];
      const p = border(s, center(t)), q = border(t, center(s)), mid = {x: (p.x + q.x) / 2, y: (p.y + q.y) / 2};
      const vertical = Math.abs(q.y - p.y) >= Math.abs(q.x - p.x);
      // Vertical loop line: the label sits in a gap of the line. Otherwise it sits just below it.
      let d = `M${p.x} ${p.y} L${q.x} ${q.y}`, labelY = mid.y + 30;
      if (vertical) {
        const dir = Math.sign(q.y - p.y), half = 24;
        d = `M${p.x} ${p.y} L${mid.x} ${mid.y - dir * half} M${mid.x} ${mid.y + dir * half} L${q.x} ${q.y}`;
        labelY = mid.y + 7;
      }
      svgElement('path', {d, class: 'template-loop', 'marker-end': arrow}, svg);
      const text = svgElement('text', {x: String(mid.x), y: String(labelY), 'text-anchor': 'middle', class: 'template-loop-label'}, svg);
      text.textContent = `feedback · up to ${preview.loop.final_iteration} iteration${preview.loop.final_iteration === 1 ? '' : 's'}`;
    }
    for (const n of preview.nodes) {
      const r = at[n.id], group = svgElement('g', {class: `template-node capability-${n.capability}`}, svg);
      svgElement('rect', {x: String(r.x), y: String(r.y), width: String(r.w), height: String(r.h), rx: '12'}, group);
      const text = svgElement('text', {x: String(r.x + r.w / 2), y: String(r.y + r.h / 2 + 8), 'text-anchor': 'middle'}, group);
      text.textContent = label(n.capability);
    }
    return svg;
  }

  // Lucide-style 20px glyphs (repeat / arrow-right), currentColor.
  const ICONS = {loop: ['m17 2 4 4-4 4', 'M3 11v-1a4 4 0 0 1 4-4h14', 'm7 22-4-4 4-4', 'M21 13v1a4 4 0 0 1-4 4H3'], step: ['M5 12h14', 'm12 5 7 7-7 7']};
  function icon(name) {
    const svg = document.createElementNS(svgNs, 'svg');
    for (const [key, value] of Object.entries({viewBox: '0 0 24 24', width: '20', height: '20', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: 'template-icon'})) svg.setAttribute(key, value);
    for (const d of ICONS[name]) svgElement('path', {d}, svg);
    return svg;
  }
  function editorBlock() {
    const state = window.workflowEditor?.state;
    if (!window.consoleSession.connected) return 'Connect first.';
    if (!state?.projectId || !state.sourceAvailable) return 'Open a workflow project first: a template keeps that project\'s task and data references.';
    if (state.saving) return 'Saving the workflow.';
    if (state.conflict) return 'Resolve the source conflict first.';
    // Typed Python is not a draft state: an import would drop it beyond Undo (like restoring a version).
    if (state.sourceDirty) return 'Save or revert your typed Python text first, then use a template.';
    return '';
  }
  function status(message) { const value = $('editor-template-status'); if (value) value.textContent = message; }

  function renderDetail() {
    const detail = $('editor-template-detail'); detail.replaceChildren();
    if (chosen === BLANK) {
      element('h3', 'Blank workflow', detail);
      element('p', 'Starts an empty canvas in your unsaved draft (Undo brings the current modules back). Then pick modules from the list on the left.', detail, 'muted');
      const start = element('button', 'Start blank', detail); start.type = 'button'; start.id = 'editor-template-blank';
      start.addEventListener('click', () => {
        $('editor-template-gallery').close(); window.workflowEditor.clearAll();
        document.querySelector('#editor-palette .palette-search')?.focus();
      });
      return;
    }
    const template = catalog?.find(item => item.id === chosen);
    if (!template) { element('p', 'Choose a template to preview its workflow.', detail, 'muted'); return; }
    element('h3', template.title, detail);
    element('p', template.description, detail, 'muted');
    // Own frame: a preview wider than the dialog scrolls inside it instead of widening the dialog.
    element('div', '', detail, 'template-preview').append(thumbnail(template.preview, true));
    if (template.preview.loop) {
      // Template-specific loop details stay collapsed; the Research loop panel edits them after import.
      const more = element('details', '', detail, 'template-advanced'); element('summary', 'Loop details', more);
      element('p', `Feedback from ${template.preview.loop.source} back to ${template.preview.loop.target}; at most ${template.preview.loop.final_iteration} iteration${template.preview.loop.final_iteration === 1 ? '' : 's'} until you raise the limit. Stop conditions are added later in Research loop.`, more, 'muted');
    }
    element('p', 'Using it replaces the workflow in your unsaved draft. Your task and data references stay as they are. Then write your advice, edit parameters and Save.', detail, 'muted');
    const button = element('button', 'Use template', detail); button.type = 'button'; button.id = 'editor-template-import';
    const blocked = editorBlock(); button.disabled = busy || !!blocked; if (blocked) status(blocked);
    button.addEventListener('click', () => void importTemplate(template));
  }
  function renderList() {
    const list = $('editor-template-list'); list.replaceChildren();
    if (!catalog) { element('p', loading ? 'Loading templates…' : 'Connect to load templates.', list, 'muted'); return; }
    // First card: build it yourself (canvas-study T1). It changes nothing in the draft.
    const blank = element('button', '', list, 'template-card'); blank.type = 'button'; blank.dataset.template = BLANK;
    blank.setAttribute('aria-pressed', String(chosen === BLANK));
    blank.append(window.consoleIcons?.make('plus', 20) || icon('step'));
    const blankText = element('span', '', blank, 'template-card-text');
    element('strong', 'Blank workflow', blankText); element('span', 'Add modules yourself from the list on the left.', blankText, 'muted');
    blank.addEventListener('click', () => { chosen = BLANK; renderList(); renderDetail(); });
    for (const template of catalog) {
      const card = element('button', '', list, 'template-card'); card.type = 'button'; card.dataset.template = template.id;
      card.setAttribute('aria-pressed', String(template.id === chosen));
      // Compact beginner card: icon, title, one sentence; the graph preview opens on demand.
      card.append(icon(template.preview.loop ? 'loop' : 'step'));
      const text = element('span', '', card, 'template-card-text');
      element('strong', template.title, text); element('span', template.description, text, 'muted');
      card.addEventListener('click', () => { chosen = template.id; renderList(); renderDetail(); });
    }
  }
  async function load() {
    if (catalog || loading || !window.consoleSession.connected) return;
    loading = window.consoleSession.request('editor/templates');
    renderList();
    try { catalog = (await loading).templates; }
    catch (error) { if (!error.stale) status(`Templates unavailable: ${error.message}`); }
    finally { loading = null; renderList(); renderDetail(); }
  }
  async function importTemplate(template) {
    const blocked = editorBlock(); if (blocked) { status(blocked); return; }
    const state = window.workflowEditor.state;
    if (state.dirty && !window.confirm('Importing replaces the workflow in your draft. Your current edits stay in Undo history. Continue?')) return;
    busy = true; renderDetail(); status(`Importing ${template.title}…`);
    try {
      const value = await window.consoleSession.request(`editor/${encodeURIComponent(state.projectId)}/template`,
        {template_id: template.id, expected_sha256: state.savedSha256});
      // The import's own check is not a save request: the page bar keeps the save step closed.
      const reviewed = await (window.editorPageBar?.quietly || (run => run()))(() => window.workflowEditor.importSource(value.source, `Import template: ${template.title}`));
      if (reviewed) {
        $('editor-template-gallery').close();
        status(`Imported ${template.title} as an unsaved draft.`);
        // Human advice is the first thing to write (canvas-study T5).
        void window.editorAdvice?.focusFirst();
      } else {
        status(`Not imported: ${document.getElementById('editor-status')?.textContent || 'Review refused the template.'}`);
      }
    } catch (error) {
      if (!error.stale) status(`Not imported: ${error.message}`);
    } finally { busy = false; renderDetail(); }
  }
  function open() {
    $('editor-template-gallery').showModal(); status(''); void load(); renderList(); renderDetail();
    ($('editor-template-list').querySelector('.template-card') || $('editor-template-close')).focus();
  }

  function mount() {
    // Entries: the canvas header "Templates" button, the empty-canvas primary action and Home.
    const buttons = ['editor-template-open', 'workflow-start-template'].map($).filter(Boolean);
    if (!buttons.length) return;
    for (const button of buttons) button.addEventListener('click', open);
    const dialog = element('dialog', '', document.body, 'template-gallery'); dialog.id = 'editor-template-gallery';
    dialog.setAttribute('aria-labelledby', 'editor-template-title');
    const title = element('h2', 'Start from a template', dialog); title.id = 'editor-template-title';
    element('p', `Templates are workflow shapes, not tasks: they never choose a task, data or model. Start from ${label('proposal')}; ${label('interpretation')} adds the research loop.`, dialog, 'muted');
    const body = element('div', '', dialog, 'template-body');
    const list = element('div', '', body, 'template-list'); list.id = 'editor-template-list';
    const detail = element('div', '', body, 'template-detail'); detail.id = 'editor-template-detail';
    const footer = element('div', '', dialog, 'template-footer');
    const state = element('p', '', footer, 'muted'); state.id = 'editor-template-status'; state.setAttribute('role', 'status');
    const close = element('button', 'Close', footer, 'secondary'); close.type = 'button'; close.id = 'editor-template-close';
    close.addEventListener('click', () => dialog.close());
    // Opening needs a connection (templates keep the open project's task references).
    const enable = () => { for (const button of buttons) button.disabled = !window.consoleSession.connected; };
    window.consoleSession.subscribe(({connected}) => { if (!connected) catalog = null; enable(); });
    window.addEventListener('workflow-editor-state', () => { if (dialog.open) renderDetail(); });
    enable();
  }
  // Quick start reuses this one import path; it resolves true once the draft is imported.
  async function importById(id) {
    await load();
    const template = catalog?.find(item => item.id === id);
    if (!template) { status(`Template ${id} is unavailable.`); return false; }
    await importTemplate(template);
    return document.getElementById('editor-template-status')?.textContent.startsWith('Imported') === true;
  }
  window.editorTemplates = Object.freeze({open, importById});
  mount();
})();
