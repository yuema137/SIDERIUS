/** Shared witness helper (not a witness): show every Settings-gated console section.
 * Console sections marked data-ui-flag are hidden until the user turns on Settings >
 * "Show advanced tools" / "Show developer details" (static/ui-settings.js). Witnesses that
 * exercise those sections call showAllConsoleSections(browser) right after launch; every
 * later context/page then starts with both flags stored, exactly as a user who enabled them.
 * layout_onboarding.mjs covers the default (hidden) state and the toggles themselves. */
const enable = context => context.addInitScript(() => {
  try { for (const flag of ['advanced', 'developer']) localStorage.setItem('siderius.console.ui.' + flag, 'on'); }
  catch { /* A storage-denied page keeps the default view. */ }
});
export function showAllConsoleSections(browser) {
  const newContext = browser.newContext.bind(browser), newPage = browser.newPage.bind(browser);
  browser.newContext = async (...args) => { const context = await newContext(...args); await enable(context); return context; };
  browser.newPage = async (...args) => { const page = await newPage(...args); await enable(page.context()); return page; };
  return browser;
}
