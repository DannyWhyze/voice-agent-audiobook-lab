import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

export function openTrimOverlay({ t, sourceUrl, applyUrl, fadeApplyUrl, onActivateVariant, onApplied, onClosed }) {
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
  title.textContent = "Bars2Bars Trim/Fade";
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
  const stopResizing = makeResizable(panel, resizeHandle, "trim");

  const waveformContainer = document.createElement("div");
  waveformContainer.className = "trim-waveform-container";
  panel.appendChild(waveformContainer);

  const canvas = document.createElement("canvas");
  canvas.className = "trim-waveform-canvas";
  canvas.width = 572;
  canvas.height = 120;
  waveformContainer.appendChild(canvas);

  const startMarker = document.createElement("div");
  startMarker.className = "trim-marker";
  const startLabel = document.createElement("span");
  startLabel.className = "trim-marker-label";
  startMarker.appendChild(startLabel);
  waveformContainer.appendChild(startMarker);

  const endMarker = document.createElement("div");
  endMarker.className = "trim-marker";
  const endLabel = document.createElement("span");
  endLabel.className = "trim-marker-label";
  endMarker.appendChild(endLabel);
  waveformContainer.appendChild(endMarker);

  const fadeInHandle = document.createElement("div");
  fadeInHandle.className = "trim-fade-handle";
  waveformContainer.appendChild(fadeInHandle);

  const fadeOutHandle = document.createElement("div");
  fadeOutHandle.className = "trim-fade-handle trim-fade-handle-out";
  waveformContainer.appendChild(fadeOutHandle);

  let audioCtx = null;
  let audioBuffer = null;
  let duration = 0;
  let startSeconds = 0;
  let endSeconds = 0;
  let activeSourceNode = null;
  let fadeInSeconds = 0;
  let fadeOutSeconds = 0;

  function secondsToPixels(seconds) {
    return (seconds / duration) * waveformContainer.clientWidth;
  }

  function pixelsToSeconds(pixels) {
    return (pixels / waveformContainer.clientWidth) * duration;
  }

  function refreshMarkers() {
    startMarker.style.left = `${secondsToPixels(startSeconds)}px`;
    endMarker.style.left = `${secondsToPixels(endSeconds)}px`;
    startLabel.textContent = startSeconds.toFixed(2) + "s";
    endLabel.textContent = endSeconds.toFixed(2) + "s";
  }

  function refreshFadeHandles() {
    fadeInHandle.style.left = `${secondsToPixels(startSeconds + fadeInSeconds)}px`;
    fadeOutHandle.style.left = `${secondsToPixels(endSeconds - fadeOutSeconds)}px`;
  }

  function drawWaveform() {
    const canvasCtx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    canvasCtx.clearRect(0, 0, width, height);
    if (!audioBuffer) return;

    const channelCount = audioBuffer.numberOfChannels;
    const channelData = [];
    for (let c = 0; c < channelCount; c++) {
      channelData.push(audioBuffer.getChannelData(c));
    }
    const sampleCount = audioBuffer.length;
    const samplesPerPixel = Math.max(1, Math.floor(sampleCount / width));

    canvasCtx.fillStyle = "rgba(255, 255, 255, 0.6)";
    for (let x = 0; x < width; x++) {
      const start = x * samplesPerPixel;
      const end = Math.min(sampleCount, start + samplesPerPixel);
      let peak = 0;
      for (let i = start; i < end; i++) {
        for (let c = 0; c < channelCount; c++) {
          const value = Math.abs(channelData[c][i]);
          if (value > peak) peak = value;
        }
      }
      const barHeight = peak * height;
      canvasCtx.fillRect(x, (height - barHeight) / 2, 1, barHeight);
    }
    drawFadeOverlay(canvasCtx, width, height);
  }

  function drawFadeOverlay(canvasCtx, width, height) {
    canvasCtx.fillStyle = "rgba(0, 0, 0, 0.35)";
    if (fadeInSeconds > 0) {
      const fadeStartX = (startSeconds / duration) * width;
      const fadeEndX = (Math.min(startSeconds + fadeInSeconds, endSeconds) / duration) * width;
      canvasCtx.beginPath();
      canvasCtx.moveTo(fadeStartX, 0);
      canvasCtx.lineTo(fadeEndX, 0);
      canvasCtx.lineTo(fadeStartX, height);
      canvasCtx.closePath();
      canvasCtx.fill();
    }
    if (fadeOutSeconds > 0) {
      const fadeStartX = (Math.max(endSeconds - fadeOutSeconds, startSeconds) / duration) * width;
      const fadeEndX = (endSeconds / duration) * width;
      canvasCtx.beginPath();
      canvasCtx.moveTo(fadeStartX, 0);
      canvasCtx.lineTo(fadeEndX, 0);
      canvasCtx.lineTo(fadeEndX, height);
      canvasCtx.closePath();
      canvasCtx.fill();
    }
  }

  function setupMarkerDrag(marker, isStart) {
    let dragging = false;

    marker.addEventListener("pointerdown", (event) => {
      dragging = true;
      marker.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    marker.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = waveformContainer.getBoundingClientRect();
      const pixels = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const seconds = pixelsToSeconds(pixels);
      if (isStart) {
        startSeconds = Math.max(0, Math.min(seconds, endSeconds));
      } else {
        endSeconds = Math.min(duration, Math.max(seconds, startSeconds));
      }
      const available = endSeconds - startSeconds;
      fadeInSeconds = Math.max(0, Math.min(fadeInSeconds, available - fadeOutSeconds));
      fadeOutSeconds = Math.max(0, Math.min(fadeOutSeconds, available - fadeInSeconds));
      refreshMarkers();
      refreshFadeHandles();
      drawWaveform();
    });

    function endDrag(event) {
      if (dragging) {
        dragging = false;
        marker.releasePointerCapture(event.pointerId);
      }
    }
    marker.addEventListener("pointerup", endDrag);
    marker.addEventListener("pointercancel", endDrag);
  }

  setupMarkerDrag(startMarker, true);
  setupMarkerDrag(endMarker, false);

  function setupFadeHandleDrag(handle, isFadeIn) {
    let dragging = false;

    handle.addEventListener("pointerdown", (event) => {
      dragging = true;
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    handle.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = waveformContainer.getBoundingClientRect();
      const pixels = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const seconds = pixelsToSeconds(pixels);
      const available = endSeconds - startSeconds;
      if (isFadeIn) {
        fadeInSeconds = Math.max(0, Math.min(seconds - startSeconds, available - fadeOutSeconds));
      } else {
        fadeOutSeconds = Math.max(0, Math.min(endSeconds - seconds, available - fadeInSeconds));
      }
      refreshFadeHandles();
      drawWaveform();
    });

    function endDrag(event) {
      if (dragging) {
        dragging = false;
        handle.releasePointerCapture(event.pointerId);
      }
    }
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  }

  setupFadeHandleDrag(fadeInHandle, true);
  setupFadeHandleDrag(fadeOutHandle, false);

  const actionsRow = document.createElement("div");
  actionsRow.className = "compressor-actions-row";

  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.className = "compressor-preview-btn";
  previewBtn.textContent = t("compressorPreview");
  previewBtn.disabled = true;

  const applyBtn = document.createElement("button");
  applyBtn.type = "button";
  applyBtn.className = "compressor-apply-btn";
  applyBtn.textContent = t("compressorApply");
  applyBtn.disabled = true;

  function closeOverlay() {
    if (activeSourceNode) {
      try {
        activeSourceNode.stop();
      } catch {
        // already stopped
      }
      activeSourceNode = null;
    }
    if (audioCtx && audioCtx.state !== "closed") {
      audioCtx.close();
    }
    stopDragging();
    stopResizing();
    unregisterOverlay(backdrop);
    backdrop.remove();
  }

  const overlayHandle = registerOverlay(backdrop, panel, closeOverlay, onClosed);

  closeBtn.addEventListener("click", closeOverlay);

  function buildFadeCurve(previewDuration, fadeIn, fadeOut, pointCount = 50) {
    const curve = new Float32Array(pointCount);
    for (let i = 0; i < pointCount; i++) {
      const timeInPreview = (i / (pointCount - 1)) * previewDuration;
      let gain = 1.0;
      if (fadeIn > 0 && timeInPreview < fadeIn) {
        gain = Math.sin((timeInPreview / fadeIn) * (Math.PI / 2));
      } else if (fadeOut > 0 && timeInPreview > previewDuration - fadeOut) {
        const t = (timeInPreview - (previewDuration - fadeOut)) / fadeOut;
        gain = Math.cos(t * (Math.PI / 2));
      }
      curve[i] = gain;
    }
    return curve;
  }

  previewBtn.addEventListener("click", () => {
    if (!audioBuffer || !audioCtx) return;
    if (activeSourceNode) {
      try {
        activeSourceNode.stop();
      } catch {
        // already stopped
      }
    }
    activeSourceNode = audioCtx.createBufferSource();
    activeSourceNode.buffer = audioBuffer;
    const gainNode = audioCtx.createGain();
    activeSourceNode.connect(gainNode);
    gainNode.connect(audioCtx.destination);

    const previewDuration = endSeconds - startSeconds;
    if (fadeInSeconds > 0 || fadeOutSeconds > 0) {
      gainNode.gain.setValueCurveAtTime(
        buildFadeCurve(previewDuration, fadeInSeconds, fadeOutSeconds),
        audioCtx.currentTime,
        previewDuration
      );
    }
    activeSourceNode.start(0, startSeconds, previewDuration);
  });

  applyBtn.addEventListener("click", async () => {
    previewBtn.disabled = true;
    applyBtn.disabled = true;
    try {
      const trimChanged = startSeconds > 0 || endSeconds < duration;
      const fadeChanged = fadeInSeconds > 0 || fadeOutSeconds > 0;
      let response = null;

      if (trimChanged) {
        response = await fetch(applyUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            start_ms: startSeconds * 1000,
            end_ms: endSeconds * 1000,
          }),
        });
        if (!response.ok) return;
        if (fadeChanged) {
          const filename = response.headers.get("X-Variant-Filename");
          await onActivateVariant(filename);
        }
      }

      if (fadeChanged) {
        response = await fetch(fadeApplyUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            fade_in_ms: fadeInSeconds * 1000,
            fade_out_ms: fadeOutSeconds * 1000,
          }),
        });
      }

      if (response && response.ok) {
        closeOverlay();
        await onApplied(response);
      }
    } finally {
      previewBtn.disabled = false;
      applyBtn.disabled = false;
    }
  });

  actionsRow.appendChild(previewBtn);
  actionsRow.appendChild(applyBtn);
  panel.appendChild(actionsRow);

  document.body.appendChild(backdrop);

  (async () => {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      waveformContainer.textContent = t("trimLoadError");
      return;
    }
    audioCtx = new AudioContextClass();

    try {
      const response = await fetch(sourceUrl);
      if (!response.ok) throw new Error("fetch failed");
      const arrayBuffer = await response.arrayBuffer();
      audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    } catch {
      waveformContainer.textContent = t("trimLoadError");
      return;
    }

    duration = audioBuffer.duration;
    startSeconds = 0;
    endSeconds = duration;

    drawWaveform();
    refreshMarkers();
    refreshFadeHandles();
    previewBtn.disabled = false;
    applyBtn.disabled = false;
  })();

  return overlayHandle;
}


