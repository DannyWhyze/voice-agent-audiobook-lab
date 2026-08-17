import io
import json
import struct
import wave
import zipfile
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.orchestrator.dialog import projects as dialog_projects
from src.orchestrator.engine_client import EngineError
from src.orchestrator.main import app


def _read_chapter_json(project_dir, name="Chapter1"):
    path = project_dir / "TestProject" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_delete_chapter_removes_json_and_audio_dir(project_dir):
    dialog_projects.delete_chapter("TestProject", "Chapter1")

    project_path = project_dir / "TestProject"
    assert not (project_path / "Chapter1.json").exists()
    assert not (project_path / "Chapter1_audio").exists()


def test_delete_chapter_raises_404_for_missing_chapter(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.delete_chapter("TestProject", "NoSuchChapter")


def test_clear_chapter_audio_removes_the_whole_audio_dir(project_dir):
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    (audio_dir / "box_0.wav").write_bytes(b"BOX_AUDIO")
    variants_dir = audio_dir / "variants"
    variants_dir.mkdir()
    (variants_dir / "box_0_variant_x.wav").write_bytes(b"BOX_VARIANT")
    combined_variants_dir = audio_dir / "combined_variants"
    combined_variants_dir.mkdir()
    (combined_variants_dir / "combined_variant_x.wav").write_bytes(b"COMBINED_VARIANT")

    dialog_projects.clear_chapter_audio("TestProject", "Chapter1")

    assert not audio_dir.exists()


def test_clear_chapter_audio_resets_variant_bookkeeping_in_chapter_json(project_dir):
    chapter_path = project_dir / "TestProject" / "Chapter1.json"
    chapter_path.write_text(
        json.dumps(
            {
                "boxes": [
                    {
                        "text": "hi",
                        "voice": None,
                        "variants": ["box_0_variant_x.wav"],
                        "activeIndex": 0,
                        "variantLocks": {"box_0_variant_x.wav": True},
                    }
                ],
                "pause_ms": 400,
                "combinedVariants": ["combined_variant_x.wav"],
                "activeCombinedIndex": 0,
                "combinedVariantLocks": {"combined_variant_x.wav": True},
                "combinedVariantLabels": {"combined_variant_x.wav": "Take 1"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dialog_projects.clear_chapter_audio("TestProject", "Chapter1")

    data = _read_chapter_json(project_dir)
    assert data["boxes"][0]["variants"] == []
    assert data["boxes"][0]["activeIndex"] == -1
    assert "variantLocks" not in data["boxes"][0]
    assert data["combinedVariants"] == []
    assert data["activeCombinedIndex"] == -1
    assert "combinedVariantLocks" not in data
    assert "combinedVariantLabels" not in data
    # Box text itself is untouched -- only audio/variant bookkeeping resets.
    assert data["boxes"][0]["text"] == "hi"


def test_clear_chapter_audio_raises_404_for_missing_chapter(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.clear_chapter_audio("TestProject", "NoSuchChapter")


def test_delete_project_removes_directory(project_dir):
    dialog_projects.delete_project("TestProject")

    assert not (project_dir / "TestProject").exists()


def test_delete_project_raises_404_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.delete_project("NoSuchProject")


def test_rename_project_renames_directory(project_dir):
    dialog_projects.rename_project("TestProject", "RenamedProject")

    assert not (project_dir / "TestProject").exists()
    assert (project_dir / "RenamedProject" / "Chapter1.json").exists()
    assert (
        project_dir / "RenamedProject" / "Chapter1_audio" / "combined.wav"
    ).read_bytes() == (b"ORIGINALCOMBINEDBYTES")


def test_rename_project_case_only_change_survives_case_insensitive_fs(project_dir):
    dialog_projects.rename_project("TestProject", "testproject")

    matches = list(project_dir.glob("[Tt]est[Pp]roject"))
    assert len(matches) == 1
    assert (matches[0] / "Chapter1.json").exists()


def test_rename_project_raises_409_for_existing_target(project_dir):
    (project_dir / "OtherProject").mkdir()

    with pytest.raises(EngineError):
        dialog_projects.rename_project("TestProject", "OtherProject")

    assert (project_dir / "TestProject").exists()


def test_rename_project_raises_404_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.rename_project("NoSuchProject", "New")


def test_rename_project_is_a_no_op_for_the_same_name(project_dir):
    dialog_projects.rename_project("TestProject", "TestProject")

    assert (project_dir / "TestProject" / "Chapter1.json").exists()


def test_rename_chapter_renames_json_and_audio_dir(project_dir):
    dialog_projects.rename_chapter("TestProject", "Chapter1", "Renamed")

    project_path = project_dir / "TestProject"
    assert not (project_path / "Chapter1.json").exists()
    assert (project_path / "Renamed.json").exists()
    assert (project_path / "Renamed_audio" / "combined.wav").read_bytes() == (
        b"ORIGINALCOMBINEDBYTES"
    )


def test_rename_chapter_case_only_change_survives_case_insensitive_fs(project_dir):
    dialog_projects.rename_chapter("TestProject", "Chapter1", "chapter1")

    project_path = project_dir / "TestProject"
    assert (project_path / "chapter1.json").exists() or (
        project_path / "Chapter1.json"
    ).exists()
    matches = list(project_path.glob("[Cc]hapter1.json"))
    assert len(matches) == 1


def test_rename_chapter_overwrites_existing_target(project_dir):
    project_path = project_dir / "TestProject"
    (project_path / "Existing.json").write_text(
        json.dumps({"boxes": []}), encoding="utf-8"
    )

    dialog_projects.rename_chapter("TestProject", "Chapter1", "Existing")

    assert not (project_path / "Chapter1.json").exists()
    data = _read_chapter_json(project_dir, "Existing")
    assert data == {"boxes": [], "pause_ms": "400"}


def test_rename_chapter_updates_chapter_order(project_dir):
    dialog_projects.save_chapter_order("TestProject", ["Chapter1"])

    dialog_projects.rename_chapter("TestProject", "Chapter1", "Renamed")

    order_path = project_dir / "TestProject" / "_chapter_order.json"
    order = json.loads(order_path.read_text(encoding="utf-8"))
    assert order == ["Renamed"]


def test_rename_chapter_raises_404_for_missing_chapter(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.rename_chapter("TestProject", "NoSuchChapter", "New")


def test_save_chapter_deletes_stale_audio_for_a_box_that_became_empty(project_dir):
    # Regression test: inserting a new box before an existing one shifts
    # every later box's array position by one. The newly inserted box is
    # empty (no variants) but a stale box_0.wav from whatever box previously
    # occupied position 0 must not be left behind — add_box_variant() would
    # otherwise mistake it for this new box's own prior audio the next time
    # it generates (its "seed an Original variant" check only looks at file
    # existence, not which box actually produced it). See docs/FIXES.md.
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "box_0.wav").write_bytes(b"OLD_BOX_0_AUDIO")

    boxes = [
        {"text": "", "voice": None, "variants": [], "activeIndex": -1},
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_1_variant_x.wav"],
            "activeIndex": 0,
        },
    ]

    dialog_projects.save_chapter("TestProject", "Chapter1", boxes, 400, {})

    assert not (audio_dir / "box_0.wav").exists()


def test_save_chapter_keeps_audio_for_a_box_with_variants(project_dir):
    # A box that legitimately has generated audio (non-empty variants) must
    # not have its box_N.wav swept up by the new "now-blank" cleanup.
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "box_0.wav").write_bytes(b"REAL_AUDIO")

    boxes = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_x.wav"],
            "activeIndex": 0,
        },
    ]

    dialog_projects.save_chapter("TestProject", "Chapter1", boxes, 400, {})

    assert (audio_dir / "box_0.wav").read_bytes() == b"REAL_AUDIO"


def test_save_chapter_order_persists_order(project_dir):
    dialog_projects.save_chapter_order("TestProject", ["Chapter1", "Chapter2"])

    order_path = project_dir / "TestProject" / "_chapter_order.json"
    assert json.loads(order_path.read_text(encoding="utf-8")) == [
        "Chapter1",
        "Chapter2",
    ]


def test_save_chapter_order_raises_404_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_projects.save_chapter_order("NoSuchProject", ["Chapter1"])


@pytest.fixture
def client():
    return TestClient(app)


def test_clear_chapter_audio_route(project_dir, client):
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    assert audio_dir.exists()

    response = client.post("/projects/TestProject/chapters/Chapter1/clear-audio")

    assert response.status_code == 200
    assert not audio_dir.exists()


def test_clear_chapter_audio_route_404_for_missing_chapter(project_dir, client):
    response = client.post("/projects/TestProject/chapters/NoSuchChapter/clear-audio")

    assert response.status_code == 404


def test_delete_chapter_route(project_dir, client):
    response = client.delete("/projects/TestProject/chapters/Chapter1")

    assert response.status_code == 200
    assert not (project_dir / "TestProject" / "Chapter1.json").exists()


def test_delete_chapter_route_404_for_missing_chapter(project_dir, client):
    response = client.delete("/projects/TestProject/chapters/NoSuchChapter")

    assert response.status_code == 404


def test_delete_project_route(project_dir, client):
    response = client.delete("/projects/TestProject")

    assert response.status_code == 200
    assert not (project_dir / "TestProject").exists()


def test_rename_project_route(project_dir, client):
    response = client.put(
        "/projects/TestProject/rename",
        json={"new_name": "Renamed"},
    )

    assert response.status_code == 200
    assert (project_dir / "Renamed" / "Chapter1.json").exists()


def test_rename_project_route_returns_409_for_existing_target(project_dir, client):
    (project_dir / "OtherProject").mkdir()

    response = client.put(
        "/projects/TestProject/rename",
        json={"new_name": "OtherProject"},
    )

    assert response.status_code == 409


def test_rename_chapter_route(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1/rename",
        json={"new_name": "Renamed"},
    )

    assert response.status_code == 200
    assert (project_dir / "TestProject" / "Renamed.json").exists()


def test_reorder_chapters_route(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapter-order",
        json={"order": ["Chapter1"]},
    )

    assert response.status_code == 200
    order_path = project_dir / "TestProject" / "_chapter_order.json"
    assert json.loads(order_path.read_text(encoding="utf-8")) == ["Chapter1"]


def test_list_projects_route_returns_existing_projects(project_dir, client):
    response = client.get("/projects")

    assert response.status_code == 200
    assert response.json() == ["TestProject"]


def test_list_projects_route_returns_empty_list_when_none_exist(
    tmp_path, monkeypatch, client
):
    monkeypatch.setattr(dialog_projects, "DIALOG_PROJECTS_DIR", tmp_path)

    response = client.get("/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_get_chapter_combined_audio_route_returns_audio(project_dir, client):
    response = client.get("/projects/TestProject/chapters/Chapter1/combined-audio")

    assert response.status_code == 200
    assert response.content == b"ORIGINALCOMBINEDBYTES"


def test_get_chapter_combined_audio_route_404_when_missing(project_dir, client):
    response = client.get("/projects/TestProject/chapters/NoSuchChapter/combined-audio")

    assert response.status_code == 404


def test_get_chapter_box_audio_route_returns_audio(project_dir, client):
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    (audio_dir / "box_0.wav").write_bytes(b"BOXAUDIOBYTES")

    response = client.get("/projects/TestProject/chapters/Chapter1/audio/0")

    assert response.status_code == 200
    assert response.content == b"BOXAUDIOBYTES"


def test_get_chapter_box_audio_route_404_when_missing(project_dir, client):
    response = client.get("/projects/TestProject/chapters/Chapter1/audio/0")

    assert response.status_code == 404


def test_get_chapter_box_audio_route_self_heals_from_active_variant(
    project_dir, client
):
    chapter_json_path = project_dir / "TestProject" / "Chapter1.json"
    data = json.loads(chapter_json_path.read_text(encoding="utf-8"))
    data["boxes"] = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_a.wav"],
            "activeIndex": 0,
        }
    ]
    chapter_json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    variants_dir = audio_dir / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "box_0_variant_a.wav").write_bytes(b"VARIANTBYTES")

    response = client.get("/projects/TestProject/chapters/Chapter1/audio/0")

    assert response.status_code == 200
    assert response.content == b"VARIANTBYTES"
    assert (audio_dir / "box_0.wav").exists()


