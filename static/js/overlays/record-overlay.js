import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

const FALLBACK_SAMPLE_RATE = 44100;

function audioBufferToWav(buffer) {
  const numChannels = 1;
  const sampleRate = buffer.sampleRate;
  const samples = buffer.getChannelData(0);
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const dataSize = samples.length * bytesPerSample;
  const bufferArray = new ArrayBuffer(44 + dataSize);
  const view = new DataView(bufferArray);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 32768 : clamped * 32767, true);
    offset += 2;
  }

  return new Blob([bufferArray], { type: "audio/wav" });
}

async function resampleToTargetWav(blob, targetSampleRate) {
  const arrayBuffer = await blob.arrayBuffer();
  const tempCtx = new (window.AudioContext || window.webkitAudioContext)();
  const decoded = await tempCtx.decodeAudioData(arrayBuffer);
  await tempCtx.close();

  const offlineCtx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(
    1,
    Math.ceil(decoded.duration * targetSampleRate),
    targetSampleRate
  );
  const source = offlineCtx.createBufferSource();
  source.buffer = decoded;
  source.connect(offlineCtx.destination);
  source.start();
  const rendered = await offlineCtx.startRendering();

  return audioBufferToWav(rendered);
}

export function openRecordOverlay({ t, uploadUrl, referenceFramerateUrl, onApplied, onClosed }) {
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
  title.textContent = "Bars2Bars Record";
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
  const stopResizing = makeResizable(panel, resizeHandle, "record");

  const timerLabel = document.createElement("div");
  timerLabel.className = "record-timer";
  timerLabel.textContent = "00:00";
  panel.appendChild(timerLabel);

  const levelTrack = document.createElement("div");
  levelTrack.className = "record-level-bar-track";
  const levelFill = document.createElement("div");
  levelFill.className = "record-level-bar-fill";
  levelTrack.appendChild(levelFill);
  panel.appendChild(levelTrack);

  const errorLabel = document.createElement("div");
  errorLabel.className = "chat-error-label";
  errorLabel.hidden = true;
  panel.appendChild(errorLabel);

  const previewPlayer = document.createElement("audio");
  previewPlayer.controls = true;
  previewPlayer.hidden = true;
  panel.appendChild(previewPlayer);

  const actionsRow = document.createElement("div");
  actionsRow.className = "compressor-actions-row";

  const startBtn = document.createElement("button");
  startBtn.type = "button";
  startBtn.className = "compressor-preview-btn";
  startBtn.textContent = t("recordStartBtn");

  const stopBtn = document.createElement("button");
  stopBtn.type = "button";
  stopBtn.className = "compressor-apply-btn";
  stopBtn.textContent = t("recordStopBtn");
  stopBtn.hidden = true;

  const discardBtn = document.createElement("button");
  discardBtn.type = "button";
  discardBtn.className = "compressor-reset-btn";
  discardBtn.textContent = t("recordDiscardBtn");
  discardBtn.hidden = true;

  const useBtn = document.createElement("button");
  useBtn.type = "button";
  useBtn.className = "compressor-apply-btn";
  useBtn.textContent = t("recordUseBtn");
  useBtn.hidden = true;

  actionsRow.appendChild(startBtn);
  actionsRow.appendChild(stopBtn);
  actionsRow.appendChild(discardBtn);
  actionsRow.appendChild(useBtn);
  panel.appendChild(actionsRow);

  let mediaStream = null;
  let mediaRecorder = null;
  let recordedChunks = [];
  let recordedBlob = null;
  let audioCtx = null;
  let analyser = null;
  let rafId = null;
  let timerInterval = null;
  let elapsedSeconds = 0;

  function showError(message) {
    errorLabel.textContent = message;
    errorLabel.hidden = false;
  }

  function hideError() {
    errorLabel.hidden = true;
  }

  function resetToRecordingPhase() {
    previewPlayer.hidden = true;
    if (previewPlayer.src) {
      URL.revokeObjectURL(previewPlayer.src);
      previewPlayer.src = "";
    }
    discardBtn.hidden = true;
    useBtn.hidden = true;
    startBtn.hidden = false;
    timerLabel.textContent = "00:00";
    levelFill.style.width = "0%";
    recordedBlob = null;
  }

  function updateLevelMeter() {
    if (!analyser) return;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (let i = 0; i < data.length; i++) {
      const normalized = (data[i] - 128) / 128;
      sumSquares += normalized * normalized;
    }
    const rms = Math.sqrt(sumSquares / data.length);
    levelFill.style.width = `${Math.min(100, rms * 200)}%`;
    rafId = requestAnimationFrame(updateLevelMeter);
  }

  async function startRecording() {
    hideError();
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      showError(t("recordMicError", error.message));
      return;
    }

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioCtx = new AudioContextClass();
    const source = audioCtx.createMediaStreamSource(mediaStream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    updateLevelMeter();

    recordedChunks = [];
    mediaRecorder = new MediaRecorder(mediaStream);
    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) recordedChunks.push(event.data);
    });
    mediaRecorder.addEventListener("stop", () => {
      recordedBlob = new Blob(recordedChunks, { type: mediaRecorder.mimeType });
      previewPlayer.src = URL.createObjectURL(recordedBlob);
      previewPlayer.hidden = false;
      discardBtn.hidden = false;
      useBtn.hidden = false;
    });
    mediaRecorder.start();

    elapsedSeconds = 0;
    timerLabel.textContent = "00:00";
    timerInterval = setInterval(() => {
      elapsedSeconds += 1;
      const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
      const seconds = String(elapsedSeconds % 60).padStart(2, "0");
      timerLabel.textContent = `${minutes}:${seconds}`;
    }, 1000);

    startBtn.hidden = true;
    stopBtn.hidden = false;
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    if (mediaStream) {
      for (const track of mediaStream.getTracks()) track.stop();
      mediaStream = null;
    }
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (audioCtx && audioCtx.state !== "closed") {
      audioCtx.close();
    }
    clearInterval(timerInterval);
    levelFill.style.width = "0%";
    stopBtn.hidden = true;
  }

  function closeOverlay() {
    stopRecording();
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
  startBtn.addEventListener("click", startRecording);
  stopBtn.addEventListener("click", stopRecording);

  discardBtn.addEventListener("click", () => {
    resetToRecordingPhase();
  });

  useBtn.addEventListener("click", async () => {
    if (!recordedBlob) return;
    useBtn.disabled = true;
    discardBtn.disabled = true;
    hideError();
    try {
      let targetSampleRate = FALLBACK_SAMPLE_RATE;
      try {
        const rateResponse = await fetch(referenceFramerateUrl);
        if (rateResponse.ok) {
          const rateData = await rateResponse.json();
          targetSampleRate = rateData.framerate || FALLBACK_SAMPLE_RATE;
        }
      } catch {
        // Fall back to FALLBACK_SAMPLE_RATE if the lookup itself fails.
      }

      const wavBlob = await resampleToTargetWav(recordedBlob, targetSampleRate);
      const formData = new FormData();
      formData.append("audio", wavBlob, "recording.wav");
      const response = await fetch(uploadUrl, { method: "POST", body: formData });
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        showError(t("recordErrorUpload", errorBody.detail || response.statusText));
        return;
      }
      closeOverlay();
      await onApplied(response);
    } catch (error) {
      showError(t("recordErrorUpload", error.message));
    } finally {
      useBtn.disabled = false;
      discardBtn.disabled = false;
    }
  });

  document.body.appendChild(backdrop);

  return overlayHandle;
}
