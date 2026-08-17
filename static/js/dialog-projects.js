import { t } from "./i18n.js";
import { reorderChapters } from "./shared.js";
import {
  addDialogBox,
  buildBoxDownloadFilename,
  clearBoxesOnly,
  endPauseMsInput,
  getActiveBoxBlob,
  pauseMsInput,
  refreshOverviewIfVisible,
  renderPauseConnectors,
  setLoadedBoxBlob,
  setLoadedBoxVariants,
  updateLoudnessLabel,
} from "./dialog-boxes.js";
import {
  combinedDownloadLink,
  combinedPlayer,
  getCombinedAudioBlob,
  renderCombinedVariantsList,
  resetCombinedOutput,
  setCombinedAudioBlob,
} from "./dialog-combined.js";
import { setDialogStatus, setProjectContext } from "./dialog-context.js";
import { refreshScriptFromBoxes } from "./dialog-script-mode.js";
import { collectDialogDraft, loadSkillsFilesExplorer } from "./dialog.js";
import {
  clearAllChatHistoriesForProject,
  clearChatHistoriesEntry,
  clearScriptChatHistory,
  loadChatHistories,
  loadProjectChatHistory,
  loadScriptChatHistory,
  renameChatHistoriesEntry,
  renameScriptChatHistory,
} from "./chat-history-storage.js";
import { restoreChatHistories } from "./overlays/chat-overlay.js";
import { closeAllOverlays } from "./overlays/overlay-chrome.js";
import { setScriptChatHistory } from "./overlays/script-chat-overlay.js";
import { openOrFocusProjectChatOverlay } from "./dialog.js";
import { setProjectChatHistory } from "./overlays/project-chat-overlay.js";

export const toggleExplorerBtn = document.getElementById("toggle-explorer-btn");
export const projectSelect = document.getElementById("project-select");
export const newProjectBtn = document.getElementById("new-project-btn");
export const renameProjectBtn = document.getElementById("rename-project-btn");
export const deleteProjectBtn = document.getElementById("delete-project-btn");
export const projectChatPanelBtn = document.getElementById("project-chat-panel-btn");

export const newProjectForm = document.getElementById("new-project-form");
export const newProjectNameInput = document.getElementById("new-project-name");
export const confirmNewProjectBtn = document.getElementById("confirm-new-project-btn");
export const renameProjectForm = document.getElementById("rename-project-form");
export const renameProjectNameInput = document.getElementById("rename-project-name");
export const confirmRenameProjectBtn = document.getElementById("confirm-rename-project-btn");
export const chapterChips = document.getElementById("chapter-chips");
export const chapterExplorer = document.getElementById("chapter-explorer");
export const newChapterForm = document.getElementById("new-chapter-form");
export const newChapterNameInput = document.getElementById("new-chapter-name");
export const confirmNewChapterBtn = document.getElementById("confirm-new-chapter-btn");
export const saveChapterBtn = document.getElementById("save-chapter-btn");
export const cleanupVariantsBtn = document.getElementById("cleanup-variants-btn");
export const saveChapterConfirmation = document.getElementById("save-chapter-confirmation");
export const dialogWorkspaceMain = document.getElementById("dialog-workspace-main");
export const dialogTagPanel = document.getElementById("dialog-tag-panel");

const dialogBoxesContainer = document.getElementById("dialog-boxes");

let saveConfirmationTimer = null;
let currentProject = "";
let currentChapter = "";
let draggedChapterName = null;
let explorerManuallyHidden = false;
let latestChaptersFetchId = 0;
let latestExplorerFetchId = 0;

export function updateExplorerCardVisibility() {
  const isDialogTab = document.querySelector('.tab-button[data-tab="dialog"]').classList.contains("active");
  const explorerCard = document.getElementById("dialog-explorer-card");
  if (explorerCard) {
    explorerCard.hidden = !(isDialogTab && currentProject && !explorerManuallyHidden);
  }

  const skillsFilesCard = document.getElementById("skills-files-explorer-card");
  if (skillsFilesCard) {
    skillsFilesCard.hidden = !(isDialogTab && currentProject && !explorerManuallyHidden);
  }
}

async function persistChapterOrder(order) {
  await fetch(`/projects/${encodeURIComponent(currentProject)}/chapter-order`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  });
  await loadChapterChips();
}

