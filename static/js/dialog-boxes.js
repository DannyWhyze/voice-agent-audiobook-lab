import { t, applyTranslations } from "./i18n.js";
import {
  attachWaveform,
  connectToGain,
  measureLoudnessDb,
  getVoiceAccentColor,
} from "./shared.js";
import { openCompressorOverlay } from "./overlays/compressor-overlay.js";
import { openReverbOverlay } from "./overlays/reverb-overlay.js";
import { openTrimOverlay } from "./overlays/trim-fade-overlay.js";
import { openChatOverlay } from "./overlays/chat-overlay.js";
import { removeChatHistoriesEntry, saveChatHistoriesEntry } from "./chat-history-storage.js";
import { openEqOverlay } from "./overlays/eq-overlay.js";
import { openRecordOverlay } from "./overlays/record-overlay.js";
import { openNormalizeOverlay } from "./overlays/normalize-overlay.js";
import { openPitchOverlay } from "./overlays/pitch-overlay.js";
import { openFormantOverlay } from "./overlays/formant-overlay.js";
import { openDelayOverlay } from "./overlays/delay-overlay.js";
import {
  getCurrentProject,
  getCurrentChapterName,
  getVoiceNamesCache,
  setDialogStatus,
  setLastFocusedTextarea,
  setVoiceNamesCache,
} from "./dialog-context.js";
import { refreshScriptFromBoxes } from "./dialog-script-mode.js";
import { enqueueGeneration } from "./dialog-queue.js";
import { saveDialogDraft } from "./dialog.js";
import { saveCurrentChapter } from "./dialog-projects.js";

const dialogBoxesContainer = document.getElementById("dialog-boxes");
const boxTemplate = document.getElementById("dialog-box-template");
const dialogOverviewPanel = document.getElementById("dialog-overview-panel");
const toggleOverviewBtn = document.getElementById("toggle-overview-btn");

export const pauseMsInput = document.getElementById("pause-ms");
pauseMsInput.addEventListener("input", () => {
  for (const box of dialogBoxesContainer.querySelectorAll(".dialog-box")) {
    if (box.dataset.pauseLocked === "true") continue;
    box.dataset.pauseAfterMs = pauseMsInput.value || "400";
  }
  saveDialogDraft();
  renderPauseConnectors();
});

export const endPauseMsInput = document.getElementById("end-pause-ms");
const endPauseConnector = document.getElementById("end-pause-connector");
endPauseMsInput.addEventListener("input", () => {
  saveDialogDraft();
});

const boxAudioBlobs = new WeakMap();
const boxRawLoudnessDb = new WeakMap();
const boxGainNodes = new WeakMap();
const openBoxOverlays = new WeakMap();

function openOrFocusBoxOverlay(box, effectType, openFn) {
  let boxMap = openBoxOverlays.get(box);
  if (!boxMap) {
    boxMap = new Map();
    openBoxOverlays.set(box, boxMap);
  }
  const existing = boxMap.get(effectType);
  if (existing) {
    existing.bringToFront();
    return;
  }
  const handle = openFn(() => boxMap.delete(effectType));
  boxMap.set(effectType, handle);
}

export function applyVoiceAccent(box, voiceName) {
  const color = getVoiceAccentColor(voiceName);
  if (color) {
    box.style.setProperty("--speaker-accent", color);
  } else {
    box.style.removeProperty("--speaker-accent");
  }
}

export function updateSpeakerLabel(box, voiceName) {
  const speakerLabel = box.querySelector(".dialog-box-speaker");
  speakerLabel.style.color = getVoiceAccentColor(voiceName) || "";
  speakerLabel.textContent = voiceName || t("noVoice");
}

function isRecordingVariant(data, filename) {
  if (!filename) return false;
  if (variantSuffixFromFilename(filename) === "recorded") return true;
  return !!(data && data.recordingLineage && data.recordingLineage[filename]);
}

export function updateBoxSpeakerHeader(box) {
  const speakerLabel = box.querySelector(".dialog-box-speaker");
  const recordedNameWrap = box.querySelector(".dialog-box-recorded-name-wrap");
  const recordedNameInput = box.querySelector(".dialog-box-recorded-name-input");
  const data = boxAudioBlobs.get(box);
  const activeItem = data && data.activeIndex >= 0 ? data.variants[data.activeIndex] : null;
  const filename = activeItem?.filename;
  const isRecording = isRecordingVariant(data, filename);

  if (isRecording) {
    speakerLabel.hidden = true;
    recordedNameWrap.hidden = false;
    if (document.activeElement !== recordedNameInput) {
      recordedNameInput.value = (data.variantLabels && data.variantLabels[filename]) || "";
    }
  } else {
    speakerLabel.hidden = false;
    recordedNameWrap.hidden = true;
    const voiceSelect = box.querySelector(".dialog-box-voice");
    updateSpeakerLabel(box, voiceSelect.value);
  }
}

export function getBoxSpeakerName(box) {
  const data = boxAudioBlobs.get(box);
  const activeItem = data && data.activeIndex >= 0 ? data.variants[data.activeIndex] : null;
  const filename = activeItem?.filename;
  const isRecording = isRecordingVariant(data, filename);
  if (isRecording) {
    const label = (data.variantLabels && data.variantLabels[filename]) || "";
    if (label) return label;
  }
  return box.querySelector(".dialog-box-voice").value;
}

export function setBoxRecordedName(box, name) {
  const data = boxAudioBlobs.get(box);
  const activeItem = data && data.activeIndex >= 0 ? data.variants[data.activeIndex] : null;
  const filename = activeItem?.filename;
  const isRecording = isRecordingVariant(data, filename);
  if (!isRecording) return false;
  data.variantLabels = data.variantLabels || {};
  data.variantLabels[filename] = name;
  updateBoxSpeakerHeader(box);
  return true;
}

export function buildBoxDownloadFilename(box) {
  const boxIndex = Array.from(document.querySelectorAll(".dialog-box")).indexOf(box);
  const project = getCurrentProject() || t("noProject");
  const chapter = getCurrentChapterName() || t("noProject");

  const data = boxAudioBlobs.get(box);
  const activeItem = data && data.activeIndex >= 0 ? data.variants[data.activeIndex] : null;
  const filename = activeItem?.filename;

  let speaker;
  if (isRecordingVariant(data, filename)) {
    speaker = (data.variantLabels && data.variantLabels[filename]) || t("variantLabelRecorded");
  } else {
    speaker = box.querySelector(".dialog-box-voice").value || t("noVoice");
  }

  const art = filename && data
    ? deriveVariantLabel(filename, data.variants, data.activeIndex)
    : t("variantLabelOriginal");

  const date = new Date().toISOString().slice(0, 10);

  return [`Box${boxIndex + 1}`, project, chapter, speaker, date, art].join("_") + ".wav";
}

