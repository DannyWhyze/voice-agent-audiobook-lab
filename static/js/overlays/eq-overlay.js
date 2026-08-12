import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

const EQ_BAND_FREQUENCIES_HZ = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const EQ_BAND_Q = 1.4;

function formatEqBandFrequency(freqHz) {
  return freqHz >= 1000 ? `${freqHz / 1000}k` : `${freqHz}`;
}

function normalizeBandGains(bandGains) {
  // Defends against band_gains_db arrays saved before EQ_BAND_FREQUENCIES_HZ's
  // length last changed (e.g. old presets, old persisted eq_params) -- pads
  // missing bands with 0 dB, truncates extra ones, so callers always get an
  // array matching the current band count.
  const normalized = bandGains.slice(0, EQ_BAND_FREQUENCIES_HZ.length);
  while (normalized.length < EQ_BAND_FREQUENCIES_HZ.length) {
    normalized.push(0);
  }
  return normalized;
}

export function openEqOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    band_gains_db: initialParams
      ? normalizeBandGains(initialParams.band_gains_db)
      : EQ_BAND_FREQUENCIES_HZ.map(() => 0),
  };

  let audioCtx = null;
  let filterNodes = null;
  let sourceNode = null;

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
  title.textContent = "Bars2Bars EQ";
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
  const stopResizing = makeResizable(panel, resizeHandle, "eq");

  const sliderGrid = document.createElement("div");
  sliderGrid.className = "eq-slider-grid";
  panel.appendChild(sliderGrid);

  const sliderRefreshFns = [];

  EQ_BAND_FREQUENCIES_HZ.forEach((freqHz, bandIndex) => {
    const unit = document.createElement("div");
    unit.className = "eq-band-unit";

    const valueLabel = document.createElement("span");
    valueLabel.className = "eq-band-value";

    const sliderWrap = document.createElement("div");
    sliderWrap.className = "eq-band-slider-wrap";

    const slider = document.createElement("input");
    slider.type = "range";
    slider.className = "eq-band-slider";
    slider.min = "-12";
    slider.max = "12";
    slider.step = "0.5";
    slider.value = String(params.band_gains_db[bandIndex]);
    sliderWrap.appendChild(slider);

    const freqLabel = document.createElement("span");
    freqLabel.className = "eq-band-freq-label";
    freqLabel.textContent = formatEqBandFrequency(freqHz);

    function refreshValue() {
      const value = Number(slider.value);
      valueLabel.textContent = `${value > 0 ? "+" : ""}${value.toFixed(1)} dB`;
    }
    refreshValue();
    sliderRefreshFns.push(() => {
      slider.value = String(params.band_gains_db[bandIndex]);
      refreshValue();
    });

    slider.addEventListener("input", () => {
      params.band_gains_db[bandIndex] = Number(slider.value);
      refreshValue();
      if (filterNodes) {
        filterNodes[bandIndex].gain.value = params.band_gains_db[bandIndex];
      }
    });

    unit.appendChild(valueLabel);
    unit.appendChild(sliderWrap);
    unit.appendChild(freqLabel);
    sliderGrid.appendChild(unit);
  });

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "eq",
    params,
    refreshFns: sliderRefreshFns,
    onPresetApplied: () => {
      params.band_gains_db = normalizeBandGains(params.band_gains_db);
      sliderRefreshFns.forEach((refresh) => refresh());
      if (filterNodes) {
        filterNodes.forEach((node, i) => {
          node.gain.value = params.band_gains_db[i];
        });
      }
    },
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

  function initWebAudio() {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    filterNodes = EQ_BAND_FREQUENCIES_HZ.map((freqHz, bandIndex) => {
      const node = audioCtx.createBiquadFilter();
      node.type = "peaking";
      node.frequency.value = freqHz;
      node.Q.value = EQ_BAND_Q;
      node.gain.value = params.band_gains_db[bandIndex];
      return node;
    });

    sourceNode = audioCtx.createMediaElementSource(previewPlayer);
    sourceNode.connect(filterNodes[0]);
    for (let i = 0; i < filterNodes.length - 1; i++) {
      filterNodes[i].connect(filterNodes[i + 1]);
    }
    filterNodes[filterNodes.length - 1].connect(audioCtx.destination);
  }

  previewPlayer.addEventListener("play", () => {
    initWebAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
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
    params.band_gains_db = EQ_BAND_FREQUENCIES_HZ.map(() => 0);
    sliderRefreshFns.forEach((refresh) => refresh());
    if (filterNodes) {
      filterNodes.forEach((node) => {
        node.gain.value = 0;
      });
    }
  });

  function closeOverlay() {
    if (audioCtx && audioCtx.state !== "closed") {
      audioCtx.close();
    }
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
      const rawUrl = previewUrl.includes("/boxes/")
        ? previewUrl.replace(/\/boxes\/(\d+)\/eq\/preview/, "/audio/$1")
        : previewUrl.replace("/eq/preview", "/combined-audio");

      const response = await fetch(rawUrl);
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