def test_download_all_route_returns_zip_with_combined_audio(project_dir, client):
    response = client.get("/projects/TestProject/download-all")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    expected_name = f"Chapter1_TestProject_{date}.wav"
    zip_file = zipfile.ZipFile(io.BytesIO(response.content))
    assert zip_file.namelist() == [expected_name]
    assert zip_file.read(expected_name) == b"ORIGINALCOMBINEDBYTES"


def test_download_all_route_404_when_no_combined_audio_exists(
    tmp_path, monkeypatch, client
):
    monkeypatch.setattr(dialog_projects, "DIALOG_PROJECTS_DIR", tmp_path)
    project_path = tmp_path / "EmptyProject"
    project_path.mkdir()
    (project_path / "Chapter1.json").write_text(
        json.dumps({"boxes": []}), encoding="utf-8"
    )

    response = client.get("/projects/EmptyProject/download-all")

    assert response.status_code == 404


def _make_wav(
    sample_value: int = 1000, count: int = 44100, framerate: int = 44100
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(struct.pack(f"<{count}h", *([sample_value] * count)))
    return buffer.getvalue()


def test_download_all_route_mp3_format_returns_320kbps_mp3(project_dir, client):
    framerate = 44100
    duration_s = 1.0
    wav_bytes = _make_wav(count=int(framerate * duration_s), framerate=framerate)
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        wav_bytes
    )

    response = client.get("/projects/TestProject/download-all?audio_format=mp3")

    assert response.status_code == 200
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    expected_name = f"Chapter1_TestProject_{date}.mp3"
    zip_file = zipfile.ZipFile(io.BytesIO(response.content))
    assert zip_file.namelist() == [expected_name]

    mp3_bytes = zip_file.read(expected_name)
    actual_bitrate = len(mp3_bytes) * 8 / duration_s
    assert 300_000 <= actual_bitrate <= 340_000