export async function loadExplorerPanel() {
  if (!currentProject) {
    chapterExplorer.innerHTML = "";
    return;
  }

  const fetchId = ++latestExplorerFetchId;
  const response = await fetch(`/projects/${encodeURIComponent(currentProject)}/chapters-with-audio`);
  const chapters = response.ok ? await response.json() : [];

  if (fetchId !== latestExplorerFetchId) {
    return;
  }

  chapterExplorer.innerHTML = "";
  if (chapters.length === 0) {
    chapterExplorer.textContent = t("noChaptersYet");
    return;
  }

  const controlsRow = document.createElement("div");
  controlsRow.className = "explorer-controls-row";

  const playAllBtn = document.createElement("button");
  playAllBtn.type = "button";
  playAllBtn.className = "explorer-play-all-btn";
  playAllBtn.textContent = "▶";
  playAllBtn.title = t("playAllExplorer");
  controlsRow.appendChild(playAllBtn);

  const downloadAllLink = document.createElement("a");
  downloadAllLink.className = "explorer-download-all-btn download-btn";
  downloadAllLink.download = `${currentProject}.zip`;
  downloadAllLink.textContent = "⬇";
  downloadAllLink.title = t("downloadAllExplorer");
  controlsRow.appendChild(downloadAllLink);

  const downloadAllMp3Checkbox = document.createElement("input");
  downloadAllMp3Checkbox.type = "checkbox";
  downloadAllMp3Checkbox.id = "download-all-mp3-checkbox";
  downloadAllMp3Checkbox.className = "explorer-download-all-mp3-checkbox";

  const downloadAllMp3Label = document.createElement("label");
  downloadAllMp3Label.htmlFor = "download-all-mp3-checkbox";
  downloadAllMp3Label.className = "explorer-download-all-mp3-label";
  downloadAllMp3Label.textContent = t("downloadAllMp3Label");

  function updateDownloadAllHref() {
    const audioFormat = downloadAllMp3Checkbox.checked ? "mp3" : "wav";
    downloadAllLink.href = `/projects/${encodeURIComponent(currentProject)}/download-all?audio_format=${audioFormat}`;
  }
  downloadAllMp3Checkbox.addEventListener("change", updateDownloadAllHref);
  updateDownloadAllHref();

  controlsRow.appendChild(downloadAllMp3Checkbox);
  controlsRow.appendChild(downloadAllMp3Label);

  chapterExplorer.appendChild(controlsRow);

  const players = [];
  let sequencePlaying = false;
  let sequenceIndex = -1;

  function stopSequence() {
    sequencePlaying = false;
    if (sequenceIndex >= 0 && sequenceIndex < players.length) {
      players[sequenceIndex].pause();
    }
    sequenceIndex = -1;
    playAllBtn.textContent = "▶";
    playAllBtn.title = t("playAllExplorer");
  }

  function playNextInSequence() {
    sequenceIndex += 1;
    if (sequenceIndex >= players.length) {
      stopSequence();
      return;
    }
    players[sequenceIndex].play();
  }

  playAllBtn.addEventListener("click", () => {
    if (sequencePlaying) {
      stopSequence();
      return;
    }
    if (players.length === 0) return;
    sequencePlaying = true;
    playAllBtn.textContent = "■";
    playAllBtn.title = t("stopAllExplorer");
    sequenceIndex = -1;
    playNextInSequence();
  });

  for (const { name, has_combined_audio } of chapters) {
    const row = document.createElement("div");
    row.className = "explorer-row";

    const label = document.createElement("span");
    label.className = "explorer-row-name";
    label.textContent = name;
    row.appendChild(label);

    if (has_combined_audio) {
      const audioUrl = `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(name)}/combined-audio?t=${Date.now()}`;

      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "metadata";
      player.src = audioUrl;
      player.addEventListener("ended", () => {
        if (sequencePlaying) playNextInSequence();
      });
      row.appendChild(player);
      players.push(player);

      const downloadLink = document.createElement("a");
      downloadLink.className = "download-btn";
      downloadLink.href = audioUrl;
      downloadLink.download = `${currentProject}_${name}_${new Date().toISOString().slice(0, 10)}.wav`;
      downloadLink.textContent = t("download");
      row.appendChild(downloadLink);
    } else {
      const empty = document.createElement("span");
      empty.className = "explorer-row-empty";
      empty.textContent = t("noCombinedAudio");
      row.appendChild(empty);
    }

    chapterExplorer.appendChild(row);
  }

  if (players.length === 0) {
    playAllBtn.hidden = true;
    downloadAllLink.hidden = true;
  }
}

