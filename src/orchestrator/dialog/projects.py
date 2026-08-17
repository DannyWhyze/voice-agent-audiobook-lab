from __future__ import annotations

import io
import json
import logging
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from ..audio.mp3 import wav_to_mp3
from ..engine_client import EngineError, list_voices
from ..paths import DIALOG_PROJECTS_DIR

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^\w\- .]")


def sanitize_name(raw: str) -> str:
    name = _SAFE_NAME_RE.sub("", raw).strip(" .")
    if not name:
        raise EngineError(400, "Invalid name.")
    return name


def _natural_sort_key(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def _project_dir(project: str) -> Path:
    safe = sanitize_name(project)
    path = (DIALOG_PROJECTS_DIR / safe).resolve()
    if not path.is_relative_to(DIALOG_PROJECTS_DIR.resolve()):
        raise EngineError(400, "Invalid project name.")
    return path


DEFAULT_AGENTS_MD = (
    "# Agent Memory\n"
    "\n"
    "## Charaktere\n"
    "(Noch keine Charaktere notiert — der Agent trägt hier Namen, "
    "Persönlichkeit und Sprechweise ein, sobald sie im Skript auftauchen.)\n"
    "\n"
    "## Worldbuilding\n"
    "(Noch keine Welt-Regeln notiert — Setting, Zeit, Ort, wiederkehrende "
    "Fakten, die über Kapitel hinweg konsistent bleiben müssen.)\n"
)


def ensure_agents_md(project_dir: Path) -> None:
    agents_md_path = project_dir / "AGENTS.md"
    if not agents_md_path.exists():
        agents_md_path.write_text(DEFAULT_AGENTS_MD, encoding="utf-8")


def _chapter_path(project: str, chapter: str) -> Path:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    path = (project_dir / f"{safe_chapter}.json").resolve()
    if not path.is_relative_to(DIALOG_PROJECTS_DIR.resolve()):
        raise EngineError(400, "Invalid chapter name.")
    return path


def _chapter_order_path(project: str) -> Path:
    return _project_dir(project) / "_chapter_order.json"


def _read_chapter_order(project: str) -> list[str]:
    path = _chapter_order_path(project)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _write_chapter_order(project: str, order: list[str]) -> None:
    _chapter_order_path(project).write_text(
        json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_chapter_json(project: str, chapter: str) -> dict | None:
    safe_chapter = sanitize_name(chapter)
    json_path = _project_dir(project) / f"{safe_chapter}.json"
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text(encoding="utf-8"))


def _save_chapter_json(project: str, chapter: str, data: dict) -> None:
    safe_chapter = sanitize_name(chapter)
    json_path = _project_dir(project) / f"{safe_chapter}.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_projects() -> list[str]:
    if not DIALOG_PROJECTS_DIR.exists():
        return []
    return sorted(
        (p.name for p in DIALOG_PROJECTS_DIR.iterdir() if p.is_dir()),
        key=_natural_sort_key,
    )


def list_chapters(project: str) -> list[str]:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    existing = sorted(
        (
            p.stem
            for p in project_dir.glob("*.json")
            if p.stem not in ("_chapter_order", "_presets")
        ),
        key=_natural_sort_key,
    )
    order = _read_chapter_order(project)

    existing_lower = {name.lower(): name for name in existing}
    ordered = []
    for name in order:
        if name.lower() in existing_lower:
            ordered.append(name)

    ordered_set_lower = {name.lower() for name in ordered}
    remaining = [name for name in existing if name.lower() not in ordered_set_lower]
    return ordered + remaining


def list_chapters_with_audio(project: str) -> list[dict]:
    chapters = list_chapters(project)
    project_dir = _project_dir(project)
    result = []
    for name in chapters:
        safe_chapter = sanitize_name(name)
        combined_path = project_dir / f"{safe_chapter}_audio" / "combined.wav"
        json_path = project_dir / f"{safe_chapter}.json"
        combined_variants: list[str] = []
        active_combined_index = -1
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            combined_variants = data.get("combinedVariants", [])
            active_combined_index = data.get("activeCombinedIndex", -1)
        result.append(
            {
                "name": name,
                "has_combined_audio": combined_path.exists(),
                "combined_variants": combined_variants,
                "active_combined_index": active_combined_index,
            }
        )
    return result


def save_chapter_order(project: str, order: list[str]) -> None:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    _write_chapter_order(project, order)


def load_chapter(project: str, chapter: str) -> dict:
    path = _chapter_path(project, chapter)
    if not path.exists():
        raise EngineError(404, f"Chapter '{chapter}' not found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_chapter(
    project: str,
    chapter: str,
    boxes: list[dict],
    pause_ms: int,
    audio_clips: dict[int, bytes],
    combined_audio: bytes | None = None,
    end_pause_ms: int = 0,
) -> None:
    project_dir = _project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_agents_md(project_dir)
    safe_chapter = sanitize_name(chapter)
    path = project_dir / f"{safe_chapter}.json"
    content = {
        "boxes": boxes,
        "pause_ms": pause_ms,
        "end_pause_ms": end_pause_ms,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    audio_dir = project_dir / f"{safe_chapter}_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Delete files for indexes that no longer exist (e.g. box deleted), and
    # for indexes whose box is now empty/untouched (no variants, no fresh
    # clip this save) — a box inserted before/between existing ones reuses
    # an array position a *different* box previously occupied, and its old
    # box_N.wav would otherwise linger and get mistaken for this box's own
    # prior audio (add_box_variant()'s "seed an Original variant from
    # box_N.wav" check only looks at file existence, not which box actually
    # produced it). See docs/FIXES.md.
    num_boxes = len(boxes)
    for f in audio_dir.glob("box_*.wav"):
        try:
            # Extract box index from filename "box_{index}.wav"
            parts = f.stem.split("_")
            if len(parts) == 2 and parts[1].isdigit():
                idx = int(parts[1])
                is_now_blank = (
                    idx < num_boxes
                    and not boxes[idx].get("variants")
                    and idx not in audio_clips
                )
                if idx >= num_boxes or is_now_blank:
                    f.unlink()
        except OSError:
            logger.exception("Failed to delete unused box audio file %s", f)

    if combined_audio and (audio_dir / "combined.wav").exists():
        (audio_dir / "combined.wav").unlink()

    # Write newly provided audio clips
    for index, clip_bytes in audio_clips.items():
        (audio_dir / f"box_{index}.wav").write_bytes(clip_bytes)
    if combined_audio:
        (audio_dir / "combined.wav").write_bytes(combined_audio)


def get_chapter_reference_framerate(project: str, chapter: str) -> int | None:
    """Best-effort framerate of this chapter's existing generated audio, so new
    recordings can be resampled to match. Returns None if the chapter has no
    generated box audio yet (e.g. a brand new chapter)."""
    from ..audio.combine import _read_wav_as_pcm16

    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    if not audio_dir.exists():
        return None
    for wav_path in sorted(audio_dir.glob("box_*.wav")):
        try:
            _, framerate, _ = _read_wav_as_pcm16(wav_path.read_bytes())
            return framerate
        except (ValueError, OSError):
            continue
    return None


def get_chapter_audio(project: str, chapter: str, box_index: int) -> Path:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    path = project_dir / f"{safe_chapter}_audio" / f"box_{box_index}.wav"
    if not path.exists():
        # Self-healing: if the active box audio is missing, look up the active variant in chapter.json
        json_path = project_dir / f"{safe_chapter}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                boxes = data.get("boxes", [])
                if 0 <= box_index < len(boxes):
                    box = boxes[box_index]
                    variants = box.get("variants", [])
                    active_idx = box.get("activeIndex", -1)
                    if 0 <= active_idx < len(variants):
                        variant_file = sanitize_name(variants[active_idx])
                        variants_dir = (
                            project_dir / f"{safe_chapter}_audio" / "variants"
                        )
                        variant_path = variants_dir / variant_file
                        if variant_path.exists():
                            path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy(variant_path, path)
            except (json.JSONDecodeError, OSError):
                logger.exception(
                    "Self-healing failed to restore active variant for box %d",
                    box_index,
                )

    if not path.exists():
        raise EngineError(404, f"No audio for box {box_index} in chapter '{chapter}'")
    return path


def get_combined_audio(project: str, chapter: str) -> Path:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    path = project_dir / f"{safe_chapter}_audio" / "combined.wav"
    if not path.exists():
        raise EngineError(404, f"No combined audio for chapter '{chapter}'")
    return path


def build_combined_audio_zip(project: str, audio_format: str = "wav") -> bytes:
    chapters = list_chapters_with_audio(project)
    available = [c["name"] for c in chapters if c["has_combined_audio"]]
    if not available:
        raise EngineError(404, f"No combined audio in project '{project}'")

    date = datetime.now(UTC).strftime("%Y-%m-%d")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for name in available:
            path = get_combined_audio(project, name)
            data = path.read_bytes()
            if audio_format == "mp3":
                data = wav_to_mp3(data)
            zip_file.writestr(f"{name}_{project}_{date}.{audio_format}", data)
    return buffer.getvalue()


def rename_chapter(project: str, chapter: str, new_name: str) -> None:
    source = _chapter_path(project, chapter)
    if not source.exists():
        raise EngineError(404, f"Chapter '{chapter}' not found")

    safe_chapter = sanitize_name(chapter)
    safe_new_name = sanitize_name(new_name)
    if safe_new_name == safe_chapter:
        return

    project_dir = _project_dir(project)
    # Built directly instead of via _chapter_path(project, new_name): on
    # Windows, Path.resolve() normalizes an existing file's path back to its
    # actual on-disk casing, so a case-only new_name would silently resolve
    # back to the OLD casing before the rename even runs.
    target = source.parent / f"{safe_new_name}.json"

    if safe_new_name.lower() == safe_chapter.lower():
        # Case-only change: rename through a temporary name first. A direct
        # source.rename(target) risks the OS treating source/target as the
        # same path (case-insensitive filesystem) and no-op'ing the rename.
        temp_path = source.with_suffix(".tmp_rename")
        source.rename(temp_path)
        temp_path.rename(target)
    else:
        if target.exists():
            target.unlink()
            target_audio_dir = project_dir / f"{safe_new_name}_audio"
            if target_audio_dir.exists():
                shutil.rmtree(target_audio_dir)
        source.rename(target)

    source_audio_dir = project_dir / f"{safe_chapter}_audio"
    if source_audio_dir.exists():
        if safe_new_name.lower() == safe_chapter.lower():
            temp_audio_dir = project_dir / f"{safe_chapter}_audio_tmp_rename"
            if temp_audio_dir.exists():
                shutil.rmtree(temp_audio_dir)
            source_audio_dir.rename(temp_audio_dir)
            temp_audio_dir.rename(project_dir / f"{safe_new_name}_audio")
        else:
            source_audio_dir.rename(project_dir / f"{safe_new_name}_audio")

    order = _read_chapter_order(project)
    if safe_chapter in order:
        order = [safe_new_name if name == safe_chapter else name for name in order]
        _write_chapter_order(project, order)


def delete_chapter(project: str, chapter: str) -> None:
    path = _chapter_path(project, chapter)
    if not path.exists():
        raise EngineError(404, f"Chapter '{chapter}' not found")
    path.unlink()

    safe_chapter = sanitize_name(chapter)
    audio_dir = _project_dir(project) / f"{safe_chapter}_audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)


def clear_chapter_audio(project: str, chapter: str) -> None:
    """Wipe all generated audio for a chapter (box takes, combined takes,
    and every variant), used by the frontend's "Clear dialog" action. Unlike
    delete_chapter(), the chapter itself and its box text survive -- only
    audio and the variant bookkeeping in chapter.json are reset."""
    path = _chapter_path(project, chapter)
    if not path.exists():
        raise EngineError(404, f"Chapter '{chapter}' not found")

    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)

    data = _load_chapter_json(project, chapter)
    if data is not None:
        for box in data.get("boxes", []):
            box["variants"] = []
            box["activeIndex"] = -1
            box.pop("variantLocks", None)
        data["combinedVariants"] = []
        data["activeCombinedIndex"] = -1
        data.pop("combinedVariantLocks", None)
        data.pop("combinedVariantLabels", None)
        _save_chapter_json(project, chapter, data)


def rename_project(project: str, new_name: str) -> None:
    source = _project_dir(project)
    if not source.exists():
        raise EngineError(404, f"Project '{project}' not found")

    safe_project = sanitize_name(project)
    safe_new_name = sanitize_name(new_name)
    if safe_new_name == safe_project:
        return

    target = source.parent / safe_new_name

    if safe_new_name.lower() == safe_project.lower():
        # Case-only change: rename through a temporary name first, same
        # reasoning as rename_chapter() -- a case-insensitive filesystem can
        # treat source/target as the same path and no-op a direct rename.
        temp_path = source.parent / f"{safe_project}_tmp_rename"
        source.rename(temp_path)
        temp_path.rename(target)
    else:
        if target.exists():
            raise EngineError(409, f"Project '{new_name}' already exists")
        source.rename(target)


def delete_project(project: str) -> None:
    project_dir = _project_dir(project)
    if not project_dir.exists():
        raise EngineError(404, f"Project '{project}' not found")
    shutil.rmtree(project_dir)


def find_voice_usage(voice_name: str) -> list[dict]:
    if voice_name not in list_voices():
        raise EngineError(400, f"Voice '{voice_name}' not found")
    usages = []
    for project in list_projects():
        for chapter in list_chapters(project):
            data = _load_chapter_json(project, chapter)
            if data is None:
                continue
            for i, box in enumerate(data.get("boxes", [])):
                if box.get("voice") == voice_name:
                    usages.append(
                        {"project": project, "chapter": chapter, "box_index": i}
                    )
    return usages


def rename_voice_everywhere(old_name: str, new_name: str) -> None:
    for project in list_projects():
        for chapter in list_chapters(project):
            data = _load_chapter_json(project, chapter)
            if data is None:
                continue
            changed = False
            for box in data.get("boxes", []):
                if box.get("voice") == old_name:
                    box["voice"] = new_name
                    changed = True
            if changed:
                _save_chapter_json(project, chapter, data)
