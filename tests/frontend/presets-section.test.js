import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// i18n.js wires up #language-toggle-btn at module load time (addEventListener
// on a null element throws), so it has to exist before that import below.
const dom = new JSDOM('<!doctype html><html><body><button id="language-toggle-btn"></button></body></html>');
globalThis.document = dom.window.document;

// In-memory stand-in for the presets backend (routers/projects.py's
// /projects/{project}/presets endpoints), keyed the same way the real
// storage is: one list per (project, effectType). Lets tests exercise the
// real save/load/delete round trip through buildPresetsSection() instead of
// stubbing each fetch response by hand.
const store = new Map();

function presetsFor(project, effectType) {
  const key = `${project}:${effectType}`;
  if (!store.has(key)) store.set(key, []);
  return store.get(key);
}

globalThis.fetch = async (url, options = {}) => {
  const method = options.method || "GET";

  if (method === "GET") {
    const [, project] = url.match(/^\/projects\/([^/]+)\/presets$/);
    const result = {};
    for (const [key, list] of store) {
      const [keyProject, effectType] = key.split(":");
      if (keyProject === project) result[effectType] = list;
    }
    return { ok: true, json: async () => result };
  }

  if (method === "POST") {
    const [, project, effectType] = url.match(/^\/projects\/([^/]+)\/presets\/([^/]+)$/);
    const body = JSON.parse(options.body);
    const list = presetsFor(project, effectType);
    if (!body.name || list.some((preset) => preset.name === body.name)) {
      return { ok: false, json: async () => ({ detail: "invalid or duplicate name" }) };
    }
    list.push({ name: body.name, params: body.params });
    return { ok: true, json: async () => ({ status: "ok" }) };
  }

  if (method === "DELETE") {
    const [, project, effectType, encodedName] = url.match(
      /^\/projects\/([^/]+)\/presets\/([^/]+)\/(.+)$/
    );
    const name = decodeURIComponent(encodedName);
    const list = presetsFor(project, effectType);
    const index = list.findIndex((preset) => preset.name === name);
    if (index !== -1) list.splice(index, 1);
    return { ok: true, json: async () => ({ status: "ok" }) };
  }

  throw new Error(`unhandled fetch in test: ${method} ${url}`);
};

const { buildPresetsSection } = await import("../../static/js/overlays/overlay-chrome.js");
const { t } = await import("../../static/js/i18n.js");

// buildPresetsSection()'s renderList() is async but fire-and-forget (not
// awaited by callers, including the click handlers below) -- give its
// fetch().then() chain a macrotask to resolve before asserting on the DOM.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function build(project, effectType, params, overrides = {}) {
  const refreshCalls = [];
  const appliedCalls = [];
  const container = buildPresetsSection({
    t,
    project,
    effectType,
    params,
    refreshFns: [() => refreshCalls.push(true)],
    onPresetApplied: () => appliedCalls.push(true),
    ...overrides,
  });
  return { container, refreshCalls, appliedCalls };
}

test("zeigt eine zugeklappte Sektion mit korrektem Zähler für bereits gespeicherte Presets", async () => {
  presetsFor("P1", "compressor").push(
    { name: "Warme Stimme", params: { threshold_db: -18 } },
    { name: "Punchy", params: { threshold_db: -24 } }
  );

  const { container } = build("P1", "compressor", {});
  await flush();

  const details = container.querySelector(".presets-details");
  assert.ok(details, "erwartet ein <details>-Element");
  assert.equal(details.open, false, "soll standardmäßig zugeklappt sein");
  assert.equal(details.querySelector("summary").textContent, "▶Vorlagen (2)");

  const rows = container.querySelectorAll(".preset-row");
  assert.equal(rows.length, 2);
  assert.equal(rows[0].querySelector(".preset-name").textContent, "Warme Stimme");
  assert.equal(rows[1].querySelector(".preset-name").textContent, "Punchy");
});

test("Klick auf eine Preset-Zeile lädt sie: Object.assign auf params, refreshFns und onPresetApplied laufen", async () => {
  presetsFor("P2", "compressor").push({ name: "Sanft", params: { threshold_db: -30, ratio: 2 } });

  const params = { threshold_db: -20, ratio: 4 };
  const { container, refreshCalls, appliedCalls } = build("P2", "compressor", params);
  await flush();

  container.querySelector(".preset-row").click();

  assert.deepEqual(params, { threshold_db: -30, ratio: 2 });
  assert.equal(refreshCalls.length, 1);
  assert.equal(appliedCalls.length, 1);
});

test("Klick auf das Lösch-✕ lädt die Zeile NICHT mit (stopPropagation) und entfernt den Preset serverseitig", async () => {
  presetsFor("P3", "compressor").push(
    { name: "Bleibt", params: { threshold_db: -10 } },
    { name: "Wird gelöscht", params: { threshold_db: -40 } }
  );

  const params = { threshold_db: -20 };
  const { container, appliedCalls } = build("P3", "compressor", params);
  await flush();

  const rows = container.querySelectorAll(".preset-row");
  const targetRow = [...rows].find((row) => row.querySelector(".preset-name").textContent === "Wird gelöscht");
  targetRow.querySelector(".preset-delete-btn").click();
  await flush();

  assert.equal(appliedCalls.length, 0, "Löschen darf nicht auch als Laden zählen");
  assert.deepEqual(params, { threshold_db: -20 }, "params dürfen durch Löschen nicht verändert werden");

  const remainingNames = [...container.querySelectorAll(".preset-name")].map((el) => el.textContent);
  assert.deepEqual(remainingNames, ["Bleibt"]);
  assert.equal(container.querySelector("summary").textContent, "▶Vorlagen (1)");
  assert.deepEqual(presetsFor("P3", "compressor").map((p) => p.name), ["Bleibt"]);
});

test("Speichern-Formular: leerer Name schickt keinen Request, gültiger Name legt einen neuen Preset an", async () => {
  const params = { threshold_db: -15 };
  const { container } = build("P4", "compressor", params);
  await flush();

  container.querySelector(".btn-compact").click(); // "Als Vorlage speichern" oeffnet das Formular
  const nameInput = container.querySelector(".inline-name-form input");
  const confirmBtn = container.querySelector(".inline-name-form .btn-compact");

  nameInput.value = "";
  confirmBtn.click();
  await flush();
  assert.equal(presetsFor("P4", "compressor").length, 0, "leerer Name darf nichts anlegen");

  nameInput.value = "Neu";
  confirmBtn.click();
  await flush();

  assert.deepEqual(presetsFor("P4", "compressor"), [{ name: "Neu", params: { threshold_db: -15 } }]);
  assert.equal(container.querySelector("summary").textContent, "▶Vorlagen (1)");
});
