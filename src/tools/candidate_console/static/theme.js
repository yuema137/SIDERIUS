/* Load before styles/body so the first paint uses the selected palette. */
(() => {
  "use strict";
  const key = "siderius.console.theme";
  const choices = ["system", "light", "dark"];
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = "system";
  try {
    const stored = window.localStorage.getItem(key);
    if (choices.includes(stored)) preference = stored;
  } catch { /* Storage denial leaves this page's preference in memory. */ }

  const apply = () => {
    document.documentElement.dataset.theme = preference === "system"
      ? (system.matches ? "dark" : "light") : preference;
  };
  apply();
  system.addEventListener("change", () => {
    if (preference === "system") apply();
  });
  document.addEventListener("DOMContentLoaded", () => {
    const control = document.getElementById("theme-preference");
    control.value = preference;
    control.addEventListener("change", () => {
      if (!choices.includes(control.value)) return;
      preference = control.value;
      try { window.localStorage.setItem(key, preference); }
      catch { /* Keep working without persistent storage. */ }
      apply();
    });
  });
})();
