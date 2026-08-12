from __future__ import annotations

import json

from ..engine_client import EngineError
from .projects import _load_chapter_json, _project_dir, _save_chapter_json

PRESET_EFFECT_TYPES = (
    "compressor",
    "reverb",
    "eq",
    "normalize",
    "pitch",
    "formant",
    "delay",
)


def save_box_effect_params(
    project: str, chapter: str, box_index: int, key: str, params: dict
) -> None:
    data = _load_chapter_json(project, chapter)
    if data is not None:
        boxes = data.get("boxes", [])
        if 0 <= box_index < len(boxes):
            boxes[box_index][key] = params
            _save_chapter_json(project, chapter, data)


def save_combined_effect_params(
    project: str, chapter: str, key: str, params: dict
) -> None:
    data = _load_chapter_json(project, chapter)
    if data is not None:
        data[key] = params
        _save_chapter_json(project, chapter, data)


def _presets_path(project: str):
    return _project_dir(project) / "_presets.json"


def _read_presets(project: str) -> dict:
    path = _presets_path(project)
    if not path.exists():
        return {effect_type: [] for effect_type in PRESET_EFFECT_TYPES}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {effect_type: [] for effect_type in PRESET_EFFECT_TYPES}
    for effect_type in PRESET_EFFECT_TYPES:
        data.setdefault(effect_type, [])
    return data


def _write_presets(project: str, data: dict) -> None:
    _presets_path(project).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_presets(project: str) -> dict:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    return _read_presets(project)


def save_preset(project: str, effect_type: str, name: str, params: dict) -> None:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    if not name.strip():
        raise ValueError("Preset name must not be empty.")
    data = _read_presets(project)
    if any(preset["name"] == name for preset in data[effect_type]):
        raise ValueError(f"A preset named '{name}' already exists.")
    data[effect_type].append({"name": name, "params": params})
    _write_presets(project, data)


def delete_preset(project: str, effect_type: str, name: str) -> None:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    data = _read_presets(project)
    data[effect_type] = [
        preset for preset in data[effect_type] if preset["name"] != name
    ]
    _write_presets(project, data)
