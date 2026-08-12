import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

export function openVoicesOverlay({ t, onClosed, onVoicesChanged }) {
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
  title.textContent = t("voicesOverlayTitle");
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
  const stopResizing = makeResizable(panel, resizeHandle, "voices");

  const errorLabel = document.createElement("div");
  errorLabel.className = "skills-files-error";
  errorLabel.hidden = true;
  panel.appendChild(errorLabel);

  const activeHint = document.createElement("p");
  activeHint.className = "voices-overlay-hint";
  activeHint.textContent = t("voicesOverlayActiveHint");
  panel.appendChild(activeHint);

  const bulkRow = document.createElement("div");
  bulkRow.className = "voices-overlay-bulk-row";
  panel.appendChild(bulkRow);

  const activateAllBtn = document.createElement("button");
  activateAllBtn.type = "button";
  activateAllBtn.className = "pause-connector-insert-btn";
  activateAllBtn.textContent = t("voicesOverlayActivateAllBtn");
  bulkRow.appendChild(activateAllBtn);

  const deactivateAllBtn = document.createElement("button");
  deactivateAllBtn.type = "button";
  deactivateAllBtn.className = "pause-connector-insert-btn";
  deactivateAllBtn.textContent = t("voicesOverlayDeactivateAllBtn");
  bulkRow.appendChild(deactivateAllBtn);

  const list = document.createElement("div");
  list.className = "voices-overlay-list";
  panel.appendChild(list);

  let currentVoiceNames = [];

  async function setAllActive(active) {
    clearError();
    const results = await Promise.all(
      currentVoiceNames.map((name) =>
        fetch(`/voices/${encodeURIComponent(name)}/active`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active }),
        })
      )
    );
    if (results.some((r) => !r.ok)) {
      showError(t("voicesOverlayError"));
    }
    await loadList();
    if (onVoicesChanged) onVoicesChanged();
  }

  activateAllBtn.addEventListener("click", () => setAllActive(true));
  deactivateAllBtn.addEventListener("click", () => setAllActive(false));

  function showError(message) {
    errorLabel.textContent = message;
    errorLabel.hidden = false;
  }

  function clearError() {
    errorLabel.hidden = true;
  }

  function formatUsage(usages) {
    return usages
      .map((u) => `${u.project} / ${u.chapter} / Box ${u.box_index + 1}`)
      .join("\n");
  }

  async function loadList() {
    clearError();
    list.innerHTML = "";
    const response = await fetch("/voices/detail");
    if (!response.ok) {
      showError(t("voicesOverlayLoadError"));
      return;
    }
    const voices = await response.json();
    currentVoiceNames = voices.map((voice) => voice.name);
    const groups = new Map();
    for (const voice of voices) {
      const key = voice.folder || "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(voice);
    }
    for (const voice of groups.get("") || []) {
      list.appendChild(buildRow(voice.name, voice.locked, voice.active));
    }
    groups.delete("");
    for (const folder of [...groups.keys()].sort()) {
      const details = document.createElement("details");
      details.className = "voices-overlay-group";
      details.open = true;
      const summary = document.createElement("summary");
      summary.className = "voices-overlay-group-heading";
      summary.textContent = folder;
      details.appendChild(summary);
      for (const voice of groups.get(folder)) {
        details.appendChild(buildRow(voice.name, voice.locked, voice.active));
      }
      list.appendChild(details);
    }
  }

  function buildRow(name, initialLocked, initialActive) {
    let locked = initialLocked;
    let active = initialActive;
    const row = document.createElement("div");
    row.className = "voices-overlay-row";
    row.classList.toggle("voices-overlay-row-inactive", !active);

    const preview = document.createElement("audio");
    preview.controls = true;
    preview.preload = "metadata";
    preview.src = `/voices/${encodeURIComponent(name)}/preview`;
    row.appendChild(preview);

    const controls = document.createElement("div");
    controls.className = "voices-overlay-row-controls";
    row.appendChild(controls);

    const activeBtn = document.createElement("button");
    activeBtn.type = "button";
    activeBtn.className = "pause-connector-insert-btn";
    controls.appendChild(activeBtn);

    function updateActiveUI() {
      activeBtn.textContent = active ? "👁" : "🚫";
      activeBtn.title = active
        ? t("voicesOverlayActiveOnTitle")
        : t("voicesOverlayActiveOffTitle");
      row.classList.toggle("voices-overlay-row-inactive", !active);
    }
    updateActiveUI();

    activeBtn.addEventListener("click", async () => {
      clearError();
      const response = await fetch(`/voices/${encodeURIComponent(name)}/active`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !active }),
      });
      if (!response.ok) {
        showError(t("voicesOverlayError"));
        return;
      }
      active = !active;
      updateActiveUI();
      if (onVoicesChanged) onVoicesChanged();
    });

    const nameLabel = document.createElement("span");
    nameLabel.className = "voices-overlay-row-name";
    nameLabel.textContent = name;
    controls.appendChild(nameLabel);

    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.className = "pause-connector-insert-btn";
    renameBtn.textContent = "✎";
    renameBtn.title = t("voicesOverlayRenameBtnTitle");
    controls.appendChild(renameBtn);

    const lockBtn = document.createElement("button");
    lockBtn.type = "button";
    lockBtn.className = "pause-connector-insert-btn";
    lockBtn.title = t("voicesOverlayLockBtnTitle");
    controls.appendChild(lockBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "pause-connector-insert-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.title = t("voicesOverlayDeleteBtnTitle");
    controls.appendChild(deleteBtn);

    function updateLockedUI() {
      lockBtn.textContent = locked ? "🔒" : "🔓";
      renameBtn.disabled = locked;
      deleteBtn.disabled = locked;
    }
    updateLockedUI();

    lockBtn.addEventListener("click", async () => {
      clearError();
      const response = await fetch(`/voices/${encodeURIComponent(name)}/lock`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ locked: !locked }),
      });
      if (!response.ok) {
        showError(t("voicesOverlayError"));
        return;
      }
      locked = !locked;
      updateLockedUI();
    });

    renameBtn.addEventListener("click", () => {
      if (locked) return;
      const input = document.createElement("input");
      input.type = "text";
      input.className = "voices-overlay-row-name-input";
      input.value = name;
      controls.replaceChild(input, nameLabel);
      input.focus();
      input.select();

      async function commit() {
        const newName = input.value.trim();
        if (!newName || newName === name) {
          controls.replaceChild(nameLabel, input);
          return;
        }
        clearError();
        const response = await fetch(`/voices/${encodeURIComponent(name)}/rename`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_name: newName }),
        });
        if (!response.ok) {
          const errorBody = await response.json().catch(() => ({}));
          showError(errorBody.detail || t("voicesOverlayError"));
          controls.replaceChild(nameLabel, input);
          return;
        }
        await loadList();
        if (onVoicesChanged) onVoicesChanged({ oldName: name, newName });
      }

      input.addEventListener("blur", commit);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") input.blur();
      });
    });

    deleteBtn.addEventListener("click", async () => {
      if (locked) return;
      clearError();
      const usageResponse = await fetch(`/voices/${encodeURIComponent(name)}/usage`);
      const usages = usageResponse.ok ? await usageResponse.json() : [];
      const confirmed =
        usages.length === 0
          ? confirm(t("voicesOverlayConfirmDelete"))
          : confirm(t("voicesOverlayConfirmDeleteInUse", formatUsage(usages)));
      if (!confirmed) return;

      const response = await fetch(`/voices/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        showError(t("voicesOverlayError"));
        return;
      }
      await loadList();
      if (onVoicesChanged) onVoicesChanged();
    });

    return row;
  }

  function closeOverlay() {
    stopDragging();
    stopResizing();
    unregisterOverlay(backdrop);
    backdrop.remove();
  }
  closeBtn.addEventListener("click", closeOverlay);

  const overlayHandle = registerOverlay(backdrop, panel, closeOverlay, onClosed);

  loadList();
  document.body.appendChild(backdrop);

  return overlayHandle;
}
