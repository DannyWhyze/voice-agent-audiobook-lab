import { t } from "./i18n.js";
import { attachWaveform } from "./shared.js";
import { openCompressorOverlay } from "./overlays/compressor-overlay.js";
import { openReverbOverlay } from "./overlays/reverb-overlay.js";
import { openTrimOverlay } from "./overlays/trim-fade-overlay.js";
import { openEqOverlay } from "./overlays/eq-overlay.js";
import { openNormalizeOverlay } from "./overlays/normalize-overlay.js";
import { openPitchOverlay } from "./overlays/pitch-overlay.js";
import { openFormantOverlay } from "./overlays/formant-overlay.js";
import { openDelayOverlay } from "./overlays/delay-overlay.js";
import { getCurrentChapterName, getCurrentProject, setDialogStatus } from "./dialog-context.js";
import { deriveVariantLabel, endPauseMsInput, getActiveBoxBlob } from "./dialog-boxes.js";
import { setBulkControlsDisabled } from "./dialog-queue.js";
import { getCurrentChapter } from "./dialog-projects.js";

export const combinedPlayer = document.getElementById("combined-player");
const combinedPlayerWaveform = document.getElementById("combined-player-waveform");
export const combinedDownloadLink = document.getElementById("combined-download-link");
const dialogBoxesContainer = document.getElementById("dialog-boxes");
const recombineBtn = document.getElementById("recombine-btn");
const combinedCompressorBtn = document.getElementById("combined-compressor-btn");
const combinedReverbBtn = document.getElementById("combined-reverb-btn");
const combinedDelayBtn = document.getElementById("combined-delay-btn");
const combinedEqBtn = document.getElementById("combined-eq-btn");
const combinedTrimBtn = document.getElementById("combined-trim-btn");
const combinedNormalizeBtn = document.getElementById("combined-normalize-btn");
const combinedPitchBtn = document.getElementById("combined-pitch-btn");
const combinedFormantBtn = document.getElementById("combined-formant-btn");

let combinedAudioBlob = null;
let selectedCombinedVariants = new Set();

export function getCombinedAudioBlob() {
  return combinedAudioBlob;
}

export function setCombinedAudioBlob(blob) {
  combinedAudioBlob = blob;
}

export function resetCombinedOutput() {
  if (combinedPlayer.src) {
    URL.revokeObjectURL(combinedPlayer.src);
  }
  combinedPlayer.removeAttribute("src");
  combinedDownloadLink.hidden = true;
  combinedDownloadLink.removeAttribute("href");
  combinedDownloadLink.removeAttribute("download");
  combinedAudioBlob = null;
  selectedCombinedVariants = new Set();
  renderCombinedVariantsList([], -1);
}

async function deleteCombinedVariant(filename) {
  await fetch(
    `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}`,
    { method: "DELETE" }
  );
  selectedCombinedVariants.delete(filename);
}

async function deleteSelectedCombinedVariants() {
  if (selectedCombinedVariants.size === 0) return;
  if (!confirm(t("confirmDeleteVariants", selectedCombinedVariants.size))) return;
  // Sequential, not Promise.all: delete_combined_variant() (variants.py) does
  // an unsynchronized read-modify-write of chapter.json, same as box variants
  // (see docs/FIXES.md) — concurrent DELETEs can race and silently drop one
  // removal from chapter.json even though its file was actually deleted.
  for (const filename of [...selectedCombinedVariants]) {
    await deleteCombinedVariant(filename);
  }
  await refreshCombinedVariantsList();
}

