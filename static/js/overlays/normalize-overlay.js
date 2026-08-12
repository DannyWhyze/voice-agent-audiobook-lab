import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

const MODE_DEFAULTS = {
  peak: -1.0,
  rms: -20.0,
  lufs: -16.0,
};

export function openNormalizeOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    mode: "rms",
    target_db: -20.0,
  };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

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
  title.textContent = "Bars2Bars Normalize";
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
  const stopResizing = makeResizable(panel, resizeHandle, "normalize");

  const modeRow = document.createElement("div");
  modeRow.className = "normalize-mode-row";

  const modeLabel = document.createElement("label");
  modeLabel.textContent = t("normalizeModeLabel");
  modeRow.appendChild(modeLabel);

  const modeSelect = document.createElement("select");
  for (const [value, labelKey] of [
    ["peak", "normalizeModePeak"],
    ["rms", "normalizeModeRms"],
    ["lufs", "normalizeModeLufs"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = t(labelKey);
    modeSelect.appendChild(option);
  }
  modeSelect.value = params.mode;
  modeRow.appendChild(modeSelect);
  panel.appendChild(modeRow);

  const targetRow = document.createElement("div");
  targetRow.className = "normalize-target-row";

  const targetLabel = document.createElement("label");
  targetLabel.textContent = t("normalizeTargetLabel");
  targetRow.appendChild(targetLabel);

  const targetInput = document.createElement("input");
  targetInput.type = "number";
  targetInput.step = "0.5";
  targetInput.value = String(params.target_db);
  targetRow.appendChild(targetInput);
  panel.appendChild(targetRow);

  modeSelect.addEventListener("change", () => {
    params.mode = modeSelect.value;
    params.target_db = MODE_DEFAULTS[params.mode];
    targetInput.value = String(params.target_db);
  });

  targetInput.addEventListener("input", () => {
    params.target_db = Number(targetInput.value);
  });

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "normalize",
    params,
    refreshFns: [
      () => {
        modeSelect.value = params.mode;
        targetInput.value = String(params.target_db);
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

  const applyBtn = document.createElement("button");
  applyBtn.type = "button";
  applyBtn.className = "compressor-apply-btn";
  applyBtn.textContent = t("compressorApply");

  const resetBtn = document.createElement("button");
  resetBtn.type = "button";
  resetBtn.className = "compressor-reset-btn";
  resetBtn.textContent = t("resetToDefault");
  resetBtn.addEventListener("click", () => {
    params.mode = "rms";
    params.target_db = -20.0;
    modeSelect.value = params.mode;
    targetInput.value = String(params.target_db);
  });

  function closeOverlay() {
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