function renderLoudnessLabel(box) {
  const rawDb = boxRawLoudnessDb.get(box);
  if (rawDb === undefined) return;

  const loudnessEl = box.querySelector(".dialog-box-loudness");
  if (rawDb === null) {
    loudnessEl.textContent = t("noLoudnessMeasured");
    return;
  }

  const gainDb = Number(box.querySelector(".dialog-box-volume").value);
  loudnessEl.textContent = gainDb === 0
    ? t("measuredLoudness", rawDb.toFixed(1))
    : t("measuredLoudnessWithGain", rawDb.toFixed(1), (rawDb + gainDb).toFixed(1));
}

export function updateLoudnessLabel(box, blob) {
  measureLoudnessDb(blob).then((db) => {
    boxRawLoudnessDb.set(box, db);
    renderLoudnessLabel(box);
  });
}

export function populateVoiceSelect(select) {
  const noneOption = document.createElement("option");
  noneOption.value = "";
  noneOption.dataset.i18n = "noVoice";
  noneOption.textContent = t("noVoice");
  select.appendChild(noneOption);

  for (const name of getVoiceNamesCache()) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
}

export async function refreshAllVoiceSelects(rename) {
  const response = await fetch("/voices");
  if (!response.ok) return;
  setVoiceNamesCache(await response.json());

  for (const box of document.querySelectorAll(".dialog-box")) {
    const select = box.querySelector(".dialog-box-voice");
    let previousValue = select.value;
    if (rename && previousValue === rename.oldName) {
      previousValue = rename.newName;
    }
    select.innerHTML = "";
    populateVoiceSelect(select);
    select.value = previousValue;
  }
}

export function getActiveBoxBlob(box) {
  const data = boxAudioBlobs.get(box);
  if (!data || data.activeIndex < 0) return undefined;
  return data.variants[data.activeIndex]?.blob;
}

export function setLoadedBoxBlob(box, blob, filename = "") {
  let data = boxAudioBlobs.get(box);
  if (!data) {
    data = { variants: [{ blob: blob, filename: filename }], activeIndex: 0 };
    boxAudioBlobs.set(box, data);
  } else {
    const activeIdx = data.activeIndex >= 0 ? data.activeIndex : 0;
    if (data.variants[activeIdx]) {
      data.variants[activeIdx].blob = blob;
      if (filename && !data.variants[activeIdx].filename) {
        data.variants[activeIdx].filename = filename;
      }
    } else {
      data.variants[activeIdx] = { blob: blob, filename: filename };
    }
  }
}

export function setLoadedBoxVariants(box, variants, activeIndex, compressorParams, reverbParams, eqParams, variantLabels, normalizeParams, pitchParams, formantParams, variantLocks, delayParams, recordingLineage) {
  boxAudioBlobs.set(box, {
    variants: (variants || []).map((f) => ({ blob: null, filename: f })),
    activeIndex: activeIndex !== undefined ? activeIndex : -1,
    compressorParams: compressorParams || null,
    reverbParams: reverbParams || null,
    eqParams: eqParams || null,
    variantLabels: variantLabels || {},
    normalizeParams: normalizeParams || null,
    pitchParams: pitchParams || null,
    formantParams: formantParams || null,
    variantLocks: variantLocks || {},
    delayParams: delayParams || null,
    recordingLineage: recordingLineage || {},
  });
}

export function getBoxCompressorParams(box) {
  return boxAudioBlobs.get(box)?.compressorParams || null;
}

export function getBoxReverbParams(box) {
  return boxAudioBlobs.get(box)?.reverbParams || null;
}

export function getBoxEqParams(box) {
  return boxAudioBlobs.get(box)?.eqParams || null;
}

export function getBoxPitchParams(box) {
  return boxAudioBlobs.get(box)?.pitchParams || null;
}

export function getBoxFormantParams(box) {
  return boxAudioBlobs.get(box)?.formantParams || null;
}

export function getBoxDelayParams(box) {
  return boxAudioBlobs.get(box)?.delayParams || null;
}

export function getBoxNormalizeParams(box) {
  return boxAudioBlobs.get(box)?.normalizeParams || null;
}


export function appendBoxVariants(box, newItems) {
  let data = boxAudioBlobs.get(box);
  if (!data) {
    data = { variants: [], activeIndex: -1, variantLabels: {}, variantLocks: {}, recordingLineage: {} };
    boxAudioBlobs.set(box, data);
  }
  const hadActive = data.activeIndex >= 0;
  const firstNewIndex = data.variants.length;
  data.variants.push(...newItems);
  return { hadActive, firstNewIndex, variantCount: data.variants.length };
}

// context, if given, overrides the live project/chapter/box-index lookup —
// used by dialog-queue.js's background generation path, where the box may
// already be detached from a different chapter by the time this runs (see
// its comment, and docs/FIXES.md). Every other call site (variant button
// clicks, delete fallback) omits it and keeps the original live-lookup
// behavior.
export async function activateVariant(box, index, context = null) {
  const data = boxAudioBlobs.get(box);
  if (!data || !data.variants[index]) return;
  data.activeIndex = index;
  const item = data.variants[index];

  const project = context?.project ?? getCurrentProject();
  const chapter = context?.chapter ?? getCurrentChapterName();

  if (item.filename && project && chapter) {
    const boxIndex = box.isConnected
      ? Array.from(document.querySelectorAll(".dialog-box")).indexOf(box)
      : context?.boxIndex;
    await fetch(
      `/projects/${encodeURIComponent(project)}/chapters/${encodeURIComponent(chapter)}/boxes/${boxIndex}/variants/${encodeURIComponent(item.filename)}/activate`,
      { method: "PUT" }
    );

    const audioResponse = await fetch(
      `/projects/${encodeURIComponent(project)}/chapters/${encodeURIComponent(chapter)}/audio/${boxIndex}?t=${Date.now()}`
    );
    if (audioResponse.ok) {
      item.blob = await audioResponse.blob();
    }
  }

  const blob = item.blob;
  const player = box.querySelector(".dialog-box-player");
  const downloadLink = box.querySelector(".dialog-box-download");
  if (player.src) {
    URL.revokeObjectURL(player.src);
  }
  if (blob) {
    player.src = URL.createObjectURL(blob);
    downloadLink.href = player.src;
    downloadLink.download = buildBoxDownloadFilename(box);
    downloadLink.hidden = false;
    updateLoudnessLabel(box, blob);
  } else {
    player.removeAttribute("src");
    player.load();
    downloadLink.hidden = true;
  }

  renderVariantsList(box);
  saveDialogDraft();
}