export function renderCombinedVariantsList(
  combinedVariants,
  activeCombinedIndex,
  combinedVariantLocks,
  combinedVariantLabels
) {
  const container = document.getElementById("combined-variants-list");
  if (!container) return;
  container.innerHTML = "";

  if (!combinedVariants || combinedVariants.length === 0) {
    return;
  }

  const locks = combinedVariantLocks || {};
  const labels = combinedVariantLabels || {};
  const variantItems = combinedVariants.map((filename) => ({ filename }));

  if (combinedVariants.length > 1) {
    const bulkBar = document.createElement("div");
    bulkBar.className = "dialog-box-variants-bulk-bar";

    const bulkDeleteBtn = document.createElement("button");
    bulkDeleteBtn.type = "button";
    bulkDeleteBtn.className = "pause-connector-insert-btn";
    bulkDeleteBtn.textContent = t("deleteSelectedVariantsBtn");
    bulkDeleteBtn.disabled = selectedCombinedVariants.size === 0;
    bulkDeleteBtn.addEventListener("click", deleteSelectedCombinedVariants);
    bulkBar.appendChild(bulkDeleteBtn);

    container.appendChild(bulkBar);
  }

  combinedVariants.forEach((filename, index) => {
    const isLocked = !!locks[filename];
    if (isLocked) {
      selectedCombinedVariants.delete(filename);
    }

    const variantRow = document.createElement("div");
    variantRow.className = "dialog-box-variant-row";

    const preview = document.createElement("audio");
    preview.controls = true;
    preview.preload = "metadata";
    preview.src = `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}`;
    variantRow.appendChild(preview);

    const controls = document.createElement("div");
    controls.className = "dialog-box-variant-controls";
    variantRow.appendChild(controls);

    const selectCheckbox = document.createElement("input");
    selectCheckbox.type = "checkbox";
    selectCheckbox.className = "dialog-box-variant-select-checkbox";
    selectCheckbox.title = t("variantSelectCheckboxTitle");
    selectCheckbox.checked = selectedCombinedVariants.has(filename);
    selectCheckbox.disabled = isLocked;
    selectCheckbox.addEventListener("change", () => {
      if (selectCheckbox.checked) {
        selectedCombinedVariants.add(filename);
      } else {
        selectedCombinedVariants.delete(filename);
      }
      renderCombinedVariantsList(combinedVariants, activeCombinedIndex, locks, labels);
    });
    controls.appendChild(selectCheckbox);

    const labelSpan = document.createElement("span");
    labelSpan.className = "dialog-box-variant-label";
    labelSpan.textContent = labels[filename] || deriveVariantLabel(filename, variantItems, index);
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
      input.value = labels[filename] || "";
      input.placeholder = deriveVariantLabel(filename, variantItems, index);

      async function commit() {
        const value = input.value.trim();
        await fetch(
          `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}/label`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: value }),
          }
        );
        await refreshCombinedVariantsList();
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

    if (index === activeCombinedIndex) {
      const activeLabel = document.createElement("span");
      activeLabel.className = "dialog-box-variant-active-label";
      activeLabel.textContent = t("variantActive");
      controls.appendChild(activeLabel);
    } else {
      const activateBtn = document.createElement("button");
      activateBtn.type = "button";
      activateBtn.className = "dialog-box-variant-activate-btn pause-connector-insert-btn";
      activateBtn.textContent = t("variantMakeActive");
      activateBtn.addEventListener("click", async () => {
        await fetch(
          `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}/activate`,
          { method: "PUT" }
        );
        const audioUrl = `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-audio?t=${Date.now()}`;
        const audioResponse = await fetch(audioUrl);
        if (audioResponse.ok) {
          combinedAudioBlob = await audioResponse.blob();
        }
        combinedPlayer.src = audioUrl;
        combinedPlayer.hidden = false;
        combinedDownloadLink.href = audioUrl;
        // .download (the suggested save-as filename, with its date stamp)
        // was never set here, unlike combineClips()/the chapter-load path --
        // it kept whatever project/chapter/date the last real recombine had
        // set, so activating a variant without recombining first offered a
        // stale filename. See docs/FIXES.md.
        combinedDownloadLink.download = `${getCurrentProject()}_${getCurrentChapterName()}_${new Date().toISOString().slice(0, 10)}.wav`;
        combinedDownloadLink.hidden = false;
        await refreshCombinedVariantsList();
      });
      controls.appendChild(activateBtn);
    }

    const lockBtn = document.createElement("button");
    lockBtn.type = "button";
    lockBtn.className = "dialog-box-variant-lock-btn pause-connector-insert-btn";
    lockBtn.textContent = isLocked ? "🔒" : "🔓";
    lockBtn.title = t("variantLockBtnTitle");
    lockBtn.addEventListener("click", async () => {
      await fetch(
        `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}/lock`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ locked: !isLocked }),
        }
      );
      await refreshCombinedVariantsList();
    });
    controls.appendChild(lockBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "dialog-box-variant-delete-btn pause-connector-insert-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.disabled = isLocked;
    deleteBtn.title = isLocked ? t("variantLockedTooltip") : "";
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(t("confirmDeleteVariant"))) return;
      await deleteCombinedVariant(filename);
      await refreshCombinedVariantsList();
    });
    controls.appendChild(deleteBtn);

    container.appendChild(variantRow);
  });
}

