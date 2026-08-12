export const LLM_SELECTION_KEY = "fishaudio_llm_selection";

let currentSelection = { provider: "ollama", model: null };

function loadSavedSelection() {
  try {
    const raw = localStorage.getItem(LLM_SELECTION_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && (parsed.provider === "ollama" || parsed.provider === "nvidia")) {
        currentSelection = parsed;
      }
    }
  } catch (err) {
    console.warn("Could not read saved LLM selection", err);
  }
}

function saveSelection() {
  try {
    localStorage.setItem(LLM_SELECTION_KEY, JSON.stringify(currentSelection));
  } catch (err) {
    console.warn("Could not save LLM selection", err);
  }
}

export function getSelectedLLM() {
  return { ...currentSelection };
}

export function initLLMModelSelect() {
  loadSavedSelection();

  const selectEl = document.getElementById("global-llm-select");
  const fetchBtn = document.getElementById("global-llm-fetch-btn");
  if (!selectEl || !fetchBtn) return;

  let ollamaModels = [];
  let defaultOllamaModel = null;
  let nvidiaModels = [];

  function getEffectiveOllamaModels() {
    if (ollamaModels.length > 0) return ollamaModels;
    if (defaultOllamaModel) return [{ id: defaultOllamaModel }];
    return [];
  }

  function renderSelectOptions() {
    selectEl.innerHTML = "";

    const effectiveOllamaModels = getEffectiveOllamaModels();

    if (effectiveOllamaModels.length > 0) {
      const ollamaGroup = document.createElement("optgroup");
      ollamaGroup.label = "Ollama";
      for (const m of effectiveOllamaModels) {
        const opt = document.createElement("option");
        opt.value = `ollama:${m.id}`;
        opt.textContent = ollamaModels.length > 0 ? m.id : `${m.id} (.env)`;
        ollamaGroup.appendChild(opt);
      }
      selectEl.appendChild(ollamaGroup);
    } else {
      const noneOpt = document.createElement("option");
      noneOpt.value = "ollama:none";
      noneOpt.disabled = true;
      noneOpt.dataset.i18n = "llmOllamaNoneFound";
      noneOpt.textContent = "Ollama: keine Modelle gefunden";
      selectEl.appendChild(noneOpt);
    }

    if (nvidiaModels.length === 0) {
      const nvidiaFetchOpt = document.createElement("option");
      nvidiaFetchOpt.value = "nvidia:fetch";
      nvidiaFetchOpt.dataset.i18n = "llmNvidiaFetch";
      nvidiaFetchOpt.textContent = "NVIDIA (Modelle laden...)";
      selectEl.appendChild(nvidiaFetchOpt);
    } else {
      const group = document.createElement("optgroup");
      group.label = "NVIDIA AI Models";
      for (const m of nvidiaModels) {
        const opt = document.createElement("option");
        opt.value = `nvidia:${m.id}`;
        opt.textContent = `NVIDIA: ${m.id}`;
        group.appendChild(opt);
      }
      selectEl.appendChild(group);
    }

    const firstOllamaModel = effectiveOllamaModels[0]?.id || null;
    const wantedVal =
      currentSelection.provider === "ollama" && currentSelection.model
        ? `ollama:${currentSelection.model}`
        : currentSelection.provider === "nvidia" && currentSelection.model
          ? `nvidia:${currentSelection.model}`
          : firstOllamaModel
            ? `ollama:${firstOllamaModel}`
            : "ollama:none";

    if ([...selectEl.options].some((o) => o.value === wantedVal && !o.disabled)) {
      selectEl.value = wantedVal;
      if (wantedVal.startsWith("ollama:") && currentSelection.model !== wantedVal.substring(7)) {
        currentSelection = { provider: "ollama", model: wantedVal.substring(7) };
        saveSelection();
      }
    } else {
      selectEl.value = "ollama:none";
      currentSelection = { provider: "ollama", model: null };
      saveSelection();
    }

    fetchBtn.hidden = selectEl.value !== "nvidia:fetch";
  }

  async function handleFetchOllama() {
    try {
      const res = await fetch("/api/llm/ollama-models");
      if (!res.ok) return;
      const data = await res.json();
      ollamaModels = data.models || [];
      defaultOllamaModel = data.default_model || null;
      renderSelectOptions();
    } catch (err) {
      console.warn("Could not fetch Ollama models", err);
    }
  }

  async function handleFetchNVIDIA() {
    fetchBtn.disabled = true;
    fetchBtn.textContent = "Lade...";
    try {
      const res = await fetch("/api/llm/nvidia-models");
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server-Fehler ${res.status}`);
      }
      const data = await res.json();
      const models = data.models || [];
      if (models.length === 0) {
        alert("Keine aktiven NVIDIA-Modelle gefunden.");
        nvidiaModels = [];
        renderSelectOptions();
        return;
      }
      nvidiaModels = models;
      renderSelectOptions();
      selectEl.value = `nvidia:${models[0].id}`;
      currentSelection = { provider: "nvidia", model: models[0].id };
      saveSelection();
    } catch (err) {
      alert(`Fehler beim Laden der NVIDIA-Modelle: ${err.message}`);
      nvidiaModels = [];
      renderSelectOptions();
    } finally {
      fetchBtn.disabled = false;
      fetchBtn.textContent = "Laden";
    }
  }

  selectEl.addEventListener("change", () => {
    const val = selectEl.value;
    if (val === "nvidia:fetch") {
      fetchBtn.hidden = false;
      handleFetchNVIDIA();
    } else if (val.startsWith("nvidia:")) {
      fetchBtn.hidden = true;
      currentSelection = { provider: "nvidia", model: val.substring(7) };
      saveSelection();
    } else if (val.startsWith("ollama:") && val !== "ollama:none") {
      fetchBtn.hidden = true;
      currentSelection = { provider: "ollama", model: val.substring(7) };
      saveSelection();
    }
  });

  fetchBtn.addEventListener("click", handleFetchNVIDIA);

  renderSelectOptions();
  handleFetchOllama();
}
