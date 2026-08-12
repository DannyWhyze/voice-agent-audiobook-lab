from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agents.chat_agent import stream_chat_reply
from ..agents.project_chat_agent import stream_project_chat_reply
from ..agents.script_chat_agent import stream_script_chat_reply
from ..engine_client import list_active_voices
from ..schemas import ChatRequest, ProjectChatRequest
from ..utils.fetch_ollama_models import fetch_ollama_models
from ..utils.verify_nvidia_models import fetch_verified_nvidia_models

router = APIRouter()

_nvidia_models_cache: list[dict] | None = None


def _format_sse_chunk(chunk_type: str, text: str) -> str:
    event_line = "" if chunk_type == "content" else f"event: {chunk_type}\n"
    return f"{event_line}data: {json.dumps({'chunk': text})}\n\n"


@router.get("/api/llm/ollama-models")
def list_ollama_models():
    return {"models": fetch_ollama_models(), "default_model": os.getenv("OLLAMA_MODEL")}


@router.get("/api/llm/nvidia-models")
def list_nvidia_models():
    global _nvidia_models_cache
    if _nvidia_models_cache is not None:
        return {"models": _nvidia_models_cache}
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        return {"models": []}
    _nvidia_models_cache = fetch_verified_nvidia_models(api_key=api_key)
    return {"models": _nvidia_models_cache}


@router.post("/projects/{project}/chapters/{chapter}/boxes/{box_index}/chat")
async def project_box_chat(
    project: str, chapter: str, box_index: int, request: ChatRequest
) -> StreamingResponse:
    prompt_messages = []
    if request.context_text:
        prompt_messages.append(
            {
                "role": "system",
                "content": f"Gesamtes Skript als Kontext: {request.context_text}",
            }
        )
    prompt_messages.append(
        {
            "role": "system",
            "content": f"Aktueller Text der Box: {request.current_text}",
        }
    )
    prompt_messages.extend(message.model_dump() for message in request.messages)

    try:
        reply_stream = stream_chat_reply(
            prompt_messages,
            project=project,
            provider=request.provider,
            model=request.model,
        )
        first_chunk = await anext(reply_stream, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def sse_events():
        try:
            if first_chunk is not None:
                yield _format_sse_chunk(*first_chunk)
            async for chunk_type, text in reply_stream:
                yield _format_sse_chunk(chunk_type, text)
        except Exception as exc:  # noqa: BLE001 - must catch any stream failure to emit event: error
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(sse_events(), media_type="text/event-stream")


def _voices_context_message() -> dict:
    voices = list_active_voices()
    if voices:
        content = (
            "Verfügbare Stimmen in diesem Projekt: "
            + ", ".join(voices)
            + ". Verwende ausschließlich diese Namen oder 'base_voice' für einen "
            "Sprecher ohne bestimmte Stimme — niemals andere oder erfundene Namen."
        )
    else:
        content = (
            "Aktuell sind keine Stimmen konfiguriert — verwende ausschließlich "
            "'base_voice' für alle Sprecher."
        )
    return {"role": "system", "content": content}


@router.post("/projects/{project}/chapters/{chapter}/script-chat")
async def project_script_chat(
    project: str, chapter: str, request: ChatRequest
) -> StreamingResponse:
    prompt_messages = [
        _voices_context_message(),
        {
            "role": "system",
            "content": f"Aktueller Text der Box: {request.current_text}",
        },
    ]
    prompt_messages.extend(message.model_dump() for message in request.messages)

    try:
        reply_stream = stream_script_chat_reply(
            prompt_messages,
            project=project,
            provider=request.provider,
            model=request.model,
            allow_extend_recorded_roles=request.allow_extend_recorded_roles,
        )
        first_chunk = await anext(reply_stream, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def sse_events():
        try:
            if first_chunk is not None:
                yield _format_sse_chunk(*first_chunk)
            async for chunk_type, text in reply_stream:
                yield _format_sse_chunk(chunk_type, text)
        except Exception as exc:  # noqa: BLE001 - must catch any stream failure to emit event: error
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(sse_events(), media_type="text/event-stream")


@router.post("/projects/{project}/chat")
async def project_chat(project: str, request: ProjectChatRequest) -> StreamingResponse:
    prompt_messages = [_voices_context_message()]
    prompt_messages.extend(message.model_dump() for message in request.messages)

    try:
        reply_stream = stream_project_chat_reply(
            prompt_messages,
            project=project,
            provider=request.provider,
            model=request.model,
        )
        first_chunk = await anext(reply_stream, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def sse_events():
        try:
            if first_chunk is not None:
                yield _format_sse_chunk(*first_chunk)
            async for chunk_type, text in reply_stream:
                yield _format_sse_chunk(chunk_type, text)
        except Exception as exc:  # noqa: BLE001 - must catch any stream failure to emit event: error
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(sse_events(), media_type="text/event-stream")