// Mirrors handleEffectApplied() in dialog-boxes.js: the backend now auto-
// activates every newly created combined variant (add_combined_variant(),
// see docs/FIXES.md), but the visible/playing combinedPlayer still needs an
// explicit refresh to actually show and play that new active audio, same as
// the box player already gets after a box-level effect apply.
async function handleCombinedEffectApplied(applyResponse) {
  if (applyResponse) {
    const blob = await applyResponse.blob();
    if (combinedPlayer.src) {
      URL.revokeObjectURL(combinedPlayer.src);
    }
    const objectUrl = URL.createObjectURL(blob);
    combinedPlayer.src = objectUrl;
    combinedPlayer.hidden = false;
    combinedDownloadLink.href = objectUrl;
    combinedDownloadLink.download = getCurrentChapter()
      ? `${getCurrentProject()}_${getCurrentChapter()}_${new Date().toISOString().slice(0, 10)}.wav`
      : `fishaudio_dialog_${Date.now()}.wav`;
    combinedDownloadLink.hidden = false;
    combinedAudioBlob = blob;
  }
  await refreshCombinedVariantsList();
}

export async function refreshCombinedVariantsList() {
  if (!getCurrentProject() || !getCurrentChapterName()) return;
  const response = await fetch(
    `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}`
  );
  if (!response.ok) return;
  const data = await response.json();
  renderCombinedVariantsList(
    data.combinedVariants || [],
    data.activeCombinedIndex ?? -1,
    data.combinedVariantLocks || {},
    data.combinedVariantLabels || {}
  );
}

export async function combineClips(clips, gainsDb, pausesMs, trailingPauseMs, pans, signal) {
  const formData = new FormData();
  for (const [index, clip] of clips.entries()) {
    formData.append("clips", clip, `clip_${index}.wav`);
  }
  formData.append("pauses", JSON.stringify(pausesMs));
  formData.append("gains", JSON.stringify(gainsDb));
  formData.append("pans", JSON.stringify(pans));
  formData.append("trailing_pause_ms", String(trailingPauseMs || 0));

  const response = await fetch("/combine", {
    method: "POST",
    body: formData,
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(errorBody.detail || t("errorStatusCode", response.status));
  }

  const combinedBlob = await response.blob();
  if (combinedPlayer.src) {
    URL.revokeObjectURL(combinedPlayer.src);
  }
  combinedPlayer.src = URL.createObjectURL(combinedBlob);
  combinedDownloadLink.href = combinedPlayer.src;
  combinedDownloadLink.download = getCurrentChapter()
    ? `${getCurrentProject()}_${getCurrentChapter()}_${new Date().toISOString().slice(0, 10)}.wav`
    : `fishaudio_dialog_${Date.now()}.wav`;
  combinedDownloadLink.hidden = false;
  combinedAudioBlob = combinedBlob;
}

recombineBtn.addEventListener("click", async () => {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  if (boxes.length === 0) {
    setDialogStatus(t("noBoxes"), "error");
    return;
  }

  const clips = [];
  const gainsDb = [];
  const pausesMs = [];
  const pans = [];
  for (let i = 0; i < boxes.length; i++) {
    const blob = getActiveBoxBlob(boxes[i]);
    if (!blob) {
      setDialogStatus(t("errorMissingAudio", i + 1), "error");
      return;
    }
    clips.push(blob);
    gainsDb.push(Number(boxes[i].querySelector(".dialog-box-volume").value));
    pans.push(Number(boxes[i].dataset.panValue) / 100 || 0);
    if (i > 0) {
      pausesMs.push(Number(boxes[i - 1].dataset.pauseAfterMs) || 400);
    }
  }

  setBulkControlsDisabled(true);
  setDialogStatus(t("mergingClips"), "busy");
  try {
    await combineClips(clips, gainsDb, pausesMs, Number(endPauseMsInput.value) || 0, pans, undefined);
    setDialogStatus(t("done"), "ok");
  } catch (error) {
    setDialogStatus(t("errorMerging", error.message), "error");
  } finally {
    setBulkControlsDisabled(false);
  }
});

const openCombinedOverlays = new Map();

function openOrFocusCombinedOverlay(effectType, openFn) {
  const existing = openCombinedOverlays.get(effectType);
  if (existing) {
    existing.bringToFront();
    return;
  }
  const handle = openFn(() => openCombinedOverlays.delete(effectType));
  openCombinedOverlays.set(effectType, handle);
}

function wireCombinedEffectButton({ btn, effectType, needProjectKey, routeSegment, openOverlay }) {
  btn.addEventListener("click", async () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t(needProjectKey));
      return;
    }
    let initialParams = null;
    const response = await fetch(
      `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}`
    );
    if (response.ok) {
      const data = await response.json();
      initialParams = data[`combined_${effectType}_params`] || null;
    }
    openOrFocusCombinedOverlay(effectType, (onClosed) => openOverlay({
      t,
      project: getCurrentProject(),
      previewUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/${routeSegment}/preview`,
      applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/${routeSegment}/apply`,
      initialParams,
      onApplied: handleCombinedEffectApplied,
      onClosed,
    }));
  });
}