function startChapterRename(nameSpan, oldName, chapters) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "chapter-chip-rename-input";
  input.value = oldName;
  nameSpan.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;

  const cancel = () => {
    if (settled) return;
    settled = true;
    input.replaceWith(nameSpan);
  };

  const commit = () => {
    if (settled) return;
    settled = true;
    confirmChapterRename(oldName, input.value, chapters, cancel);
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") commit();
    if (event.key === "Escape") cancel();
  });
  input.addEventListener("blur", () => cancel());
}

async function confirmChapterRename(oldName, rawNewName, chapters, cancel) {
  const newName = rawNewName.trim();
  if (!newName || newName === oldName) {
    cancel();
    return;
  }

  if (chapters.includes(newName) && !confirm(t("confirmOverwriteChapter", newName))) {
    cancel();
    return;
  }

  await fetch(
    `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(oldName)}/rename`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName }),
    },
  );

  renameChatHistoriesEntry(currentProject, oldName, newName);
  renameScriptChatHistory(currentProject, oldName, newName);

  if (currentChapter === oldName) {
    currentChapter = newName;
    setProjectContext(currentProject, newName);
  }
  await loadChapterChips();
  updateProjectUI();
}

async function loadChapterChips() {
  if (!currentProject) {
    chapterChips.innerHTML = "";
    await loadExplorerPanel();
    return;
  }

  const fetchId = ++latestChaptersFetchId;
  const response = await fetch(`/projects/${encodeURIComponent(currentProject)}/chapters`);
  const chapters = response.ok ? await response.json() : [];

  if (fetchId !== latestChaptersFetchId) {
    return;
  }

  chapterChips.innerHTML = "";
  for (const name of chapters) {
    const chip = document.createElement("span");
    chip.className = "chapter-chip" + (name === currentChapter ? " active" : "");
    const nameSpan = document.createElement("span");
    nameSpan.className = "chapter-chip-name";
    nameSpan.textContent = name;
    chip.appendChild(nameSpan);
    chip.draggable = true;
    chip.addEventListener("click", () => selectChapter(name));

    chip.addEventListener("dragstart", () => {
      draggedChapterName = name;
      chip.classList.add("dragging");
    });
    chip.addEventListener("dragend", () => {
      chip.classList.remove("dragging");
      draggedChapterName = null;
    });
    chip.addEventListener("dragover", (event) => {
      event.preventDefault();
      chip.classList.add("drag-over");
    });
    chip.addEventListener("dragleave", () => {
      chip.classList.remove("drag-over");
    });
    chip.addEventListener("drop", async (event) => {
      event.preventDefault();
      chip.classList.remove("drag-over");
      if (!draggedChapterName || draggedChapterName === name) return;
      await persistChapterOrder(reorderChapters(chapters, draggedChapterName, name));
    });

    const renameBtn = document.createElement("span");
    renameBtn.className = "chapter-chip-rename";
    renameBtn.textContent = "✎";
    renameBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      startChapterRename(nameSpan, name, chapters);
    });
    chip.appendChild(renameBtn);

    const deleteBtn = document.createElement("span");
    deleteBtn.className = "chapter-chip-delete";
    deleteBtn.textContent = "✕";
    deleteBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (!confirm(t("confirmDeleteChapter", name))) return;
      await fetch(
        `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(name)}`,
        { method: "DELETE" },
      );
      clearChatHistoriesEntry(currentProject, name);
      clearScriptChatHistory(currentProject, name);
      if (currentChapter === name) {
        currentChapter = "";
        setProjectContext(currentProject, "");
        clearBoxesOnly();
        resetCombinedOutput();
        addDialogBox();
        pauseMsInput.value = "400";
        renderPauseConnectors();
      }
      loadChapterChips();
      updateProjectUI();
    });
    chip.appendChild(deleteBtn);

    chapterChips.appendChild(chip);
  }

  const newChip = document.createElement("span");
  newChip.className = "chapter-chip";
  newChip.textContent = "+ Kapitel";
  newChip.addEventListener("click", () => {
    newChapterForm.hidden = false;
    newChapterNameInput.value = "";
    newChapterNameInput.focus();
  });
  newChip.addEventListener("dragover", (event) => {
    event.preventDefault();
    newChip.classList.add("drag-over");
  });
  newChip.addEventListener("dragleave", () => {
    newChip.classList.remove("drag-over");
  });
  newChip.addEventListener("drop", async (event) => {
    event.preventDefault();
    newChip.classList.remove("drag-over");
    if (!draggedChapterName) return;
    await persistChapterOrder(reorderChapters(chapters, draggedChapterName, null));
  });
  chapterChips.appendChild(newChip);
  await loadExplorerPanel();
}

