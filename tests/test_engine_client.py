import io
import wave
from unittest.mock import MagicMock

import httpx
import pytest

from src.orchestrator import engine_client
from src.orchestrator.engine_client import EngineError


def _make_wav_bytes(
    pcm16: bytes = b"\x00\x00\x01\x00", channels: int = 1, framerate: int = 24000
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(pcm16)
    return buf.getvalue()


def test_list_voices_returns_sorted_voice_stems(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "VoiceB.txt").write_text("Hello", encoding="utf-8")
    (voices_dir / "VoiceB.wav").write_bytes(b"WAVB")
    (voices_dir / "VoiceA.txt").write_text("Hi", encoding="utf-8")
    (voices_dir / "VoiceA.wav").write_bytes(b"WAVA")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.list_voices() == ["VoiceA", "VoiceB"]


def test_list_voices_returns_empty_list_when_dir_missing(tmp_path, monkeypatch):
    missing_dir = tmp_path / "non_existent_voices"
    monkeypatch.setattr(engine_client, "VOICES_DIR", missing_dir)

    assert engine_client.list_voices() == []


def test_list_voices_ignores_wav_without_matching_txt(tmp_path, monkeypatch):
    # list_voices() globs *.txt only, so a .wav dropped in manually without
    # its transcript is silently invisible -- not a bug, just documented,
    # intended behavior (confirmed with Danny 2026-08-10, see JOURNAL_8.md).
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Orphan.wav").write_bytes(b"WAV")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.list_voices() == []


def test_list_voices_includes_txt_without_matching_wav(tmp_path, monkeypatch):
    # The reverse mismatch: a .txt with no matching .wav still gets listed
    # (nothing cross-checks the .wav side), but is unusable -- reading its
    # preview raises because the .wav file was never there.
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Orphan.txt").write_text("Hello", encoding="utf-8")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.list_voices() == ["Orphan"]
    with pytest.raises(FileNotFoundError):
        engine_client.get_voice_preview("Orphan")


def test_find_voice_dir_rejects_glob_and_traversal_payloads(tmp_path, monkeypatch):
    # _find_voice_dir() must never feed the untrusted `name` into rglob()'s
    # pattern -- only match it by exact comparison against real filenames
    # afterward. Otherwise "*" or "../" in `name` can walk rglob outside
    # VOICES_DIR (regression test for the fix described in
    # docs_dw/reviewer-qa-security.md).
    root = tmp_path / "project"
    voices_dir = root / "data" / "audio_data" / "voices"
    voices_dir.mkdir(parents=True)
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())

    secret_dir = root / "secrets"
    secret_dir.mkdir()
    (secret_dir / "outside.txt").write_text("do not leak", encoding="utf-8")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client._find_voice_dir("*") is None
    assert engine_client._find_voice_dir("../../secrets/outside") is None
    # A real voice must still resolve normally.
    assert engine_client._find_voice_dir("Anna") == voices_dir


def test_get_voice_preview_rejects_traversal_payload(tmp_path, monkeypatch):
    root = tmp_path / "project"
    voices_dir = root / "data" / "audio_data" / "voices"
    voices_dir.mkdir(parents=True)

    secret_dir = root / "secrets"
    secret_dir.mkdir()
    (secret_dir / "outside.txt").write_text("do not leak", encoding="utf-8")
    (secret_dir / "outside.wav").write_bytes(b"SECRET_WAV_BYTES")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    with pytest.raises(EngineError) as exc_info:
        engine_client.get_voice_preview("../../secrets/outside")

    assert exc_info.value.status_code == 400


def test_get_voice_preview_success(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Alice.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Alice.wav").write_bytes(b"ALICEWAV")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    preview = engine_client.get_voice_preview("Alice")
    assert preview == b"ALICEWAV"


def test_get_voice_preview_raises_400_for_unknown_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_client, "VOICES_DIR", tmp_path)

    with pytest.raises(EngineError) as exc_info:
        engine_client.get_voice_preview("Unknown")

    assert exc_info.value.status_code == 400
    assert "Voice 'Unknown' not found" in exc_info.value.detail


def test_generate_speech_without_voice(monkeypatch):
    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.content = b"AUDIOBYTES"
    monkeypatch.setattr(httpx, "post", mock_post)

    audio = engine_client.generate_speech("Hello world", voice=None)

    assert audio == b"AUDIOBYTES"
    mock_post.assert_called_once()
    kwargs = mock_post.call_args.kwargs
    assert kwargs["files"]["text"] == (None, "Hello world")
    assert "reference" not in kwargs["files"]


