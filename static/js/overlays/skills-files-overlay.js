import { makeDraggable, makeResizable, registerOverlay, unregisterOverlay } from "./overlay-chrome.js";

function encodeFilePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function openSkillsFilesOverlay({ t, initialPath, initialIsNote = false, getProject, onClosed, onFilesChanged }) {
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
  title.textContent = "Bars2Bars Dateien";
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
  const stopResizing = makeResizable(panel, resizeHandle, "skillsFiles");

  const errorLabel = document.createElement("div");
  errorLabel.className = "skills-files-error";
  errorLabel.hidden = true;
  panel.appendChild(errorLabel);

  const fileList = document.createElement("div");
  fileList.className = "skills-files-list";
  panel.appendChild(fileList);

  const newButtonsRow = document.createElement("div");
  newButtonsRow.className = "skills-files-new-buttons-row";
  panel.appendChild(newButtonsRow);

  const newSkillBtn = document.createElement("button");
  newSkillBtn.type = "button";
  newSkillBtn.className = "btn-compact";
  newSkillBtn.textContent = t("skillsFilesNewSkill");
  newButtonsRow.appendChild(newSkillBtn);

  const newMemoryFileBtn = document.createElement("button");
  newMemoryFileBtn.type = "button";
  newMemoryFileBtn.className = "btn-compact";
  newMemoryFileBtn.textContent = t("skillsFilesNewMemoryFile");
  newButtonsRow.appendChild(newMemoryFileBtn);

  const newSkillForm = document.createElement("div");
  newSkillForm.className = "inline-name-form skills-files-new-form";
  newSkillForm.hidden = true;
  panel.appendChild(newSkillForm);

  const newSkillNameInput = document.createElement("input");
  newSkillNameInput.type = "text";
  newSkillNameInput.placeholder = t("skillsFilesNewSkillNamePlaceholder");
  newSkillForm.appendChild(newSkillNameInput);

  const newSkillDescInput = document.createElement("input");
  newSkillDescInput.type = "text";
  newSkillDescInput.placeholder = t("skillsFilesNewSkillDescPlaceholder");
  newSkillForm.appendChild(newSkillDescInput);

  const confirmNewSkillBtn = document.createElement("button");
  confirmNewSkillBtn.type = "button";
  confirmNewSkillBtn.className = "btn-compact";
  confirmNewSkillBtn.textContent = t("create");
  newSkillForm.appendChild(confirmNewSkillBtn);

  const newMemoryFileForm = document.createElement("div");
  newMemoryFileForm.className = "inline-name-form skills-files-new-form";
  newMemoryFileForm.hidden = true;
  panel.appendChild(newMemoryFileForm);

  const newMemoryFileNameInput = document.createElement("input");
  newMemoryFileNameInput.type = "text";
  newMemoryFileNameInput.placeholder = t("skillsFilesNewMemoryFileNamePlaceholder");
  newMemoryFileForm.appendChild(newMemoryFileNameInput);

  const confirmNewMemoryFileBtn = document.createElement("button");
  confirmNewMemoryFileBtn.type = "button";
  confirmNewMemoryFileBtn.className = "btn-compact";
  confirmNewMemoryFileBtn.textContent = t("create");
  newMemoryFileForm.appendChild(confirmNewMemoryFileBtn);

  const textarea = document.createElement("textarea");
  textarea.className = "skills-files-editor";
  textarea.hidden = true;
  panel.appendChild(textarea);
  textarea.addEventListener("input", () => {
    dirty = true;
  });

  const actionRow = document.createElement("div");
  actionRow.className = "skills-files-action-row";
  actionRow.hidden = true;
  panel.appendChild(actionRow);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "btn-compact";
  saveBtn.textContent = t("skillsFilesSave");
  actionRow.appendChild(saveBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "cancel-btn btn-compact";
  deleteBtn.textContent = t("skillsFilesDelete");
  actionRow.appendChild(deleteBtn);

  const savedLabel = document.createElement("span");
  savedLabel.className = "skills-files-saved-label";
  savedLabel.hidden = true;
  actionRow.appendChild(savedLabel);

  let currentPath = null;
  let currentIsNote = false;
  let dirty = false;

  function showError(message) {
    errorLabel.textContent = message;
    errorLabel.hidden = false;
  }

  function clearError() {
    errorLabel.hidden = true;
  }

  function updateActiveButtonHighlight() {
    for (const btn of fileList.querySelectorAll(".skills-files-list-btn")) {
      const isActive =
        currentPath !== null &&
        btn.dataset.path === currentPath &&
        btn.dataset.isNote === String(currentIsNote);
      btn.classList.toggle("skills-files-list-btn-active", isActive);
    }
  }

  async function loadFileList() {
    fileList.innerHTML = "";
    const project = getProject();
    newMemoryFileBtn.hidden = !project;
    if (!project) newMemoryFileForm.hidden = true;

    if (project) {
      const notesTitle = document.createElement("div");
      notesTitle.className = "skills-files-group-title";
      notesTitle.textContent = t("skillsFilesSectionProjectNotes");
      fileList.appendChild(notesTitle);

      const notesResp = await fetch(`/projects/${encodeURIComponent(project)}/notes`);
      if (notesResp.ok) {
        const notes = await notesResp.json();
        for (const file of notes) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "pause-connector-insert-btn skills-files-list-btn";
          btn.textContent = file.name;
          btn.title = file.path;
          btn.dataset.path = file.path;
          btn.dataset.isNote = "true";
          btn.addEventListener("click", () => openFile(file.path, true));
          fileList.appendChild(btn);
        }
      }
    }

    const skillsTitle = document.createElement("div");
    skillsTitle.className = "skills-files-group-title";
    skillsTitle.textContent = t("skillsFilesSectionSkills");
    fileList.appendChild(skillsTitle);

    const skillsResp = await fetch("/skills-files");
    if (skillsResp.ok) {
      const skills = await skillsResp.json();
      for (const file of skills) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pause-connector-insert-btn skills-files-list-btn";
        btn.textContent = file.name;
        btn.title = file.path;
        btn.dataset.path = file.path;
        btn.dataset.isNote = "false";
        btn.addEventListener("click", () => openFile(file.path, false));
        fileList.appendChild(btn);
      }
    }

    updateActiveButtonHighlight();
  }

  async function openFile(path, isNote = false) {
    clearError();
    savedLabel.hidden = true;
    const project = getProject();
    const url = isNote && project
      ? `/projects/${encodeURIComponent(project)}/notes/${encodeFilePath(path)}`
      : `/skills-files/${encodeFilePath(path)}`;

    const response = await fetch(url);
    if (!response.ok) {
      showError(t("skillsFilesLoadError"));
      return;
    }
    const data = await response.json();
    currentPath = path;
    currentIsNote = isNote;
    textarea.value = data.content;
    dirty = false;
    textarea.hidden = false;
    actionRow.hidden = false;
    updateActiveButtonHighlight();
  }

  // Skipped while the user has unsaved local edits (dirty), so an agent's
  // write to the same file never silently discards in-progress work — see
  // docs/FIXES.md.
  async function refreshCurrentFile() {
    if (!currentPath || dirty) return;
    await openFile(currentPath, currentIsNote);
  }

  newSkillBtn.addEventListener("click", () => {
    newMemoryFileForm.hidden = true;
    newSkillForm.hidden = false;
    newSkillNameInput.value = "";
    newSkillDescInput.value = "";
    newSkillNameInput.focus();
  });

  confirmNewSkillBtn.addEventListener("click", async () => {
    const name = newSkillNameInput.value.trim();
    const description = newSkillDescInput.value.trim();
    if (!name) return;
    clearError();
    const response = await fetch("/skills-files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      showError(errorBody.detail || t("skillsFilesSaveError"));
      return;
    }
    const data = await response.json();
    newSkillForm.hidden = true;
    await loadFileList();
    await openFile(data.path, false);
    if (onFilesChanged) onFilesChanged();
  });

  newMemoryFileBtn.addEventListener("click", () => {
    newSkillForm.hidden = true;
    newMemoryFileForm.hidden = false;
    newMemoryFileNameInput.value = "";
    newMemoryFileNameInput.focus();
  });

  confirmNewMemoryFileBtn.addEventListener("click", async () => {
    const name = newMemoryFileNameInput.value.trim();
    const project = getProject();
    if (!name || !project) return;
    clearError();
    const response = await fetch(`/projects/${encodeURIComponent(project)}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      showError(errorBody.detail || t("skillsFilesSaveError"));
      return;
    }
    const data = await response.json();
    newMemoryFileForm.hidden = true;
    await loadFileList();
    await openFile(data.path, true);
    if (onFilesChanged) onFilesChanged();
  });

  saveBtn.addEventListener("click", async () => {
    if (!currentPath) return;
    clearError();
    const project = getProject();
    const url = currentIsNote && project
      ? `/projects/${encodeURIComponent(project)}/notes/${encodeFilePath(currentPath)}`
      : `/skills-files/${encodeFilePath(currentPath)}`;

    const response = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: textarea.value }),
    });
    if (!response.ok) {
      showError(t("skillsFilesSaveError"));
      return;
    }
    savedLabel.hidden = false;
    dirty = false;
  });

  deleteBtn.addEventListener("click", async () => {
    if (!currentPath) return;
    if (!confirm(t("skillsFilesConfirmDelete", currentPath))) return;
    clearError();
    const project = getProject();
    const url = currentIsNote && project
      ? `/projects/${encodeURIComponent(project)}/notes/${encodeFilePath(currentPath)}`
      : `/skills-files/${encodeFilePath(currentPath)}`;

    const response = await fetch(url, {
      method: "DELETE",
    });
    if (!response.ok) {
      showError(t("skillsFilesSaveError"));
      return;
    }
    textarea.hidden = true;
    actionRow.hidden = true;
    savedLabel.hidden = true;
    currentPath = null;
    currentIsNote = false;
    await loadFileList();
    if (onFilesChanged) onFilesChanged();
  });

  function closeOverlay() {
    stopDragging();
    stopResizing();
    unregisterOverlay(backdrop);
    backdrop.remove();
  }
  closeBtn.addEventListener("click", closeOverlay);

  const overlayHandle = registerOverlay(backdrop, panel, closeOverlay, onClosed);

  loadFileList().then(() => {
    if (initialPath) openFile(initialPath, initialIsNote);
  });
  document.body.appendChild(backdrop);

  return { ...overlayHandle, openFile, loadFileList, refreshCurrentFile };
}

