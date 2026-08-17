from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..dialog.projects import (
    build_combined_audio_zip,
    clear_chapter_audio,
    delete_chapter,
    delete_project,
    get_chapter_audio,
    get_chapter_reference_framerate,
    get_combined_audio,
    list_chapters,
    list_chapters_with_audio,
    list_projects,
    load_chapter,
    rename_chapter,
    rename_project,
    replace_voice_in_chapter,
    save_chapter,
    save_chapter_order,
)
from ..engine_client import EngineError
from ..schemas import (
    RenameChapterRequest,
    RenameProjectRequest,
    RenameVoiceRequest,
    ReorderChaptersRequest,
)

router = APIRouter()


def _parse_json_field(name: str, value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON in '{name}': {exc}"
        ) from exc


@router.get("/projects")
def projects() -> list[str]:
    return list_projects()


@router.put("/projects/{project}/rename")
def rename_project_route(project: str, request: RenameProjectRequest) -> dict:
    try:
        rename_project(project, request.new_name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.get("/projects/{project}/chapters")
def project_chapters(project: str) -> list[str]:
    try:
        return list_chapters(project)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/projects/{project}/chapter-order")
def reorder_chapters(project: str, request: ReorderChaptersRequest) -> dict:
    try:
        save_chapter_order(project, request.order)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put("/projects/{project}/chapters/{chapter}/rename")
def rename_project_chapter(
    project: str, chapter: str, request: RenameChapterRequest
) -> dict:
    try:
        rename_chapter(project, chapter, request.new_name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.get("/projects/{project}/chapters/{chapter}")
def project_chapter(project: str, chapter: str) -> dict:
    try:
        return load_chapter(project, chapter)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project}/chapters/{chapter}/reference-framerate")
def project_chapter_reference_framerate(project: str, chapter: str) -> dict:
    # 44100 matches s2.cpp's own hardcoded codec default (s2_codec.cpp:757), used
    # only when this chapter has no generated audio yet to read a real value from.
    framerate = get_chapter_reference_framerate(project, chapter) or 44100
    return {"framerate": framerate}


@router.get("/projects/{project}/chapters/{chapter}/audio/{box_index}")
def project_chapter_audio(project: str, chapter: str, box_index: int) -> FileResponse:
    try:
        path = get_chapter_audio(project, chapter, box_index)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return FileResponse(path, media_type="audio/wav")


@router.get("/projects/{project}/chapters/{chapter}/combined-audio")
def project_chapter_combined_audio(project: str, chapter: str) -> FileResponse:
    try:
        path = get_combined_audio(project, chapter)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return FileResponse(path, media_type="audio/wav")


@router.get("/projects/{project}/download-all")
def project_download_all(project: str, audio_format: str = "wav") -> Response:
    if audio_format not in ("wav", "mp3"):
        raise HTTPException(
            status_code=400, detail="audio_format must be 'wav' or 'mp3'."
        )
    try:
        zip_bytes = build_combined_audio_zip(project, audio_format=audio_format)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return Response(content=zip_bytes, media_type="application/zip")


@router.get("/projects/{project}/chapters-with-audio")
def project_chapters_with_audio(project: str) -> list[dict]:
    try:
        return list_chapters_with_audio(project)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/projects/{project}/chapters/{chapter}")
async def save_project_chapter(
    project: str,
    chapter: str,
    boxes: str = Form(...),
    pause_ms: int = Form(400),
    clips: list[UploadFile] = File(default=[]),
    clip_indices: str = Form("[]"),
    combined_clip: UploadFile | None = File(None),
    end_pause_ms: int = Form(0),
) -> dict:
    parsed_boxes = _parse_json_field("boxes", boxes)
    parsed_indices = _parse_json_field("clip_indices", clip_indices)
    if len(clips) != len(parsed_indices):
        raise HTTPException(
            status_code=400, detail="clips and clip_indices length mismatch"
        )
    if not all(
        isinstance(index, int) and 0 <= index < len(parsed_boxes)
        for index in parsed_indices
    ):
        raise HTTPException(status_code=400, detail="Invalid clip_indices value")

    audio_clips = {
        index: await clip.read() for index, clip in zip(parsed_indices, clips)
    }
    combined_audio = await combined_clip.read() if combined_clip is not None else None
    try:
        save_chapter(
            project,
            chapter,
            parsed_boxes,
            pause_ms,
            audio_clips,
            combined_audio,
            end_pause_ms,
        )
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.post("/projects/{project}/chapters/{chapter}/clear-audio")
def clear_project_chapter_audio(project: str, chapter: str) -> dict:
    try:
        clear_chapter_audio(project, chapter)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.put("/projects/{project}/chapters/{chapter}/voices/{name}/replace")
def replace_project_chapter_voice(
    project: str, chapter: str, name: str, request: RenameVoiceRequest
) -> dict:
    try:
        count = replace_voice_in_chapter(project, chapter, name, request.new_name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"replaced": count}



@router.delete("/projects/{project}/chapters/{chapter}")
def delete_project_chapter(project: str, chapter: str) -> dict:
    try:
        delete_chapter(project, chapter)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.delete("/projects/{project}")
def delete_project_route(project: str) -> dict:
    try:
        delete_project(project)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}
