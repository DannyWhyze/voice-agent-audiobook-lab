from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..dialog.project_notes import (
    create_memory_file,
    delete_file,
    get_file_content,
    list_files,
    save_file_content,
)
from ..engine_client import EngineError
from ..schemas import CreateMemoryFileRequest, SaveSkillsFileRequest

router = APIRouter()


@router.get("/projects/{project}/notes")
def project_notes_list(project: str) -> list[dict]:
    return list_files(project)


@router.post("/projects/{project}/notes")
def project_notes_create(project: str, request: CreateMemoryFileRequest) -> dict:
    try:
        path = create_memory_file(project, request.name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"path": path}


@router.get("/projects/{project}/notes/{file_path:path}")
def project_notes_get(project: str, file_path: str) -> dict:
    try:
        content = get_file_content(project, file_path)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"content": content}


@router.put("/projects/{project}/notes/{file_path:path}")
def project_notes_save(
    project: str, file_path: str, request: SaveSkillsFileRequest
) -> dict:
    try:
        save_file_content(project, file_path, request.content)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.delete("/projects/{project}/notes/{file_path:path}")
def project_notes_delete(project: str, file_path: str) -> dict:
    try:
        delete_file(project, file_path)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}
