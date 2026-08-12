from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .audio.combine import concat_wavs
from .paths import STATIC_DIR
from .routers import (
    chat,
    effects,
    presets,
    project_notes,
    projects,
    skills_files,
    variants,
    voices,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(voices.router)
app.include_router(projects.router)
app.include_router(project_notes.router)
app.include_router(variants.router)
app.include_router(effects.router)
app.include_router(chat.router)
app.include_router(presets.router)
app.include_router(skills_files.router)


@app.get("/")
def landing() -> FileResponse:
    return FileResponse(STATIC_DIR / "landing.html")


@app.get("/app")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _parse_json_field(name: str, value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid JSON in '{name}': {exc}"
        ) from exc


@app.post("/combine")
async def combine(
    clips: list[UploadFile] = File(...),
    pauses: str = Form("[]"),
    gains: str = Form("[]"),
    pans: str = Form("[]"),
    trailing_pause_ms: int = Form(0),
) -> Response:
    clip_bytes = [await clip.read() for clip in clips]
    parsed_pauses = _parse_json_field("pauses", pauses)
    parsed_gains = _parse_json_field("gains", gains)
    parsed_pans = _parse_json_field("pans", pans)
    try:
        combined = concat_wavs(
            clip_bytes,
            parsed_pauses,
            parsed_gains or None,
            trailing_pause_ms,
            parsed_pans or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=combined, media_type="audio/wav")
