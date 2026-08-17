import { t } from "./i18n.js";
import { TAGS, fetchTags, insertAtCursor } from "./shared.js";
import { clearAllChatHistories, restoreChatHistories } from "./overlays/chat-overlay.js";
import { setScriptChatHistory } from "./overlays/script-chat-overlay.js";
import { openSkillsFilesOverlay } from "./overlays/skills-files-overlay.js";
import { openProjectChatOverlay, setProjectChatHistory } from "./overlays/project-chat-overlay.js";
import { openVoicesOverlay } from "./overlays/voices-overlay.js";
import { closeAllOverlays } from "./overlays/overlay-chrome.js";
import { loadProjects, updateProjectUI, updateExplorerCardVisibility, saveCurrentChapter } from "./dialog-projects.js";
import {
  getCurrentProject,
  getCurrentChapterName,
  getLastFocusedTextarea,
  setDialogStatus,
  setProjectContext,
  setVoiceNamesCache,
} from "./dialog-context.js";
import {
  addDialogBox,
  clearBoxesOnly,
  collectBoxesDraftData,
  endPauseMsInput,
  pauseMsInput,
  refreshAllVoiceSelects,
  renderPauseConnectors,
} from "./dialog-boxes.js";
import { resetCombinedOutput } from "./dialog-combined.js";
import { clearChatHistoriesEntry, loadChatHistories, loadScriptChatHistory, saveProjectChatHistory } from "./chat-history-storage.js";


export { setProjectContext };

const tabButtons = document.querySelectorAll(".tab-button");
const tabContents = document.querySelectorAll(".tab-content");

const SINGLE_UNLOCK_KEY = "fishaudio_unlock_single";
if (localStorage.getItem(SINGLE_UNLOCK_KEY) === "true") {
  document.getElementById("single-coming-soon-overlay")?.classList.remove("active");
  document.getElementById("single-content")?.removeAttribute("inert");
}

for (const button of tabButtons) {
  button.addEventListener("click", () => {
    for (const btn of tabButtons) btn.classList.remove("active");
    for (const content of tabContents) content.classList.remove("active");
    button.classList.add("active");
    document.getElementById(`tab-${button.dataset.tab}`).classList.add("active");
    updateExplorerCardVisibility();
  });
}

const dialogTagList = document.getElementById("dialog-tag-list");
const clearDialogBtn = document.getElementById("clear-dialog-btn");
const clearAllChatsBtn = document.getElementById("clear-all-chats-btn");
const collapseAllBtn = document.getElementById("collapse-all-btn");
const collapseAllBottomBtn = document.getElementById("collapse-all-btn-bottom");
const expandAllBtn = document.getElementById("expand-all-btn");
const expandAllBottomBtn = document.getElementById("expand-all-btn-bottom");
const jumpToStartBtn = document.getElementById("jump-to-start-btn");
const jumpToEndBtn = document.getElementById("jump-to-end-btn");
const dialogBoxesContainer = document.getElementById("dialog-boxes");
const addBoxBtn = document.getElementById("add-box-btn");
const insertBoxTopBtn = document.getElementById("insert-box-top-btn");

const DIALOG_DRAFT_KEY = "fishaudio_dialog_draft";

export function collectDialogDraft() {
  return {
    boxes: collectBoxesDraftData(),
    pauseMs: pauseMsInput.value,
    endPauseMs: endPauseMsInput.value,
  };
}

const DRAFT_SAVE_DEBOUNCE_MS = 400;
let draftSaveTimer = null;

// Debounced: called on every keystroke/slider-tick/knob-drag-move across the
// dialog boxes. Without this, each of those events synchronously scans the
// whole box DOM (collectBoxesDraftData) and writes to localStorage. See
// docs/FIXES.md.
export function saveDialogDraft() {
  clearTimeout(draftSaveTimer);
  draftSaveTimer = setTimeout(() => {
    localStorage.setItem(DIALOG_DRAFT_KEY, JSON.stringify(collectDialogDraft()));
  }, DRAFT_SAVE_DEBOUNCE_MS);
}

