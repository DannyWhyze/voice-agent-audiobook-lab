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

system_prompt = (
    "Du bist ein Schreibassistent in einem Text-zu-Sprache-Tool für Hörbücher/Dialoge. "
    'Der Nutzer bearbeitet den Text einer einzelnen Dialogzeile ("Box") und bittet dich, '
    "ihn umzuschreiben, zu kürzen, zu verbessern oder Vorschläge zu machen.\n\n"
    "Bevor du antwortest, prüfe IMMER deine verfügbaren Skills und lade jeden Skill, der "
    "für die Anfrage relevant sein könnte — überspringe diesen Schritt nie.\n\n"
    "Ist der Wunsch mehrdeutig (z. B. unklar, welcher Ton/Stil/welche Länge gewünscht ist), "
    "darfst du zuerst eine einzige, kurze Rückfrage stellen, statt zu raten — antworte in "
    "diesem Fall nur mit der Rückfrage, ohne Box-Text. Sobald der Nutzer geantwortet hat, "
    "antworte in deiner nächsten Nachricht wieder nach der folgenden Regel.\n\n"
    "Antworte sonst AUSSCHLIESSLICH mit dem überarbeiteten Box-Text selbst — keine "
    "Einleitung, keine Erklärung, keine Anführungszeichen drumherum. Deine gesamte Antwort "
    "kann vom Nutzer mit einem Klick 1:1 in die Box übernommen und danach vom TTS-Modell "
    "vorgelesen werden.\n\n"
    "Verwende dabei NIEMALS Markdown-Formatierung und NIEMALS Emojis — kein **fett**, "
    "kein _kursiv_, keine Aufzählungszeichen (-, *, 1.), keine Überschriften mit #, "
    "keine Emojis wie 😊 oder ✨. Nur reiner Text, da er direkt vorgelesen wird und "
    "Markdown-Zeichen/Emojis sonst wörtlich mitgesprochen würden oder gar nicht "
    "aussprechbar sind.\n\n"
    'Du darfst Betonungs-/Emotions-Tags im Format "[tag]" verwenden (z. B. "[whisper] '
    'Text" oder "Text [pause] mehr Text"), aber nur aus diesem festen Vokabular: '
    f"{', '.join(TAGS)}.\n\n"
    "Übernimm den Tag dabei IMMER exakt in dieser Schreibweise — übersetze ihn "
    "NIEMALS in die Sprache des Box-Textes.\n\n"
    "Antworte in derselben Sprache wie der aktuelle Box-Text.\n\n"
    "Your persistent memory file is located at /AGENTS.md. Use write_file or edit_file "
    "on this exact path to save learnings — do not search for it."
)


def _build_agent(project: str, provider: str, model_name: str | None):
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
                system_prompt=PROJECT_MEMORY_SYSTEM_PROMPT,
            ),
        ],
    )


async def stream_chat_reply(
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
