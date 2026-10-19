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

  // El logo horizontal completo queda diminuto a 16 px. Para la pestaña se usa
  // su motivo central, recortado simétricamente y sin deformar el PNG original.
  function prepareFavicon(icon) {
    if (icon.dataset.squareReady || icon.dataset.squareLoading) return;
    icon.dataset.squareLoading = "true";
    const source = new Image();
    source.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = 64;
      canvas.height = 64;
      const sourceWidth = source.naturalWidth * 0.7;
      const sourceX = (source.naturalWidth - sourceWidth) / 2;
      const width = 60;
      const height = width * source.naturalHeight / sourceWidth;
      canvas.getContext("2d").drawImage(
        source, sourceX, 0, sourceWidth, source.naturalHeight,
        (64 - width) / 2, (64 - height) / 2, width, height,
      );
      icon.href = canvas.toDataURL("image/png");
      icon.dataset.squareReady = "true";
      delete icon.dataset.squareLoading;
    };
    source.onerror = () => { delete icon.dataset.squareLoading; };
    source.src = icon.href;
  }

  function updateButtons() {
    const current = effectiveTheme();
    document.querySelectorAll("[data-theme-icon]").forEach((icon) => {
      icon.media = icon.dataset.themeIcon === current ? "all" : "not all";
      prepareFavicon(icon);
    });
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
