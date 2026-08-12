import { t } from "./i18n.js";
import { getCurrentProject, getCurrentChapterName, setDialogStatus } from "./dialog-context.js";
import {
  activateVariant,
  appendBoxVariants,
  endPauseMsInput,
  getActiveBoxBlob,
  renderVariantsList,
} from "./dialog-boxes.js";
import { combineClips, resetCombinedOutput } from "./dialog-combined.js";
import { saveDialogDraft } from "./dialog.js";

const dialogBoxesContainer = document.getElementById("dialog-boxes");
const generateAllBtn = document.getElementById("generate-all-btn");
const forceRegenerateCheckbox = document.getElementById("force-regenerate-checkbox");
const cancelAllBtn = document.getElementById("cancel-all-btn");
const recombineBtn = document.getElementById("recombine-btn");

const generationQueue = [];
const pendingGenerations = new Map();
let queueProcessing = false;
let activeDialogController = null;
let dialogElapsedTimer = null;
let dialogElapsedSeconds = 0;

function startDialogElapsedTimer(label) {
  dialogElapsedSeconds = 0;
  setDialogStatus(t("dialogStatusGenerating", label, 0), "busy");
  dialogElapsedTimer = setInterval(() => {
    dialogElapsedSeconds += 1;
    setDialogStatus(t("dialogStatusGenerating", label, dialogElapsedSeconds), "busy");
  }, 1000);
}

function stopDialogElapsedTimer() {
  if (dialogElapsedTimer) {
    clearInterval(dialogElapsedTimer);
    dialogElapsedTimer = null;
  }
}

function setBoxGenerationControlsDisabled(box, disabled) {
  box.querySelector(".dialog-box-generate-btn").disabled = disabled;
  box.querySelector(".dialog-box-variant-count").disabled = disabled;
}

export function setBulkControlsDisabled(disabled) {
  generateAllBtn.disabled = disabled;
  recombineBtn.disabled = disabled;
}

export function enqueueGeneration(box, count = 1, forceActivateNewest = false) {
  const existing = pendingGenerations.get(box);
  if (existing) return existing;

  const text = box.querySelector(".dialog-box-text").value.trim();
  if (!text) {
    const statusEl = box.querySelector(".dialog-box-status");
    statusEl.textContent = t("emptyTextWarning");
    statusEl.className = "dialog-box-status status status-error";
    return Promise.resolve(false);
  }

  const promise = new Promise((resolve) => {
    generationQueue.push({ box, count, forceActivateNewest, resolve });
  });
  pendingGenerations.set(box, promise);
  setBoxGenerationControlsDisabled(box, true);
  const statusEl = box.querySelector(".dialog-box-status");
  statusEl.textContent = t("queuedForGeneration");
  statusEl.className = "dialog-box-status status status-idle";
  cancelAllBtn.disabled = false;
  processQueue();
  return promise;
}

async function processQueue() {
  if (queueProcessing) return;
  queueProcessing = true;
  while (generationQueue.length > 0) {
    const { box, count, forceActivateNewest, resolve } = generationQueue.shift();
    const controller = new AbortController();
    activeDialogController = controller;
    let success = true;
    try {
      await runBoxGeneration(box, count, controller.signal, forceActivateNewest);
    } catch {
      success = false;
    }
    activeDialogController = null;
    pendingGenerations.delete(box);
    setBoxGenerationControlsDisabled(box, false);
    resolve(success);
  }
  queueProcessing = false;
  cancelAllBtn.disabled = true;
}

