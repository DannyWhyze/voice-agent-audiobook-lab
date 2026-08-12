import json

import pytest

from src.orchestrator.dialog import projects as dialog_projects


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dialog_projects, "DIALOG_PROJECTS_DIR", tmp_path)

    project_path = tmp_path / "TestProject"
    project_path.mkdir()
    (project_path / "Chapter1.json").write_text(
        json.dumps({"boxes": [], "pause_ms": "400"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    audio_dir = project_path / "Chapter1_audio"
    audio_dir.mkdir()
    (audio_dir / "combined.wav").write_bytes(b"ORIGINALCOMBINEDBYTES")

    return tmp_path
