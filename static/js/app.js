const voiceSelect = document.getElementById("voice");
const voicePreviewBtn = document.getElementById("voice-preview-btn");
const voicePreviewPlayer = document.getElementById("voice-preview-player");
const form = document.getElementById("generate-form");
const statusEl = document.getElementById("status");
const player = document.getElementById("player");
const playerWaveform = document.getElementById("player-waveform");
const downloadLink = document.getElementById("download-link");
const textArea = document.getElementById("text");
const tagList = document.getElementById("tag-list");
const submitBtn = document.getElementById("generate-btn");
const cancelBtn = document.getElementById("cancel-btn");
const clearBtn = document.getElementById("clear-btn");

import { TAGS, fetchTags, insertAtCursor, attachWaveform, recordGenerationMetric, estimateGenerationSeconds } from "./shared.js";
import { t } from "./i18n.js";
import { initLLMModelSelect } from "./llm-model-select.js";

const TEXT_DRAFT_KEY = "fishaudio_text_draft";

function saveTextDraft() {
  localStorage.setItem(TEXT_DRAFT_KEY, JSON.stringify({
    text: textArea.value,
    voice: voiceSelect.value,
  }));
}

function loadTextDraft() {
  const raw = localStorage.getItem(TEXT_DRAFT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

let activeController = null;
let elapsedTimer = null;
let elapsedSeconds = 0;

function startElapsedTimer(estimateSeconds) {
  elapsedSeconds = 0;
  const suffix = estimateSeconds ? ` / ~${estimateSeconds}s` : "";
  setStatus(t("statusGenerating", suffix), "busy");
  elapsedTimer = setInterval(() => {
    elapsedSeconds += 1;
    setStatus(t("statusGeneratingTick", elapsedSeconds, suffix), "busy");
  }, 1000);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

async function loadTags() {
  await fetchTags();
  for (const tag of TAGS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-button";
    button.textContent = `[${tag}]`;
    button.addEventListener("click", () => {
      insertAtCursor(textArea, `[${tag}] `);
    });
    tagList.appendChild(button);
  }
}

async function loadVoices() {
  const noneOption = document.createElement("option");
  noneOption.value = "";
  noneOption.dataset.i18n = "noVoice";
  noneOption.textContent = t("noVoice");
  voiceSelect.appendChild(noneOption);

  let voiceNames;
  try {
    const response = await fetch("/voices");
    if (!response.ok) throw new Error(t("errorStatusCode", response.status));
    voiceNames = await response.json();
  } catch (error) {
    setStatus(t("errorLoadingVoices", error.message), "error");
    return;
  }

  for (const name of voiceNames) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    voiceSelect.appendChild(option);
  }
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.className = `status status-${state}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = textArea.value;
  const voice = voiceSelect.value || null;

  activeController = new AbortController();
  submitBtn.disabled = true;
  cancelBtn.disabled = false;
  const estimate = estimateGenerationSeconds(text.length, Boolean(voice));
  startElapsedTimer(estimate);
  player.removeAttribute("src");
  downloadLink.hidden = true;

  try {
    const response = await fetch("/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
      signal: activeController.signal,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(errorBody.detail || t("errorStatusCode", response.status));
    }

    const blob = await response.blob();
    if (player.src) {
      URL.revokeObjectURL(player.src);
    }
    player.src = URL.createObjectURL(blob);
    downloadLink.href = player.src;
    downloadLink.download = `fishaudio_einzeltext_${Date.now()}.wav`;
    downloadLink.hidden = false;
    setStatus(t("done"), "ok");
    recordGenerationMetric(text.length, Boolean(voice), elapsedSeconds);
  } catch (error) {
    if (error.name === "AbortError") {
      setStatus(t("aborted"), "idle");
    } else {
      setStatus(t("errorGeneric", error.message), "error");
    }
  } finally {
    stopElapsedTimer();
    submitBtn.disabled = false;
    cancelBtn.disabled = true;
    activeController = null;
  }
});

cancelBtn.addEventListener("click", () => {
  if (activeController) {
    activeController.abort();
  }
});

clearBtn.addEventListener("click", () => {
  textArea.value = "";
  voiceSelect.value = "";
  if (player.src) {
    URL.revokeObjectURL(player.src);
  }
  player.removeAttribute("src");
  downloadLink.hidden = true;
  if (voicePreviewPlayer.src) {
    URL.revokeObjectURL(voicePreviewPlayer.src);
  }
  voicePreviewPlayer.hidden = true;
  voicePreviewBtn.disabled = true;
  setStatus("", "idle");
  saveTextDraft();
});

voiceSelect.addEventListener("change", () => {
  voicePreviewBtn.disabled = !voiceSelect.value;
});

voicePreviewBtn.addEventListener("click", async () => {
  const voice = voiceSelect.value;
  if (!voice) return;

  if (
    !voicePreviewPlayer.hidden &&
    !voicePreviewPlayer.paused &&
    voicePreviewPlayer.dataset.voice === voice
  ) {
    voicePreviewPlayer.pause();
    voicePreviewPlayer.hidden = true;
    return;
  }

  voicePreviewBtn.disabled = true;
  try {
    const response = await fetch(`/voices/${encodeURIComponent(voice)}/preview`);
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(errorBody.detail || t("errorStatusCode", response.status));
    }

    const blob = await response.blob();
    if (voicePreviewPlayer.src) {
      URL.revokeObjectURL(voicePreviewPlayer.src);
    }
    voicePreviewPlayer.src = URL.createObjectURL(blob);
    voicePreviewPlayer.dataset.voice = voice;
    voicePreviewPlayer.hidden = false;
    voicePreviewPlayer.play();
  } catch (error) {
    setStatus(t("errorPreview", error.message), "error");
  } finally {
    voicePreviewBtn.disabled = false;
  }
});

textArea.addEventListener("input", saveTextDraft);
voiceSelect.addEventListener("change", saveTextDraft);

loadTags();
attachWaveform(player, playerWaveform);
initLLMModelSelect();
loadVoices().then(() => {
  const draft = loadTextDraft();
  if (draft) {
    if (draft.text) textArea.value = draft.text;
    if (draft.voice) voiceSelect.value = draft.voice;
  }
  voicePreviewBtn.disabled = !voiceSelect.value;
});
