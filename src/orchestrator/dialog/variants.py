from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..engine_client import EngineError
from .projects import (
    _load_chapter_json,
    _project_dir,
    _save_chapter_json,
    sanitize_name,
)

# Sanity cap for auto-extending a chapter's box list (see add_box_variant) —
# generous for any real chapter, just guards against a wildly out-of-range
# box_index blowing up the JSON.
MAX_BOX_INDEX = 500


def add_box_variant(
    project: str,
    chapter: str,
    box_index: int,
    audio_bytes: bytes,
    suffix: str | None = None,
) -> str:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)

    suffix_part = f"_{suffix}" if suffix else ""
    filename = f"box_{box_index}_variant_{int(time.time() * 1000)}{suffix_part}.wav"
    (variants_dir / filename).write_bytes(audio_bytes)

    data = _load_chapter_json(project, chapter)
    if data is not None:
        boxes = data.setdefault("boxes", [])
        if 0 <= box_index <= MAX_BOX_INDEX:
            # Boxes added in the browser since the chapter was last explicitly
            # saved don't exist in chapter.json yet — extend the list with
            # empty placeholders so generation/effects work without requiring
            # a save first. The next real "Kapitel speichern" overwrites these
            # with the actual box data anyway.
            while len(boxes) <= box_index:
                boxes.append(
                    {"text": "", "voice": None, "variants": [], "activeIndex": -1}
                )
            box = boxes[box_index]
            if (
                not box.get("variants")
                and (audio_dir / f"box_{box_index}.wav").exists()
            ):
                orig_filename = f"box_{box_index}_variant_original.wav"
                shutil.copy(
                    audio_dir / f"box_{box_index}.wav", variants_dir / orig_filename
                )
                box["variants"] = [orig_filename]
                box["activeIndex"] = 0

            if "variants" not in box:
                box["variants"] = []
            box["variants"].append(filename)

            # Every newly added variant becomes the active one, so effects/generation
            # always chain onto whatever was produced last (see docs/FIXES.md,
            # "Effekte wurden nicht auf die zuletzt aktive Variante angewendet").
            box["activeIndex"] = len(box["variants"]) - 1
            # Copy to box_{box_index}.wav, the file every later effect apply reads from.
            shutil.copy(variants_dir / filename, audio_dir / f"box_{box_index}.wav")

            _save_chapter_json(project, chapter, data)

    return filename


def delete_box_variant(
    project: str, chapter: str, box_index: int, filename: str
) -> None:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "variants"

    data = _load_chapter_json(project, chapter)
    if data is not None:
        boxes = data.get("boxes", [])
        if 0 <= box_index < len(boxes):
            box = boxes[box_index]
            if box.get("variantLocks", {}).get(safe_filename):
                raise EngineError(400, f"Variant {filename} is locked")

    file_path = variants_dir / safe_filename
    if file_path.exists():
        file_path.unlink()

    if data is not None:
        boxes = data.get("boxes", [])
        if 0 <= box_index < len(boxes):
            box = boxes[box_index]
            variants = box.get("variants", [])
            if safe_filename in variants:
                idx = variants.index(safe_filename)
                variants.remove(safe_filename)
                box.get("variantLocks", {}).pop(safe_filename, None)
                active_idx = box.get("activeIndex", -1)

                if not variants:
                    box["activeIndex"] = -1
                    active_wav = audio_dir / f"box_{box_index}.wav"
                    if active_wav.exists():
                        active_wav.unlink()
                else:
                    if idx == active_idx:
                        # Make the last remaining variant active
                        new_active_idx = len(variants) - 1
                        box["activeIndex"] = new_active_idx
                        shutil.copy(
                            variants_dir / variants[new_active_idx],
                            audio_dir / f"box_{box_index}.wav",
                        )
                    elif idx < active_idx:
                        box["activeIndex"] = active_idx - 1

            _save_chapter_json(project, chapter, data)


def activate_box_variant(
    project: str, chapter: str, box_index: int, filename: str
) -> None:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "variants"

    data = _load_chapter_json(project, chapter)
    if data is not None:
        boxes = data.get("boxes", [])
        if 0 <= box_index < len(boxes):
            box = boxes[box_index]
            variants = box.get("variants", [])
            if safe_filename in variants:
                box["activeIndex"] = variants.index(safe_filename)
                shutil.copy(
                    variants_dir / safe_filename, audio_dir / f"box_{box_index}.wav"
                )
                _save_chapter_json(project, chapter, data)


def get_variant_audio(
    project: str, chapter: str, box_index: int, filename: str
) -> Path:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    path = project_dir / f"{safe_chapter}_audio" / "variants" / safe_filename
    if not path.exists():
        raise EngineError(404, f"Variant {filename} not found")
    return path


