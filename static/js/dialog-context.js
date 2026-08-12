let currentProject = "";
let currentChapter = "";

export function setProjectContext(project, chapter) {
  currentProject = project;
  currentChapter = chapter;
}

export function getCurrentProject() {
  return currentProject;
}

export function getCurrentChapterName() {
  return currentChapter;
}

const dialogStatusEl = document.getElementById("dialog-status");

export function setDialogStatus(text, state) {
  dialogStatusEl.textContent = text;
  dialogStatusEl.className = `status status-${state}`;
}

let lastFocusedBoxTextarea = null;

export function getLastFocusedTextarea() {
  return lastFocusedBoxTextarea;
}

export function setLastFocusedTextarea(el) {
  lastFocusedBoxTextarea = el;
}

let voiceNamesCache = [];

export function getVoiceNamesCache() {
  return voiceNamesCache;
}

export function setVoiceNamesCache(names) {
  voiceNamesCache = names;
}
