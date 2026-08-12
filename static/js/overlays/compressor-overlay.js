import { buildPresetsSection, makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { buildKnobGrid } from "./knob-grid.js";

export function openCompressorOverlay({ t, project, previewUrl, applyUrl, onApplied, initialParams, onClosed }) {
  const params = {
    threshold_db: -20.0,
    ratio: 4.0,
    attack_ms: 10.0,
    release_ms: 100.0,
    knee_db: 0.0,
    makeup_gain_db: 0.0,
    detector: "rms",
    rms_window_ms: 10.0,
  };
  const DEFAULT_PARAMS = { ...params };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

  let audioCtx = null;
  let compressorNode = null;
  let gainNode = null;
  let sourceNode = null;
  let animationFrameId = null;

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
  title.textContent = "Bars2Bars Compressor";
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
  const stopResizing = makeResizable(panel, resizeHandle, "compressor");

  const graphRow = document.createElement("div");
  graphRow.className = "compressor-graph-row";
  panel.appendChild(graphRow);

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 220 150");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.classList.add("compressor-curve-svg");
  graphRow.appendChild(svg);

  const kneeRect = document.createElementNS(svgNS, "rect");
  kneeRect.setAttribute("y", "10");
  kneeRect.setAttribute("height", "110");
  kneeRect.setAttribute("fill", "#e8823c");
  kneeRect.setAttribute("opacity", "0.08");
  svg.appendChild(kneeRect);

  const axisY = document.createElementNS(svgNS, "line");
  axisY.setAttribute("x1", "20");
  axisY.setAttribute("y1", "10");
  axisY.setAttribute("x2", "20");
  axisY.setAttribute("y2", "120");
  axisY.setAttribute("stroke", "#f5ede466");
  svg.appendChild(axisY);

  const axisX = document.createElementNS(svgNS, "line");
  axisX.setAttribute("x1", "20");
  axisX.setAttribute("y1", "120");
  axisX.setAttribute("x2", "210");
  axisX.setAttribute("y2", "120");
  axisX.setAttribute("stroke", "#f5ede466");
  svg.appendChild(axisX);

  const curvePath = document.createElementNS(svgNS, "path");
  curvePath.setAttribute("fill", "none");
  curvePath.setAttribute("stroke", "#e8823c");
  curvePath.setAttribute("stroke-width", "2.5");
  svg.appendChild(curvePath);

  const grPanel = document.createElement("div");
  grPanel.className = "compressor-gr-panel";
  const grLabel = document.createElement("span");
  grLabel.textContent = t("compressorGainReduction");
  const grMeterFill = document.createElement("div");
  grMeterFill.className = "compressor-gr-meter-fill";
  const grMeter = document.createElement("div");
  grMeter.className = "compressor-gr-meter";
  grMeter.appendChild(grMeterFill);
  const grValue = document.createElement("span");
  grValue.className = "compressor-gr-value";
  grPanel.appendChild(grLabel);
  grPanel.appendChild(grMeter);
  grPanel.appendChild(grValue);
  graphRow.appendChild(grPanel);

  function dbToX(db) {
    return 20 + ((db + 60) / 60) * 190;
  }
  function dbToY(db) {
    return 120 - ((db + 60) / 60) * 110;
  }

  // Mirrors _gain_reduction_db from src/orchestrator/compressor.py exactly,
  // so the drawn curve always matches what the backend will actually do.
  function gainReductionDb(levelDb, thresholdDb, ratio, kneeDb) {
    if (kneeDb === 0) {
      if (levelDb <= thresholdDb) return 0;
      const targetDb = thresholdDb + (levelDb - thresholdDb) / ratio;
      return targetDb - levelDb;
    }
    const kneeStart = thresholdDb - kneeDb / 2;
    const kneeEnd = thresholdDb + kneeDb / 2;
    if (levelDb <= kneeStart) return 0;
    if (levelDb >= kneeEnd) {
      const targetDb = thresholdDb + (levelDb - thresholdDb) / ratio;
      return targetDb - levelDb;
    }
    const kneePosition = levelDb - kneeStart;
    return ((1 / ratio - 1) * kneePosition * kneePosition) / (2 * kneeDb);
  }

  function updateGraph() {
    const kneeStartX = dbToX(params.threshold_db - params.knee_db / 2);
    const kneeEndX = dbToX(params.threshold_db + params.knee_db / 2);
    kneeRect.setAttribute("x", String(kneeStartX));
    kneeRect.setAttribute("width", String(kneeEndX - kneeStartX));

    let d = "";
    for (let levelDb = -60; levelDb <= 0; levelDb += 2) {
      const reduction = gainReductionDb(levelDb, params.threshold_db, params.ratio, params.knee_db);
      const outputDb = levelDb + reduction;
      const x = dbToX(levelDb);
      const y = dbToY(outputDb);
      d += (d === "" ? "M " : "L ") + x + " " + y + " ";
    }
    curvePath.setAttribute("d", d.trim());

    updateStaticGraphGR();
  }

  function updateStaticGraphGR() {
    if (previewPlayer && !previewPlayer.paused) return;
    grMeterFill.style.height = "0%";
    grValue.textContent = "0.0 dB";
  }

  function initWebAudio() {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    
    const bufferSize = 1024;
    const channels = 2;
    compressorNode = audioCtx.createScriptProcessor(bufferSize, channels, channels);

    let smoothedSq = 0.0;
    let currentReductionDb = 0.0;

    compressorNode.onaudioprocess = (audioProcessingEvent) => {
      const inputBuffer = audioProcessingEvent.inputBuffer;
      const outputBuffer = audioProcessingEvent.outputBuffer;
      const sampleRate = inputBuffer.sampleRate;
      
      const channelCount = inputBuffer.numberOfChannels;
      const length = inputBuffer.length;
      
      const inputData = [];
      const outputData = [];
      for (let c = 0; c < channelCount; c++) {
        inputData.push(inputBuffer.getChannelData(c));
        outputData.push(outputBuffer.getChannelData(c));
      }
      
      const thresholdDb = params.threshold_db;
      const ratio = params.ratio;
      const attackMs = params.attack_ms;
      const releaseMs = params.release_ms;
      const kneeDb = params.knee_db;
      const makeupGainDb = params.makeup_gain_db;
      const detector = params.detector || "rms";
      const rmsWindowMs = params.rms_window_ms || 10.0;
      
      const MIN_AMPLITUDE = 1e-6;
      
      const alpha = 1.0 - Math.exp(-1.0 / (sampleRate * rmsWindowMs / 1000.0));
      const attackCoeff = Math.exp(-1.0 / (sampleRate * attackMs / 1000.0));
      const releaseCoeff = Math.exp(-1.0 / (sampleRate * releaseMs / 1000.0));
      
      for (let i = 0; i < length; i++) {
        let maxVal = 0.0;
        for (let c = 0; c < channelCount; c++) {
          const val = Math.abs(inputData[c][i]);
          if (val > maxVal) maxVal = val;
        }
        
        let levelDb = -120.0;
        if (detector === "peak") {
          levelDb = 20.0 * Math.log10(Math.max(maxVal, MIN_AMPLITUDE));
        } else {
          // RMS
          const frameSq = maxVal * maxVal;
          smoothedSq = alpha * frameSq + (1.0 - alpha) * smoothedSq;
          const amplitude = Math.sqrt(smoothedSq);
          levelDb = 20.0 * Math.log10(Math.max(amplitude, MIN_AMPLITUDE));
        }
        
        // Gain reduction
        let rawReduction = 0.0;
        if (kneeDb === 0.0) {
          if (levelDb > thresholdDb) {
            const targetDb = thresholdDb + (levelDb - thresholdDb) / ratio;
            rawReduction = targetDb - levelDb;
          }
        } else {
          const kneeStart = thresholdDb - kneeDb / 2.0;
          const kneeEnd = thresholdDb + kneeDb / 2.0;
          if (levelDb > kneeStart) {
            if (levelDb >= kneeEnd) {
              const targetDb = thresholdDb + (levelDb - thresholdDb) / ratio;
              rawReduction = targetDb - levelDb;
            } else {
              const kneePosition = levelDb - kneeStart;
              rawReduction = ((1.0 / ratio - 1.0) * kneePosition * kneePosition) / (2.0 * kneeDb);
            }
          }
        }
        
        // Envelope smoothing
        if (rawReduction < currentReductionDb) {
          currentReductionDb = attackCoeff * currentReductionDb + (1.0 - attackCoeff) * rawReduction;
        } else {
          currentReductionDb = releaseCoeff * currentReductionDb + (1.0 - releaseCoeff) * rawReduction;
        }
        
        const totalGainDb = currentReductionDb + makeupGainDb;
        const factor = Math.pow(10, totalGainDb / 20.0);
        
        for (let c = 0; c < channelCount; c++) {
          outputData[c][i] = inputData[c][i] * factor;
        }
      }
      
      compressorNode.lastReduction = currentReductionDb;
    };

    sourceNode = audioCtx.createMediaElementSource(previewPlayer);
    sourceNode.connect(compressorNode);
    compressorNode.connect(audioCtx.destination);

    updateLiveWebAudioParams();
  }

  function updateLiveWebAudioParams() {
    if (!compressorNode) return;
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
  }

  function startMeterLoop() {
    stopMeterLoop();
    function tick() {
      if (compressorNode && previewPlayer && !previewPlayer.paused) {
        const reductionDb = compressorNode.lastReduction ?? 0.0; // float (0 to -40 dB)
        const percent = Math.min(100, Math.abs(reductionDb) * 3.33);
        grMeterFill.style.height = `${percent}%`;
        grValue.textContent = `${reductionDb.toFixed(1)} dB`;
        animationFrameId = requestAnimationFrame(tick);
      } else {
        updateStaticGraphGR();
      }
    }
    animationFrameId = requestAnimationFrame(tick);
  }

  function stopMeterLoop() {
    if (animationFrameId !== null) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
  }

  const stepperGrid = document.createElement("div");
  stepperGrid.className = "compressor-stepper-grid";
  panel.appendChild(stepperGrid);

  const stepperDefs = [
    { key: "threshold_db", label: t("compressorThreshold"), step: 1, min: -60, max: 0, unit: "dB", decimals: 0, roundDecimals: 1 },
    { key: "ratio", label: t("compressorRatio"), step: 0.5, min: 1, max: 20, unit: ":1", decimals: 1, roundDecimals: 1 },
    { key: "knee_db", label: t("compressorKnee"), step: 1, min: 0, max: 24, unit: "dB", decimals: 0, roundDecimals: 1 },
    { key: "attack_ms", label: t("compressorAttack"), step: 1, min: 0.1, max: 200, unit: "ms", decimals: 0, roundDecimals: 1 },
    { key: "release_ms", label: t("compressorRelease"), step: 5, min: 1, max: 1000, unit: "ms", decimals: 0, roundDecimals: 1 },
    { key: "makeup_gain_db", label: t("compressorMakeup"), step: 1, min: -24, max: 24, unit: "dB", decimals: 0, roundDecimals: 1 },
  ];

  const knobRefreshFns = buildKnobGrid({
    container: stepperGrid,
    defs: stepperDefs,
    params,
    onChange: () => {
      updateGraph();
      updateLiveWebAudioParams();
    },
  });

  const detectorRow = document.createElement("div");
  detectorRow.className = "compressor-detector-row";

  const detectorLabel = document.createElement("label");
  detectorLabel.textContent = t("compressorDetectorMode");
  detectorRow.appendChild(detectorLabel);

  const detectorSelect = document.createElement("select");
  detectorSelect.className = "compressor-detector-select";

  const optRms = document.createElement("option");
  optRms.value = "rms";
  optRms.textContent = t("compressorDetectorRms");
  detectorSelect.appendChild(optRms);

  const optPeak = document.createElement("option");
  optPeak.value = "peak";
  optPeak.textContent = t("compressorDetectorPeak");
  detectorSelect.appendChild(optPeak);

  detectorSelect.value = params.detector || "rms";
  detectorRow.appendChild(detectorSelect);

  detectorSelect.addEventListener("change", () => {
    params.detector = detectorSelect.value;
    updateLiveWebAudioParams();
  });

  panel.appendChild(detectorRow);

  const presetsSection = buildPresetsSection({
    t,
    project,
    effectType: "compressor",
    params,
    refreshFns: [
      () => {
        knobRefreshFns.forEach((fn) => fn());
        detectorSelect.value = params.detector || "rms";
        updateGraph();
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

  updateGraph();

  previewPlayer.addEventListener("play", () => {
    initWebAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    updateLiveWebAudioParams();
    startMeterLoop();
  });

  previewPlayer.addEventListener("pause", () => {
    stopMeterLoop();
    updateStaticGraphGR();
  });

  previewPlayer.addEventListener("ended", () => {
    stopMeterLoop();
    updateStaticGraphGR();
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
    detectorSelect.value = params.detector || "rms";
    updateGraph();
    updateLiveWebAudioParams();
  });

  function closeOverlay() {
    stopMeterLoop();
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
