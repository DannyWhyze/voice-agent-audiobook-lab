from __future__ import annotations

import io
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..audio.combine import _read_wav_as_pcm16
from ..audio.compressor import compress_pcm16
from ..audio.delay import apply_delay_pcm16
from ..audio.eq import apply_eq_pcm16
from ..audio.fade import apply_fade_pcm16
from ..audio.formant import formant_shift_pcm16
from ..audio.normalize import normalize_pcm16
from ..audio.pitch import pitch_shift_pcm16
from ..audio.reverb import apply_reverb_pcm16
from ..audio.trim import trim_pcm16
from ..dialog.effect_params import (
    save_box_effect_params,
    save_combined_effect_params,
)
from ..dialog.projects import get_chapter_audio, get_combined_audio
from ..dialog.variants import add_box_variant, add_combined_variant
from ..engine_client import EngineError
from ..schemas import (
    CompressorParams,
    DelayParams,
    EqParams,
    FadeParams,
    FormantParams,
    NormalizeParams,
    PitchParams,
    ReverbParams,
    TrimParams,
)

router = APIRouter()


@dataclass(frozen=True)
class EffectSpec:
    route_name: str
    dsp_fn: Callable[..., bytes]
    param_model: type[BaseModel]
    suffix: str
    box_key: str | None = None
    combined_key: str | None = None
    force_stereo: bool = False
    has_preview: bool = True


EFFECT_SPECS: list[EffectSpec] = [
    EffectSpec(
        route_name="compress",
        dsp_fn=compress_pcm16,
        param_model=CompressorParams,
        suffix="compressed",
        box_key="compressor_params",
        combined_key="combined_compressor_params",
    ),
    EffectSpec(
        route_name="reverb",
        dsp_fn=apply_reverb_pcm16,
        param_model=ReverbParams,
        suffix="reverb",
        box_key="reverb_params",
        combined_key="combined_reverb_params",
        force_stereo=True,
    ),
    EffectSpec(
        route_name="eq",
        dsp_fn=apply_eq_pcm16,
        param_model=EqParams,
        suffix="eq",
        box_key="eq_params",
        combined_key="combined_eq_params",
    ),
    EffectSpec(
        route_name="normalize",
        dsp_fn=normalize_pcm16,
        param_model=NormalizeParams,
        suffix="normalized",
        box_key="normalize_params",
        combined_key="combined_normalize_params",
    ),
    EffectSpec(
        route_name="pitch",
        dsp_fn=pitch_shift_pcm16,
        param_model=PitchParams,
        suffix="pitch_shifted",
        box_key="pitch_params",
        combined_key="combined_pitch_params",
    ),
    EffectSpec(
        route_name="formant",
        dsp_fn=formant_shift_pcm16,
        param_model=FormantParams,
        suffix="formant_shifted",
        box_key="formant_params",
        combined_key="combined_formant_params",
    ),
    EffectSpec(
        route_name="delay",
        dsp_fn=apply_delay_pcm16,
        param_model=DelayParams,
        suffix="delay",
        box_key="delay_params",
        combined_key="combined_delay_params",
    ),
    EffectSpec(
        route_name="trim",
        dsp_fn=trim_pcm16,
        param_model=TrimParams,
        suffix="trimmed",
        has_preview=False,
    ),
    EffectSpec(
        route_name="fade",
        dsp_fn=apply_fade_pcm16,
        param_model=FadeParams,
        suffix="faded",
        has_preview=False,
    ),
]


def _run_effect(path: Path, spec: EffectSpec, params: BaseModel) -> bytes:
    data = path.read_bytes()
    channels, framerate, pcm16 = _read_wav_as_pcm16(data)
    processed_pcm16 = spec.dsp_fn(pcm16, channels, framerate, **params.model_dump())

    output_channels = 2 if spec.force_stereo else channels
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_out:
        wav_out.setnchannels(output_channels)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(processed_pcm16)
    return output.getvalue()


def _register_effect_routes(spec: EffectSpec) -> None:
    def box_preview(project: str, chapter: str, box_index: int, params) -> Response:
        try:
            path = get_chapter_audio(project, chapter, box_index)
            result = _run_effect(path, spec, params)
        except EngineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(content=result, media_type="audio/wav")

    def combined_preview(project: str, chapter: str, params) -> Response:
        try:
            path = get_combined_audio(project, chapter)
            result = _run_effect(path, spec, params)
        except EngineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(content=result, media_type="audio/wav")

    def box_apply(project: str, chapter: str, box_index: int, params) -> Response:
        try:
            path = get_chapter_audio(project, chapter, box_index)
            result = _run_effect(path, spec, params)
            filename = add_box_variant(
                project, chapter, box_index, result, suffix=spec.suffix
            )
            if spec.box_key is not None:
                save_box_effect_params(
                    project, chapter, box_index, spec.box_key, params.model_dump()
                )
        except EngineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=result,
            media_type="audio/wav",
            headers={"X-Variant-Filename": filename},
        )

    def combined_apply(project: str, chapter: str, params) -> Response:
        try:
            path = get_combined_audio(project, chapter)
            result = _run_effect(path, spec, params)
            filename = add_combined_variant(
                project, chapter, result, suffix=spec.suffix
            )
            if spec.combined_key is not None:
                save_combined_effect_params(
                    project, chapter, spec.combined_key, params.model_dump()
                )
        except EngineError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=result,
            media_type="audio/wav",
            headers={"X-Variant-Filename": filename},
        )

    box_apply.__name__ = f"{spec.route_name}_box_apply"
    box_apply.__annotations__["params"] = spec.param_model
    combined_apply.__name__ = f"{spec.route_name}_combined_apply"
    combined_apply.__annotations__["params"] = spec.param_model

    router.post(
        f"/projects/{{project}}/chapters/{{chapter}}/boxes/{{box_index}}/{spec.route_name}/apply"
    )(box_apply)
    router.post(f"/projects/{{project}}/chapters/{{chapter}}/{spec.route_name}/apply")(
        combined_apply
    )

    if spec.has_preview:
        box_preview.__name__ = f"{spec.route_name}_box_preview"
        box_preview.__annotations__["params"] = spec.param_model
        combined_preview.__name__ = f"{spec.route_name}_combined_preview"
        combined_preview.__annotations__["params"] = spec.param_model

        router.post(
            f"/projects/{{project}}/chapters/{{chapter}}/boxes/{{box_index}}/{spec.route_name}/preview"
        )(box_preview)
        router.post(
            f"/projects/{{project}}/chapters/{{chapter}}/{spec.route_name}/preview"
        )(combined_preview)


for _spec in EFFECT_SPECS:
    _register_effect_routes(_spec)
