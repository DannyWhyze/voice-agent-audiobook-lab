import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { ReverbTank } from "../dsp/reverb-tank.js";
import { buildKnobGrid } from "./knob-grid.js";

export function openReverbOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    pre_delay_ms: 0.0,
    bandwidth: 0.9999,
    input_diffusion_1: 0.75,
    input_diffusion_2: 0.625,
    decay: 0.5,
    decay_diffusion_1: 0.7,
    decay_diffusion_2: 0.5,
    damping: 0.005,
    excursion_rate: 0.5,
    excursion_depth: 0.7,
    wet_dry_mix: 0.3,
  };
  const DEFAULT_PARAMS = { ...params };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

  let audioCtx = null;
  let reverbNode = null;
  let sourceNode = null;
  let tank = null;

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
  title.textContent = "Bars2Bars Reverb";
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
  const stopResizing = makeResizable(panel, resizeHandle, "reverb");

  const knobGrid = document.createElement("div");
  knobGrid.className = "compressor-stepper-grid reverb-knob-grid";
  panel.appendChild(knobGrid);

  // Matches the RT60-style tail estimate in src/orchestrator/reverb.py's
  // _estimate_tail_seconds -- used to let the Decay knob be dragged/displayed
  // in seconds/ms (uniform precision across the whole range) instead of the
  // raw 0-1 feedback coefficient the backend actually expects.
  const DECAY_LOOP_SECONDS = 0.36;
  const DECAY_MAX_TAIL_SECONDS = 15.0;

  function decayCoefficientToSeconds(decay) {
    if (decay <= 0) return 0;
    if (decay >= 0.999) return DECAY_MAX_TAIL_SECONDS;
    const bounces = Math.log(0.001) / Math.log(decay);
    return Math.min(bounces * DECAY_LOOP_SECONDS, DECAY_MAX_TAIL_SECONDS);
  }

  function decaySecondsToCoefficient(seconds) {
    if (seconds <= 0) return 0;
    const clamped = Math.min(seconds, DECAY_MAX_TAIL_SECONDS);
    const bounces = clamped / DECAY_LOOP_SECONDS;
    return Math.exp(Math.log(0.001) / bounces);
  }

  function formatDecaySeconds(seconds) {
    if (seconds < 1) {
      return Math.round(seconds * 1000) + " ms";
    }
    return seconds.toFixed(2) + " s";
  }

  const knobDefs = [
    { key: "pre_delay_ms", label: t("reverbPreDelay"), step: 10, min: 0, max: 1000, unit: "ms", decimals: 0 },
    { key: "bandwidth", label: t("reverbBandwidth"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    {
      key: "input_diffusion_1",
      label: t("reverbInputDiffusion1"),
      step: 0.01,
      min: 0,
      max: 1,
      unit: "",
      decimals: 2,
      // Input Diffusion 2 isn't shown as its own knob -- it's kept at its
      // original ratio to Input Diffusion 1 (0.625/0.75 by default) so the
      // two different allpass coefficients that avoid metallic ringing stay
      // intact, without exposing a second knob to the user.
      linkedKey: "input_diffusion_2",
      linkedRatio: 0.625 / 0.75,
    },
    {
      key: "decay",
      label: t("reverbDecay"),
      step: 0.1,
      min: 0,
      max: DECAY_MAX_TAIL_SECONDS,
      unit: "",
      decimals: 2,
      toParam: decaySecondsToCoefficient,
      fromParam: decayCoefficientToSeconds,
      formatValue: formatDecaySeconds,
    },
    {
      key: "decay_diffusion_1",
      label: t("reverbDecayDiffusion1"),
      step: 0.01,
      min: 0,
      max: 0.99,
      unit: "",
      decimals: 2,
      // Same idea as Input Diffusion 2 above -- Decay Diffusion 2 stays
      // linked at its original ratio (0.5/0.7 by default) instead of getting
      // its own knob.
      linkedKey: "decay_diffusion_2",
      linkedRatio: 0.5 / 0.7,
    },
    { key: "damping", label: t("reverbDamping"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "excursion_rate", label: t("reverbExcursionRate"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    { key: "excursion_depth", label: t("reverbExcursionDepth"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    {
      key: "wet_dry_mix",
      label: t("reverbWetDryMix"),
      step: 1,
      min: 0,
      max: 100,
      unit: "%",
      decimals: 0,
      toParam: (percent) => percent / 100,
      fromParam: (fraction) => fraction * 100,
    },
  ];

  const knobRefreshFns = buildKnobGrid({
    container: knobGrid,
    defs: knobDefs,
    params,
    onChange: () => updateLiveWebAudioParams(),
  });

  function initWebAudio() {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    tank = new ReverbTank(audioCtx.sampleRate);
    
    const bufferSize = 1024;
    const channels = 2;
    reverbNode = audioCtx.createScriptProcessor(bufferSize, channels, channels);

    reverbNode.onaudioprocess = (audioProcessingEvent) => {
      const inputBuffer = audioProcessingEvent.inputBuffer;
      const outputBuffer = audioProcessingEvent.outputBuffer;

      const channelCount = inputBuffer.numberOfChannels;
      const inputChannels = [];
      for (let c = 0; c < channelCount; c++) {
        inputChannels.push(inputBuffer.getChannelData(c));
      }

      const outputL = outputBuffer.getChannelData(0);
      const outputR = outputBuffer.getChannelData(1);

      tank.process(inputChannels, outputL, outputR);
    };

    sourceNode = audioCtx.createMediaElementSource(previewPlayer);
    sourceNode.connect(reverbNode);
    reverbNode.connect(audioCtx.destination);

    updateLiveWebAudioParams();
  }

  function updateLiveWebAudioParams() {
    if (tank) {
      tank.setParams(params);
    }
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
  }

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "reverb",
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