def test_download_all_route_rejects_invalid_audio_format(project_dir, client):
    response = client.get("/projects/TestProject/download-all?audio_format=flac")

    assert response.status_code == 400


def test_find_voice_usage_finds_matching_boxes_across_chapters(project_dir):
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}, {"voice": None}, {"voice": "Anna"}]}),
        encoding="utf-8",
    )
    other_project = project_dir / "OtherProject"
    other_project.mkdir()
    (other_project / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Berta"}]}), encoding="utf-8"
    )
    monkeypatch_voices = ["Anna", "Berta"]

    import src.orchestrator.dialog.projects as dp

    original_list_voices = dp.list_voices
    dp.list_voices = lambda: monkeypatch_voices
    try:
        usages = dp.find_voice_usage("Anna")
    finally:
        dp.list_voices = original_list_voices

    assert usages == [
        {"project": "TestProject", "chapter": "Chapter1", "box_index": 0},
        {"project": "TestProject", "chapter": "Chapter1", "box_index": 2},
    ]


def test_find_voice_usage_empty_when_unused(project_dir):
    import src.orchestrator.dialog.projects as dp

    original_list_voices = dp.list_voices
    dp.list_voices = lambda: ["Anna"]
    try:
        assert dp.find_voice_usage("Anna") == []
    finally:
        dp.list_voices = original_list_voices


