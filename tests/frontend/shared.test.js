import { test } from "node:test";
import assert from "node:assert/strict";
import { hashString, voiceAccentColor, getVoiceAccentColor, reorderChapters } from "../../static/js/shared.js";

test("hashString ist deterministisch für denselben String", () => {
  assert.equal(hashString("Alice"), hashString("Alice"));
});

test("hashString liefert für verschiedene Strings meist verschiedene Werte", () => {
  assert.notEqual(hashString("Alice"), hashString("Bob"));
});

test("voiceAccentColor gibt für base_voice die feste Sonderfarbe zurück", () => {
  assert.equal(voiceAccentColor("base_voice"), "rgba(255, 255, 255, 0.45)");
});

test("voiceAccentColor gibt null für leeren Namen zurück", () => {
  assert.equal(voiceAccentColor(""), null);
  assert.equal(voiceAccentColor(null), null);
});

test("getVoiceAccentColor vergibt für neue Stimmen kollisionsfreie Farben", () => {
  const colorA = getVoiceAccentColor("stimme-test-a");
  const colorB = getVoiceAccentColor("stimme-test-b");
  assert.notEqual(colorA, colorB);
});

test("getVoiceAccentColor liefert für dieselbe Stimme immer dieselbe Farbe", () => {
  const first = getVoiceAccentColor("stimme-test-sticky");
  const second = getVoiceAccentColor("stimme-test-sticky");
  assert.equal(first, second);
});

test("reorderChapters verschiebt das gezogene Kapitel vor das Ziel-Kapitel", () => {
  const result = reorderChapters(["a", "b", "c"], "c", "b");
  assert.deepEqual(result, ["a", "c", "b"]);
});

test("reorderChapters hängt das gezogene Kapitel ans Ende, wenn kein Ziel angegeben ist", () => {
  const result = reorderChapters(["a", "b", "c"], "a", null);
  assert.deepEqual(result, ["b", "c", "a"]);
});
