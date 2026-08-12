import { t } from "./i18n.js";

const STORAGE_KEY = "fishaudio_theme";

export function getTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "dark" ? "dark" : "warm";
}

export function setTheme(theme) {
  const normalized = theme === "dark" ? "dark" : "warm";
  document.documentElement.dataset.theme = normalized === "dark" ? "dark" : "";
  localStorage.setItem(STORAGE_KEY, normalized);
}

setTheme(getTheme());

const themeToggleBtn = document.getElementById("theme-toggle-btn");

if (themeToggleBtn) {
  function updateThemeToggleLabel() {
    themeToggleBtn.textContent = getTheme() === "warm" ? t("themeToggleDark") : t("themeToggleWarm");
  }

  themeToggleBtn.addEventListener("click", () => {
    setTheme(getTheme() === "warm" ? "dark" : "warm");
    updateThemeToggleLabel();
  });

  updateThemeToggleLabel();
}
