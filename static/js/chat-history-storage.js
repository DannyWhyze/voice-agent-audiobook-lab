function storageKey(project, chapter) {
  return `fishaudio_chat_histories:${project}:${chapter}`;
}

// Guards against corrupted/hand-edited localStorage: entries missing role/content,
// or with a non-string content, would otherwise reach history.push/.forEach/.slice
// calls in chat-overlay.js/script-chat-overlay.js (crash) or get sent to the
// backend chat endpoint as-is (422). See docs/FIXES.md.
function isValidChatMessage(entry) {
  return (
    entry !== null &&
    typeof entry === "object" &&
    (entry.role === "user" || entry.role === "assistant") &&
    typeof entry.content === "string"
  );
}

function sanitizeChatMessages(list) {
  return Array.isArray(list) ? list.filter(isValidChatMessage) : [];
}

export function loadChatHistories(project, chapter) {
  const raw = localStorage.getItem(storageKey(project, chapter));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(sanitizeChatMessages);
  } catch {
    return [];
  }
}

export function saveChatHistoriesEntry(project, chapter, boxIndex, history) {
  const histories = loadChatHistories(project, chapter);
  histories[boxIndex] = history;
  localStorage.setItem(storageKey(project, chapter), JSON.stringify(histories));
}

export function clearChatHistoriesEntry(project, chapter) {
  localStorage.removeItem(storageKey(project, chapter));
}

// Splices out boxIndex's entry (not just clearing/overwriting it) so every
// later box's history shifts down to match its new position — otherwise a
// removed box's slot stays in the array and every subsequent box loads the
// wrong (shifted) history the next time the chapter is loaded. See docs/FIXES.md.
export function removeChatHistoriesEntry(project, chapter, boxIndex) {
  const histories = loadChatHistories(project, chapter);
  if (boxIndex < 0 || boxIndex >= histories.length) return;
  histories.splice(boxIndex, 1);
  localStorage.setItem(storageKey(project, chapter), JSON.stringify(histories));
}

// Moves the box-chat histories from oldChapter's key to newChapter's key,
// so renaming a chapter doesn't silently orphan its chat history under the
// old, now-unreferenced key while the renamed chapter starts empty. A no-op
// if oldChapter never had any history saved, so it can't wipe out an
// existing newChapter entry (the overwrite-rename case) with an empty one.
export function renameChatHistoriesEntry(project, oldChapter, newChapter) {
  const raw = localStorage.getItem(storageKey(project, oldChapter));
  if (raw === null) return;
  localStorage.removeItem(storageKey(project, oldChapter));
  localStorage.setItem(storageKey(project, newChapter), raw);
}

function scriptChatStorageKey(project, chapter) {
  return `fishaudio_script_chat_history:${project}:${chapter}`;
}

export function loadScriptChatHistory(project, chapter) {
  const raw = localStorage.getItem(scriptChatStorageKey(project, chapter));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return sanitizeChatMessages(parsed);
  } catch {
    return [];
  }
}

export function saveScriptChatHistory(project, chapter, history) {
  localStorage.setItem(scriptChatStorageKey(project, chapter), JSON.stringify(history));
}

export function clearScriptChatHistory(project, chapter) {
  localStorage.removeItem(scriptChatStorageKey(project, chapter));
}

// Same move-not-overwrite behavior as renameChatHistoriesEntry, for the
// script-chat key.
export function renameScriptChatHistory(project, oldChapter, newChapter) {
  const raw = localStorage.getItem(scriptChatStorageKey(project, oldChapter));
  if (raw === null) return;
  localStorage.removeItem(scriptChatStorageKey(project, oldChapter));
  localStorage.setItem(scriptChatStorageKey(project, newChapter), raw);
}

function projectChatStorageKey(project) {
  return `fishaudio_project_chat_history:${project}`;
}

export function loadProjectChatHistory(project) {
  const raw = localStorage.getItem(projectChatStorageKey(project));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return sanitizeChatMessages(parsed);
  } catch {
    return [];
  }
}

export function saveProjectChatHistory(project, history) {
  localStorage.setItem(projectChatStorageKey(project), JSON.stringify(history));
}

export function clearProjectChatHistory(project) {
  localStorage.removeItem(projectChatStorageKey(project));
}

// Deleting a project leaves every chapter's chat-history keys behind
// otherwise (project/chapter names never contain ":", see sanitize_name(),
// so a trailing ":" makes each prefix collision-free against similarly
// named projects) — a later project with the same name would silently
// resurrect old, unrelated chat histories. See docs/FIXES.md.
export function clearAllChatHistoriesForProject(project) {
  const prefixes = [
    `fishaudio_chat_histories:${project}:`,
    `fishaudio_script_chat_history:${project}:`,
  ];
  const keysToRemove = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      keysToRemove.push(key);
    }
  }
  // Collected first, removed after: removeItem() during the loop above would
  // shift every later key's index, silently skipping entries.
  keysToRemove.forEach((key) => localStorage.removeItem(key));
  clearProjectChatHistory(project);
}