def test_find_voice_usage_raises_400_for_unknown_voice(project_dir):
    import src.orchestrator.dialog.projects as dp

    original_list_voices = dp.list_voices
    dp.list_voices = list
    try:
        with pytest.raises(EngineError) as exc_info:
            dp.find_voice_usage("Ghost")
    finally:
        dp.list_voices = original_list_voices

    assert exc_info.value.status_code == 400


def test_rename_voice_everywhere_updates_only_matching_boxes(project_dir):
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(
            {"boxes": [{"voice": "Anna"}, {"voice": "Berta"}, {"voice": "Anna"}]}
        ),
        encoding="utf-8",
    )

    dialog_projects.rename_voice_everywhere("Anna", "Anna Neu")

    data = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data["boxes"][0]["voice"] == "Anna Neu"
    assert data["boxes"][1]["voice"] == "Berta"
    assert data["boxes"][2]["voice"] == "Anna Neu"


def test_rename_voice_everywhere_skips_unaffected_chapters(project_dir):
    chapter_path = project_dir / "TestProject" / "Chapter1.json"
    before_mtime = chapter_path.stat().st_mtime_ns

    dialog_projects.rename_voice_everywhere("NoSuchVoice", "Whatever")

    after_mtime = chapter_path.stat().st_mtime_ns
    assert before_mtime == after_mtime