def delete_inactive_variants(project: str, chapter: str) -> None:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "variants"
    combined_variants_dir = audio_dir / "combined_variants"

    data = _load_chapter_json(project, chapter)
    if data is not None:
        boxes = data.get("boxes", [])

        # Locked variants survive cleanup even when inactive -- only
        # unlocked, inactive variants get pruned.
        active_filenames = set()
        for box in boxes:
            variants = box.get("variants", [])
            active_idx = box.get("activeIndex", -1)
            active_file = (
                variants[active_idx] if 0 <= active_idx < len(variants) else None
            )
            locks = box.get("variantLocks", {})

            kept = []
            for f in variants:
                if (f == active_file or locks.get(f)) and f not in kept:
                    kept.append(f)

            box["variants"] = kept
            box["activeIndex"] = kept.index(active_file) if active_file in kept else -1
            active_filenames.update(kept)

        # add_combined_variant() always activates its own result (see there),
        # so "no active index" only happens with an empty combinedVariants
        # list or a legacy chapter.json predating that fix -- guard it
        # instead of assuming index 0, and only prune once something's
        # genuinely active. Locked combined variants survive the same way as
        # locked box variants.
        combined_variants = data.get("combinedVariants", [])
        active_combined_idx = data.get("activeCombinedIndex", -1)
        active_combined_filenames: set[str] = set()
        if 0 <= active_combined_idx < len(combined_variants):
            active_combined_file = combined_variants[active_combined_idx]
            combined_locks = data.get("combinedVariantLocks", {})

            kept_combined = []
            for f in combined_variants:
                if (
                    f == active_combined_file or combined_locks.get(f)
                ) and f not in kept_combined:
                    kept_combined.append(f)

            active_combined_filenames = set(kept_combined)
            data["combinedVariants"] = kept_combined
            data["activeCombinedIndex"] = kept_combined.index(active_combined_file)

        _save_chapter_json(project, chapter, data)

        if variants_dir.exists():
            for f in variants_dir.glob("*.wav"):
                if f.name not in active_filenames:
                    f.unlink()

        if active_combined_filenames and combined_variants_dir.exists():
            for f in combined_variants_dir.glob("*.wav"):
                if f.name not in active_combined_filenames:
                    f.unlink()


def add_combined_variant(
    project: str, chapter: str, audio_bytes: bytes, suffix: str | None = None
) -> str:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "combined_variants"
    variants_dir.mkdir(parents=True, exist_ok=True)

    suffix_part = f"_{suffix}" if suffix else ""
    filename = f"combined_variant_{int(time.time() * 1000)}{suffix_part}.wav"
    (variants_dir / filename).write_bytes(audio_bytes)

    data = _load_chapter_json(project, chapter)
    if data is not None:
        variants = data.setdefault("combinedVariants", [])
        variants.append(filename)
        # Every newly added variant becomes the active one, so effects always
        # chain onto whatever was produced last (same fix as add_box_variant,
        # see docs/FIXES.md).
        data["activeCombinedIndex"] = len(variants) - 1
        # Copy to combined.wav, the file every later effect apply reads from.
        shutil.copy(variants_dir / filename, audio_dir / "combined.wav")
        _save_chapter_json(project, chapter, data)

    return filename


def delete_combined_variant(project: str, chapter: str, filename: str) -> None:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "combined_variants"

    data = _load_chapter_json(project, chapter)
    if data is not None and data.get("combinedVariantLocks", {}).get(safe_filename):
        raise EngineError(400, f"Variant {filename} is locked")

    file_path = variants_dir / safe_filename
    if file_path.exists():
        file_path.unlink()

    if data is not None:
        variants = data.get("combinedVariants", [])
        if safe_filename in variants:
            idx = variants.index(safe_filename)
            variants.remove(safe_filename)
            data.get("combinedVariantLocks", {}).pop(safe_filename, None)
            data.get("combinedVariantLabels", {}).pop(safe_filename, None)
            active_idx = data.get("activeCombinedIndex", -1)

            if idx == active_idx:
                data["activeCombinedIndex"] = -1
            elif idx < active_idx:
                data["activeCombinedIndex"] = active_idx - 1

            data["combinedVariants"] = variants
            _save_chapter_json(project, chapter, data)


def activate_combined_variant(project: str, chapter: str, filename: str) -> None:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    audio_dir = project_dir / f"{safe_chapter}_audio"
    variants_dir = audio_dir / "combined_variants"

    data = _load_chapter_json(project, chapter)
    if data is not None:
        variants = data.get("combinedVariants", [])
        if safe_filename in variants:
            data["activeCombinedIndex"] = variants.index(safe_filename)
            shutil.copy(variants_dir / safe_filename, audio_dir / "combined.wav")
            _save_chapter_json(project, chapter, data)


def set_combined_variant_lock(
    project: str, chapter: str, filename: str, locked: bool
) -> None:
    safe_filename = sanitize_name(filename)

    data = _load_chapter_json(project, chapter)
    if data is not None:
        locks = data.setdefault("combinedVariantLocks", {})
        if locked:
            locks[safe_filename] = True
        else:
            locks.pop(safe_filename, None)
        _save_chapter_json(project, chapter, data)


def set_combined_variant_label(
    project: str, chapter: str, filename: str, label: str
) -> None:
    safe_filename = sanitize_name(filename)

    data = _load_chapter_json(project, chapter)
    if data is not None:
        labels = data.setdefault("combinedVariantLabels", {})
        if label:
            labels[safe_filename] = label
        else:
            labels.pop(safe_filename, None)
        _save_chapter_json(project, chapter, data)


def get_combined_variant_audio(project: str, chapter: str, filename: str) -> Path:
    safe_chapter = sanitize_name(chapter)
    safe_filename = sanitize_name(filename)
    project_dir = _project_dir(project)
    path = project_dir / f"{safe_chapter}_audio" / "combined_variants" / safe_filename
    if not path.exists():
        raise EngineError(404, f"Combined variant {filename} not found")
    return path
