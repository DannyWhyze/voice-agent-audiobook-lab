from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ..dialog.effect_params import delete_preset, list_presets, save_preset
from ..engine_client import EngineError
from ..schemas import (
    CompressorParams,
    DelayParams,
    EqParams,
    FormantParams,
    NormalizeParams,
    PitchParams,
    ReverbParams,
    SavePresetRequest,
)

router = APIRouter()

EFFECT_PARAM_MODELS = {
    "compressor": CompressorParams,
    "reverb": ReverbParams,
    "eq": EqParams,
    "normalize": NormalizeParams,
    "pitch": PitchParams,
    "formant": FormantParams,
    "delay": DelayParams,
}


@router.get("/projects/{project}/presets")
def project_presets(project: str) -> dict:
    try:
        return list_presets(project)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/projects/{project}/presets/{effect_type}")
def project_save_preset(
    project: str, effect_type: str, request: SavePresetRequest
) -> dict:
    if effect_type not in EFFECT_PARAM_MODELS:
        raise HTTPException(
            status_code=400, detail=f"Unknown effect_type '{effect_type}'"
        )
    try:
        EFFECT_PARAM_MODELS[effect_type](**request.params)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        save_preset(project, effect_type, request.name, request.params)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.delete("/projects/{project}/presets/{effect_type}/{name}")
def project_delete_preset(project: str, effect_type: str, name: str) -> dict:
    if effect_type not in EFFECT_PARAM_MODELS:
        raise HTTPException(
            status_code=400, detail=f"Unknown effect_type '{effect_type}'"
        )
    try:
        delete_preset(project, effect_type, name)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"status": "ok"}
