/** Shared witness helper (not a witness): choose the first configured task after Connect.
 * Workflow and Run stay closed until a task is selected (static/task-selection.js); a
 * console with one task selects it automatically, but fixtures configuring several task
 * versions do not. Witnesses that exercise the editor or Run with such a fixture call
 * chooseFirstConfiguredTask(browser) right after launch: every later page then behaves as
 * a user who chose the first task on the Task tab (task_panel.mjs covers the tab itself). */
const choose = target => target.addInitScript(() => {
  window.addEventListener('console-task', () => {
    const tasks = window.consoleTask;
    if (tasks?.state === 'ready' && !tasks.selectedId && tasks.tasks.length) tasks.select(tasks.tasks[0].task_id);
  });
});
export function chooseFirstConfiguredTask(browser) {
  const newContext = browser.newContext.bind(browser), newPage = browser.newPage.bind(browser);
  browser.newContext = async (...args) => { const context = await newContext(...args); await choose(context); return context; };
  browser.newPage = async (...args) => { const page = await newPage(...args); await choose(page.context()); return page; };
  return browser;
}