const VARIANT_SUFFIX_LABEL_KEYS = {
  compressed: "variantLabelCompressed",
  reverb: "variantLabelReverb",
  eq: "variantLabelEq",
  trimmed: "variantLabelTrimmed",
  faded: "variantLabelFaded",
  recorded: "variantLabelRecorded",
  normalized: "variantLabelNormalized",
  pitch_shifted: "variantLabelPitchShifted",
  formant_shifted: "variantLabelFormantShifted",
  delay: "variantLabelDelay",
};

export function variantSuffixFromFilename(filename) {
  const match = filename.match(/_variant_\d+(?:_([a-z_]+))?\.wav$/);
  return match ? match[1] || null : null;
}

export function deriveVariantLabel(filename, allVariants, index) {
  const suffix = variantSuffixFromFilename(filename);
  const baseLabel = suffix
    ? t(VARIANT_SUFFIX_LABEL_KEYS[suffix] || "variantLabelOriginal")
    : t("variantLabelOriginal");

  let occurrence = 0;
  for (let i = 0; i <= index; i++) {
    if (variantSuffixFromFilename(allVariants[i].filename) === suffix) {
      occurrence++;
    }
  }

  let totalOccurrences = 0;
  for (const item of allVariants) {
    if (variantSuffixFromFilename(item.filename) === suffix) {
      totalOccurrences++;
    }
  }

  return totalOccurrences > 1 ? `${baseLabel} ${occurrence}` : baseLabel;
}

function openSaveAsVoiceForm(box, row, item, audioPreviewEl) {
  const controls = row.querySelector(".dialog-box-variant-controls");
  controls.hidden = true;

  const form = document.createElement("div");
  form.className = "dialog-box-save-voice-form";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "dialog-box-save-voice-name-input";
  nameInput.placeholder = t("saveAsVoiceNamePlaceholder");
  form.appendChild(nameInput);

  const textInput = document.createElement("textarea");
  textInput.className = "dialog-box-save-voice-text-input";
  textInput.value = box.querySelector(".dialog-box-text").value;
  form.appendChild(textInput);

  const errorLabel = document.createElement("div");
  errorLabel.className = "dialog-box-save-voice-error";
  errorLabel.hidden = true;
  form.appendChild(errorLabel);

  const actionRow = document.createElement("div");
  actionRow.className = "dialog-box-save-voice-actions";
  form.appendChild(actionRow);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "pause-connector-insert-btn";
  saveBtn.textContent = t("saveAsVoiceSaveBtn");
  actionRow.appendChild(saveBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "pause-connector-insert-btn";
  cancelBtn.textContent = t("saveAsVoiceCancelBtn");
  actionRow.appendChild(cancelBtn);

  function closeForm() {
    form.remove();
    controls.hidden = false;
  }
  cancelBtn.addEventListener("click", closeForm);

  saveBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (!name) return;
    errorLabel.hidden = true;
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    try {
      const audioBlob = item.blob || (await (await fetch(audioPreviewEl.src)).blob());
      const formData = new FormData();
      formData.append("name", name);
      formData.append("text", textInput.value);
      formData.append("audio", audioBlob, "voice.wav");
      const response = await fetch("/voices", { method: "POST", body: formData });
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        errorLabel.textContent = errorBody.detail || t("saveAsVoiceError");
        errorLabel.hidden = false;
        return;
      }
      await refreshAllVoiceSelects();
      closeForm();
    } catch (error) {
      errorLabel.textContent = t("saveAsVoiceError");
      errorLabel.hidden = false;
    } finally {
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  });

  row.appendChild(form);
}

