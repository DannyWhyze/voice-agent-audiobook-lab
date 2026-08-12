from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..audio.combine import _read_wav_as_pcm16
from ..dialog.projects import get_chapter_reference_framerate
from ..dialog.variants import (
    activate_box_variant,
    activate_combined_variant,
    add_box_variant,
    delete_box_variant,
    delete_combined_variant,
    delete_inactive_variants,
    get_combined_variant_audio,
    get_variant_audio,
    set_combined_variant_label,
    set_combined_variant_lock,
)
from ..engine_client import EngineError, generate_speech
from ..schemas import GenerateRequest, SetVariantLabelRequest, SetVariantLockRequest

router = APIRouter()


@router.post("/projects/{project}/chapters/{chapter}/boxes/{box_index}/variants")
def project_box_generate_variant(
    project: str, chapter: str, box_index: int, request: GenerateRequest
) -> Response:
    try:
        audio_bytes = generate_speech(request.text, request.voice)
        filename = add_box_variant(project, chapter, box_index, audio_bytes)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"X-Variant-Filename": filename},
    )


@router.post("/projects/{project}/chapters/{chapter}/boxes/{box_index}/variants/upload")
async def project_box_upload_variant(
    project: str, chapter: str, box_index: int, audio: UploadFile = File(...)
) -> Response:
    audio_bytes = await audio.read()
    try:
        channels, framerate, _ = _read_wav_as_pcm16(audio_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    expected_framerate = get_chapter_reference_framerate(project, chapter) or 44100
    if framerate != expected_framerate:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected a {expected_framerate}Hz recording (matching this "
                f"chapter's existing audio), got {framerate}Hz."
            ),
        )
    if channels != 1:
        raise HTTPException(
            status_code=400,
            detail=f"Expected a mono (1-channel) recording, got {channels} channels.",
        )
    try:
        filename = add_box_variant(
            project, chapter, box_index, audio_bytes, suffix="recorded"
        )
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"X-Variant-Filename": filename},
    )


@router.get(
    "/projects/{project}/chapters/{chapter}/boxes/{box_index}/variants/{filename}"
)
def project_box_get_variant(
    project: str, chapter: str, box_index: int, filename: str
) -> FileResponse:
    try:
        path = get_variant_audio(project, chapter, box_index, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return FileResponse(path, media_type="audio/wav")


@router.delete(
    "/projects/{project}/chapters/{chapter}/boxes/{box_index}/variants/{filename}"
)
def project_box_delete_variant(
    project: str, chapter: str, box_index: int, filename: str
) -> dict:
    try:
        delete_box_variant(project, chapter, box_index, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put(
    "/projects/{project}/chapters/{chapter}/boxes/{box_index}/variants/{filename}/activate"
)
def project_box_activate_variant(
    project: str, chapter: str, box_index: int, filename: str
) -> dict:
    try:
        activate_box_variant(project, chapter, box_index, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.post("/projects/{project}/chapters/{chapter}/cleanup-variants")
def project_cleanup_variants(project: str, chapter: str) -> dict:
    try:
        delete_inactive_variants(project, chapter)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.get("/projects/{project}/chapters/{chapter}/combined-variants/{filename}")
def project_combined_get_variant(
    project: str, chapter: str, filename: str
) -> FileResponse:
    try:
        path = get_combined_variant_audio(project, chapter, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return FileResponse(path, media_type="audio/wav")


@router.delete("/projects/{project}/chapters/{chapter}/combined-variants/{filename}")
def project_combined_delete_variant(project: str, chapter: str, filename: str) -> dict:
    try:
        delete_combined_variant(project, chapter, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put(
    "/projects/{project}/chapters/{chapter}/combined-variants/{filename}/activate"
)
def project_combined_activate_variant(
    project: str, chapter: str, filename: str
) -> dict:
    try:
        activate_combined_variant(project, chapter, filename)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put("/projects/{project}/chapters/{chapter}/combined-variants/{filename}/lock")
def project_combined_lock_variant(
    project: str, chapter: str, filename: str, request: SetVariantLockRequest
) -> dict:
    set_combined_variant_lock(project, chapter, filename, request.locked)
    return {"status": "ok"}


@router.put("/projects/{project}/chapters/{chapter}/combined-variants/{filename}/label")
def project_combined_label_variant(
    project: str, chapter: str, filename: str, request: SetVariantLabelRequest
) -> dict:
    set_combined_variant_label(project, chapter, filename, request.label)
    return {"status": "ok"}
