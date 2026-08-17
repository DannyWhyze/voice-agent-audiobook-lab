import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// i18n.js wires up #language-toggle-btn at module load time (addEventListener
// on a null element throws), so it has to exist before that import below.
const dom = new JSDOM('<!doctype html><html><body><button id="language-toggle-btn"></button></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;

// In-memory stand-in for the skills-files/notes backend, keyed by the same
// URL each request actually hits.
const files = new Map();

globalThis.fetch = async (url, options = {}) => {
  const method = options.method || "GET";

  if (method === "GET") {
    if (!files.has(url)) return { ok: false, json: async () => ({}) };
    return { ok: true, json: async () => ({ content: files.get(url) }) };
  }

  if (method === "PUT") {
    const body = JSON.parse(options.body);
    files.set(url, body.content);
    return { ok: true, json: async () => ({ status: "ok" }) };
  }

  throw new Error(`unhandled fetch in test: ${method} ${url}`);
};

const { openSkillsFilesOverlay } = await import("../../static/js/overlays/skills-files-overlay.js");
const { t } = await import("../../static/js/i18n.js");

// Each test builds its own overlay instance and closes it afterward, so
// there's never more than one ".skills-files-editor" in the shared JSDOM
// document at a time -- lets tests use a plain document.querySelector
// instead of threading DOM references out through the overlay's handle
// (which deliberately only exposes openFile/loadFileList/refreshCurrentFile,
// not its internal elements).
function build() {
  return openSkillsFilesOverlay({
    t,
    getProject: () => "",
    onClosed: () => {},
    onFilesChanged: () => {},
  });
}

test("refreshCurrentFile() ist ein No-op, solange keine Datei geöffnet ist", async () => {
  const filesCountBefore = files.size;
  const handle = build();
  await handle.refreshCurrentFile();
  assert.equal(files.size, filesCountBefore);
  handle.close();
});

test("refreshCurrentFile() laedt frischen Serverinhalt nach, wenn nicht dirty", async () => {
  const url = "/skills-files/skill-a.md";
  files.set(url, "Alter Inhalt");

  const handle = build();
  await handle.openFile("skill-a.md", false);
  const textarea = document.querySelector(".skills-files-editor");
  assert.equal(textarea.value, "Alter Inhalt");

  files.set(url, "Neuer Inhalt vom Agenten");
  await handle.refreshCurrentFile();

  assert.equal(textarea.value, "Neuer Inhalt vom Agenten");
  handle.close();
});

test("refreshCurrentFile() ueberschreibt ungespeicherte lokale Aenderungen NICHT (dirty)", async () => {
  const url = "/skills-files/skill-b.md";
  files.set(url, "Serverstand 1");

  const handle = build();
  await handle.openFile("skill-b.md", false);
  const textarea = document.querySelector(".skills-files-editor");

  textarea.value = "Lokal getippter, noch nicht gespeicherter Text";
  textarea.dispatchEvent(new dom.window.Event("input", { bubbles: true }));

  files.set(url, "Serverstand 2, vom Agenten geschrieben");
  await handle.refreshCurrentFile();

  assert.equal(textarea.value, "Lokal getippter, noch nicht gespeicherter Text");
  handle.close();
});

test("Speichern räumt die dirty-Markierung auf, refreshCurrentFile() greift danach wieder", async () => {
  const url = "/skills-files/skill-c.md";
  files.set(url, "Serverstand 1");

  const handle = build();
  await handle.openFile("skill-c.md", false);
  const textarea = document.querySelector(".skills-files-editor");
  const saveBtn = document.querySelector(".skills-files-action-row .btn-compact");

  textarea.value = "Lokale Aenderung";
  textarea.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  saveBtn.click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  files.set(url, "Serverstand 2, vom Agenten geschrieben");
  await handle.refreshCurrentFile();

  assert.equal(textarea.value, "Serverstand 2, vom Agenten geschrieben");
  handle.close();
});