async function selectChapter(name) {
  const response = await fetch(
    `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(name)}`,
  );
  if (!response.ok) return;
  const data = await response.json();

  clearBoxesOnly();
  resetCombinedOutput();
  pauseMsInput.value = data.pause_ms || 400;
  endPauseMsInput.value = data.end_pause_ms || 0;

  // Must run before addDialogBox() below: renderVariantsList() (called from
  // within addDialogBox() for boxes with saved variants) needs an active
  // project+chapter context to build each variant's audio URL. Setting this
  // after the loop left every variant <audio> without a src at all.
  currentChapter = name;
  setProjectContext(currentProject, name);

  for (const savedBox of data.boxes) {
    addDialogBox(savedBox);
  }
  renderPauseConnectors();

  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));

  restoreChatHistories(boxes, loadChatHistories(currentProject, name));
  setScriptChatHistory(loadScriptChatHistory(currentProject, name));
  loadChapterChips();
  updateProjectUI();

  // Parallel, not sequential: each box's audio is an independent request
  // touching only that box's own DOM nodes / WeakMap entry, so there's no
  // shared state to race on. See docs/FIXES.md.
  await Promise.all(
    boxes.map(async (box, i) => {
      const audioUrl = `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(name)}/audio/${i}?t=${Date.now()}`;
      const audioResponse = await fetch(audioUrl);
      if (!audioResponse.ok) return;

      const blob = await audioResponse.blob();
      const player = box.querySelector(".dialog-box-player");
      const downloadLink = box.querySelector(".dialog-box-download");
      // Network URL, not a Blob URL: Blob-sourced WAV audio has a known
      // Chromium quirk where duration doesn't display until a seek/play
      // happens. The network route already supports Range requests
      // (FileResponse, routers/projects.py), so duration shows immediately,
      // same as the per-box variant rows (dialog-boxes.js's renderVariantsList).
      player.src = audioUrl;
      downloadLink.href = audioUrl;
      downloadLink.download = buildBoxDownloadFilename(box);
      downloadLink.hidden = false;
      setLoadedBoxBlob(box, blob);
      updateLoudnessLabel(box, blob);
    })
  );

  const combinedUrl = `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(name)}/combined-audio?t=${Date.now()}`;
  const combinedResponse = await fetch(combinedUrl);
  if (combinedResponse.ok) {
    const combinedBlob = await combinedResponse.blob();
    combinedPlayer.src = combinedUrl;
    combinedDownloadLink.href = combinedUrl;
    combinedDownloadLink.download = `${currentProject}_${name}_${new Date().toISOString().slice(0, 10)}.wav`;
    combinedDownloadLink.hidden = false;
    setCombinedAudioBlob(combinedBlob);
  }

  renderCombinedVariantsList(
    data.combinedVariants,
    data.activeCombinedIndex,
    data.combinedVariantLocks || {},
    data.combinedVariantLabels || {}
  );

  refreshOverviewIfVisible();
  refreshScriptFromBoxes();
}

export async function saveCurrentChapter({ silent = false } = {}) {
  if (!currentProject || !currentChapter) return;
  const draft = collectDialogDraft();
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));

  const formData = new FormData();
  formData.append("boxes", JSON.stringify(draft.boxes));
  formData.append("pause_ms", String(Number(draft.pauseMs) || 400));
  formData.append("end_pause_ms", String(Number(draft.endPauseMs) || 0));

  const clipIndices = [];
  boxes.forEach((box, index) => {
    const blob = getActiveBoxBlob(box);
    if (blob) {
      formData.append("clips", blob, `clip_${index}.wav`);
      clipIndices.push(index);
    }
  });
  formData.append("clip_indices", JSON.stringify(clipIndices));

  const combinedBlob = getCombinedAudioBlob();
  if (combinedBlob) {
    formData.append("combined_clip", combinedBlob, "combined.wav");
  }

  await fetch(
    `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(currentChapter)}`,
    {
      method: "PUT",
      body: formData,
    },
  );

  await loadChapterChips();

  if (silent) return;

  saveChapterConfirmation.hidden = false;
  if (saveConfirmationTimer) {
    clearTimeout(saveConfirmationTimer);
  }
  saveConfirmationTimer = setTimeout(() => {
    saveChapterConfirmation.hidden = true;
    saveConfirmationTimer = null;
  }, 1800);
}

