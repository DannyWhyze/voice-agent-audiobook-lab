import pytest
from fastapi.testclient import TestClient

from src.orchestrator.dialog import skills_files
from src.orchestrator.engine_client import EngineError
from src.orchestrator.main import app


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_files, "SKILLS_DIR", tmp_path)
    (tmp_path / "AGENTS.md").write_text("# Memory\n", encoding="utf-8")
    skill_dir = tmp_path / "some-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Some Skill\n", encoding="utf-8")
    return tmp_path


def test_list_files_includes_agents_md_and_skill_md(skills_dir):
    files = skills_files.list_files()
    assert {"path": "AGENTS.md", "name": "AGENTS.md"} in files
    assert {"path": "some-skill/SKILL.md", "name": "some-skill"} in files


def test_list_files_omits_agents_md_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_files, "SKILLS_DIR", tmp_path)
    files = skills_files.list_files()
    assert files == []


def test_get_file_content_returns_text(skills_dir):
    assert skills_files.get_file_content("AGENTS.md") == "# Memory\n"


def test_get_file_content_raises_404_for_missing_file(skills_dir):
    with pytest.raises(EngineError):
        skills_files.get_file_content("AGENTS.md.does-not-exist")


def test_get_file_content_allows_any_top_level_md_file(skills_dir):
    (skills_dir / "Charaktere.md").write_text("# Charaktere\n", encoding="utf-8")
    assert skills_files.get_file_content("Charaktere.md") == "# Charaktere\n"


def test_get_file_content_rejects_non_md_top_level_file(skills_dir):
    (skills_dir / "notes.txt").write_text("nope", encoding="utf-8")
    with pytest.raises(EngineError):
        skills_files.get_file_content("notes.txt")


def test_get_file_content_rejects_nested_non_skill_md_file(skills_dir):
    (skills_dir / "some-skill" / "notes.md").write_text("nope", encoding="utf-8")
    with pytest.raises(EngineError):
        skills_files.get_file_content("some-skill/notes.md")


def test_get_file_content_rejects_path_traversal(skills_dir):
    outside_file = skills_dir.parent / "secret.txt"
    outside_file.write_text("do not read me", encoding="utf-8")
    with pytest.raises(EngineError):
        skills_files.get_file_content("../secret.txt")
    assert outside_file.exists()


def test_save_file_content_overwrites_existing_file(skills_dir):
    skills_files.save_file_content("AGENTS.md", "# New content\n")
    assert (skills_dir / "AGENTS.md").read_text(encoding="utf-8") == "# New content\n"


def test_save_file_content_rejects_creating_a_new_file(skills_dir):
    with pytest.raises(EngineError):
        skills_files.save_file_content("some-skill/SKILL.md.new", "content")
    assert not (skills_dir / "some-skill" / "SKILL.md.new").exists()


def test_delete_file_removes_agents_md(skills_dir):
    skills_files.delete_file("AGENTS.md")
    assert not (skills_dir / "AGENTS.md").exists()


def test_delete_file_raises_404_for_missing_file(skills_dir):
    with pytest.raises(EngineError):
        skills_files.delete_file("AGENTS.md.does-not-exist")


def test_create_skill_writes_skill_md_with_frontmatter(skills_dir):
    path = skills_files.create_skill("My New Skill", "Does a thing.")

    assert path == "my-new-skill/SKILL.md"
    content = (skills_dir / "my-new-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: my-new-skill" in content
    assert "description: Does a thing." in content


def test_create_skill_rejects_duplicate_name(skills_dir):
    skills_files.create_skill("dup-skill", "First.")

    with pytest.raises(EngineError):
        skills_files.create_skill("dup-skill", "Second.")


def test_create_skill_rejects_empty_name(skills_dir):
    with pytest.raises(EngineError):
        skills_files.create_skill("   ", "Description.")


@pytest.fixture
def client():
    return TestClient(app)


def test_skills_files_list_route(skills_dir, client):
    response = client.get("/skills-files")
    assert response.status_code == 200
    paths = [f["path"] for f in response.json()]
    assert "AGENTS.md" in paths
    assert "some-skill/SKILL.md" in paths


def test_skills_files_get_route(skills_dir, client):
    response = client.get("/skills-files/AGENTS.md")
    assert response.status_code == 200
    assert response.json() == {"content": "# Memory\n"}


def test_skills_files_save_route(skills_dir, client):
    response = client.put("/skills-files/AGENTS.md", json={"content": "# Updated\n"})
    assert response.status_code == 200
    assert (skills_dir / "AGENTS.md").read_text(encoding="utf-8") == "# Updated\n"


def test_skills_files_delete_route(skills_dir, client):
    response = client.delete("/skills-files/AGENTS.md")
    assert response.status_code == 200
    assert not (skills_dir / "AGENTS.md").exists()


def test_skills_files_get_route_404_for_missing_file(skills_dir, client):
    response = client.get("/skills-files/AGENTS.md.does-not-exist")
    assert response.status_code == 400


def test_skills_files_create_route(skills_dir, client):
    response = client.post(
        "/skills-files", json={"name": "route-skill", "description": "Via the route."}
    )
    assert response.status_code == 200
    assert response.json() == {"path": "route-skill/SKILL.md"}
    assert (skills_dir / "route-skill" / "SKILL.md").exists()


def test_skills_files_create_route_returns_409_for_duplicate(skills_dir, client):
    client.post("/skills-files", json={"name": "dup-route", "description": "First."})
    response = client.post(
        "/skills-files", json={"name": "dup-route", "description": "Second."}
    )
    assert response.status_code == 409