export function renderVariantsList(box) {
  const container = box.querySelector(".dialog-box-variants");
  for (const audioEl of container.querySelectorAll("audio")) {
    if (audioEl.src && audioEl.src.startsWith("blob:")) {
      URL.revokeObjectURL(audioEl.src);
    }
  }
  container.innerHTML = "";

  const data = boxAudioBlobs.get(box);
  updateBoxSpeakerHeader(box);
  if (!data || data.variants.length < 1) {
    container.hidden = true;
    return;
  }
  container.hidden = false;

  data.selectedVariants = data.selectedVariants || new Set();

  if (data.variants.length > 1) {
    const bulkBar = document.createElement("div");
    bulkBar.className = "dialog-box-variants-bulk-bar";

    const bulkDeleteBtn = document.createElement("button");
    bulkDeleteBtn.type = "button";
    bulkDeleteBtn.className = "pause-connector-insert-btn";
    bulkDeleteBtn.textContent = t("deleteSelectedVariantsBtn");
    bulkDeleteBtn.disabled = data.selectedVariants.size === 0;
    bulkDeleteBtn.addEventListener("click", () => deleteSelectedVariants(box));
    bulkBar.appendChild(bulkDeleteBtn);

    container.appendChild(bulkBar);
  }

  data.variants.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "dialog-box-variant-row";

    const isLocked = !!(data.variantLocks || {})[item.filename];
    if (isLocked) {
      data.selectedVariants.delete(item);
    }

    const preview = document.createElement("audio");
    preview.controls = true;
    preview.preload = "metadata";
    if (item.blob) {
      preview.src = URL.createObjectURL(item.blob);
    } else if (getCurrentProject() && getCurrentChapterName()) {
      const boxes = Array.from(document.querySelectorAll(".dialog-box"));
      const boxIndex = boxes.indexOf(box);
      preview.src = `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants/${encodeURIComponent(item.filename)}`;
    }
    const boxGainNode = boxGainNodes.get(box);
    if (boxGainNode) {
      connectToGain(preview, boxGainNode);
    }
    row.appendChild(preview);

    const controls = document.createElement("div");
    controls.className = "dialog-box-variant-controls";
    row.appendChild(controls);

    const selectCheckbox = document.createElement("input");
    selectCheckbox.type = "checkbox";
    selectCheckbox.className = "dialog-box-variant-select-checkbox";
    selectCheckbox.title = t("variantSelectCheckboxTitle");
    selectCheckbox.checked = data.selectedVariants.has(item);
    selectCheckbox.disabled = isLocked;
    selectCheckbox.addEventListener("change", () => {
      if (selectCheckbox.checked) {
        data.selectedVariants.add(item);
      } else {
        data.selectedVariants.delete(item);
      }
      renderVariantsList(box);
    });
    controls.appendChild(selectCheckbox);

    const labelSpan = document.createElement("span");
    labelSpan.className = "dialog-box-variant-label";
    labelSpan.textContent = data.variantLabels[item.filename] || deriveVariantLabel(item.filename, data.variants, index);
    controls.appendChild(labelSpan);

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "dialog-box-variant-rename-btn pause-connector-insert-btn";
    renameBtn.textContent = "✎";
    renameBtn.title = t("variantRenameBtnTitle");
    renameBtn.addEventListener("click", () => {
      const input = document.createElement("input");
      input.type = "text";
      input.className = "dialog-box-variant-label-input";
      input.value = data.variantLabels[item.filename] || "";
      input.placeholder = deriveVariantLabel(item.filename, data.variants, index);

      function commit() {
        const value = input.value.trim();
        if (value) {
          data.variantLabels[item.filename] = value;
        } else {
          delete data.variantLabels[item.filename];
        }
        saveDialogDraft();
        renderVariantsList(box);
      }

      input.addEventListener("blur", commit);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") input.blur();
      });

      controls.replaceChild(input, labelSpan);
      input.focus();
      input.select();
    });
    controls.appendChild(renameBtn);

    if (index === data.activeIndex) {
      const activeLabel = document.createElement("span");
      activeLabel.className = "dialog-box-variant-active-label";
      activeLabel.textContent = t("variantActive");
      controls.appendChild(activeLabel);
    } else {
      const activateBtn = document.createElement("button");
      activateBtn.type = "button";
      activateBtn.className = "dialog-box-variant-activate-btn pause-connector-insert-btn";
      activateBtn.textContent = t("variantMakeActive");
      activateBtn.addEventListener("click", () => activateVariant(box, index));
      controls.appendChild(activateBtn);
    }

    const saveVoiceBtn = document.createElement("button");
    saveVoiceBtn.type = "button";
    saveVoiceBtn.className = "dialog-box-variant-save-voice-btn pause-connector-insert-btn";
    saveVoiceBtn.textContent = "💾";
    saveVoiceBtn.title = t("saveAsVoiceBtnTitle");
    saveVoiceBtn.addEventListener("click", () => openSaveAsVoiceForm(box, row, item, preview));
    controls.appendChild(saveVoiceBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "dialog-box-variant-delete-btn pause-connector-insert-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.disabled = isLocked;
    deleteBtn.title = isLocked ? t("variantLockedTooltip") : "";
    deleteBtn.addEventListener("click", () => deleteVariant(box, index));

    const lockBtn = document.createElement("button");
    lockBtn.type = "button";
    lockBtn.className = "dialog-box-variant-lock-btn pause-connector-insert-btn";
    lockBtn.textContent = isLocked ? "🔒" : "🔓";
    lockBtn.title = t("variantLockBtnTitle");
    lockBtn.addEventListener("click", () => {
      data.variantLocks = data.variantLocks || {};
      if (data.variantLocks[item.filename]) {
        delete data.variantLocks[item.filename];
      } else {
        data.variantLocks[item.filename] = true;
      }
      saveDialogDraft();
      renderVariantsList(box);
    });
    controls.appendChild(lockBtn);
    controls.appendChild(deleteBtn);

    container.appendChild(row);
  });
}

async function deleteVariant(box, index) {
  const data = boxAudioBlobs.get(box);
  if (!data) return;
  if ((data.variantLocks || {})[data.variants[index]?.filename]) return;
  if (!confirm(t("confirmDeleteVariant"))) return;

  const item = data.variants[index];
  const wasActive = index === data.activeIndex;

  if (item.filename && getCurrentProject() && getCurrentChapterName()) {
    const boxes = Array.from(document.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);
    await fetch(
      `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants/${encodeURIComponent(item.filename)}`,
      { method: "DELETE" }
    );
  }

  data.variants.splice(index, 1);

  if (data.variants.length === 0) {
    boxAudioBlobs.delete(box);
    const player = box.querySelector(".dialog-box-player");
    const downloadLink = box.querySelector(".dialog-box-download");
    if (player.src) {
      URL.revokeObjectURL(player.src);
    }
    player.removeAttribute("src");
    player.load();
    downloadLink.hidden = true;
    box.querySelector(".dialog-box-loudness").textContent = "";
    renderVariantsList(box);
    saveDialogDraft();
    return;
  }

  if (wasActive) {
    await activateVariant(box, data.variants.length - 1);
    return;
  }

  if (index < data.activeIndex) {
    data.activeIndex -= 1;
  }
  renderVariantsList(box);
  saveDialogDraft();
}

async function deleteVariantItems(box, items) {
  const data = boxAudioBlobs.get(box);
  if (!data || items.length === 0) return;

  const activeItem = data.variants[data.activeIndex];

  if (getCurrentProject() && getCurrentChapterName()) {
    const boxes = Array.from(document.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);
    // Sequential, not Promise.all: delete_box_variant() (variants.py) does an
    // unsynchronized read-modify-write of chapter.json (load, remove this one
    // filename from its own in-memory copy, save). Concurrent DELETE requests
    // each read chapter.json before the other has written back, so whichever
    // finishes last silently overwrites the other's removal — the variant's
    // audio file is gone from disk, but its entry survives in chapter.json
    // and reappears as an empty placeholder next time the box's variant list
    // is reloaded from the server (e.g. after any effect apply). See
    // docs/FIXES.md.
    for (const item of items) {
      if (!item.filename) continue;
      await fetch(
        `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants/${encodeURIComponent(item.filename)}`,
        { method: "DELETE" }
      );
    }
  }

  const toDelete = new Set(items);
  data.variants = data.variants.filter((item) => !toDelete.has(item));
  if (data.selectedVariants) {
    data.selectedVariants = new Set([...data.selectedVariants].filter((item) => !toDelete.has(item)));
  }

  if (data.variants.length === 0) {
    boxAudioBlobs.delete(box);
    const player = box.querySelector(".dialog-box-player");
    const downloadLink = box.querySelector(".dialog-box-download");
    if (player.src) {
      URL.revokeObjectURL(player.src);
    }
    player.removeAttribute("src");
    player.load();
    downloadLink.hidden = true;
    box.querySelector(".dialog-box-loudness").textContent = "";
    renderVariantsList(box);
    saveDialogDraft();
    return;
  }

  if (!data.variants.includes(activeItem)) {
    await activateVariant(box, data.variants.length - 1);
    return;
  }

  data.activeIndex = data.variants.indexOf(activeItem);
  renderVariantsList(box);
  saveDialogDraft();
}

