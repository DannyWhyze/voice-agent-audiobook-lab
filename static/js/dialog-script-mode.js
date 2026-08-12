import { t } from "./i18n.js";
import { insertAtCursor, getVoiceAccentColor } from "./shared.js";
import {
  getCurrentProject,
  getCurrentChapterName,
  getVoiceNamesCache,
  setDialogStatus,
  setLastFocusedTextarea,
} from "./dialog-context.js";
import {
  addDialogBox,
  applyVoiceAccent,
  getActiveBoxBlob,
  getBoxSpeakerName,
  populateVoiceSelect,
  refreshOverviewIfVisible,
  renderPauseConnectors,
  setBoxRecordedName,
  updateSpeakerLabel,
} from "./dialog-boxes.js";
import { saveDialogDraft } from "./dialog.js";
import { saveCurrentChapter } from "./dialog-projects.js";
import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlays/overlay-chrome.js";
import { openScriptChatOverlay, setScriptChatHistory } from "./overlays/script-chat-overlay.js";
import { loadScriptChatHistory, saveScriptChatHistory } from "./chat-history-storage.js";

const scriptPanel = document.getElementById("script-panel");
const scriptSpeakerSelect = document.getElementById("script-speaker-select");
const scriptInsertSpeakerBtn = document.getElementById("script-insert-speaker-btn");
const scriptTextarea = document.getElementById("script-textarea");
const scriptHighlightOverlay = document.getElementById("script-highlight");
const scriptApplyBtn = document.getElementById("script-apply-btn");
const toggleScriptPanelBtn = document.getElementById("toggle-script-panel-btn");
const dialogBoxesContainer = document.getElementById("dialog-boxes");

const SCRIPT_NO_VOICE_LABEL = "base_voice";

let scriptOverlayHeader = null;
let scriptResizeHandle = null;
let scriptOverlayBackdrop = null;
let stopScriptDragging = null;
let stopScriptResizing = null;
let scriptChatOverlayHandle = null;

export function refreshScriptFromBoxes() {
  if (!scriptTextarea) return;
  const scrollTop = scriptTextarea.scrollTop;
  const scrollLeft = scriptTextarea.scrollLeft;

  scriptTextarea.value = collectScriptText();
  updateScriptHighlight();

  scriptTextarea.scrollTop = scrollTop;
  scriptTextarea.scrollLeft = scrollLeft;
  if (scriptHighlightOverlay) {
    scriptHighlightOverlay.scrollTop = scrollTop;
    scriptHighlightOverlay.scrollLeft = scrollLeft;
  }
}

function collectScriptText() {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  return boxes
    .map((box) => {
      const speakerName = getBoxSpeakerName(box);
      const text = box.querySelector(".dialog-box-text").value;
      return `${speakerName || SCRIPT_NO_VOICE_LABEL}: ${text}`;
    })
    .join("\n");
}

function collectKnownRecordedNames() {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  return boxes
    .map((box) => getBoxSpeakerName(box))
    .filter((name) => name && !getVoiceNamesCache().includes(name));
}

function parseScriptTurns(text) {
  const knownRecordedNames = collectKnownRecordedNames();
  const turns = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const match = line.match(/^([^:]+):\s*(.*)$/);
    const speaker = match ? match[1].trim() : null;
    const matchedVoice = speaker
      ? getVoiceNamesCache().find((name) => name.toLowerCase() === speaker.toLowerCase())
      : null;
    const isNoVoice = speaker && speaker.toLowerCase() === SCRIPT_NO_VOICE_LABEL.toLowerCase();
    const matchedRecordedName = speaker
      ? knownRecordedNames.find((name) => name.toLowerCase() === speaker.toLowerCase())
      : null;

    if (match && (matchedVoice || isNoVoice || matchedRecordedName)) {
      turns.push({ voice: matchedVoice || "", recordedName: matchedRecordedName || null, text: match[2] });
    } else if (turns.length > 0) {
      turns[turns.length - 1].text += `\n${line}`;
    } else {
      turns.push({ voice: "", recordedName: null, text: line });
    }
  }
  return turns;
}

