from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama


def build_chat_model(
    provider: str, model: str | None, default_ollama_model: str | None
) -> BaseChatModel:
    """Build the LangChain chat model for the given provider/model selection.

    Raises ValueError if `provider == "nvidia"` and either NVIDIA_API_KEY is
    unset or no model id was given, or if `provider == "ollama"` and neither
    an explicit model nor OLLAMA_MODEL is available — the router turns this
    into a 400. There is deliberately no hardcoded Ollama model name here:
    which models exist is entirely local to whoever runs this app.
    """
    if provider == "nvidia":
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is not set")
        if not model:
            raise ValueError("model is required for nvidia provider")
        return ChatNVIDIA(model=model, api_key=api_key)

    resolved_model = model or default_ollama_model
    if not resolved_model:
        raise ValueError(
            "No Ollama model selected and OLLAMA_MODEL is not set — pick a "
            "model in the LLM dropdown or install one via 'ollama pull'."
        )
    return ChatOllama(model=resolved_model, reasoning=True)
