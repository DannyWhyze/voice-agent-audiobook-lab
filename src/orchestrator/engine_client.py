from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .audio.combine import _read_wav_as_pcm16
from .paths import VOICES_DIR

load_dotenv()

DEFAULT_ENGINE_URL = "http://127.0.0.1:3030"


class EngineError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _engine_url() -> str:
    return os.getenv("ENGINE_URL", DEFAULT_ENGINE_URL)


def engine_ready() -> bool:
    try:
        httpx.get(_engine_url(), timeout=1.0)
    except httpx.HTTPError:
        return False
    return True


def list_voices() -> list[str]:
    if not VOICES_DIR.exists():
        return []
    return sorted(p.stem for p in VOICES_DIR.rglob("*.txt"))


def _find_voice_dir(name: str) -> Path | None:
    if not VOICES_DIR.exists():
        return None
    # Only ever glob with a fixed, safe pattern ("*.txt") and match the
    # untrusted `name` by exact dict lookup afterward -- never embed `name`
    # itself in the glob pattern, or "../"/"*" in it can walk rglob outside
    # VOICES_DIR (see docs_dw/reviewer-qa-security.md).
    for txt_path in VOICES_DIR.rglob("*.txt"):
        if txt_path.stem == name:
            return txt_path.parent
    return None


def _voice_dir(name: str) -> Path:
    voice_dir = _find_voice_dir(name)
    if voice_dir is None:
        raise EngineError(400, f"Voice '{name}' not found")
    return voice_dir


def _require_known_voice(voice: str) -> None:
    if voice not in list_voices():
        raise EngineError(400, f"Voice '{voice}' not found")


def _load_voice(voice: str) -> tuple[bytes, str]:
    voice_dir = _voice_dir(voice)
    wav_path = voice_dir / f"{voice}.wav"
    txt_path = voice_dir / f"{voice}.txt"
    return wav_path.read_bytes(), txt_path.read_text(encoding="utf-8").strip()


def create_voice(name: str, audio_bytes: bytes, text: str) -> str:
    from .dialog.projects import sanitize_name

    safe_name = sanitize_name(name)
    if safe_name in list_voices():
        raise EngineError(409, f"Voice '{safe_name}' already exists")
    try:
        _read_wav_as_pcm16(audio_bytes)
    except ValueError as exc:
        raise EngineError(400, str(exc)) from exc

    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    (VOICES_DIR / f"{safe_name}.wav").write_bytes(audio_bytes)
    (VOICES_DIR / f"{safe_name}.txt").write_text(text.strip(), encoding="utf-8")
    return safe_name


def is_voice_locked(name: str) -> bool:
    voice_dir = _find_voice_dir(name)
    if voice_dir is None:
        return False
    return (voice_dir / f"{name}.lock").exists()


def is_voice_active(name: str) -> bool:
    voice_dir = _find_voice_dir(name)
    if voice_dir is None:
        return True
    return not (voice_dir / f"{name}.hidden").exists()


def set_voice_active(name: str, active: bool) -> None:
    hidden_path = _voice_dir(name) / f"{name}.hidden"
    if active:
        hidden_path.unlink(missing_ok=True)
    else:
        hidden_path.touch()


def list_active_voices() -> list[str]:
    return [name for name in list_voices() if is_voice_active(name)]


def set_voice_locked(name: str, locked: bool) -> None:
    lock_path = _voice_dir(name) / f"{name}.lock"
    if locked:
        lock_path.touch()
    else:
        lock_path.unlink(missing_ok=True)


def delete_voice(name: str) -> None:
    voice_dir = _voice_dir(name)
    if is_voice_locked(name):
        raise EngineError(400, f"Voice '{name}' is locked")
    (voice_dir / f"{name}.wav").unlink(missing_ok=True)
    (voice_dir / f"{name}.txt").unlink(missing_ok=True)
    (voice_dir / f"{name}.lock").unlink(missing_ok=True)
    (voice_dir / f"{name}.hidden").unlink(missing_ok=True)


def rename_voice(old_name: str, new_name: str) -> str:
    from .dialog.projects import sanitize_name

    voice_dir = _voice_dir(old_name)
    if is_voice_locked(old_name):
        raise EngineError(400, f"Voice '{old_name}' is locked")
    safe_new_name = sanitize_name(new_name)
    if safe_new_name in list_voices():
        raise EngineError(409, f"Voice '{safe_new_name}' already exists")

    (voice_dir / f"{old_name}.wav").rename(voice_dir / f"{safe_new_name}.wav")
    (voice_dir / f"{old_name}.txt").rename(voice_dir / f"{safe_new_name}.txt")
    old_hidden = voice_dir / f"{old_name}.hidden"
    if old_hidden.exists():
        old_hidden.rename(voice_dir / f"{safe_new_name}.hidden")
    return safe_new_name


def _voice_folder(txt_path: Path) -> str | None:
    parent = txt_path.parent
    if parent == VOICES_DIR:
        return None
    relative = parent.relative_to(VOICES_DIR)
    if relative.parts[0] == "legacy_voices":
        return None
    return str(relative)


def list_voices_detail() -> list[dict]:
    if not VOICES_DIR.exists():
        return []
    return [
        {
            "name": txt_path.stem,
            "locked": is_voice_locked(txt_path.stem),
            "folder": _voice_folder(txt_path),
            "active": is_voice_active(txt_path.stem),
        }
        for txt_path in sorted(VOICES_DIR.rglob("*.txt"))
    ]


def get_voice_preview(voice: str) -> bytes:
    wav_path = _voice_dir(voice) / f"{voice}.wav"
    return wav_path.read_bytes()


def generate_speech(text: str, voice: str | None) -> bytes:
    if not text.strip():
        raise EngineError(400, "Text must not be empty.")

    # Immer als multipart/form-data senden (auch ohne Datei) -- s2.cpp
    # befuellt req.form nur bei Multipart-Requests (s2_server.cpp:501).
    files: dict[str, tuple[str | None, object] | tuple[str, bytes, str]] = {
        "text": (None, text),
    }
    if voice:
        wav_bytes, ref_text = _load_voice(voice)
        files["reference_text"] = (None, ref_text)
        files["reference"] = (f"{voice}.wav", wav_bytes, "audio/wav")

    engine_url = _engine_url()
    try:
        response = httpx.post(f"{engine_url}/generate", files=files, timeout=900.0)
    except httpx.ConnectError as exc:
        raise EngineError(
            502, f"Engine server unreachable at {engine_url}: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise EngineError(504, f"Engine server did not respond in time: {exc}") from exc

    if response.status_code != 200:
        raise EngineError(response.status_code, response.text or "Engine server error")

    return response.content
