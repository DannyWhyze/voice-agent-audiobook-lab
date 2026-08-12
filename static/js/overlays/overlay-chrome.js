export function buildPresetsSection({ t, project, effectType, params, refreshFns, onPresetApplied }) {
  const container = document.createElement("div");
  container.className = "presets-section";

  const list = document.createElement("div");
  list.className = "presets-list";
  container.appendChild(list);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn-compact";
  saveBtn.textContent = t("presetSaveAs");
  container.appendChild(saveBtn);

  const saveForm = document.createElement("div");
  saveForm.className = "inline-name-form";
  saveForm.hidden = true;

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = t("presetNamePlaceholder");
  saveForm.appendChild(nameInput);

  const confirmSaveBtn = document.createElement("button");
  confirmSaveBtn.type = "button";
  confirmSaveBtn.className = "btn-compact";
  confirmSaveBtn.textContent = t("create");
  saveForm.appendChild(confirmSaveBtn);

  container.appendChild(saveForm);

  async function renderList() {
    list.innerHTML = "";
    let presets = [];
    try {
      const response = await fetch(`/projects/${encodeURIComponent(project)}/presets`);
      if (response.ok) {
        const data = await response.json();
        presets = data[effectType] || [];
      }
    } catch {
      // Presets are a convenience feature -- failing silently just means an empty list.
    }

    for (const preset of presets) {
      const row = document.createElement("div");
      row.className = "preset-row";

      const nameLabel = document.createElement("span");
      nameLabel.className = "preset-name";
      nameLabel.textContent = preset.name;
      row.appendChild(nameLabel);

      const loadBtn = document.createElement("button");
      loadBtn.type = "button";
      loadBtn.className = "pause-connector-insert-btn";
      loadBtn.textContent = t("presetLoad");
      loadBtn.addEventListener("click", () => {
        Object.assign(params, preset.params);
        refreshFns.forEach((refresh) => refresh());
        onPresetApplied();
      });
      row.appendChild(loadBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "pause-connector-insert-btn";
      deleteBtn.textContent = "✕";
      deleteBtn.addEventListener("click", async () => {
        await fetch(
          `/projects/${encodeURIComponent(project)}/presets/${effectType}/${encodeURIComponent(preset.name)}`,
          { method: "DELETE" }
        );
        renderList();
      });
      row.appendChild(deleteBtn);

      list.appendChild(row);
    }
  }

  saveBtn.addEventListener("click", () => {
    saveForm.hidden = false;
    nameInput.value = "";
    nameInput.focus();
  });

  confirmSaveBtn.addEventListener("click", async () => {
    const name = nameInput.value.trim();
    if (!name) return;
    const response = await fetch(
      `/projects/${encodeURIComponent(project)}/presets/${effectType}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, params }),
      }
    );
    if (response.ok) {
      saveForm.hidden = true;
      renderList();
    } else {
      const errorBody = await response.json().catch(() => ({}));
      alert(errorBody.detail || t("presetSaveAs"));
    }
  });

  renderList();
  return container;
}

export function makeDraggable(panel, handle) {
  handle.style.cursor = "move";
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;

  function onMouseDown(event) {
    if (event.target.closest("button")) return;
    const rect = panel.getBoundingClientRect();
    dragging = true;
    startX = event.clientX;
    startY = event.clientY;
    startLeft = rect.left;
    startTop = rect.top;
    panel.style.position = "fixed";
    panel.style.margin = "0";
    panel.style.left = `${startLeft}px`;
    panel.style.top = `${startTop}px`;
    event.preventDefault();
  }

  function onMouseMove(event) {
    if (!dragging) return;
    const newLeft = startLeft + (event.clientX - startX);
    const newTop = startTop + (event.clientY - startY);
    const maxLeft = window.innerWidth - panel.offsetWidth;
    const maxTop = window.innerHeight - panel.offsetHeight;
    panel.style.left = `${Math.max(0, Math.min(newLeft, maxLeft))}px`;
    panel.style.top = `${Math.max(0, Math.min(newTop, maxTop))}px`;
  }

  function onMouseUp() {
    dragging = false;
  }

  handle.addEventListener("mousedown", onMouseDown);
  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);

  return function stopDragging() {
    handle.removeEventListener("mousedown", onMouseDown);
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  };
}

const OVERLAY_SIZES_STORAGE_KEY = "fishaudio_overlay_sizes";
const MIN_PANEL_WIDTH = 320;
const MIN_PANEL_HEIGHT = 200;

function loadOverlaySizes() {
  try {
    return JSON.parse(localStorage.getItem(OVERLAY_SIZES_STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveOverlaySize(storageKey, width, height) {
  const sizes = loadOverlaySizes();
  sizes[storageKey] = { width, height };
  localStorage.setItem(OVERLAY_SIZES_STORAGE_KEY, JSON.stringify(sizes));
}

export function makeResizable(panel, handle, storageKey) {
  const savedSize = loadOverlaySizes()[storageKey];
  if (savedSize) {
    panel.style.width = `${savedSize.width}px`;
    panel.style.height = `${savedSize.height}px`;
  }

  let resizing = false;
  let startX = 0;
  let startY = 0;
  let startWidth = 0;
  let startHeight = 0;

  function onMouseDown(event) {
    const rect = panel.getBoundingClientRect();
    resizing = true;
    startX = event.clientX;
    startY = event.clientY;
    startWidth = rect.width;
    startHeight = rect.height;
    event.preventDefault();
    event.stopPropagation();
  }

  function onMouseMove(event) {
    if (!resizing) return;
    const maxWidth = window.innerWidth * 0.95;
    const maxHeight = window.innerHeight * 0.9;
    const newWidth = startWidth + (event.clientX - startX);
    const newHeight = startHeight + (event.clientY - startY);
    panel.style.width = `${Math.max(MIN_PANEL_WIDTH, Math.min(newWidth, maxWidth))}px`;
    panel.style.height = `${Math.max(MIN_PANEL_HEIGHT, Math.min(newHeight, maxHeight))}px`;
  }

  function onMouseUp() {
    if (!resizing) return;
    resizing = false;
    const rect = panel.getBoundingClientRect();
    saveOverlaySize(storageKey, Math.round(rect.width), Math.round(rect.height));
  }

  handle.addEventListener("mousedown", onMouseDown);
  window.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);

  return function stopResizing() {
    handle.removeEventListener("mousedown", onMouseDown);
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  };
}

const BASE_Z_INDEX = 1000;
const CASCADE_STEP_PX = 24;
const CASCADE_MAX_STEPS = 5;

const openOverlays = [];
let nextZIndex = BASE_Z_INDEX;

function bumpZIndex(backdrop) {
  nextZIndex += 1;
  backdrop.style.zIndex = String(nextZIndex);
}

function handleEscape(event) {
  if (event.key !== "Escape") return;
  const top = openOverlays[openOverlays.length - 1];
  if (top) top.closeOverlay();
}

export function registerOverlay(backdrop, panel, closeOverlay, onClosed) {
  const step = openOverlays.length % CASCADE_MAX_STEPS;
  panel.style.marginLeft = `${step * CASCADE_STEP_PX}px`;
  panel.style.marginTop = `${step * CASCADE_STEP_PX}px`;

  bumpZIndex(backdrop);

  const entry = { backdrop, closeOverlay, onClosed };
  openOverlays.push(entry);
  if (openOverlays.length === 1) {
    document.addEventListener("keydown", handleEscape);
  }

  function bringToFront() {
    bumpZIndex(backdrop);
  }
  panel.addEventListener("mousedown", bringToFront);

  return { bringToFront };
}

export function closeAllOverlays() {
  // Snapshot first: each closeOverlay() call synchronously mutates
  // openOverlays via unregisterOverlay(), so iterating the live array while
  // closing entries would skip whichever one shifts into the current index.
  for (const entry of [...openOverlays]) {
    entry.closeOverlay();
  }
}

export function unregisterOverlay(backdrop) {
  const index = openOverlays.findIndex((entry) => entry.backdrop === backdrop);
  if (index === -1) return;
  const [entry] = openOverlays.splice(index, 1);
  if (openOverlays.length === 0) {
    document.removeEventListener("keydown", handleEscape);
  }
  entry.onClosed?.();
}

