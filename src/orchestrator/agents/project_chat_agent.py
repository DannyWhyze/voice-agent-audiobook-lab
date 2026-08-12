from __future__ import annotations

import os
from collections.abc import AsyncIterator

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware import (
    FilesystemMiddleware,
    MemoryMiddleware,
    SkillsMiddleware,
)
from dotenv import load_dotenv
from langchain.agents import create_agent

from ..dialog.projects import _project_dir, ensure_agents_md
from ..paths import SKILLS_DIR
from .llm_provider import build_chat_model
from .memory_prompt import PROJECT_CHAT_MEMORY_SYSTEM_PROMPT

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

system_prompt = (
    "Du bist ein Onboarding-Assistent in einem Text-zu-Sprache-Tool für "
    "Hörbücher/Dialoge. Der Nutzer arbeitet an einem Projekt und möchte "
    "dir in einem lockeren Gespräch von seiner Geschichte, den Figuren, "
    "der Welt oder wichtigen Regeln erzählen.\n\n"
    "Du hast vollen Lese- und Schreibzugriff auf den gesamten "
    "Projektordner (nicht nur auf AGENTS.md). Trage neues Wissen "
    "selbstständig in passende Dateien ein, sobald du es erfährst — "
    "frag nicht erst um Erlaubnis:\n"
    "- Ergänze AGENTS.md für allgemeine Notizen und Regeln.\n"
    "- Lege bei Bedarf eigene, thematisch benannte Dateien an (z. B. "
    "Charaktere.md, Welt.md), statt alles in einer einzigen Datei zu "
    "sammeln.\n\n"
    "Verwende NIEMALS Emojis — weder in deinen Chat-Antworten noch in "
    "den .md-Dateien, die du schreibst. Auch keine Markdown-Symbol-"
    "Spielereien wie 📝 oder ✨ als Deko-Elemente vor Überschriften. Reiner "
    "Text (in den .md-Dateien normale Markdown-Struktur wie Überschriften "
    "und Listen ist dort erlaubt, nur keine Emojis).\n\n"
    "Bevor du antwortest, prüfe IMMER deine verfügbaren Skills und lade "
    "jeden Skill, der für die Anfrage relevant sein könnte.\n\n"
    "Im Kontext bekommst du die Liste der tatsächlich verfügbaren Stimmennamen. "
    "Wenn du einer Figur eine Stimme zuordnest oder das in einer Notiz "
    "festhältst, verwende ausschließlich einen dieser echten Namen (oder "
    "'base_voice' für eine Figur ohne bestimmte Stimme) — erfinde niemals "
    "einen Stimmennamen.\n\n"
    "Hat der Nutzer noch nichts über sein Projekt erzählt, stelle von dir "
    "aus natürliche, konkrete Rückfragen (z. B. nach Genre, "
    "Hauptfiguren oder Setting), statt zu warten.\n\n"
    "Antworte direkt, freundlich und auf Deutsch (oder in der Sprache des "
    "Nutzers)."
)


def _build_agent(project: str, provider: str, model_name: str | None):
    model = build_chat_model(provider, model_name, OLLAMA_MODEL)
    project_path = _project_dir(project)
    project_path.mkdir(parents=True, exist_ok=True)
    ensure_agents_md(project_path)
    project_backend = FilesystemBackend(root_dir=project_path, virtual_mode=True)
    skills_backend = FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)
    project_and_skills_backend = CompositeBackend(
        default=project_backend,
        routes={"/skills/": skills_backend},
    )
    return create_agent(
        model=model,
        tools=[],
        system_prompt=system_prompt,
        middleware=[
            FilesystemMiddleware(
                backend=project_and_skills_backend,
                tools=["ls", "read_file", "write_file", "edit_file", "glob", "grep"],
            ),
            SkillsMiddleware(backend=project_and_skills_backend, sources=["/skills/"]),
            MemoryMiddleware(
                backend=project_backend,
                sources=["/AGENTS.md"],
                system_prompt=PROJECT_CHAT_MEMORY_SYSTEM_PROMPT,
            ),
        ],
    )


async def stream_project_chat_reply(
    messages: list[dict],
    project: str,
    provider: str = "ollama",
    model: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    agent = _build_agent(project, provider, model)
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield ("reasoning", reasoning)
            if chunk.content:
                yield ("content", chunk.content)