def test_replace_voice_in_chapter_updates_matching_boxes_in_target_chapter(
    project_dir, monkeypatch
):
    monkeypatch.setattr(dialog_projects, "list_voices", lambda: ["Anna", "Berta", "Cora"])
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(
            {"boxes": [{"voice": "Anna"}, {"voice": "Berta"}, {"voice": "Anna"}]}
        ),
        encoding="utf-8",
    )

    count = dialog_projects.replace_voice_in_chapter(
        "TestProject", "Chapter1", "Anna", "Cora"
    )
    assert count == 2

    data = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data["boxes"][0]["voice"] == "Cora"
    assert data["boxes"][1]["voice"] == "Berta"
    assert data["boxes"][2]["voice"] == "Cora"


def test_replace_voice_in_chapter_leaves_other_chapters_and_projects_untouched(
    project_dir, monkeypatch
):
    monkeypatch.setattr(dialog_projects, "list_voices", lambda: ["Anna", "Cora"])
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )
    (project_dir / "TestProject" / "Chapter2.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )
    (project_dir / "OtherProject") .mkdir(parents=True, exist_ok=True)
    (project_dir / "OtherProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )

    dialog_projects.replace_voice_in_chapter("TestProject", "Chapter1", "Anna", "Cora")

    assert (
        json.loads(
            (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
        )["boxes"][0]["voice"]
        == "Cora"
    )
    assert (
        json.loads(
            (project_dir / "TestProject" / "Chapter2.json").read_text(encoding="utf-8")
        )["boxes"][0]["voice"]
        == "Anna"
    )
    assert (
        json.loads(
            (project_dir / "OtherProject" / "Chapter1.json").read_text(encoding="utf-8")
        )["boxes"][0]["voice"]
        == "Anna"
    )


def test_replace_voice_in_chapter_raises_404_for_missing_chapter():
    with pytest.raises(EngineError) as exc_info:
        dialog_projects.replace_voice_in_chapter(
            "NoSuchProject", "NoSuchChapter", "Anna", "Cora"
        )
    assert exc_info.value.status_code == 404


def test_replace_voice_in_chapter_raises_400_for_unknown_new_voice(
    project_dir, monkeypatch
):
    monkeypatch.setattr(dialog_projects, "list_voices", lambda: ["Anna"])
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )
    with pytest.raises(EngineError) as exc_info:
        dialog_projects.replace_voice_in_chapter(
            "TestProject", "Chapter1", "Anna", "UnknownVoice"
        )
    assert exc_info.value.status_code == 400


def test_replace_voice_in_chapter_allows_empty_new_voice(project_dir, monkeypatch):
    monkeypatch.setattr(dialog_projects, "list_voices", lambda: ["Anna"])
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )
    count = dialog_projects.replace_voice_in_chapter(
        "TestProject", "Chapter1", "Anna", ""
    )
    assert count == 1
    data = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data["boxes"][0]["voice"] == ""


def test_replace_voice_in_chapter_returns_zero_when_no_matches(project_dir, monkeypatch):
    monkeypatch.setattr(dialog_projects, "list_voices", lambda: ["Cora"])
    chapter_path = project_dir / "TestProject" / "Chapter1.json"
    before_mtime = chapter_path.stat().st_mtime_ns

    count = dialog_projects.replace_voice_in_chapter(
        "TestProject", "Chapter1", "NoSuchVoice", "Cora"
    )
    assert count == 0
    after_mtime = chapter_path.stat().st_mtime_ns
    assert before_mtime == after_mtime



def test_ensure_agents_md_writes_default_when_missing(tmp_path):
    dialog_projects.ensure_agents_md(tmp_path)
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Charaktere" in content
    assert "Worldbuilding" in content


def test_ensure_agents_md_does_not_overwrite_existing_file(tmp_path):
    (tmp_path / "AGENTS.md").write_text("existing content", encoding="utf-8")
    dialog_projects.ensure_agents_md(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "existing content"


def test_save_chapter_creates_default_agents_md_for_new_project(project_dir):
    dialog_projects.save_chapter("NewProject", "Chapter1", [], 400, {})
    content = (project_dir / "NewProject" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Charaktere" in content


def test_save_chapter_does_not_overwrite_existing_agents_md(project_dir):
    agents_md_path = project_dir / "TestProject" / "AGENTS.md"
    agents_md_path.write_text("# Custom content\n", encoding="utf-8")

    dialog_projects.save_chapter("TestProject", "Chapter1", [], 400, {})

    assert agents_md_path.read_text(encoding="utf-8") == "# Custom content\n"
