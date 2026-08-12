from __future__ import annotations

import re
from pathlib import Path

from ..engine_client import EngineError
from ..paths import SKILLS_DIR

_SKILL_NAME_RE = re.compile(r"[^a-z0-9\-]")


def _sanitize_skill_name(raw: str) -> str:
    slug = _SKILL_NAME_RE.sub("", raw.strip().lower().replace(" ", "-"))
    if not slug:
        raise EngineError(400, "Invalid skill name.")
    return slug


def _resolve_file_path(file_path: str) -> Path:
    path = (SKILLS_DIR / file_path).resolve()
    skills_dir_resolved = SKILLS_DIR.resolve()
    if not path.is_relative_to(skills_dir_resolved):
        raise EngineError(400, "Invalid file path.")

    is_top_level_md = path.parent == skills_dir_resolved and path.suffix == ".md"
    is_skill_md = path.name == "SKILL.md" and path.parent.parent == skills_dir_resolved
    if not (is_top_level_md or is_skill_md):
        raise EngineError(
            400,
            "Only a top-level .md file or a '<skill>/SKILL.md' file may be accessed.",
        )
    return path


def list_files() -> list[dict]:
    files = []
    for md_file in sorted(SKILLS_DIR.glob("*.md")):
        files.append({"path": md_file.name, "name": md_file.name})
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        rel = skill_md.relative_to(SKILLS_DIR)
        files.append({"path": rel.as_posix(), "name": rel.parent.name})
    return files


def get_file_content(file_path: str) -> str:
    path = _resolve_file_path(file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    return path.read_text(encoding="utf-8")


def save_file_content(file_path: str, content: str) -> None:
    path = _resolve_file_path(file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    path.write_text(content, encoding="utf-8")


def delete_file(file_path: str) -> None:
    path = _resolve_file_path(file_path)
    if not path.exists():
        raise EngineError(404, f"File '{file_path}' not found")
    path.unlink()


def create_skill(name: str, description: str) -> str:
    safe_name = _sanitize_skill_name(name)
    skill_dir = SKILLS_DIR / safe_name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        raise EngineError(409, f"Skill '{safe_name}' already exists")

    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\nname: {safe_name}\ndescription: {description}\n---\n\n# {safe_name}\n\n"
    )
    skill_md.write_text(content, encoding="utf-8")
    return f"{safe_name}/SKILL.md"