async function deleteSelectedVariants(box) {
  const data = boxAudioBlobs.get(box);
  if (!data || !data.selectedVariants || data.selectedVariants.size === 0) return;

  const selected = data.variants.filter((item) => data.selectedVariants.has(item));
  if (selected.length === 0) return;
  if (!confirm(t("confirmDeleteVariants", selected.length))) return;

  await deleteVariantItems(box, selected);
}

async function clearBoxAudio(box) {
  const data = boxAudioBlobs.get(box);
  if (!data || data.variants.length === 0) return;

  const deletable = data.variants.filter((item) => !(data.variantLocks || {})[item.filename]);
  if (deletable.length === 0) return;
  if (!confirm(t("confirmClearAudio"))) return;

  await deleteVariantItems(box, deletable);
}

function clearBoxText(box) {
  const textarea = box.querySelector(".dialog-box-text");
  if (!textarea.value) return;
  if (!confirm(t("confirmClearText"))) return;

  textarea.value = "";
  saveDialogDraft();
  refreshOverviewIfVisible();
  refreshScriptFromBoxes();
}

export function renderPauseConnectors() {
  for (const connector of dialogBoxesContainer.querySelectorAll(".pause-connector")) {
    connector.remove();
  }

  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  for (let i = 0; i < boxes.length - 1; i++) {
    const box = boxes[i];
    const connector = document.createElement("div");
    connector.className = "pause-connector";

    const input = document.createElement("input");
    input.type = "number";
    input.className = "pause-connector-input";
    input.min = "0";
    input.value = box.dataset.pauseAfterMs || pauseMsInput.value || "400";
    input.addEventListener("input", () => {
      box.dataset.pauseAfterMs = input.value || "400";
      saveDialogDraft();
    });
    connector.appendChild(input);

    const suffix = document.createElement("span");
    suffix.textContent = t("pauseConnectorSuffix");
    connector.appendChild(suffix);

    const lockBtn = document.createElement("button");
    lockBtn.type = "button";
    lockBtn.className = "pause-connector-insert-btn";
    lockBtn.title = t("pauseLockTitle");
    lockBtn.textContent = box.dataset.pauseLocked === "true" ? "🔒" : "🔓";
    lockBtn.addEventListener("click", () => {
      box.dataset.pauseLocked = box.dataset.pauseLocked === "true" ? "false" : "true";
      lockBtn.textContent = box.dataset.pauseLocked === "true" ? "🔒" : "🔓";
      saveDialogDraft();
    });
    connector.appendChild(lockBtn);

    const insertBtn = document.createElement("button");
    insertBtn.type = "button";
    insertBtn.className = "pause-connector-insert-btn";
    insertBtn.textContent = "+";
    insertBtn.title = t("insertBoxHere");
    insertBtn.addEventListener("click", async () => {
      addDialogBox({}, boxes[i + 1]);
      saveDialogDraft();
      // Sync immediately: every later box just shifted one position down on
      // the server too, and the new (empty) box would otherwise inherit
      // whatever box previously sat at its array index. See docs/FIXES.md.
      await saveCurrentChapter({ silent: true });
    });
    connector.appendChild(insertBtn);

    box.insertAdjacentElement("afterend", connector);
  }

  if (boxes.length > 0) {
    endPauseConnector.hidden = false;
    boxes[boxes.length - 1].insertAdjacentElement("afterend", endPauseConnector);
  } else {
    endPauseConnector.hidden = true;
  }
}

function renderDialogOverview() {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  if (boxes.length === 0) {
    dialogOverviewPanel.textContent = t("noBoxes");
    return;
  }

  dialogOverviewPanel.innerHTML = "";
  for (const box of boxes) {
    const voice = box.querySelector(".dialog-box-voice").value;
    const speakerName = getBoxSpeakerName(box);
    const text = box.querySelector(".dialog-box-text").value;
    const accent = getVoiceAccentColor(voice);

    const line = document.createElement("p");
    const label = document.createElement("span");
    label.className = "dialog-overview-label";
    label.style.color = accent || "";
    label.textContent = speakerName || t("noVoice");
    line.appendChild(label);
    line.appendChild(document.createTextNode(": " + text));
    dialogOverviewPanel.appendChild(line);
  }
}

export function refreshOverviewIfVisible() {
  if (!dialogOverviewPanel.hidden) {
    renderDialogOverview();
  }
}

export function buildScriptOverviewText() {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  return boxes
    .map((box) => {
      const speakerName = getBoxSpeakerName(box);
      const text = box.querySelector(".dialog-box-text").value;
      return `${speakerName || t("noVoice")}: ${text}`;
    })
    .join("\n");
}

toggleOverviewBtn.addEventListener("click", () => {
  dialogOverviewPanel.hidden = !dialogOverviewPanel.hidden;
  if (!dialogOverviewPanel.hidden) {
    renderDialogOverview();
  }
});

dialogBoxesContainer.addEventListener("input", refreshOverviewIfVisible);
dialogBoxesContainer.addEventListener("change", refreshOverviewIfVisible);

document.addEventListener("click", () => {
  document.querySelectorAll(".dialog-box-menu-dropdown").forEach((el) => (el.hidden = true));
});