async function applyScriptTurns(turns) {
  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));

  for (let i = 0; i < Math.min(turns.length, boxes.length); i++) {
    const box = boxes[i];
    const turn = turns[i];
    box.querySelector(".dialog-box-text").value = turn.text;
    const voiceSelect = box.querySelector(".dialog-box-voice");
    voiceSelect.value = turn.voice;
    applyVoiceAccent(box, voiceSelect.value);
    updateSpeakerLabel(box, voiceSelect.value);
    box.querySelector(".dialog-box-voice-preview-btn").disabled = !voiceSelect.value;
    if (turn.recordedName) {
      setBoxRecordedName(box, turn.recordedName);
    }
  }

  for (let i = boxes.length - 1; i >= turns.length; i--) {
    boxes[i].remove();
  }

  for (let i = boxes.length; i < turns.length; i++) {
    addDialogBox({ voice: turns[i].voice, text: turns[i].text });
  }

  renderPauseConnectors();
  saveDialogDraft();
  refreshOverviewIfVisible();
  // Sync box add/remove to the server immediately, same as the box-level
  // remove/insert handlers (dialog-boxes.js) — otherwise chapter.json still
  // has the old box count/positions, and a new box later added at a reused
  // array position silently inherits that slot's old variant history on its
  // next generate/effect-apply. See docs/FIXES.md.
  await saveCurrentChapter({ silent: true });
}

function updateScriptHighlight() {
  const text = scriptTextarea.value;
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  const pattern = /(^|\n)([^:\n]+)(:)/g;

  html = html.replace(pattern, (match, before, speaker, colon) => {
    const trimmed = speaker.trim();
    const color = getVoiceAccentColor(trimmed) || "rgba(255, 255, 255, 0.45)";
    const style = `color: ${color}; font-weight: bold;`;
    return `${before}<span style="${style}">${speaker}</span>${colon}`;
  });

  html = html.replace(/(\[[^\]]+\])/g, '<span style="color: var(--color-accent); font-style: italic;">$1</span>');

  if (text.endsWith("\n")) {
    html += " ";
  }

  scriptHighlightOverlay.innerHTML = html;
}

scriptTextarea.addEventListener("input", updateScriptHighlight);
scriptTextarea.addEventListener("focus", () => {
  setLastFocusedTextarea(scriptTextarea);
});
scriptTextarea.addEventListener("scroll", () => {
  scriptHighlightOverlay.scrollTop = scriptTextarea.scrollTop;
  scriptHighlightOverlay.scrollLeft = scriptTextarea.scrollLeft;
});