export function updateProjectUI() {
  const hasActiveContext = !!(currentProject && currentChapter);
  dialogWorkspaceMain.hidden = !hasActiveContext;
  dialogTagPanel.hidden = !hasActiveContext;

  saveChapterBtn.hidden = !hasActiveContext;
  cleanupVariantsBtn.hidden = !hasActiveContext;
  if (hasActiveContext) {
    saveChapterBtn.textContent = t("saveChapterNamed", currentChapter);
  }
  deleteProjectBtn.hidden = !currentProject;
  renameProjectBtn.hidden = !currentProject;
  projectChatPanelBtn.hidden = !currentProject;

  if (toggleExplorerBtn) {
    toggleExplorerBtn.disabled = !currentProject;
  }
  updateExplorerCardVisibility();
  loadSkillsFilesExplorer();
  setProjectChatHistory(currentProject ? loadProjectChatHistory(currentProject) : []);
}


// #project-select has a fixed max-width (see explorer-and-projects.css) so
// long project names don't push the buttons next to it around. CSS
// text-overflow: ellipsis on a closed <select> isn't reliably clipped by
// every browser though -- the selected option's text can render past the
// box's own boundary instead of being cut off (reported by Danny: text
// still overlapped the buttons after the max-width fix). Truncating the
// option's actual text content sidesteps that entirely, since it's real
// string truncation rather than a CSS visual effect the browser might not
// honor. The full, untruncated name is kept in option.dataset.fullName and
// shown via a title tooltip on hover -- see docs/FIXES.md.
const PROJECT_NAME_DISPLAY_MAX_LENGTH = 16;

function truncateProjectNameForDisplay(name) {
  return name.length > PROJECT_NAME_DISPLAY_MAX_LENGTH
    ? `${name.slice(0, PROJECT_NAME_DISPLAY_MAX_LENGTH - 1)}…`
    : name;
}

function setProjectOptionName(option, name) {
  option.dataset.fullName = name;
  option.textContent = truncateProjectNameForDisplay(name);
}

function updateProjectSelectTitle() {
  projectSelect.title = projectSelect.options[projectSelect.selectedIndex]?.dataset.fullName || "";
}

export async function loadProjects() {
  const previousValue = projectSelect.value;
  projectSelect.innerHTML = `<option value="" data-i18n="noProject">${t("noProject")}</option>`;

  let names;
  try {
    const response = await fetch("/projects");
    if (!response.ok) throw new Error(t("errorStatusCode", response.status));
    names = await response.json();
  } catch (error) {
    setDialogStatus(t("errorLoadingProjects", error.message), "error");
    return;
  }

  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    setProjectOptionName(option, name);
    projectSelect.appendChild(option);
  }
  projectSelect.value = names.includes(previousValue) ? previousValue : "";
  updateProjectSelectTitle();
}

if (toggleExplorerBtn) {
  toggleExplorerBtn.addEventListener("click", () => {
    explorerManuallyHidden = !explorerManuallyHidden;
    updateExplorerCardVisibility();
  });
}

saveChapterBtn.addEventListener("click", saveCurrentChapter);

cleanupVariantsBtn.addEventListener("click", async () => {
  if (!currentProject || !currentChapter) return;
  if (!confirm(t("confirmCleanupVariants"))) return;
  
  const response = await fetch(
    `/projects/${encodeURIComponent(currentProject)}/chapters/${encodeURIComponent(currentChapter)}/cleanup-variants`,
    { method: "POST" }
  );
  if (response.ok) {
    await selectChapter(currentChapter);
  }
});

projectSelect.addEventListener("change", async () => {
  closeAllOverlays();
  updateProjectSelectTitle();
  currentProject = projectSelect.value;
  currentChapter = "";
  setProjectContext(currentProject, "");
  setScriptChatHistory([]);
  clearBoxesOnly();
  resetCombinedOutput();
  addDialogBox();
  pauseMsInput.value = "400";
  renderPauseConnectors();
  await loadChapterChips();
  updateProjectUI();
});

