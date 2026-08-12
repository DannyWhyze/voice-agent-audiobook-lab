import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { getSelectedLLM } from "../llm-model-select.js";
import { streamChatMessage, renderChatMessages } from "./chat-shared.js";

let history = [];
let reasoningByIndex = new Map();

export function setScriptChatHistory(newHistory) {
  history = newHistory || [];
  reasoningByIndex = new Map();
}

export function openScriptChatOverlay({ t, chatUrl, getCurrentText, onApply, onAppend, onHistoryChanged, onClosed }) {
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
  title.textContent = "Bars2Bars Skript-Chat";
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
  const stopResizing = makeResizable(panel, resizeHandle, "scriptChat");

  const contextLabel = document.createElement("div");
  contextLabel.className = "chat-context-label";
  panel.appendChild(contextLabel);

  const messageList = document.createElement("div");
  messageList.className = "chat-message-list";
  panel.appendChild(messageList);

  const errorLabel = document.createElement("div");
  errorLabel.className = "chat-error-label";
  errorLabel.hidden = true;
  panel.appendChild(errorLabel);

  const recordedRolesRow = document.createElement("label");
  recordedRolesRow.className = "chat-script-context-row";

  const recordedRolesCheckbox = document.createElement("input");
  recordedRolesCheckbox.type = "checkbox";
  recordedRolesRow.appendChild(recordedRolesCheckbox);
  recordedRolesRow.appendChild(document.createTextNode(t("scriptChatExtendRecordedRoles")));
  panel.appendChild(recordedRolesRow);

  let allowExtendRecordedRoles = false;
  recordedRolesCheckbox.addEventListener("change", () => {
    allowExtendRecordedRoles = recordedRolesCheckbox.checked;
  });

  const inputRow = document.createElement("div");
  inputRow.className = "chat-input-row";

  const input = document.createElement("textarea");
  input.className = "chat-input";
  input.rows = 2;
  input.placeholder = t("chatPlaceholder");
  inputRow.appendChild(input);

  const sendBtn = document.createElement("button");
  sendBtn.type = "button";
  sendBtn.className = "chat-send-btn btn-compact";
  sendBtn.textContent = t("chatSend");
  sendBtn.disabled = true;
  inputRow.appendChild(sendBtn);
  panel.appendChild(inputRow);

  const actionsRow = document.createElement("div");
  actionsRow.className = "compressor-actions-row";

  const resetBtn = document.createElement("button");
  resetBtn.type = "button";
  resetBtn.className = "compressor-reset-btn";
  resetBtn.textContent = t("scriptChatReset");
  actionsRow.appendChild(resetBtn);
  panel.appendChild(actionsRow);

  let abortController = null;

  function refreshContextLabel() {
    const currentText = getCurrentText();
    contextLabel.textContent = currentText
      ? `${t("scriptChatContextLabel")}: ${currentText}`
      : "";
    contextLabel.hidden = !currentText;
  }

  function renderMessages() {
    renderChatMessages({
      t,
      messageList,
      history,
      reasoningByIndex,
      onReasoningToggle: renderMessages,
      buildMessageActions: (message) => [
        {
          label: t("scriptChatApply"),
          appliedLabel: t("scriptChatApplied"),
          onClick: () => onApply(message.content),
        },
        {
          label: t("scriptChatAppend"),
          appliedLabel: t("scriptChatAppended"),
          onClick: () => onAppend(message.content),
        },
      ],
    });
  }

  function setInputEnabled(enabled) {
    input.disabled = !enabled;
    sendBtn.disabled = !enabled || input.value.trim() === "";
  }

  input.addEventListener("input", () => {
    sendBtn.disabled = input.value.trim() === "";
  });

  function closeOverlay() {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    stopDragging();
    stopResizing();
    unregisterOverlay(backdrop);
    backdrop.remove();
  }

  const overlayHandle = registerOverlay(backdrop, panel, closeOverlay, onClosed);

  closeBtn.addEventListener("click", closeOverlay);

  resetBtn.addEventListener("click", () => {
    history = [];
    reasoningByIndex = new Map();
    if (onHistoryChanged) onHistoryChanged(history);
    renderMessages();
  });

  async function sendMessage() {
    const content = input.value.trim();
    if (!content) return;

    input.value = "";
    setInputEnabled(false);
    errorLabel.hidden = true;

    history.push({ role: "user", content });
    const assistantMessage = { role: "assistant", content: "" };
    history.push(assistantMessage);
    const assistantIndex = history.length - 1;
    if (onHistoryChanged) onHistoryChanged(history);
    renderMessages();

    abortController = new AbortController();
    try {
      const llmSelection = getSelectedLLM();
      const result = await streamChatMessage({
        chatUrl,
        body: {
          current_text: getCurrentText(),
          context_text: null,
          messages: history
            .slice(0, -1)
            .map((message) => ({ role: message.role, content: message.content })),
          provider: llmSelection.provider,
          model: llmSelection.model,
          allow_extend_recorded_roles: allowExtendRecordedRoles,
        },
        signal: abortController.signal,
        onChunk: (chunk) => {
          if (!assistantMessage.content) {
            const entry = reasoningByIndex.get(assistantIndex);
            if (entry) entry.collapsed = true;
          }
          assistantMessage.content += chunk;
          renderMessages();
        },
        onReasoningChunk: (chunk) => {
          const entry = reasoningByIndex.get(assistantIndex) || { text: "", collapsed: false };
          entry.text += chunk;
          reasoningByIndex.set(assistantIndex, entry);
          renderMessages();
        },
      });

      if (!result.ok) {
        history.pop();
        errorLabel.textContent = t("chatErrorUnreachable", result.detail);
        errorLabel.hidden = false;
        renderMessages();
        return;
      }

      if (result.midStreamError) {
        if (!assistantMessage.content) {
          history.pop();
        }
        errorLabel.textContent = t("chatErrorMidStream", result.midStreamError);
        errorLabel.hidden = false;
      }

      if (onHistoryChanged) onHistoryChanged(history);
    } catch (error) {
      if (!assistantMessage.content) {
        history.pop();
        if (onHistoryChanged) onHistoryChanged(history);
      }
      if (error.name !== "AbortError") {
        errorLabel.textContent = t("chatErrorUnreachable", error.message);
        errorLabel.hidden = false;
      }
    } finally {
      abortController = null;
      setInputEnabled(true);
      renderMessages();
      refreshContextLabel();
    }
  }

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  renderMessages();
  refreshContextLabel();

  document.body.appendChild(backdrop);

  return overlayHandle;
}