function openScriptOverlay() {
  if (!scriptOverlayHeader) {
    scriptOverlayHeader = document.createElement("div");
    scriptOverlayHeader.className = "b2b-overlay-header";

    const title = document.createElement("h3");
    title.className = "b2b-overlay-title";
    title.textContent = "Bars2Bars Skript";
    scriptOverlayHeader.appendChild(title);

    const chatBtn = document.createElement("button");
    chatBtn.type = "button";
    chatBtn.className = "btn-compact";
    chatBtn.textContent = t("scriptChatBtn");
    chatBtn.addEventListener("click", () => {
      if (!getCurrentProject() || !getCurrentChapterName()) {
        alert(t("scriptChatNeedProject"));
        return;
      }
      if (scriptChatOverlayHandle) {
        scriptChatOverlayHandle.bringToFront();
        return;
      }
      scriptChatOverlayHandle = openScriptChatOverlay({
        t,
        chatUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/script-chat`,
        getCurrentText: () => scriptTextarea.value,
        onApply: (content) => {
          scriptTextarea.value = content;
          updateScriptHighlight();
        },
        onAppend: (content) => {
          const current = scriptTextarea.value;
          scriptTextarea.value = current && !current.endsWith("\n")
            ? `${current}\n${content}`
            : `${current}${content}`;
          updateScriptHighlight();
        },
        onHistoryChanged: (history) => {
          saveScriptChatHistory(getCurrentProject(), getCurrentChapterName(), history);
        },
        onClosed: () => {
          scriptChatOverlayHandle = null;
        },
      });
    });
    scriptOverlayHeader.appendChild(chatBtn);

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "compressor-overlay-close-btn";
    closeBtn.textContent = "✕";
    closeBtn.addEventListener("click", closeScriptOverlay);
    scriptOverlayHeader.appendChild(closeBtn);

    scriptPanel.classList.add("compressor-overlay-panel");
    scriptPanel.insertBefore(scriptOverlayHeader, scriptPanel.firstChild);

    scriptResizeHandle = document.createElement("div");
    scriptResizeHandle.className = "b2b-resize-handle";
    scriptPanel.appendChild(scriptResizeHandle);
  }

  scriptOverlayBackdrop = document.createElement("div");
  scriptOverlayBackdrop.className = "compressor-overlay-backdrop";
  scriptPanel.hidden = false;
  scriptOverlayBackdrop.appendChild(scriptPanel);
  document.body.appendChild(scriptOverlayBackdrop);

  stopScriptDragging = makeDraggable(scriptPanel, scriptOverlayHeader);
  stopScriptResizing = makeResizable(scriptPanel, scriptResizeHandle, "script");
  registerOverlay(scriptOverlayBackdrop, scriptPanel, closeScriptOverlay);
}

function closeScriptOverlay() {
  if (!scriptOverlayBackdrop) return;
  if (stopScriptDragging) {
    stopScriptDragging();
    stopScriptDragging = null;
  }
  if (stopScriptResizing) {
    stopScriptResizing();
    stopScriptResizing = null;
  }
  unregisterOverlay(scriptOverlayBackdrop);
  scriptOverlayBackdrop.remove();
  scriptOverlayBackdrop = null;
}

toggleScriptPanelBtn.addEventListener("click", () => {
  if (scriptOverlayBackdrop) {
    closeScriptOverlay();
    return;
  }
  if (getVoiceNamesCache().length === 0) {
    setDialogStatus(t("errorScriptNoVoices"), "error");
    return;
  }

  openScriptOverlay();

  scriptSpeakerSelect.innerHTML = "";
  populateVoiceSelect(scriptSpeakerSelect);
  delete scriptSpeakerSelect.options[0].dataset.i18n;
  scriptSpeakerSelect.options[0].textContent = SCRIPT_NO_VOICE_LABEL;

  if (!scriptTextarea.value.trim()) {
    scriptTextarea.value = collectScriptText();
  }
  updateScriptHighlight();
  refreshScriptFromBoxes();
});

scriptSpeakerSelect.addEventListener("change", () => {
  const selected = scriptSpeakerSelect.value || SCRIPT_NO_VOICE_LABEL;
  const currentVal = scriptTextarea.value;
  if (currentVal === `${SCRIPT_NO_VOICE_LABEL}: ` || currentVal === `${SCRIPT_NO_VOICE_LABEL}:`) {
    scriptTextarea.focus();
    scriptTextarea.select();
    try {
      if (!document.execCommand("insertText", false, `${selected}: `)) {
        throw new Error("execCommand failed");
      }
    } catch (e) {
      scriptTextarea.value = `${selected}: `;
    }
    updateScriptHighlight();
  }
});

scriptInsertSpeakerBtn.addEventListener("click", () => {
  const speaker = scriptSpeakerSelect.value || SCRIPT_NO_VOICE_LABEL;
  insertAtCursor(scriptTextarea, `\n${speaker}: `);
  updateScriptHighlight();
});

scriptApplyBtn.addEventListener("click", async () => {
  const turns = parseScriptTurns(scriptTextarea.value);
  if (turns.length === 0) return;

  const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
  const boxesToRemove = boxes.slice(turns.length);
  const removesAudio = boxesToRemove.some((box) => getActiveBoxBlob(box));
  if (removesAudio && !confirm(t("confirmScriptRemovesAudio"))) {
    return;
  }

  await applyScriptTurns(turns);
  scriptTextarea.value = "";
  updateScriptHighlight();
  closeScriptOverlay();
});
