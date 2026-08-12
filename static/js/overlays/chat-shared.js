export async function streamChatMessage({ chatUrl, body, signal, onChunk, onReasoningChunk }) {
  const response = await fetch(chatUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    return { ok: false, detail: errorBody.detail || response.statusText };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamDone = false;
  let midStreamError = null;

  while (!streamDone) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while (!streamDone && (boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let eventType = "message";
      let dataLine = "";
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event: ")) {
          eventType = line.slice("event: ".length);
        } else if (line.startsWith("data: ")) {
          dataLine = line.slice("data: ".length);
        }
      }

      if (eventType === "done") {
        streamDone = true;
      } else if (eventType === "error") {
        const errorData = JSON.parse(dataLine);
        midStreamError = errorData.detail;
        streamDone = true;
      } else if (eventType === "reasoning") {
        const data = JSON.parse(dataLine);
        onReasoningChunk(data.chunk);
      } else {
        const data = JSON.parse(dataLine);
        onChunk(data.chunk);
      }
    }
  }

  return { ok: true, midStreamError };
}

export function renderChatMessages({ t, messageList, history, reasoningByIndex, buildMessageActions, onReasoningToggle }) {
  messageList.innerHTML = "";
  history.forEach((message, index) => {
    if (message.role === "assistant") {
      const reasoning = reasoningByIndex.get(index);
      if (reasoning && reasoning.text) {
        const block = document.createElement("div");
        block.className = "chat-reasoning-block";
        block.dataset.collapsed = reasoning.collapsed ? "true" : "false";

        const header = document.createElement("button");
        header.type = "button";
        header.className = "chat-reasoning-header";

        const chevron = document.createElement("span");
        chevron.className = "chat-reasoning-chevron";
        chevron.textContent = "▾";
        header.appendChild(chevron);
        header.appendChild(document.createTextNode(t("chatReasoningLabel")));

        header.addEventListener("click", () => {
          reasoning.collapsed = !reasoning.collapsed;
          onReasoningToggle();
        });
        block.appendChild(header);

        const body = document.createElement("div");
        body.className = "chat-reasoning-body";
        body.textContent = reasoning.text;
        block.appendChild(body);

        messageList.appendChild(block);
      }
    }

    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble-${message.role}`;

    const textEl = document.createElement("div");
    textEl.className = "chat-bubble-text";
    textEl.textContent = message.content;
    bubble.appendChild(textEl);

    if (message.role === "assistant" && message.content) {
      const actions = buildMessageActions(message);
      if (actions.length > 0) {
        const actionsRow = document.createElement("div");
        actionsRow.className = "chat-bubble-apply-row";
        for (const action of actions) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "chat-bubble-apply-btn btn-compact";
          btn.textContent = action.label;
          btn.addEventListener("click", () => {
            action.onClick();
            btn.textContent = action.appliedLabel;
            btn.disabled = true;
            setTimeout(() => {
              btn.textContent = action.label;
              btn.disabled = false;
            }, 1500);
          });
          actionsRow.appendChild(btn);
        }
        bubble.appendChild(actionsRow);
      }
    }

    messageList.appendChild(bubble);
  });
  messageList.scrollTop = messageList.scrollHeight;
}