export function addDialogBox(initial = {}, insertBeforeBox = null) {
  const fragment = boxTemplate.content.cloneNode(true);
  const box = fragment.querySelector(".dialog-box");
  const textarea = box.querySelector(".dialog-box-text");
  const voiceSelect = box.querySelector(".dialog-box-voice");
  const previewBtn = box.querySelector(".dialog-box-voice-preview-btn");
  const previewPlayer = box.querySelector(".dialog-box-voice-preview-player");
  const removeBtn = box.querySelector(".remove-box-btn");
  const menuBtn = box.querySelector(".dialog-box-menu-btn");
  const menuDropdown = box.querySelector(".dialog-box-menu-dropdown");
  const menuClearTextBtn = box.querySelector(".dialog-box-menu-clear-text");
  const menuClearAudioBtn = box.querySelector(".dialog-box-menu-clear-audio");
  const generateBtn = box.querySelector(".dialog-box-generate-btn");
  const variantCountInput = box.querySelector(".dialog-box-variant-count");
  const volumeSlider = box.querySelector(".dialog-box-volume");
  const volumeValueLabel = box.querySelector(".dialog-box-volume-value");
  const panKnob = box.querySelector(".dialog-box-pan-knob");
  const panValueLabel = box.querySelector(".dialog-box-pan-value");
  const compressorBtn = box.querySelector(".dialog-box-compressor-btn");
  const reverbBtn = box.querySelector(".dialog-box-reverb-btn");
  const delayBtn = box.querySelector(".dialog-box-delay-btn");
  const eqBtn = box.querySelector(".dialog-box-eq-btn");
  const trimBtn = box.querySelector(".dialog-box-trim-btn");
  const chatBtn = box.querySelector(".dialog-box-chat-btn");
  const recordBtn = box.querySelector(".dialog-box-record-btn");
  const normalizeBtn = box.querySelector(".dialog-box-normalize-btn");
  const pitchBtn = box.querySelector(".dialog-box-pitch-btn");
  const formantBtn = box.querySelector(".dialog-box-formant-btn");
  const header = box.querySelector(".dialog-box-header");

  populateVoiceSelect(voiceSelect);

  const player = box.querySelector(".dialog-box-player");
  const waveformCanvas = box.querySelector(".dialog-box-waveform");
  const meterMaskEl = box.querySelector(".dialog-box-level-meter-mask");

  const { gainNode, pannerNode } = attachWaveform(player, waveformCanvas, meterMaskEl);
  boxGainNodes.set(box, gainNode);

  if (initial.text) {
    textarea.value = initial.text;
  }
  if (initial.voice) {
    voiceSelect.value = initial.voice;
  }
  applyVoiceAccent(box, voiceSelect.value);
  updateSpeakerLabel(box, voiceSelect.value);
  previewBtn.disabled = !voiceSelect.value;

  const recordedNameInput = box.querySelector(".dialog-box-recorded-name-input");
  recordedNameInput.addEventListener("click", (event) => event.stopPropagation());
  recordedNameInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") recordedNameInput.blur();
  });
  recordedNameInput.addEventListener("blur", () => {
    const data = boxAudioBlobs.get(box);
    if (!data) return;
    const activeItem = data.activeIndex >= 0 ? data.variants[data.activeIndex] : null;
    const filename = activeItem?.filename;
    if (!filename) return;
    const value = recordedNameInput.value.trim();
    data.variantLabels = data.variantLabels || {};
    if (value) {
      data.variantLabels[filename] = value;
    } else {
      delete data.variantLabels[filename];
    }
    saveDialogDraft();
    renderVariantsList(box);
  });

  box.dataset.collapsed = initial.collapsed ? "true" : "false";

  if (initial.volumeDb !== undefined) {
    volumeSlider.value = initial.volumeDb;
  }
  volumeValueLabel.textContent = `${volumeSlider.value} dB`;
  gainNode.gain.value = 10 ** (Number(volumeSlider.value) / 20);

  box.dataset.panValue = String(initial.panValue !== undefined ? initial.panValue : 0);
  pannerNode.pan.value = Number(box.dataset.panValue) / 100;

  function formatPanValue(value) {
    if (value === 0) return "C";
    return value < 0 ? `L${Math.abs(value)}` : `R${value}`;
  }

  function refreshPanKnob() {
    const value = Number(box.dataset.panValue);
    const angle = (value / 100) * 135;
    panKnob.querySelector(".compressor-knob-pointer").style.transform = `translateX(-50%) rotate(${angle}deg)`;
    panValueLabel.textContent = formatPanValue(value);
  }

  function setPanValue(newValue) {
    const clamped = Math.max(-100, Math.min(100, Math.round(newValue)));
    box.dataset.panValue = String(clamped);
    pannerNode.pan.value = clamped / 100;
    refreshPanKnob();
    saveDialogDraft();
  }

  refreshPanKnob();

  let panDragStartY = 0;
  let panDragStartValue = 0;
  const PAN_DRAG_RANGE_PX = 150;

  panKnob.addEventListener("pointerdown", (event) => {
    panKnob.setPointerCapture(event.pointerId);
    panKnob.classList.add("dragging");
    panDragStartY = event.clientY;
    panDragStartValue = Number(box.dataset.panValue);
    event.preventDefault();
  });

  panKnob.addEventListener("pointermove", (event) => {
    if (!panKnob.classList.contains("dragging")) return;
    const deltaY = panDragStartY - event.clientY;
    const fraction = deltaY / PAN_DRAG_RANGE_PX;
    setPanValue(panDragStartValue + fraction * 200);
  });

  function endPanDrag(event) {
    if (panKnob.classList.contains("dragging")) {
      panKnob.classList.remove("dragging");
      panKnob.releasePointerCapture(event.pointerId);
    }
  }
  panKnob.addEventListener("pointerup", endPanDrag);
  panKnob.addEventListener("pointercancel", endPanDrag);

  panKnob.addEventListener("dblclick", () => {
    setPanValue(0);
  });

  panKnob.addEventListener("keydown", (event) => {
    if (event.key === "ArrowUp" || event.key === "ArrowRight") {
      event.preventDefault();
      setPanValue(Number(box.dataset.panValue) + 5);
    } else if (event.key === "ArrowDown" || event.key === "ArrowLeft") {
      event.preventDefault();
      setPanValue(Number(box.dataset.panValue) - 5);
    }
  });

  box.dataset.pauseAfterMs = String(
    initial.pauseAfterMs !== undefined ? initial.pauseAfterMs : (pauseMsInput.value || "400"),
  );
  box.dataset.pauseLocked = initial.pauseLocked ? "true" : "false";

  if (initial.variants) {
    setLoadedBoxVariants(box, initial.variants, initial.activeIndex, initial.compressor_params, initial.reverb_params, initial.eq_params, initial.variantLabels, initial.normalize_params, initial.pitch_params, initial.formant_params, initial.variantLocks, initial.delay_params, initial.recordingLineage);
    renderVariantsList(box);
  }

  textarea.addEventListener("focus", () => {
    setLastFocusedTextarea(textarea);
  });
  textarea.addEventListener("input", () => {
    saveDialogDraft();
    refreshScriptFromBoxes();
  });
  textarea.addEventListener("change", refreshScriptFromBoxes);
  voiceSelect.addEventListener("change", () => {
    applyVoiceAccent(box, voiceSelect.value);
    updateBoxSpeakerHeader(box);
    saveDialogDraft();
    previewBtn.disabled = !voiceSelect.value;
    refreshScriptFromBoxes();
  });

  header.addEventListener("click", () => {
    box.dataset.collapsed = box.dataset.collapsed === "true" ? "false" : "true";
    saveDialogDraft();
  });
  volumeSlider.addEventListener("input", () => {
    const db = Number(volumeSlider.value);
    volumeValueLabel.textContent = `${db} dB`;
    gainNode.gain.value = 10 ** (db / 20);
    renderLoudnessLabel(box);
    saveDialogDraft();
  });

