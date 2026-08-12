from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from ..dialog.projects import find_voice_usage, rename_voice_everywhere
from ..engine_client import (
    EngineError,
    create_voice,
    delete_voice,
    engine_ready,
    generate_speech,
    get_voice_preview,
    list_active_voices,
    list_voices_detail,
    rename_voice,
    set_voice_active,
    set_voice_locked,
)
from ..schemas import (
    GenerateRequest,
    RenameVoiceRequest,
    SetVoiceActiveRequest,
    SetVoiceLockRequest,
)
from ..tags import TAGS

router = APIRouter()

LANGUAGES = {"de", "en"}
LANGUAGE_COOKIE = "fishaudio_language"


@router.get("/voices")
def voices() -> list[str]:
    return list_active_voices()


@router.get("/engine/status")
def engine_status() -> dict:
    return {"ready": engine_ready()}


@router.post("/voices")
async def create_voice_route(
    name: str = Form(...), text: str = Form(...), audio: UploadFile = File(...)
) -> dict:
    audio_bytes = await audio.read()
    try:
        saved_name = create_voice(name, audio_bytes, text)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"name": saved_name}


@router.get("/voices/detail")
def voices_detail() -> list[dict]:
    return list_voices_detail()


@router.delete("/voices/{name}")
def delete_voice_route(name: str) -> dict:
    try:
        delete_voice(name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.get("/voices/{name}/usage")
def voice_usage_route(name: str) -> list[dict]:
    try:
        return find_voice_usage(name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/voices/{name}/lock")
def set_voice_lock_route(name: str, request: SetVoiceLockRequest) -> dict:
    try:
        set_voice_locked(name, request.locked)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put("/voices/{name}/active")
def set_voice_active_route(name: str, request: SetVoiceActiveRequest) -> dict:
    try:
        set_voice_active(name, request.active)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put("/voices/{name}/rename")
def rename_voice_route(name: str, request: RenameVoiceRequest) -> dict:
    try:
        new_name = rename_voice(name, request.new_name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    rename_voice_everywhere(name, new_name)
    return {"name": new_name}


@router.get("/tags")
def tags() -> list[str]:
    return TAGS


@router.post("/language/{lang}")
def set_language(lang: str, response: Response) -> dict:
    if lang not in LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unknown language '{lang}'")
    response.set_cookie(LANGUAGE_COOKIE, lang, max_age=31536000, path="/")
    return {"lang": lang}


@router.get("/voices/{voice}/preview")
def voice_preview(voice: str) -> Response:
    try:
        wav_bytes = get_voice_preview(voice)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(content=wav_bytes, media_type="audio/wav")


@router.post("/generate")
def generate(request: GenerateRequest) -> Response:
    try:
        audio_bytes = generate_speech(request.text, request.voice)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(content=audio_bytes, media_type="audio/wav")
