from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..dialog.skills_files import (
    create_skill,
    delete_file,
    get_file_content,
    list_files,
    save_file_content,
)
from ..engine_client import EngineError
from ..schemas import CreateSkillRequest, SaveSkillsFileRequest

router = APIRouter()


@router.get("/skills-files")
def skills_files_list() -> list[dict]:
    return list_files()


@router.post("/skills-files")
def skills_files_create(request: CreateSkillRequest) -> dict:
    try:
        path = create_skill(request.name, request.description)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"path": path}


@router.get("/skills-files/{file_path:path}")
def skills_files_get(file_path: str) -> dict:
    try:
        content = get_file_content(file_path)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"content": content}


@router.put("/skills-files/{file_path:path}")
def skills_files_save(file_path: str, request: SaveSkillsFileRequest) -> dict:
    try:
        save_file_content(file_path, request.content)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}


@router.delete("/skills-files/{file_path:path}")
def skills_files_delete(file_path: str) -> dict:
    try:
        delete_file(file_path)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}
