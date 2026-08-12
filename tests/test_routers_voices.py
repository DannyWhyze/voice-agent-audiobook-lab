import io
import json
import wave
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from src.orchestrator import engine_client
from src.orchestrator.main import app
from src.orchestrator.tags import TAGS


@pytest.fixture
def client():
    return TestClient(app)


def _make_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00\x01\x00")
    return buf.getvalue()


def test_get_voices_route(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Voice1.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Voice1.wav").write_bytes(b"WAV1")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.get("/voices")
    assert response.status_code == 200
    assert response.json() == ["Voice1"]


def test_get_engine_status_route_ready(monkeypatch, client):
    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    monkeypatch.setattr(httpx, "get", mock_get)

    response = client.get("/engine/status")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_get_engine_status_route_not_ready(monkeypatch, client):
    mock_get = MagicMock(side_effect=httpx.ConnectError("refused"))
    monkeypatch.setattr(httpx, "get", mock_get)

    response = client.get("/engine/status")
    assert response.status_code == 200
    assert response.json() == {"ready": False}


def test_get_tags_route(client):
    response = client.get("/tags")
    assert response.status_code == 200
    assert response.json() == TAGS


def test_post_language_route_success(client):
    response = client.post("/language/en")
    assert response.status_code == 200
    assert response.json() == {"lang": "en"}
    assert "fishaudio_language=en" in response.headers.get("set-cookie", "")


def test_post_language_route_invalid_language_400(client):
    response = client.post("/language/fr")
    assert response.status_code == 400
    assert "Unknown language 'fr'" in response.json()["detail"]


def test_get_voice_preview_route_success(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Voice1.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Voice1.wav").write_bytes(b"AUDIO_BYTES")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.get("/voices/Voice1/preview")
    assert response.status_code == 200
    assert response.content == b"AUDIO_BYTES"
    assert response.headers["content-type"] == "audio/wav"


def test_get_voice_preview_route_unknown_voice_400(tmp_path, monkeypatch, client):
    monkeypatch.setattr(engine_client, "VOICES_DIR", tmp_path)

    response = client.get("/voices/UnknownVoice/preview")
    assert response.status_code == 400
    assert "Voice 'UnknownVoice' not found" in response.json()["detail"]


def test_post_generate_route_success(monkeypatch, client):
    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.content = b"GENERATED_AUDIO"
    monkeypatch.setattr(httpx, "post", mock_post)

    response = client.post("/generate", json={"text": "Hello world", "voice": None})
    assert response.status_code == 200
    assert response.content == b"GENERATED_AUDIO"
    assert response.headers["content-type"] == "audio/wav"


def test_post_generate_route_engine_error_propagation(monkeypatch, client):
    def mock_post_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Server down")

    monkeypatch.setattr(httpx, "post", mock_post_connect_error)

    response = client.post("/generate", json={"text": "Hello world", "voice": None})
    assert response.status_code == 502
    assert "Engine server unreachable" in response.json()["detail"]


def test_post_generate_route_empty_text_400(monkeypatch, client):
    mock_post = MagicMock()
    monkeypatch.setattr(httpx, "post", mock_post)

    response = client.post("/generate", json={"text": "   ", "voice": None})
    assert response.status_code == 400
    assert "Text must not be empty" in response.json()["detail"]
    mock_post.assert_not_called()


def test_post_voices_route_success(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)
    wav_bytes = _make_wav_bytes()

    response = client.post(
        "/voices",
        data={"name": "NewVoice", "text": "Hello world"},
        files={"audio": ("clip.wav", wav_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {"name": "NewVoice"}
    assert (voices_dir / "NewVoice.wav").read_bytes() == wav_bytes
    assert (voices_dir / "NewVoice.txt").read_text(encoding="utf-8") == "Hello world"


def test_post_voices_route_collision_409(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Existing.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Existing.wav").write_bytes(b"OLDWAV")
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.post(
        "/voices",
        data={"name": "Existing", "text": "Text"},
        files={"audio": ("clip.wav", _make_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 409


def test_post_voices_route_invalid_wav_400(tmp_path, monkeypatch, client):
    monkeypatch.setattr(engine_client, "VOICES_DIR", tmp_path / "voices")

    response = client.post(
        "/voices",
        data={"name": "NewVoice", "text": "Text"},
        files={"audio": ("clip.wav", b"not a wav", "audio/wav")},
    )

    assert response.status_code == 400


def test_delete_voice_route_success(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.delete("/voices/Anna")

    assert response.status_code == 200
    assert not (voices_dir / "Anna.wav").exists()


def test_delete_voice_route_locked_400(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Anna.lock").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.delete("/voices/Anna")

    assert response.status_code == 400
    assert (voices_dir / "Anna.wav").exists()


def test_voice_usage_route_returns_matches(tmp_path, monkeypatch, client, project_dir):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )

    response = client.get("/voices/Anna/usage")

    assert response.status_code == 200
    assert response.json() == [
        {"project": "TestProject", "chapter": "Chapter1", "box_index": 0}
    ]


def test_set_voice_lock_route_success(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.put("/voices/Anna/lock", json={"locked": True})

    assert response.status_code == 200
    assert (voices_dir / "Anna.lock").exists()


def test_rename_voice_route_updates_files_and_references(
    tmp_path, monkeypatch, client, project_dir
):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps({"boxes": [{"voice": "Anna"}]}), encoding="utf-8"
    )

    response = client.put("/voices/Anna/rename", json={"new_name": "Anna Neu"})

    assert response.status_code == 200
    assert response.json() == {"name": "Anna Neu"}
    assert (voices_dir / "Anna Neu.wav").exists()
    data = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data["boxes"][0]["voice"] == "Anna Neu"


def test_rename_voice_route_collision_409(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Berta.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.put("/voices/Anna/rename", json={"new_name": "Berta"})

    assert response.status_code == 409


def test_voices_detail_route_reports_lock_state(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Anna.lock").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.get("/voices/detail")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Anna", "locked": True, "folder": None, "active": True}
    ]


def test_set_voice_active_route_success(tmp_path, monkeypatch, client):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    response = client.put("/voices/Anna/active", json={"active": False})

    assert response.status_code == 200
    assert (voices_dir / "Anna.hidden").exists()