async function handleEffectApplied(box, applyResponse) {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  const boxIndex = boxes.indexOf(box);

  const dataBefore = boxAudioBlobs.get(box);
  const beforeActive = dataBefore && dataBefore.activeIndex >= 0 ? dataBefore.variants[dataBefore.activeIndex] : null;
  const beforeFilename = beforeActive?.filename;
  const beforeIsRecording = isRecordingVariant(dataBefore, beforeFilename);
  const beforeLabel = beforeIsRecording && dataBefore.variantLabels ? dataBefore.variantLabels[beforeFilename] : null;

  const response = await fetch(
    `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}`
  );
  if (!response.ok) return;
  const data = await response.json();
  const boxData = data.boxes[boxIndex];
  setLoadedBoxVariants(box, boxData.variants, boxData.activeIndex, boxData.compressor_params, boxData.reverb_params, boxData.eq_params, boxData.variantLabels, boxData.normalize_params, boxData.pitch_params, boxData.formant_params, boxData.variantLocks, boxData.delay_params, boxData.recordingLineage);

  // A recording carries no effect suffix of its own once an effect is applied on top of it
  // (add_box_variant() only ever writes the new effect's suffix, e.g. "reverb", not a chain) —
  // without this, the box header would silently drop back to the plain voice label/mic icon
  // the moment a recorded take gets trimmed/reverbed/etc. See docs/FIXES.md.
  if (beforeIsRecording) {
    const afterData = boxAudioBlobs.get(box);
    const afterActive = afterData.activeIndex >= 0 ? afterData.variants[afterData.activeIndex] : null;
    const afterFilename = afterActive?.filename;
    if (afterFilename && afterFilename !== beforeFilename) {
      afterData.recordingLineage[afterFilename] = true;
      if (beforeLabel && !afterData.variantLabels[afterFilename]) {
        afterData.variantLabels[afterFilename] = beforeLabel;
      }
    }
  }

  if (applyResponse) {
    const blob = await applyResponse.blob();
    setLoadedBoxBlob(box, blob);
    const player = box.querySelector(".dialog-box-player");
    const downloadLink = box.querySelector(".dialog-box-download");
    if (player.src) {
      URL.revokeObjectURL(player.src);
    }
    const objectUrl = URL.createObjectURL(blob);
    player.src = objectUrl;
    downloadLink.href = objectUrl;
    downloadLink.download = buildBoxDownloadFilename(box);
    downloadLink.hidden = false;
    updateLoudnessLabel(box, blob);
  }

  renderVariantsList(box);
  saveDialogDraft();
}

