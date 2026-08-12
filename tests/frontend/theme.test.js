import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

class MemoryStorage {
  constructor() {
    this.store = new Map();
  }
  getItem(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }
  setItem(key, value) {
    this.store.set(key, String(value));
  }
  removeItem(key) {
    this.store.delete(key);
  }
}

const dom = new JSDOM(
  '<!doctype html><html><body><button id="language-toggle-btn"></button><button id="theme-toggle-btn"></button></body></html>'
);
globalThis.document = dom.window.document;
globalThis.localStorage = new MemoryStorage();

const { getTheme, setTheme } = await import("../../static/js/theme.js");
const themeToggleBtn = document.getElementById("theme-toggle-btn");

test("getTheme gibt 'warm' zurück, wenn nichts gespeichert ist", () => {
  assert.equal(getTheme(), "warm");
});

test("setTheme('dark') setzt data-theme und speichert 'dark'", () => {
  setTheme("dark");
  assert.equal(document.documentElement.dataset.theme, "dark");
  assert.equal(getTheme(), "dark");
});

test("setTheme('warm') setzt data-theme auf leeren String und speichert 'warm'", () => {
  setTheme("warm");
  assert.equal(document.documentElement.dataset.theme, "");
  assert.equal(getTheme(), "warm");
});

test("setTheme mit unbekanntem Wert fällt auf 'warm' zurück", () => {
  setTheme("neon");
  assert.equal(getTheme(), "warm");
  assert.equal(document.documentElement.dataset.theme, "");
});

test("Klick auf den Theme-Button kippt das Theme und das Label", () => {
  setTheme("warm");
  themeToggleBtn.dispatchEvent(new dom.window.Event("click"));
  assert.equal(getTheme(), "dark");
  assert.equal(themeToggleBtn.textContent, "Warm");

  themeToggleBtn.dispatchEvent(new dom.window.Event("click"));
  assert.equal(getTheme(), "warm");
  assert.equal(themeToggleBtn.textContent, "Dark");
});
