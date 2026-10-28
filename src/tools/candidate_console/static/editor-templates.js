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
  const NODE_W = 220, NODE_H = 64;

  /** Thumbnail of the template graph from the server preview (positions, edges, loop). */
  function thumbnail(preview, large) {
    const xs = preview.nodes.map(n => n.x), ys = preview.nodes.map(n => n.y);
    const minX = Math.min(...xs), minY = Math.min(...ys), pad = 24, loopPad = preview.loop ? 70 : 0;
    const width = Math.max(...xs) - minX + NODE_W + 2 * pad, height = Math.max(...ys) - minY + NODE_H + 2 * pad + loopPad;
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('class', `template-thumbnail${large ? ' large' : ''}`);
    svg.setAttribute('role', 'img');
    const steps = preview.nodes.map(n => label(n.capability)).join(' → ');
    svg.setAttribute('aria-label', preview.loop ? `${steps}, repeated up to ${preview.loop.final_iteration} time(s) from ${preview.loop.source} back to ${preview.loop.target}` : steps);
    const at = Object.fromEntries(preview.nodes.map(n => [n.id, {x: n.x - minX + pad, y: n.y - minY + pad}]));
    const defs = svgElement('defs', {}, svg), marker = svgElement('marker', {id: `arrow-${large ? 'l' : 's'}`, viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse'}, defs);
    svgElement('path', {d: 'M0 0 10 5 0 10z', class: 'template-arrow'}, marker);
    const arrow = `url(#arrow-${large ? 'l' : 's'})`;
    // One line per connected pair; several arguments between the same nodes draw once.
    const pairs = new Set(preview.edges.map(edge => `${edge.source}>${edge.target}`));
    for (const pair of pairs) {
      const [source, target] = pair.split('>'), a = at[source], b = at[target];
      const straight = Math.abs(b.x - a.x) <= NODE_W + 120;
      const y1 = a.y + NODE_H / 2, y2 = b.y + NODE_H / 2, x1 = a.x + NODE_W, x2 = b.x;
      // Skipping edges arc above the row so they do not hide the cards they pass.
      const d = straight ? `M${x1} ${y1} L${x2} ${y2}` : `M${x1 - 30} ${a.y} C${x1} ${a.y - 40}, ${x2 + 30} ${b.y - 40}, ${x2 + 30} ${b.y}`;
      svgElement('path', {d, class: 'template-edge', 'marker-end': arrow}, svg);
    }
    if (preview.loop) {
      const s = at[preview.loop.source], t = at[preview.loop.target], bottom = Math.max(s.y, t.y) + NODE_H + 50;
      svgElement('path', {d: `M${s.x + NODE_W / 2} ${s.y + NODE_H} C${s.x + NODE_W / 2} ${bottom}, ${t.x + NODE_W / 2} ${bottom}, ${t.x + NODE_W / 2} ${t.y + NODE_H}`,
        class: 'template-loop', 'marker-end': arrow}, svg);
      const text = svgElement('text', {x: String((s.x + t.x + NODE_W) / 2), y: String(bottom - 4), 'text-anchor': 'middle', class: 'template-loop-label'}, svg);
      text.textContent = `feedback · up to ${preview.loop.final_iteration} iteration${preview.loop.final_iteration === 1 ? '' : 's'}`;
    }
    for (const n of preview.nodes) {
      const {x, y} = at[n.id], group = svgElement('g', {class: `template-node capability-${n.capability}`}, svg);
      svgElement('rect', {x: String(x), y: String(y), width: String(NODE_W), height: String(NODE_H), rx: '12'}, group);
      const text = svgElement('text', {x: String(x + NODE_W / 2), y: String(y + NODE_H / 2 + 8), 'text-anchor': 'middle'}, group);
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
    return '';
  }
  function status(message) { const value = $('editor-template-status'); if (value) value.textContent = message; }

  function renderDetail() {
    const detail = $('editor-template-detail'); detail.replaceChildren();
    if (chosen === BLANK) {
      element('h3', 'Blank workflow', detail);
      element('p', 'Pick modules from the list on the left and connect them. Your current workflow stays as it is; nothing changes until you add a module.', detail, 'muted');
      const start = element('button', 'Add modules myself', detail); start.type = 'button'; start.id = 'editor-template-blank';
      start.addEventListener('click', () => { $('editor-template-gallery').close(); document.querySelector('#editor-palette .palette-search')?.focus(); });
      return;
    }
    const template = catalog?.find(item => item.id === chosen);
    if (!template) { element('p', 'Choose a template to preview its workflow.', detail, 'muted'); return; }
    element('h3', template.title, detail);
    element('p', template.description, detail, 'muted');
    detail.append(thumbnail(template.preview, true));
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
  window.editorTemplates = Object.freeze({open});
  mount();
})();