def test_generate_speech_with_known_voice(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Bob.txt").write_text("Bob sample text", encoding="utf-8")
    (voices_dir / "Bob.wav").write_bytes(b"BOBWAV")

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    mock_post = MagicMock()
    mock_post.return_value.status_code = 200
    mock_post.return_value.content = b"GENERATEDAUDIO"
    monkeypatch.setattr(httpx, "post", mock_post)

    audio = engine_client.generate_speech("Hello Bob", voice="Bob")

    assert audio == b"GENERATEDAUDIO"
    mock_post.assert_called_once()
    files = mock_post.call_args.kwargs["files"]
    assert files["text"] == (None, "Hello Bob")
    assert files["reference_text"] == (None, "Bob sample text")
    assert files["reference"] == ("Bob.wav", b"BOBWAV", "audio/wav")


def test_generate_speech_raises_400_for_empty_text(monkeypatch):
    mock_post = MagicMock()
    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(EngineError) as exc_info:
        engine_client.generate_speech("", voice=None)

    assert exc_info.value.status_code == 400
    assert "Text must not be empty" in exc_info.value.detail
    mock_post.assert_not_called()


def test_generate_speech_raises_400_for_whitespace_only_text(monkeypatch):
    mock_post = MagicMock()
    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(EngineError) as exc_info:
        engine_client.generate_speech("   \n\t", voice=None)

    assert exc_info.value.status_code == 400
    assert "Text must not be empty" in exc_info.value.detail
    mock_post.assert_not_called()


def test_generate_speech_raises_502_on_connect_error(monkeypatch):
    def mock_post_connect_error(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", mock_post_connect_error)

    with pytest.raises(EngineError) as exc_info:
        engine_client.generate_speech("Test", voice=None)

    assert exc_info.value.status_code == 502
    assert "Engine server unreachable" in exc_info.value.detail


def test_generate_speech_raises_504_on_timeout(monkeypatch):
    def mock_post_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Timed out")

    monkeypatch.setattr(httpx, "post", mock_post_timeout)

    with pytest.raises(EngineError) as exc_info:
        engine_client.generate_speech("Test", voice=None)

    assert exc_info.value.status_code == 504
    assert "Engine server did not respond in time" in exc_info.value.detail


def test_generate_speech_raises_engine_error_on_non_200(monkeypatch):
    mock_post = MagicMock()
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "Internal C++ Engine Failure"
    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(EngineError) as exc_info:
        engine_client.generate_speech("Test", voice=None)

    assert exc_info.value.status_code == 500
    assert "Internal C++ Engine Failure" in exc_info.value.detail


def test_create_voice_writes_wav_and_txt_and_creates_missing_dir(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"  # deliberately does not exist yet
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)
    wav_bytes = _make_wav_bytes()

    saved_name = engine_client.create_voice("My Voice!", wav_bytes, "  Hello world  \n")

    assert saved_name == "My Voice"
    assert (voices_dir / "My Voice.wav").read_bytes() == wav_bytes
    assert (voices_dir / "My Voice.txt").read_text(encoding="utf-8") == "Hello world"


def test_create_voice_raises_409_on_name_collision(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Existing.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Existing.wav").write_bytes(b"OLDWAV")
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    with pytest.raises(EngineError) as exc_info:
        engine_client.create_voice("Existing", _make_wav_bytes(), "New text")

    assert exc_info.value.status_code == 409
    assert (voices_dir / "Existing.wav").read_bytes() == b"OLDWAV"  # untouched


def test_create_voice_raises_400_on_invalid_wav_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_client, "VOICES_DIR", tmp_path / "voices")

    with pytest.raises(EngineError) as exc_info:
        engine_client.create_voice("NewVoice", b"not a wav file", "Text")

    assert exc_info.value.status_code == 400


def test_create_voice_raises_400_on_empty_name_after_sanitizing(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_client, "VOICES_DIR", tmp_path / "voices")

    with pytest.raises(EngineError) as exc_info:
        engine_client.create_voice("!!!", _make_wav_bytes(), "Text")

    assert exc_info.value.status_code == 400


def test_is_voice_locked_false_by_default(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.is_voice_locked("Anna") is False


def test_set_voice_locked_creates_and_removes_lock_file(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    engine_client.set_voice_locked("Anna", True)
    assert (voices_dir / "Anna.lock").exists()
    assert engine_client.is_voice_locked("Anna") is True

    engine_client.set_voice_locked("Anna", False)
    assert not (voices_dir / "Anna.lock").exists()
    assert engine_client.is_voice_locked("Anna") is False


def test_is_voice_active_true_by_default(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.is_voice_active("Anna") is True


def test_set_voice_active_creates_and_removes_marker_file(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    engine_client.set_voice_active("Anna", False)
    assert (voices_dir / "Anna.hidden").exists()
    assert engine_client.is_voice_active("Anna") is False

    engine_client.set_voice_active("Anna", True)
    assert not (voices_dir / "Anna.hidden").exists()
    assert engine_client.is_voice_active("Anna") is True


def test_list_active_voices_excludes_hidden_voices(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Berta.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.hidden").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    assert engine_client.list_active_voices() == ["Anna"]


def test_delete_voice_removes_all_three_files(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    engine_client.delete_voice("Anna")

    assert not (voices_dir / "Anna.txt").exists()
    assert not (voices_dir / "Anna.wav").exists()
    assert "Anna" not in engine_client.list_voices()


def test_delete_voice_raises_400_when_locked(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Anna.lock").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    with pytest.raises(EngineError) as exc_info:
        engine_client.delete_voice("Anna")

    assert exc_info.value.status_code == 400
    assert (voices_dir / "Anna.wav").exists()  # untouched


def test_rename_voice_renames_wav_and_txt(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    new_name = engine_client.rename_voice("Anna", "Anna Neu!")

    assert new_name == "Anna Neu"
    assert (voices_dir / "Anna Neu.wav").exists()
    assert (voices_dir / "Anna Neu.txt").exists()
    assert not (voices_dir / "Anna.wav").exists()


def test_rename_voice_raises_400_when_locked(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Anna.lock").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    with pytest.raises(EngineError) as exc_info:
        engine_client.rename_voice("Anna", "Anna Neu")

    assert exc_info.value.status_code == 400


def test_rename_voice_raises_409_on_collision(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Berta.wav").write_bytes(_make_wav_bytes())
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    with pytest.raises(EngineError) as exc_info:
        engine_client.rename_voice("Anna", "Berta")

    assert exc_info.value.status_code == 409
    assert (voices_dir / "Anna.wav").exists()  # untouched


def test_list_voices_detail_reports_lock_state(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Berta.wav").write_bytes(_make_wav_bytes())
    (voices_dir / "Berta.lock").touch()
    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    detail = engine_client.list_voices_detail()

    assert detail == [
        {"name": "Anna", "locked": False, "folder": None, "active": True},
        {"name": "Berta", "locked": True, "folder": None, "active": True},
    ]


def test_list_voices_detail_reports_folder_and_excludes_legacy(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "Anna.txt").write_text("Text", encoding="utf-8")
    (voices_dir / "Anna.wav").write_bytes(_make_wav_bytes())

    german_dir = voices_dir / "german"
    german_dir.mkdir()
    (german_dir / "Berta.txt").write_text("Text", encoding="utf-8")
    (german_dir / "Berta.wav").write_bytes(_make_wav_bytes())

    legacy_dir = voices_dir / "legacy_voices"
    legacy_dir.mkdir()
    (legacy_dir / "Clara.txt").write_text("Text", encoding="utf-8")
    (legacy_dir / "Clara.wav").write_bytes(_make_wav_bytes())

    monkeypatch.setattr(engine_client, "VOICES_DIR", voices_dir)

    detail = engine_client.list_voices_detail()

    assert detail == [
        {"name": "Anna", "locked": False, "folder": None, "active": True},
        {"name": "Berta", "locked": False, "folder": "german", "active": True},
        {"name": "Clara", "locked": False, "folder": None, "active": True},
    ]


def test_engine_ready_returns_true_when_engine_responds(monkeypatch):
    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    monkeypatch.setattr(httpx, "get", mock_get)

    assert engine_client.engine_ready() is True


def test_engine_ready_returns_true_on_non_2xx_response(monkeypatch):
    # Any HTTP response (even a 404) means the engine process is up and
    # listening -- only a connection failure means "not ready".
    mock_get = MagicMock()
    mock_get.return_value.status_code = 404
    monkeypatch.setattr(httpx, "get", mock_get)

    assert engine_client.engine_ready() is True


def test_engine_ready_returns_false_when_connection_fails(monkeypatch):
    mock_get = MagicMock(side_effect=httpx.ConnectError("refused"))
    monkeypatch.setattr(httpx, "get", mock_get)

    assert engine_client.engine_ready() is False
