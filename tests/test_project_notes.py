import pytest

from src.orchestrator.dialog import project_notes
from src.orchestrator.engine_client import EngineError


def test_list_files_returns_md_files_sorted(project_dir):
    p_dir = project_dir / "TestProject"
    (p_dir / "AGENTS.md").write_text("agents", encoding="utf-8")
    (p_dir / "Charaktere.md").write_text("chars", encoding="utf-8")
    (p_dir / "notes.txt").write_text("ignored", encoding="utf-8")

    files = project_notes.list_files("TestProject")

    assert files == [
        {"path": "AGENTS.md", "name": "AGENTS.md"},
        {"path": "Charaktere.md", "name": "Charaktere.md"},
    ]


def test_list_files_returns_empty_list_for_missing_project(tmp_path, monkeypatch):
    import src.orchestrator.dialog.projects as dialog_projects

    monkeypatch.setattr(dialog_projects, "DIALOG_PROJECTS_DIR", tmp_path)

    assert project_notes.list_files("NoSuchProject") == []


def test_get_file_content_reads_file(project_dir):
    (project_dir / "TestProject" / "AGENTS.md").write_text("hello", encoding="utf-8")

    assert project_notes.get_file_content("TestProject", "AGENTS.md") == "hello"


def test_get_file_content_raises_404_when_missing(project_dir):
    with pytest.raises(EngineError) as exc_info:
        project_notes.get_file_content("TestProject", "NoSuch.md")
    assert exc_info.value.status_code == 404


def test_get_file_content_rejects_path_traversal(project_dir):
    with pytest.raises(EngineError) as exc_info:
        project_notes.get_file_content("TestProject", "../other.md")
    assert exc_info.value.status_code == 400


def test_get_file_content_rejects_non_md_file(project_dir):
    (project_dir / "TestProject" / "Chapter1.json").write_text("{}", encoding="utf-8")

    with pytest.raises(EngineError) as exc_info:
        project_notes.get_file_content("TestProject", "Chapter1.json")
    assert exc_info.value.status_code == 400


def test_save_file_content_updates_file(project_dir):
    (project_dir / "TestProject" / "AGENTS.md").write_text("old", encoding="utf-8")

    project_notes.save_file_content("TestProject", "AGENTS.md", "new content")

    assert (project_dir / "TestProject" / "AGENTS.md").read_text(
        encoding="utf-8"
    ) == "new content"


def test_delete_file_removes_file(project_dir):
    path = project_dir / "TestProject" / "Note.md"
    path.write_text("temp", encoding="utf-8")

    project_notes.delete_file("TestProject", "Note.md")

    assert not path.exists()


def test_create_memory_file_creates_empty_md_file(project_dir):
    created = project_notes.create_memory_file("TestProject", "Charaktere")

    assert created == "Charaktere.md"
    assert (project_dir / "TestProject" / "Charaktere.md").read_text(
        encoding="utf-8"
    ) == ""


def test_create_memory_file_raises_409_if_exists(project_dir):
    (project_dir / "TestProject" / "AGENTS.md").write_text("x", encoding="utf-8")

    with pytest.raises(EngineError) as exc_info:
        project_notes.create_memory_file("TestProject", "AGENTS.md")
    assert exc_info.value.status_code == 409


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.orchestrator.main import app

    return TestClient(app)


def test_project_notes_routes(project_dir, client):
    # 1. Create
    resp = client.post("/projects/TestProject/notes", json={"name": "Worldbuilding"})
    assert resp.status_code == 200
    assert resp.json() == {"path": "Worldbuilding.md"}

    # 2. List
    resp = client.get("/projects/TestProject/notes")
    assert resp.status_code == 200
    assert resp.json() == [{"path": "Worldbuilding.md", "name": "Worldbuilding.md"}]

    # 3. Get content
    resp = client.get("/projects/TestProject/notes/Worldbuilding.md")
    assert resp.status_code == 200
    assert resp.json() == {"content": ""}

    # 4. Save content
    resp = client.put(
        "/projects/TestProject/notes/Worldbuilding.md",
        json={"content": "# World rules"},
    )
    assert resp.status_code == 200

    resp = client.get("/projects/TestProject/notes/Worldbuilding.md")
    assert resp.json() == {"content": "# World rules"}

    # 5. Delete
    resp = client.delete("/projects/TestProject/notes/Worldbuilding.md")
    assert resp.status_code == 200

    resp = client.get("/projects/TestProject/notes")
    assert resp.json() == []
