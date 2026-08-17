import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";
import { getSelectedLLM } from "../llm-model-select.js";
import { streamChatMessage, renderChatMessages } from "./chat-shared.js";

const chatHistories = new WeakMap();

export function clearAllChatHistories(boxes) {
  for (const box of boxes) {
    chatHistories.set(box, []);
  }
}

export function restoreChatHistories(boxes, historiesArray) {
  boxes.forEach((box, index) => {
    chatHistories.set(box, historiesArray[index] || []);
  });
}

export function openChatOverlay({
  t,
  box,
  boxLabel,
  chatUrl,
  getCurrentText,
  getScriptOverview,
  onApply,
  onHistoryChanged,
  onMessageComplete,
  onClosed,
}) {
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
  title.textContent = boxLabel ? `Bars2Bars Chat — ${boxLabel}` : "Bars2Bars Chat";
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
  const stopResizing = makeResizable(panel, resizeHandle, "chat");

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

  const scriptContextRow = document.createElement("label");
  scriptContextRow.className = "chat-script-context-row";

  const scriptContextCheckbox = document.createElement("input");
  scriptContextCheckbox.type = "checkbox";
  scriptContextRow.appendChild(scriptContextCheckbox);
  scriptContextRow.appendChild(document.createTextNode(t("chatIncludeScript")));
  panel.appendChild(scriptContextRow);

  let includeScript = false;
  scriptContextCheckbox.addEventListener("change", () => {
    includeScript = scriptContextCheckbox.checked;
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
  resetBtn.textContent = t("chatReset");
  actionsRow.appendChild(resetBtn);
  panel.appendChild(actionsRow);

  let history = chatHistories.get(box) || [];
  let reasoningByIndex = new Map();
  let abortController = null;

  function refreshContextLabel() {
    const currentText = getCurrentText();
    contextLabel.textContent = currentText
      ? `${t("chatContextLabel")}: ${currentText}`
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
          label: t("chatApply"),
          appliedLabel: t("chatApplied"),
          onClick: () => onApply(message.content),
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
    chatHistories.set(box, history);
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
    chatHistories.set(box, history);
    if (onHistoryChanged) onHistoryChanged(history);
    renderMessages();

    abortController = new AbortController();
    try {
      const llmSelection = getSelectedLLM();
      const result = await streamChatMessage({
        chatUrl,
        body: {
          current_text: getCurrentText(),
          context_text: includeScript ? getScriptOverview() : null,
          messages: history
            .slice(0, -1)
            .map((message) => ({ role: message.role, content: message.content })),
          provider: llmSelection.provider,
          model: llmSelection.model,
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

      chatHistories.set(box, history);
      if (onHistoryChanged) onHistoryChanged(history);
      if (onMessageComplete) onMessageComplete();
    } catch (error) {
      if (!assistantMessage.content) {
        history.pop();
        chatHistories.set(box, history);
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
