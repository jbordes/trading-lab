"use strict";

// Toggle de tema claro/oscuro. Corre como script bloqueante en el head para
// aplicar la elección guardada antes del primer pintado; sin elección, el CSS
// sigue la preferencia del sistema. Solo manipula dataset, clases y textos.

(function () {
  const root = document.documentElement;
  root.classList.add("js");
  const STORAGE_KEY = "tradinglab.theme";

  let saved = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch (_) {
    // almacenamiento no disponible: se sigue al sistema
  }
  if (saved === "light" || saved === "dark") {
    root.dataset.theme = saved;
  }

  function effectiveTheme() {
    if (root.dataset.theme === "light" || root.dataset.theme === "dark") {
      return root.dataset.theme;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function updateButtons() {
    const current = effectiveTheme();
    const icon = document.querySelector("[data-theme-icon]");
    if (icon) {
      // La pestaña pertenece al navegador: su contraste no depende del tema de la app.
      const browserDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const iconTheme = browserDark ? "dark" : "light";
      if (icon.dataset.themeIcon !== iconTheme) {
        icon.href = browserDark
          ? "/assets/favicon-white.ico?v=fitted-1"
          : "/assets/favicon-black.ico?v=fitted-1";
        icon.dataset.themeIcon = iconTheme;
      }
    }
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.hidden = false;
      button.textContent = current === "dark" ? "Claro" : "Oscuro";
      button.setAttribute(
        "aria-label",
        current === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro",
      );
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    updateButtons();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const next = effectiveTheme() === "dark" ? "light" : "dark";
        root.dataset.theme = next;
        try {
          localStorage.setItem(STORAGE_KEY, next);
        } catch (_) {
          // sin almacenamiento: el cambio vale para esta pestaña
        }
        updateButtons();
      });
    });
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", updateButtons);
    window.addEventListener("storage", (event) => {
      if (event.key !== STORAGE_KEY) return;
      if (event.newValue === "light" || event.newValue === "dark") {
        root.dataset.theme = event.newValue;
      } else if (!event.newValue) {
        delete root.dataset.theme;
      }
      updateButtons();
    });
  });
})();