function wireBoxEffectButton({ btn, box, effectType, needProjectKey, routeSegment, openOverlay, getParams }) {
  btn.addEventListener("click", () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t(needProjectKey));
      return;
    }
    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);

    openOrFocusBoxOverlay(box, effectType, (onClosed) => openOverlay({
      t,
      project: getCurrentProject(),
      previewUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/${routeSegment}/preview`,
      applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/${routeSegment}/apply`,
      initialParams: getParams(box),
      onApplied: (applyResponse) => handleEffectApplied(box, applyResponse),
      onClosed,
    }));
  });
}

  wireBoxEffectButton({
    btn: compressorBtn,
    box,
    effectType: "compressor",
    needProjectKey: "compressorNeedProject",
    routeSegment: "compress",
    openOverlay: openCompressorOverlay,
    getParams: getBoxCompressorParams,
  });

  wireBoxEffectButton({
    btn: reverbBtn,
    box,
    effectType: "reverb",
    needProjectKey: "reverbNeedProject",
    routeSegment: "reverb",
    openOverlay: openReverbOverlay,
    getParams: getBoxReverbParams,
  });

  wireBoxEffectButton({
    btn: eqBtn,
    box,
    effectType: "eq",
    needProjectKey: "eqNeedProject",
    routeSegment: "eq",
    openOverlay: openEqOverlay,
    getParams: getBoxEqParams,
  });

  trimBtn.addEventListener("click", () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t("trimNeedProject"));
      return;
    }
    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);

    openOrFocusBoxOverlay(box, "trim", (onClosed) => openTrimOverlay({
      t,
      sourceUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/audio/${boxIndex}`,
      applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/trim/apply`,
      fadeApplyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/fade/apply`,
      onActivateVariant: (filename) =>
        fetch(
          `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants/${encodeURIComponent(filename)}/activate`,
          { method: "PUT" }
        ),
      onApplied: (applyResponse) => handleEffectApplied(box, applyResponse),
      onClosed,
    }));
  });

  chatBtn.addEventListener("click", () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t("chatNeedProject"));
      return;
    }
    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);
    const speakerLabel = box.querySelector(".dialog-box-speaker").textContent;

    openOrFocusBoxOverlay(box, "chat", (onClosed) => openChatOverlay({
      t,
      box,
      boxLabel: `Box ${boxIndex + 1} — ${speakerLabel}`,
      chatUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/chat`,
      getCurrentText: () => box.querySelector(".dialog-box-text").value,
      getScriptOverview: buildScriptOverviewText,
      onApply: (content) => {
        const textarea = box.querySelector(".dialog-box-text");
        textarea.value = content;
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      },
      onHistoryChanged: (history) => {
        saveChatHistoriesEntry(getCurrentProject(), getCurrentChapterName(), boxIndex, history);
      },
      onClosed,
    }));
  });

  recordBtn.addEventListener("click", () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t("recordNeedProject"));
      return;
    }
    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);

    openOrFocusBoxOverlay(box, "record", (onClosed) => openRecordOverlay({
      t,
      uploadUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants/upload`,
      referenceFramerateUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/reference-framerate`,
      onApplied: (applyResponse) => handleEffectApplied(box, applyResponse),
      onClosed,
    }));
  });

  wireBoxEffectButton({
    btn: normalizeBtn,
    box,
    effectType: "normalize",
    needProjectKey: "normalizeNeedProject",
    routeSegment: "normalize",
    openOverlay: openNormalizeOverlay,
    getParams: getBoxNormalizeParams,
  });

  wireBoxEffectButton({
    btn: pitchBtn,
    box,
    effectType: "pitch",
    needProjectKey: "pitchNeedProject",
    routeSegment: "pitch",
    openOverlay: openPitchOverlay,
    getParams: getBoxPitchParams,
  });

  wireBoxEffectButton({
    btn: formantBtn,
    box,
    effectType: "formant",
    needProjectKey: "formantNeedProject",
    routeSegment: "formant",
    openOverlay: openFormantOverlay,
    getParams: getBoxFormantParams,
  });

  wireBoxEffectButton({
    btn: delayBtn,
    box,
    effectType: "delay",
    needProjectKey: "delayNeedProject",
    routeSegment: "delay",
    openOverlay: openDelayOverlay,
    getParams: getBoxDelayParams,
  });

  removeBtn.addEventListener("click", async () => {
    if (!confirm(t("confirmRemoveBox"))) return;
    const boxIndex = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box")).indexOf(box);
    box.remove();
    if (getCurrentProject() && getCurrentChapterName()) {
      removeChatHistoriesEntry(getCurrentProject(), getCurrentChapterName(), boxIndex);
    }
    renderPauseConnectors();
    saveDialogDraft();
    refreshOverviewIfVisible();
    refreshScriptFromBoxes();
    // Sync the removal to the server immediately (not just the local draft) —
    // otherwise chapter.json still has this box's old variants at its array
    // position, and a new box added at the same spot silently inherits them
    // on its next generate/effect-apply. See docs/FIXES.md.
    await saveCurrentChapter({ silent: true });
  });

  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !menuDropdown.hidden;
    document.querySelectorAll(".dialog-box-menu-dropdown").forEach((el) => (el.hidden = true));
    menuDropdown.hidden = isOpen;
  });

  menuClearTextBtn.addEventListener("click", () => {
    menuDropdown.hidden = true;
    clearBoxText(box);
  });

  menuClearAudioBtn.addEventListener("click", () => {
    menuDropdown.hidden = true;
    clearBoxAudio(box);
  });

  previewBtn.addEventListener("click", async () => {
    const voice = voiceSelect.value;
    if (!voice) return;

    if (!previewPlayer.hidden && !previewPlayer.paused && previewPlayer.dataset.voice === voice) {
      previewPlayer.pause();
      previewPlayer.hidden = true;
      return;
    }

    previewBtn.disabled = true;
    try {
      const response = await fetch(`/voices/${encodeURIComponent(voice)}/preview`);
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(errorBody.detail || t("errorStatusCode", response.status));
      }

      const blob = await response.blob();
      if (previewPlayer.src) {
        URL.revokeObjectURL(previewPlayer.src);
      }
      previewPlayer.src = URL.createObjectURL(blob);
      previewPlayer.dataset.voice = voice;
      previewPlayer.hidden = false;
      previewPlayer.play();
    } catch (error) {
      setDialogStatus(t("errorPreview", error.message), "error");
    } finally {
      previewBtn.disabled = false;
    }
  });

  generateBtn.addEventListener("click", async () => {
    const count = Math.min(5, Math.max(1, Number(variantCountInput.value) || 1));
    await enqueueGeneration(box, count);
    refreshOverviewIfVisible();
  });

  if (insertBeforeBox) {
    dialogBoxesContainer.insertBefore(box, insertBeforeBox);
  } else {
    dialogBoxesContainer.appendChild(box);
  }
  applyTranslations();
  renderPauseConnectors();
  refreshOverviewIfVisible();
  refreshScriptFromBoxes();
}

export function clearBoxesOnly() {
  for (const box of dialogBoxesContainer.querySelectorAll(".dialog-box")) {
    const boxPlayer = box.querySelector(".dialog-box-player");
    if (boxPlayer.src) {
      URL.revokeObjectURL(boxPlayer.src);
    }
    const previewPlayer = box.querySelector(".dialog-box-voice-preview-player");
    if (previewPlayer.src) {
      URL.revokeObjectURL(previewPlayer.src);
    }
  }
  dialogBoxesContainer.innerHTML = "";
  refreshScriptFromBoxes();
}

export function collectBoxesDraftData() {
  return Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box")).map((box) => {
    const data = boxAudioBlobs.get(box);
    let variants = [];
    let activeIndex = -1;
    if (data) {
      variants = data.variants.map((v) => v.filename).filter(Boolean);
      const activeItem = data.variants[data.activeIndex];
      activeIndex = activeItem && activeItem.filename ? variants.indexOf(activeItem.filename) : -1;
    }
    return {
      text: box.querySelector(".dialog-box-text").value,
      voice: box.querySelector(".dialog-box-voice").value,
      volumeDb: Number(box.querySelector(".dialog-box-volume").value),
      panValue: Number(box.dataset.panValue) || 0,
      pauseAfterMs: Number(box.dataset.pauseAfterMs) || 400,
      pauseLocked: box.dataset.pauseLocked === "true",
      collapsed: box.dataset.collapsed === "true",
      variants,
      activeIndex,
      variantLabels: data ? data.variantLabels || {} : {},
      variantLocks: data ? data.variantLocks || {} : {},
      recordingLineage: data ? data.recordingLineage || {} : {},
    };
  });
}