function loadDialogDraft() {
  const raw = localStorage.getItem(DIALOG_DRAFT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function loadDialogTags() {
  for (const tag of TAGS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-button";
    button.textContent = `[${tag}]`;
    button.addEventListener("click", () => {
      const target = getLastFocusedTextarea();
      if (target) {
        insertAtCursor(target, `[${tag}] `);
      }
    });
    dialogTagList.appendChild(button);
  }
}

const collapseAll = () => {
  for (const box of dialogBoxesContainer.querySelectorAll(".dialog-box")) {
    box.dataset.collapsed = "true";
  }
  saveDialogDraft();
};

const expandAll = () => {
  for (const box of dialogBoxesContainer.querySelectorAll(".dialog-box")) {
    box.dataset.collapsed = "false";
  }
  saveDialogDraft();
};

collapseAllBtn.addEventListener("click", collapseAll);
if (collapseAllBottomBtn) collapseAllBottomBtn.addEventListener("click", collapseAll);
expandAllBtn.addEventListener("click", expandAll);
if (expandAllBottomBtn) expandAllBottomBtn.addEventListener("click", expandAll);

jumpToStartBtn.addEventListener("click", () => {
  const firstBox = dialogBoxesContainer.querySelector(".dialog-box");
  if (firstBox) firstBox.scrollIntoView({ behavior: "smooth", block: "start" });
});

jumpToEndBtn.addEventListener("click", () => {
  const boxes = dialogBoxesContainer.querySelectorAll(".dialog-box");
  const lastBox = boxes[boxes.length - 1];
  if (lastBox) lastBox.scrollIntoView({ behavior: "smooth", block: "start" });
});

clearDialogBtn.addEventListener("click", async () => {
  if (!confirm(t("confirmClearDialog"))) return;

  const project = getCurrentProject();
  const chapter = getCurrentChapterName();
  if (project && chapter) {
    // Wipe box + combined audio (and their variants) on the backend too --
    // otherwise the old files are still on disk and reappear as soon as the
    // chapter is reloaded (see docs/FIXES.md).
    await fetch(
      `/projects/${encodeURIComponent(project)}/chapters/${encodeURIComponent(chapter)}/clear-audio`,
      { method: "POST" },
    );
  }

  clearBoxesOnly();
  pauseMsInput.value = "400";
  resetCombinedOutput();
  setDialogStatus("", "idle");
  addDialogBox();
  saveDialogDraft();

  if (project && chapter) {
    await saveCurrentChapter({ silent: true });
  }
});

clearAllChatsBtn.addEventListener("click", () => {
  if (!confirm(t("confirmClearAllChats"))) return;
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  clearAllChatHistories(boxes);
  if (getCurrentProject() && getCurrentChapterName()) {
    clearChatHistoriesEntry(getCurrentProject(), getCurrentChapterName());
  }
});

addBoxBtn.addEventListener("click", () => {
  addDialogBox();
  saveDialogDraft();
});

insertBoxTopBtn.addEventListener("click", async () => {
  addDialogBox({}, dialogBoxesContainer.firstElementChild);
  saveDialogDraft();
  // Sync immediately: every later box just shifted one position down on the
  // server too, and the new (empty) box would otherwise inherit whatever
  // box previously sat at its array index. See docs/FIXES.md.
  await saveCurrentChapter({ silent: true });
});

async function initDialogTab() {
  try {
    const response = await fetch("/voices");
    if (!response.ok) throw new Error(t("errorStatusCode", response.status));
    setVoiceNamesCache(await response.json());
  } catch (error) {
    setVoiceNamesCache([]);
    setDialogStatus(t("errorLoadingVoices", error.message), "error");
  }
  await fetchTags();
  loadDialogTags();
  await loadProjects();
  updateProjectUI();

  if (getCurrentProject() && getCurrentChapterName()) {
    const draft = loadDialogDraft();
    if (draft && Array.isArray(draft.boxes) && draft.boxes.length > 0) {
      if (draft.pauseMs) {
        pauseMsInput.value = draft.pauseMs;
      }
      if (draft.endPauseMs) {
        endPauseMsInput.value = draft.endPauseMs;
      }
      for (const savedBox of draft.boxes) {
        addDialogBox(savedBox);
      }
    } else {
      addDialogBox();
    }

    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    restoreChatHistories(
      boxes,
      loadChatHistories(getCurrentProject(), getCurrentChapterName()),
    );
    setScriptChatHistory(loadScriptChatHistory(getCurrentProject(), getCurrentChapterName()));
  }

  renderPauseConnectors();
}

initDialogTab();
loadSkillsFilesExplorer();

const backToLandingLink = document.getElementById("back-to-landing-link");
backToLandingLink.addEventListener("click", () => {
  closeAllOverlays();
  localStorage.removeItem("fishaudio_skip_landing");
});

let skillsFilesOverlayHandle = null;

function openOrFocusSkillsFilesOverlay(initialPath, initialIsNote = false) {
  if (skillsFilesOverlayHandle) {
    skillsFilesOverlayHandle.bringToFront();
    skillsFilesOverlayHandle.loadFileList();
    if (initialPath) skillsFilesOverlayHandle.openFile(initialPath, initialIsNote);
    return;
  }
  skillsFilesOverlayHandle = openSkillsFilesOverlay({
    t,
    initialPath,
    initialIsNote,
    getProject: getCurrentProject,
    onClosed: () => {
      skillsFilesOverlayHandle = null;
    },
    onFilesChanged: loadSkillsFilesExplorer,
  });
}

const skillsFilesBtn = document.getElementById("skills-files-btn");
skillsFilesBtn.addEventListener("click", () => openOrFocusSkillsFilesOverlay());

let projectChatOverlayHandle = null;

export function openOrFocusProjectChatOverlay() {
  if (!getCurrentProject()) {
    alert(t("projectChatNeedProject"));
    return;
  }
  if (projectChatOverlayHandle) {
    projectChatOverlayHandle.bringToFront();
    return;
  }
  projectChatOverlayHandle = openProjectChatOverlay({
    t,
    chatUrl: (project) => `/projects/${encodeURIComponent(project)}/chat`,
    getProject: getCurrentProject,
    onHistoryChanged: (history) => {
      saveProjectChatHistory(getCurrentProject(), history);
    },
    onMessageComplete: () => {
      loadSkillsFilesExplorer();
      if (skillsFilesOverlayHandle) skillsFilesOverlayHandle.loadFileList();
    },
    onClosed: () => {
      projectChatOverlayHandle = null;
    },
  });
}

const projectChatBtn = document.getElementById("project-chat-btn");
projectChatBtn.addEventListener("click", () => openOrFocusProjectChatOverlay());


let voicesOverlayHandle = null;

function openOrFocusVoicesOverlay() {
  if (voicesOverlayHandle) {
    voicesOverlayHandle.bringToFront();
    return;
  }
  voicesOverlayHandle = openVoicesOverlay({
    t,
    onClosed: () => {
      voicesOverlayHandle = null;
    },
    onVoicesChanged: refreshAllVoiceSelects,
  });
}

const voicesBtn = document.getElementById("voices-btn");
voicesBtn.addEventListener("click", () => openOrFocusVoicesOverlay());

function renderSkillsFilesGroup(list, titleKey, files) {
  const title = document.createElement("div");
  title.className = "skills-files-group-title";
  title.textContent = t(titleKey);
  list.appendChild(title);

  for (const file of files) {
    const row = document.createElement("div");
    row.className = "explorer-row explorer-row-clickable";

    const name = document.createElement("span");
    name.className = "explorer-row-name";
    name.textContent = file.name;
    row.appendChild(name);

    row.addEventListener("click", () => openOrFocusSkillsFilesOverlay(file.path, file.isNote));
    list.appendChild(row);
  }
}

export async function loadSkillsFilesExplorer() {
  const list = document.getElementById("skills-files-explorer-list");
  if (!list) return;
  list.innerHTML = "";

  const currentProject = getCurrentProject();

  // Same two-section split (Memories / Skills) as the skills-files overlay's
  // own loadFileList() -- this sidebar list previously flattened both into
  // one undivided list. See docs/FIXES.md.
  if (currentProject) {
    const notesResp = await fetch(`/projects/${encodeURIComponent(currentProject)}/notes`);
    const notes = notesResp.ok ? await notesResp.json() : [];
    renderSkillsFilesGroup(
      list,
      "skillsFilesSectionProjectNotes",
      notes.map((f) => ({ ...f, isNote: true }))
    );
  }

  const skillsResp = await fetch("/skills-files");
  const skills = skillsResp.ok ? await skillsResp.json() : [];
  renderSkillsFilesGroup(
    list,
    "skillsFilesSectionSkills",
    skills.map((f) => ({ ...f, isNote: false }))
  );
}

