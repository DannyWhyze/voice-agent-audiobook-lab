import { test } from "node:test";
import assert from "node:assert/strict";
import {
  loadProjectChatHistory,
  saveProjectChatHistory,
  clearProjectChatHistory,
  loadChatHistories,
  saveChatHistoriesEntry,
  removeChatHistoriesEntry,
  loadScriptChatHistory,
  saveScriptChatHistory,
  clearAllChatHistoriesForProject,
} from "../../static/js/chat-history-storage.js";

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
  key(index) {
    return Array.from(this.store.keys())[index] ?? null;
  }
  get length() {
    return this.store.size;
  }
}

globalThis.localStorage = new MemoryStorage();

test("loadProjectChatHistory gibt leeres Array zurück, wenn nichts gespeichert ist", () => {
  assert.deepEqual(loadProjectChatHistory("NoSuchProject"), []);
});

test("saveProjectChatHistory und loadProjectChatHistory sind symmetrisch", () => {
  const history = [
    { role: "user", content: "Hallo" },
    { role: "assistant", content: "Hi!" },
  ];
  saveProjectChatHistory("TestProject", history);
  assert.deepEqual(loadProjectChatHistory("TestProject"), history);
});

test("saveProjectChatHistory trennt Verlauf nach Projekt", () => {
  saveProjectChatHistory("ProjectA", [{ role: "user", content: "A" }]);
  saveProjectChatHistory("ProjectB", [{ role: "user", content: "B" }]);
  assert.deepEqual(loadProjectChatHistory("ProjectA"), [{ role: "user", content: "A" }]);
  assert.deepEqual(loadProjectChatHistory("ProjectB"), [{ role: "user", content: "B" }]);
});

test("clearProjectChatHistory leert den Verlauf", () => {
  saveProjectChatHistory("TestProject", [{ role: "user", content: "Hallo" }]);
  clearProjectChatHistory("TestProject");
  assert.deepEqual(loadProjectChatHistory("TestProject"), []);
});

test("loadProjectChatHistory filtert ungültige Einträge heraus", () => {
  localStorage.setItem(
    "fishaudio_project_chat_history:TestProject",
    JSON.stringify([
      { role: "user", content: "ok" },
      { role: "system", content: "invalid role" },
      { bad: "entry" },
    ]),
  );
  assert.deepEqual(loadProjectChatHistory("TestProject"), [{ role: "user", content: "ok" }]);
});

test("removeChatHistoriesEntry spleißt statt zu überschreiben, damit spätere Boxen nachrücken", () => {
  saveChatHistoriesEntry("P", "K1", 0, [{ role: "user", content: "Box 0" }]);
  saveChatHistoriesEntry("P", "K1", 1, [{ role: "user", content: "Box 1" }]);
  saveChatHistoriesEntry("P", "K1", 2, [{ role: "user", content: "Box 2" }]);

  removeChatHistoriesEntry("P", "K1", 1);

  assert.deepEqual(loadChatHistories("P", "K1"), [
    [{ role: "user", content: "Box 0" }],
    [{ role: "user", content: "Box 2" }],
  ]);
});

test("removeChatHistoriesEntry ignoriert einen Index außerhalb des Arrays", () => {
  saveChatHistoriesEntry("P2", "K1", 0, [{ role: "user", content: "Box 0" }]);
  removeChatHistoriesEntry("P2", "K1", 5);
  assert.deepEqual(loadChatHistories("P2", "K1"), [[{ role: "user", content: "Box 0" }]]);
});

test("clearAllChatHistoriesForProject räumt Box-Chats, Skript-Chats und Projekt-Chat für alle Kapitel dieses Projekts auf, lässt andere Projekte in Ruhe", () => {
  saveChatHistoriesEntry("ProjA", "Kapitel1", 0, [{ role: "user", content: "a" }]);
  saveChatHistoriesEntry("ProjA", "Kapitel2", 0, [{ role: "user", content: "b" }]);
  saveScriptChatHistory("ProjA", "Kapitel1", [{ role: "user", content: "c" }]);
  saveProjectChatHistory("ProjA", [{ role: "user", content: "d" }]);

  saveChatHistoriesEntry("ProjAExtra", "Kapitel1", 0, [{ role: "user", content: "e" }]);
  saveProjectChatHistory("ProjAExtra", [{ role: "user", content: "f" }]);

  clearAllChatHistoriesForProject("ProjA");

  assert.deepEqual(loadChatHistories("ProjA", "Kapitel1"), []);
  assert.deepEqual(loadChatHistories("ProjA", "Kapitel2"), []);
  assert.deepEqual(loadScriptChatHistory("ProjA", "Kapitel1"), []);
  assert.deepEqual(loadProjectChatHistory("ProjA"), []);

  assert.deepEqual(loadChatHistories("ProjAExtra", "Kapitel1"), [[{ role: "user", content: "e" }]]);
  assert.deepEqual(loadProjectChatHistory("ProjAExtra"), [{ role: "user", content: "f" }]);
});
