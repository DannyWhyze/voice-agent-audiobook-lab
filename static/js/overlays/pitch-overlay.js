import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { buildSemitoneCentsRows, createSemitoneRatioLiveAudio } from "./semitone-cents-shared.js";
import { PitchShifter } from "../dsp/pitch-shifter.js";

export function openPitchOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    semitones: 0,
    cents: 0.0,
  };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

  const liveAudio = createSemitoneRatioLiveAudio({
    params,
    createShifter: (framerate) => new PitchShifter(framerate),
    setRatio: (shifter, ratio) => shifter.setPitchRatio(ratio),
  });

  const backdrop = document.createElement("div");
  backdrop.className = "compressor-overlay-backdrop";

  const panel = document.createElement("div");
  panel.className = "compressor-overlay-panel";
  backdrop.appendChild(panel);

  const header = document.createElement("div");
  header.className = "b2b-overlay-header";
  panel.appendChild(header);

  const title = document.createElement("h3");
  title.className = "b2b-overlay-title";
  title.textContent = "Bars2Bars Pitch";
  header.appendChild(title);

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "compressor-overlay-close-btn";
  closeBtn.textContent = "✕";
  header.appendChild(closeBtn);

  const stopDragging = makeDraggable(panel, header);

  const resizeHandle = document.createElement("div");
  resizeHandle.className = "b2b-resize-handle";
  panel.appendChild(resizeHandle);
  const stopResizing = makeResizable(panel, resizeHandle, "pitch");

  const { semitonesInput, centsInput } = buildSemitoneCentsRows({
    t,
    panel,
    params,
    semitonesLabelKey: "pitchSemitonesLabel",
    centsLabelKey: "pitchCentsLabel",
    onChange: () => liveAudio.updateLiveWebAudioParams(),
  });

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "pitch",
    params,
    refreshFns: [
      () => {
        semitonesInput.value = String(params.semitones);
        centsInput.value = String(params.cents);
        liveAudio.updateLiveWebAudioParams();
      },
    ],
    onPresetApplied: () => {},
  });
  panel.appendChild(presetsSection);

  const actionsRow = document.createElement("div");
  actionsRow.className = "compressor-actions-row";

  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.className = "compressor-preview-btn";
  previewBtn.textContent = t("compressorPreview");

  const previewPlayer = document.createElement("audio");
  previewPlayer.controls = true;
  previewPlayer.className = "compressor-preview-player";
  previewPlayer.hidden = true;

  previewPlayer.addEventListener("play", () => {
    liveAudio.initWebAudio(previewPlayer);
    liveAudio.updateLiveWebAudioParams();
  });

  const applyBtn = document.createElement("button");
  applyBtn.type = "button";
  applyBtn.className = "compressor-apply-btn";
  applyBtn.textContent = t("compressorApply");

  const resetBtn = document.createElement("button");
  resetBtn.type = "button";
  resetBtn.className = "compressor-reset-btn";
  resetBtn.textContent = t("resetToDefault");
  resetBtn.addEventListener("click", () => {
    params.semitones = 0;
    params.cents = 0.0;
    semitonesInput.value = String(params.semitones);
    centsInput.value = String(params.cents);
    liveAudio.updateLiveWebAudioParams();
  });

  function closeOverlay() {
    liveAudio.closeAudioGraph();
    if (previewPlayer.src) {
      URL.revokeObjectURL(previewPlayer.src);
    }
    stopDragging();
    stopResizing();
    unregisterOverlay(backdrop);
    backdrop.remove();
  }

  const overlayHandle = registerOverlay(backdrop, panel, closeOverlay, onClosed);
  closeBtn.addEventListener("click", closeOverlay);

  previewBtn.addEventListener("click", async () => {
    previewBtn.disabled = true;
    applyBtn.disabled = true;
    try {
      const response = await fetch(previewUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (response.ok) {
        const blob = await response.blob();
        if (previewPlayer.src) URL.revokeObjectURL(previewPlayer.src);
        previewPlayer.src = URL.createObjectURL(blob);
        previewPlayer.hidden = false;
        previewPlayer.play();
      }
    } finally {
      previewBtn.disabled = false;
      applyBtn.disabled = false;
    }
  });

  applyBtn.addEventListener("click", async () => {
    previewBtn.disabled = true;
    applyBtn.disabled = true;
    try {
      const response = await fetch(applyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (response.ok) {
        closeOverlay();
        await onApplied(response);
      }
    } finally {
      previewBtn.disabled = false;
      applyBtn.disabled = false;
    }
  });

  actionsRow.appendChild(resetBtn);
  actionsRow.appendChild(previewBtn);
  actionsRow.appendChild(previewPlayer);
  actionsRow.appendChild(applyBtn);
  panel.appendChild(actionsRow);

  document.body.appendChild(backdrop);

  return overlayHandle;
}
