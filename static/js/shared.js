export let TAGS = [];

export async function fetchTags() {
  try {
    const response = await fetch("/tags");
    if (response.ok) {
      TAGS = await response.json();
    }
  } catch {
    // Tag buttons are a convenience feature; failing silently just means none render.
  }
}

export function insertAtCursor(textarea, text) {
  textarea.focus();
  try {
    if (!document.execCommand("insertText", false, text)) {
      throw new Error("execCommand failed");
    }
  } catch (e) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    textarea.value = `${before}${text}${after}`;
    const cursorPos = start + text.length;
    textarea.setSelectionRange(cursorPos, cursorPos);
  }
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

let audioCtx = null;
const attachedElements = new WeakSet();

export function attachWaveform(audioEl, canvasEl, meterMaskEl) {
  if (attachedElements.has(audioEl)) return;
  attachedElements.add(audioEl);

  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }

  const source = audioCtx.createMediaElementSource(audioEl);
  const gainNode = audioCtx.createGain();
  const pannerNode = audioCtx.createStereoPanner();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 128;
  source.connect(gainNode);
  gainNode.connect(pannerNode);
  pannerNode.connect(analyser);
  analyser.connect(audioCtx.destination);

  const canvasCtx = canvasEl.getContext("2d");
  const bufferLength = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);
  const timeDataArray = new Uint8Array(analyser.fftSize);
  let rafId = null;

  function draw() {
    rafId = requestAnimationFrame(draw);
    analyser.getByteFrequencyData(dataArray);

    const width = canvasEl.width;
    const height = canvasEl.height;
    canvasCtx.clearRect(0, 0, width, height);

    const barWidth = width / bufferLength;
    for (let i = 0; i < bufferLength; i++) {
      const barHeight = (dataArray[i] / 255) * height;
      canvasCtx.fillStyle = "rgba(255, 255, 255, 0.6)";
      canvasCtx.fillRect(i * barWidth, height - barHeight, barWidth - 1, barHeight);
    }

    if (meterMaskEl) {
      analyser.getByteTimeDomainData(timeDataArray);
      let sumSquares = 0;
      for (let i = 0; i < timeDataArray.length; i++) {
        const normalized = (timeDataArray[i] - 128) / 128;
        sumSquares += normalized * normalized;
      }
      const rms = Math.sqrt(sumSquares / timeDataArray.length);
      const db = rms > 0 ? 20 * Math.log10(rms) : -24;
      const clampedDb = Math.max(-24, Math.min(24, db));
      const percent = ((clampedDb - -24) / 48) * 100;
      meterMaskEl.style.width = (100 - percent) + "%";
    }
  }

  audioEl.addEventListener("play", () => {
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    if (!rafId) draw();
  });

  audioEl.addEventListener("pause", stopDrawing);
  audioEl.addEventListener("ended", stopDrawing);

  function stopDrawing() {
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    canvasCtx.clearRect(0, 0, canvasEl.width, canvasEl.height);
    if (meterMaskEl) meterMaskEl.style.width = "100%";
  }

  return { gainNode, pannerNode };
}

export function connectToGain(audioEl, gainNode) {
  if (attachedElements.has(audioEl)) return;
  attachedElements.add(audioEl);

  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }

  const source = audioCtx.createMediaElementSource(audioEl);
  source.connect(gainNode);
}

export async function measureLoudnessDb(blob) {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  const arrayBuffer = await blob.arrayBuffer();
  const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
  const channelData = audioBuffer.getChannelData(0);

  let sumSquares = 0;
  for (let i = 0; i < channelData.length; i++) {
    sumSquares += channelData[i] * channelData[i];
  }
  const rms = Math.sqrt(sumSquares / channelData.length);
  return rms > 0 ? 20 * Math.log10(rms) : null;
}

const METRICS_KEY = "fishaudio_generation_metrics";
const MAX_METRICS = 50;

function readMetrics() {
  const raw = localStorage.getItem(METRICS_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export function recordGenerationMetric(charCount, hasVoice, seconds) {
  const metrics = readMetrics();
  metrics.push({ charCount, hasVoice, seconds });
  localStorage.setItem(METRICS_KEY, JSON.stringify(metrics.slice(-MAX_METRICS)));
}

export function estimateGenerationSeconds(charCount, hasVoice) {
  const metrics = readMetrics();
  const matching = metrics.filter((m) => m.hasVoice === hasVoice);
  const pool = matching.length >= 3 ? matching : metrics;
  if (pool.length < 3) return null;

  const totalChars = pool.reduce((sum, m) => sum + m.charCount, 0);
  const totalSeconds = pool.reduce((sum, m) => sum + m.seconds, 0);
  if (totalChars === 0) return null;

  const secondsPerChar = totalSeconds / totalChars;
  return Math.max(1, Math.round(secondsPerChar * charCount));
}

export const SPEAKER_ACCENTS = [
  "#6b8cbe",
  "#e8823c",
  "#7fae7a",
  "#b58ad1",
  "#d4a24c",
  "#5aa8a0",
  "#e06c75",
  "#4db6ac",
  "#ffb74d",
  "#ba68c8",
  "#4dd0e1",
  "#aed581",
];

export function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function voiceAccentColor(voiceName) {
  if (!voiceName) return null;
  const lower = voiceName.toLowerCase();
  if (lower === "base_voice" || lower === "(keine stimme)") return "rgba(255, 255, 255, 0.45)";
  return SPEAKER_ACCENTS[hashString(lower) % SPEAKER_ACCENTS.length];
}

const assignedVoiceColors = new Map();

export function getVoiceAccentColor(voiceName) {
  if (!voiceName) return null;
  const lower = voiceName.toLowerCase();
  if (lower === "base_voice" || lower === "(keine stimme)") return "rgba(255, 255, 255, 0.45)";

  if (assignedVoiceColors.has(lower)) {
    return assignedVoiceColors.get(lower);
  }

  const usedColors = new Set(assignedVoiceColors.values());
  const startIndex = hashString(lower) % SPEAKER_ACCENTS.length;
  let chosenColor = null;
  for (let offset = 0; offset < SPEAKER_ACCENTS.length; offset++) {
    const candidate = SPEAKER_ACCENTS[(startIndex + offset) % SPEAKER_ACCENTS.length];
    if (!usedColors.has(candidate)) {
      chosenColor = candidate;
      break;
    }
  }
  if (chosenColor === null) {
    chosenColor = SPEAKER_ACCENTS[startIndex];
  }

  assignedVoiceColors.set(lower, chosenColor);
  return chosenColor;
}

export function reorderChapters(chapters, draggedName, targetName) {
  const without = chapters.filter((name) => name !== draggedName);
  if (targetName === null) {
    without.push(draggedName);
    return without;
  }
  without.splice(without.indexOf(targetName), 0, draggedName);
  return without;
}

