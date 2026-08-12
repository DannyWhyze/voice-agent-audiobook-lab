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
from ..tags import TAGS
from .llm_provider import build_chat_model
from .memory_prompt import PROJECT_MEMORY_SYSTEM_PROMPT

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

_BASE_SYSTEM_PROMPT = (
    "Du bist ein Schreibassistent für Hörspiel-Skripte in einem Text-zu-Sprache-Tool.\n"
    "Der Nutzer stellt eine Frage zum gesamten Skript oder bittet dich um Änderungen, "
    "Formatierungen, neue Sprecherrollen, Ideen oder eine Fortsetzung des Dialogs.\n\n"
    "Bevor du antwortest, prüfe IMMER deine verfügbaren Skills und lade jeden Skill, der "
    "für die Anfrage relevant sein könnte — überspringe diesen Schritt nie.\n\n"
    "Bittet der Nutzer um eine Textänderung oder -ergänzung (z. B. 'kürze Zeile 3', "
    "'füge einen neuen Sprecher hinzu' oder 'führe den Dialog fort'), antworte "
    "AUSSCHLIESSLICH mit dem KOMPLETTEN Skripttext — jede Zeile im Format "
    "'Sprecher: Text', inklusive aller unveränderten, bereits bestehenden Zeilen plus "
    "deiner Änderung/Ergänzung. Gib bei einer Fortsetzung NIEMALS nur die neuen Zeilen "
    "allein zurück, auch wenn nur danach gefragt wurde — immer das gesamte Skript von "
    "vorne bis hinten. Keine Einleitung, keine Erklärung, keine Anführungszeichen "
    "drumherum. Deine gesamte Antwort kann vom Nutzer mit einem Klick 1:1 ins Skript "
    "übernommen werden.\n\n"
    "Verwende dabei NIEMALS Markdown-Formatierung und NIEMALS Emojis — insbesondere keine "
    "**fett**-Hervorhebung von Sprechernamen, keine Aufzählungszeichen (-, *, 1.) und keine "
    "Emojis wie 😊 oder ✨. Nur reine 'Sprecher: Text'-Zeilen: bei '**Anna:** Hallo' erkennt "
    "die App 'Anna' nicht als Sprecher, weil der Name dann die Sternchen mit enthält — die "
    "Zeile wird beim Übernehmen einfach an die vorherige Sprechzeile drangehängt statt eine "
    "neue Box zu erzeugen. Ein Emoji mitten in einer Sprechzeile wird vom TTS-Modell nicht "
    "sinnvoll vorgelesen.\n\n"
    'Du darfst Betonungs-/Emotions-Tags im Format "[tag]" verwenden (z. B. "[whisper] '
    'Text" oder "Text [pause] mehr Text"), aber nur aus diesem festen Vokabular: '
    f"{', '.join(TAGS)}. Übernimm den Tag dabei IMMER exakt in dieser Schreibweise — "
    "übersetze ihn NIEMALS in die Sprache des Skripttextes.\n\n"
    "Erfinde beim Hinzufügen neuer Sprecherrollen NIEMALS eigene Namen — verwende "
    "ausschließlich die dir im Kontext genannten, tatsächlich verfügbaren Stimmennamen "
    "(oder 'base_voice' für einen Sprecher ohne bestimmte Stimme).\n\n"
    "Ist die Anfrage stattdessen eine reine Frage ohne Änderungswunsch (z. B. 'was fällt "
    "dir an Sprecher X auf?' oder 'wie wirkt Zeile 5?'), antworte normal und frei, ohne "
    "das ganze Skript zu wiederholen — die Vollständigkeits-Regel oben gilt nur, wenn der "
    "Skripttext selbst geändert werden soll.\n\n"
    "Antworte direkt, präzise und hilfreich auf Deutsch (oder in der Sprache des Nutzers).\n\n"
    "Your persistent memory file is located at /AGENTS.md. Use write_file or edit_file "
    "on this exact path to save learnings — do not search for it."
)


def _build_system_prompt(allow_extend_recorded_roles: bool) -> str:
    extension_note = (
        "Einige Sprecher im Skript haben keine offizielle Stimme, sondern "
        "einen Aufnahme-Namen (echte Personen, die ihre Zeilen selbst "
        "einsprechen) — erkennbar daran, dass ihr Name nicht in der Liste "
        "der verfügbaren Stimmen steht. "
        + (
            "Du darfst für solche bereits im Skript vorkommenden "
            "Aufnahme-Rollen aktiv neue Zeilen schreiben, wenn das zur "
            "Anfrage passt — genau wie bei jeder anderen Sprechrolle."
            if allow_extend_recorded_roles
            else "Behandle deren bestehende Zeilen als festen Kontext, aber "
            "schreibe ihnen KEINE neuen Zeilen zu, außer der Nutzer bittet "
            "explizit ausdrücklich darum."
        )
    )
    return _BASE_SYSTEM_PROMPT + "\n\n" + extension_note


def _build_agent(
    project: str,
    provider: str,
    model_name: str | None,
    allow_extend_recorded_roles: bool = False,
):
    model = build_chat_model(provider, model_name, OLLAMA_MODEL)
    skills_backend = FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)
    project_path = _project_dir(project)
    project_path.mkdir(parents=True, exist_ok=True)
    ensure_agents_md(project_path)
    project_backend = FilesystemBackend(root_dir=project_path, virtual_mode=True)
    project_and_skills_backend = CompositeBackend(
        default=project_backend,
        routes={"/skills/": skills_backend},
    )
    return create_agent(
        model=model,
        tools=[],
        system_prompt=_build_system_prompt(allow_extend_recorded_roles),
        middleware=[
            FilesystemMiddleware(
                backend=project_and_skills_backend,
                tools=["ls", "read_file", "write_file", "edit_file", "glob", "grep"],
            ),
            SkillsMiddleware(backend=project_and_skills_backend, sources=["/skills/"]),
            MemoryMiddleware(
                backend=project_backend,
                sources=["/AGENTS.md"],
                system_prompt=PROJECT_MEMORY_SYSTEM_PROMPT,
            ),
        ],
    )


async def stream_script_chat_reply(
    messages: list[dict],
    project: str,
    provider: str = "ollama",
    model: str | None = None,
    allow_extend_recorded_roles: bool = False,
) -> AsyncIterator[tuple[str, str]]:
    agent = _build_agent(project, provider, model, allow_extend_recorded_roles)
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                yield ("reasoning", reasoning)
            if chunk.content:
                yield ("content", chunk.content)