async function runBoxGeneration(box, count, signal, forceActivateNewest) {
  const statusEl = box.querySelector(".dialog-box-status");
  const newItems = [];

  for (let i = 0; i < count; i++) {
    statusEl.textContent = count > 1 ? t("generatingVariant", i + 1, count) : t("generating");
    statusEl.className = "dialog-box-status status status-busy";

    let blob;
    let filename = "";
    try {
      if (getCurrentProject() && getCurrentChapterName()) {
        const boxes = Array.from(document.querySelectorAll(".dialog-box"));
        const boxIndex = boxes.indexOf(box);
        const textarea = box.querySelector(".dialog-box-text");
        const voiceSelect = box.querySelector(".dialog-box-voice");
        const text = textarea.value;
        const voice = voiceSelect.value || null;

        const response = await fetch(
          `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/variants`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, voice }),
            signal,
          }
        );
        if (!response.ok) {
          const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
          throw new Error(errorBody.detail || t("errorStatusCode", response.status));
        }
        blob = await response.blob();
        filename = response.headers.get("X-Variant-Filename") || "";
      } else {
        blob = await generateOneClip(box, signal);
      }
    } catch (error) {
      statusEl.textContent = error.name === "AbortError" ? t("aborted") : t("errorGeneric", error.message);
      statusEl.className = "dialog-box-status status status-error";
      throw error;
    }
    newItems.push({ blob, filename });
  }

  const { hadActive, firstNewIndex, variantCount } = appendBoxVariants(box, newItems);

  statusEl.textContent = t("done");
  statusEl.className = "dialog-box-status status status-ok";

  if (!hadActive) {
    await activateVariant(box, firstNewIndex);
  } else if (forceActivateNewest) {
    await activateVariant(box, variantCount - 1);
  } else {
    renderVariantsList(box);
    saveDialogDraft();
  }
}

async function generateOneClip(box, signal) {
  const textarea = box.querySelector(".dialog-box-text");
  const voiceSelect = box.querySelector(".dialog-box-voice");
  const text = textarea.value;
  const voice = voiceSelect.value || null;

  const response = await fetch("/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice }),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(errorBody.detail || t("errorStatusCode", response.status));
  }

  return await response.blob();
}

generateAllBtn.addEventListener("click", async () => {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  if (boxes.length === 0) {
    setDialogStatus(t("noBoxes"), "error");
    return;
  }

  setBulkControlsDisabled(true);
  try {
    startDialogElapsedTimer(t("generatingBoxes"));
    resetCombinedOutput();

    const boxesToGenerate = forceRegenerateCheckbox.checked
      ? boxes
      : boxes.filter((box) => getActiveBoxBlob(box) === undefined);
    if (boxesToGenerate.length === 0) {
      stopDialogElapsedTimer();
      setDialogStatus(t("allBoxesAlreadyGenerated"), "ok");
      return;
    }
    const results = await Promise.all(
      boxesToGenerate.map((box) => enqueueGeneration(box, 1, true))
    );
    stopDialogElapsedTimer();

    if (!results.every(Boolean)) {
      setDialogStatus(t("someBoxesFailed"), "error");
      return;
    }

    const clips = [];
    const gainsDb = [];
    const pausesMs = [];
    const pans = [];
    for (const [index, box] of boxes.entries()) {
      clips.push(getActiveBoxBlob(box));
      gainsDb.push(Number(box.querySelector(".dialog-box-volume").value));
      pans.push(Number(box.dataset.panValue) / 100 || 0);
      if (index > 0) {
        pausesMs.push(Number(boxes[index - 1].dataset.pauseAfterMs) || 400);
      }
    }

    setDialogStatus(t("mergingClips"), "busy");
    try {
      await combineClips(clips, gainsDb, pausesMs, Number(endPauseMsInput.value) || 0, pans, undefined);
      setDialogStatus(t("done"), "ok");
    } catch (error) {
      setDialogStatus(t("errorMerging", error.message), "error");
    }
  } finally {
    stopDialogElapsedTimer();
    setBulkControlsDisabled(false);
  }
});

cancelAllBtn.addEventListener("click", () => {
  if (activeDialogController) {
    activeDialogController.abort();
  }
  while (generationQueue.length > 0) {
    const { box, resolve } = generationQueue.shift();
    pendingGenerations.delete(box);
    setBoxGenerationControlsDisabled(box, false);
    const statusEl = box.querySelector(".dialog-box-status");
    statusEl.textContent = t("aborted");
    statusEl.className = "dialog-box-status status status-idle";
    resolve(false);
  }
});