newProjectBtn.addEventListener("click", () => {
  newProjectForm.hidden = false;
  newProjectNameInput.value = "";
  newProjectNameInput.focus();
});

confirmNewProjectBtn.addEventListener("click", async () => {
  const name = newProjectNameInput.value.trim();
  if (!name) return;

  const existingResponse = await fetch("/projects");
  const existing = await existingResponse.json();
  if (existing.includes(name) && !confirm(t("confirmUseExistingProject", name))) {
    return;
  }

  closeAllOverlays();
  newProjectForm.hidden = true;
  currentProject = name;
  currentChapter = "";
  setProjectContext(name, "");

  if (!existing.includes(name)) {
    const option = document.createElement("option");
    option.value = name;
    setProjectOptionName(option, name);
    projectSelect.appendChild(option);
  }
  projectSelect.value = name;
  updateProjectSelectTitle();

  await loadChapterChips();
  updateProjectUI();
});

renameProjectBtn.addEventListener("click", () => {
  if (!currentProject) return;
  renameProjectForm.hidden = false;
  renameProjectNameInput.value = currentProject;
  renameProjectNameInput.focus();
  renameProjectNameInput.select();
});

confirmRenameProjectBtn.addEventListener("click", async () => {
  const newName = renameProjectNameInput.value.trim();
  if (!newName || newName === currentProject) {
    renameProjectForm.hidden = true;
    return;
  }

  const response = await fetch(
    `/projects/${encodeURIComponent(currentProject)}/rename`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName }),
    },
  );

  if (!response.ok) {
    if (response.status === 409) {
      alert(t("renameProjectNameTaken", newName));
    }
    return;
  }

  renameProjectForm.hidden = true;

  const option = Array.from(projectSelect.options).find((o) => o.value === currentProject);
  if (option) {
    option.value = newName;
    setProjectOptionName(option, newName);
  }
  projectSelect.value = newName;
  updateProjectSelectTitle();

  currentProject = newName;
  setProjectContext(newName, currentChapter);
  updateProjectUI();
});

confirmNewChapterBtn.addEventListener("click", async () => {
  const name = newChapterNameInput.value.trim();
  if (!name || !currentProject) return;

  const existingResponse = await fetch(`/projects/${encodeURIComponent(currentProject)}/chapters`);
  const existing = existingResponse.ok ? await existingResponse.json() : [];
  const isOverwrite = existing.includes(name);
  if (isOverwrite && !confirm(t("confirmOverwriteChapter", name))) {
    return;
  }

  newChapterForm.hidden = true;
  // Reset to a single blank box for a genuinely new chapter name -- but not
  // when overwriting an existing one, since "overwrite" deliberately means
  // "save whatever is currently in the editor under this name" (a save-as
  // flow). The old `if (currentChapter)` check tested the wrong thing: it
  // skipped the reset whenever no chapter was active yet -- exactly the
  // case of a brand-new project's first chapter -- so stale boxes left over
  // from a previously viewed project/chapter reappeared instead of a clean
  // slate. See docs/FIXES.md.
  if (!isOverwrite) {
    clearBoxesOnly();
    resetCombinedOutput();
    addDialogBox();
    pauseMsInput.value = "400";
    renderPauseConnectors();
  }

  currentChapter = name;
  setProjectContext(currentProject, name);
  await saveCurrentChapter();
  await loadChapterChips();
  updateProjectUI();
});

deleteProjectBtn.addEventListener("click", async () => {
  if (!currentProject) return;
  if (!confirm(t("confirmDeleteProject", currentProject))) return;
  await fetch(`/projects/${encodeURIComponent(currentProject)}`, { method: "DELETE" });
  clearAllChatHistoriesForProject(currentProject);
  closeAllOverlays();
  currentProject = "";
  currentChapter = "";
  setProjectContext("", "");
  clearBoxesOnly();
  resetCombinedOutput();
  addDialogBox();
  pauseMsInput.value = "400";
  renderPauseConnectors();
  await loadProjects();
  await loadChapterChips();
  updateProjectUI();
});

projectChatPanelBtn.addEventListener("click", () => openOrFocusProjectChatOverlay());

export function getCurrentChapter() {

  return currentChapter;
}
