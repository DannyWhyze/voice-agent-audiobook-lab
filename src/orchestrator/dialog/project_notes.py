from __future__ import annotations

import re
from pathlib import Path

from ..engine_client import EngineError
from .projects import _project_dir

_MEMORY_FILENAME_RE = re.compile(r"[^\w\- .]")


def _sanitize_memory_filename(raw: str) -> str:
    name = _MEMORY_FILENAME_RE.sub("", raw).strip(" .")
    if not name:
        raise EngineError(400, "Invalid file name.")
    if not name.lower().endswith(".md"):
        name += ".md"
    return name


def _resolve_file_path(project: str, file_path: str) -> Path:
    project_dir = _project_dir(project)
    path = (project_dir / file_path).resolve()
    if not path.is_relative_to(project_dir):
        raise EngineError(400, "Invalid file path.")
    if path.parent != project_dir or path.suffix != ".md":
        raise EngineError(400, "Only a top-level .md file may be accessed.")
    return path


def list_files(project: str) -> list[dict]:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        return []
    return [
        {"path": md_file.name, "name": md_file.name}
        for md_file in sorted(project_dir.glob("*.md"))
    ]


def get_file_content(project: str, file_path: str) -> str:
    path = _resolve_file_path(project, file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    return path.read_text(encoding="utf-8")


def save_file_content(project: str, file_path: str, content: str) -> None:
    path = _resolve_file_path(project, file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    path.write_text(content, encoding="utf-8")


def delete_file(project: str, file_path: str) -> None:
    path = _resolve_file_path(project, file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    path.unlink()


def create_memory_file(project: str, name: str) -> str:
    safe_name = _sanitize_memory_filename(name)
    project_dir = _project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / safe_name
    if path.exists():
        raise EngineError(409, f"File '{safe_name}' already exists")
    path.write_text("", encoding="utf-8")
    return safe_name