wireCombinedEffectButton({
  btn: combinedCompressorBtn,
  effectType: "compressor",
  needProjectKey: "compressorNeedProject",
  routeSegment: "compress",
  openOverlay: openCompressorOverlay,
});

wireCombinedEffectButton({
  btn: combinedReverbBtn,
  effectType: "reverb",
  needProjectKey: "reverbNeedProject",
  routeSegment: "reverb",
  openOverlay: openReverbOverlay,
});

wireCombinedEffectButton({
  btn: combinedDelayBtn,
  effectType: "delay",
  needProjectKey: "delayNeedProject",
  routeSegment: "delay",
  openOverlay: openDelayOverlay,
});

wireCombinedEffectButton({
  btn: combinedEqBtn,
  effectType: "eq",
  needProjectKey: "eqNeedProject",
  routeSegment: "eq",
  openOverlay: openEqOverlay,
});

combinedTrimBtn.addEventListener("click", () => {
  if (!getCurrentProject() || !getCurrentChapterName()) {
    alert(t("trimNeedProject"));
    return;
  }
  openOrFocusCombinedOverlay("trim", (onClosed) => openTrimOverlay({
    t,
    sourceUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-audio`,
    applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/trim/apply`,
    fadeApplyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/fade/apply`,
    onActivateVariant: (filename) =>
      fetch(
        `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/combined-variants/${encodeURIComponent(filename)}/activate`,
        { method: "PUT" }
      ),
    onApplied: handleCombinedEffectApplied,
    onClosed,
  }));
});

wireCombinedEffectButton({
  btn: combinedNormalizeBtn,
  effectType: "normalize",
  needProjectKey: "normalizeNeedProject",
  routeSegment: "normalize",
  openOverlay: openNormalizeOverlay,
});

wireCombinedEffectButton({
  btn: combinedPitchBtn,
  effectType: "pitch",
  needProjectKey: "pitchNeedProject",
  routeSegment: "pitch",
  openOverlay: openPitchOverlay,
});

wireCombinedEffectButton({
  btn: combinedFormantBtn,
  effectType: "formant",
  needProjectKey: "formantNeedProject",
  routeSegment: "formant",
  openOverlay: openFormantOverlay,
});

attachWaveform(combinedPlayer, combinedPlayerWaveform);
