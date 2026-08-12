from __future__ import annotations

import sys
from pathlib import Path


def _exe_dir() -> Path:
    """Where user data lives: next to the exe when frozen, repo root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _resource_dir() -> Path:
    """Where bundled read-only assets live: PyInstaller's extraction dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


EXE_DIR = _exe_dir()
RESOURCE_DIR = _resource_dir()

STATIC_DIR = RESOURCE_DIR / "static"
DATA_DIR = EXE_DIR / "data"
VOICES_DIR = DATA_DIR / "audio_data" / "voices"
DIALOG_PROJECTS_DIR = DATA_DIR / "dialog_projects"
SKILLS_DIR = DATA_DIR / "skills"
