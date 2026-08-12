import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { buildKnobGrid } from "./knob-grid.js";

export function openDelayOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    delay_time_ms: 350.0,
    feedback: 0.35,
    damping: 0.3,
    saturation: 0.2,
    wow_flutter_rate: 0.3,
    wow_flutter_depth: 0.15,
    wet_dry_mix: 0.35,
  };
  const DEFAULT_PARAMS = { ...params };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

  let audioCtx = null;
  let delayNode = null;
  let sourceNode = null;
  let channelStates = [];

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
  title.textContent = "Bars2Bars Delay";
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
  const stopResizing = makeResizable(panel, resizeHandle, "delay");

  const knobGrid = document.createElement("div");
  knobGrid.className = "compressor-stepper-grid reverb-knob-grid";
  panel.appendChild(knobGrid);

  const knobDefs = [
    { key: "delay_time_ms", label: t("delayTime"), step: 10, min: 1, max: 2000, unit: "ms", decimals: 0 },
    { key: "feedback", label: t("delayFeedback"), step: 1, min: 0, max: 95, unit: "%", decimals: 0, toParam: (p) => p / 100, fromParam: (f) => f * 100 },
    { key: "damping", label: t("delayDamping"), step: 1, min: 0, max: 100, unit: "%", decimals: 0, toParam: (p) => p / 100, fromParam: (f) => f * 100 },
    { key: "saturation", label: t("delaySaturation"), step: 1, min: 0, max: 100, unit: "%", decimals: 0, toParam: (p) => p / 100, fromParam: (f) => f * 100 },
    { key: "wow_flutter_rate", label: t("delayWowFlutterRate"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    { key: "wow_flutter_depth", label: t("delayWowFlutterDepth"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    { key: "wet_dry_mix", label: t("delayWetDryMix"), step: 1, min: 0, max: 100, unit: "%", decimals: 0, toParam: (p) => p / 100, fromParam: (f) => f * 100 },
  ];

  const knobRefreshFns = buildKnobGrid({
    container: knobGrid,
    defs: knobDefs,
    params,
    onChange: () => updateLiveWebAudioParams(),
  });

  // Mirrors src/orchestrator/audio/delay.py's _peek_interp/_run_delay_channel
  // exactly -- keep both in sync, this is what "Anwenden" actually renders.
  class DelayLine {
    constructor(length) {
      this.length = Math.max(length, 1);
      this.buffer = new Float32Array(this.length);
      this.index = 0;
      this.lpState = 0.0;
      this.excPhase = 0.0;
    }
    peekInterp(offset) {
      const base = Math.floor(offset);
      const frac = offset - base;
      const i0 = (this.index + base - 1 + this.length * 4) % this.length;
      const i1 = (this.index + base + this.length * 4) % this.length;
      const i2 = (this.index + base + 1 + this.length * 4) % this.length;
      const i3 = (this.index + base + 2 + this.length * 4) % this.length;
      const x0 = this.buffer[i0];
      const x1 = this.buffer[i1];
      const x2 = this.buffer[i2];
      const x3 = this.buffer[i3];
      const a = (3 * (x1 - x2) - x0 + x3) / 2;
      const b = 2 * x2 + x0 - (5 * x1 + x3) / 2;
      const c = (x2 - x0) / 2;
      return ((a * frac + b) * frac + c) * frac + x1;
    }
    processSample(x, framerate) {
      const wowRate = params.wow_flutter_rate / framerate;
      const wowDepth = (params.wow_flutter_depth * framerate) / 1000.0;
      const dp = 1.0 - params.damping;
      const drive = 1.0 + params.saturation * 4.0;
      const dryGain = 1.0 - params.wet_dry_mix;

      const exc = wowDepth * (1.0 + Math.cos(this.excPhase * 6.283185307179586));
      const rawDelayed = this.peekInterp(exc);

      this.lpState += dp * (rawDelayed - this.lpState);
      const saturated = Math.tanh(this.lpState * drive);
      const processed = (1.0 - params.saturation) * this.lpState + params.saturation * saturated;

      this.buffer[this.index] = x + processed * params.feedback;
      const output = x * dryGain + processed * params.wet_dry_mix;

      this.excPhase += wowRate;
      this.index = (this.index + 1) % this.length;
      return output;
    }
  }

  function initWebAudio() {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    const framerate = audioCtx.sampleRate;

    const bufferSize = 1024;
    const channels = 2;
    delayNode = audioCtx.createScriptProcessor(bufferSize, channels, channels);
    channelStates = [];

    delayNode.onaudioprocess = (audioProcessingEvent) => {
      const inputBuffer = audioProcessingEvent.inputBuffer;
      const outputBuffer = audioProcessingEvent.outputBuffer;
      const channelCount = inputBuffer.numberOfChannels;
      const length = inputBuffer.length;

      const delaySamples = Math.max(Math.round((params.delay_time_ms / 1000.0) * framerate), 1);
      while (channelStates.length < channelCount) {
        channelStates.push(new DelayLine(delaySamples));
      }
      for (const state of channelStates) {
        if (state.length !== delaySamples) {
          state.buffer = new Float32Array(Math.max(delaySamples, 1));
          state.length = Math.max(delaySamples, 1);
          state.index = 0;
        }
      }

      for (let c = 0; c < channelCount; c++) {
        const inputData = inputBuffer.getChannelData(c);
        const outputData = outputBuffer.getChannelData(c);
        const state = channelStates[c];
        for (let i = 0; i < length; i++) {
          outputData[i] = state.processSample(inputData[i], framerate);
        }
      }
    };

    sourceNode = audioCtx.createMediaElementSource(previewPlayer);
    sourceNode.connect(delayNode);
    delayNode.connect(audioCtx.destination);
  }

  function updateLiveWebAudioParams() {
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
  }

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "delay",
    params,
    refreshFns: [
      () => {
        knobRefreshFns.forEach((fn) => fn());
        updateLiveWebAudioParams();
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
    initWebAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    updateLiveWebAudioParams();
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
    Object.assign(params, DEFAULT_PARAMS);
    knobRefreshFns.forEach((fn) => fn());
    updateLiveWebAudioParams();
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
