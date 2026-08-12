import json

import pytest

from src.orchestrator.dialog import variants as dialog_variants
from src.orchestrator.engine_client import EngineError


def _read_chapter_json(project_dir):
    path = project_dir / "TestProject" / "Chapter1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_add_combined_variant_creates_file_and_json_entry(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert variant_path.exists()
    assert variant_path.read_bytes() == b"COMPRESSEDBYTES"

    data = _read_chapter_json(project_dir)
    assert data["combinedVariants"] == [filename]
    assert data["activeCombinedIndex"] == 0


def test_add_combined_variant_activates_and_copies_to_combined_wav(project_dir):
    combined_path = project_dir / "TestProject" / "Chapter1_audio" / "combined.wav"

    dialog_variants.add_combined_variant("TestProject", "Chapter1", b"COMPRESSEDBYTES")

    # Every new variant becomes the active one (same fix as add_box_variant,
    # see docs/FIXES.md) -- otherwise a later effect apply reads combined.wav
    # via get_combined_audio() and silently reprocesses the pre-effect
    # original instead of chaining onto this result.
    assert combined_path.read_bytes() == b"COMPRESSEDBYTES"
    assert _read_chapter_json(project_dir)["activeCombinedIndex"] == 0


def test_add_combined_variant_chains_activation_across_multiple_calls(project_dir):
    combined_path = project_dir / "TestProject" / "Chapter1_audio" / "combined.wav"

    first = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"FIRST")
    assert combined_path.read_bytes() == b"FIRST"
    assert _read_chapter_json(project_dir)["activeCombinedIndex"] == 0

    second = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"SECOND")
    assert combined_path.read_bytes() == b"SECOND"
    data = _read_chapter_json(project_dir)
    assert data["combinedVariants"] == [first, second]
    assert data["activeCombinedIndex"] == 1


def test_activate_combined_variant_copies_over_combined_wav(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", filename)

    combined_path = project_dir / "TestProject" / "Chapter1_audio" / "combined.wav"
    assert combined_path.read_bytes() == b"COMPRESSEDBYTES"
    assert _read_chapter_json(project_dir)["activeCombinedIndex"] == 0


def test_delete_combined_variant_removes_file_and_entry(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    dialog_variants.delete_combined_variant("TestProject", "Chapter1", filename)

    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert not variant_path.exists()
    assert _read_chapter_json(project_dir)["combinedVariants"] == []


def test_delete_combined_variant_resets_active_index_if_it_was_active(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", filename)
    dialog_variants.delete_combined_variant("TestProject", "Chapter1", filename)

    assert _read_chapter_json(project_dir)["activeCombinedIndex"] == -1


def test_delete_combined_variant_shifts_active_index_when_earlier_entry_removed(
    project_dir,
):
    first = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"FIRST")
    second = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"SECOND")
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", second)

    dialog_variants.delete_combined_variant("TestProject", "Chapter1", first)

    data = _read_chapter_json(project_dir)
    assert data["combinedVariants"] == [second]
    assert data["activeCombinedIndex"] == 0


def test_get_combined_variant_audio_returns_path(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    path = dialog_variants.get_combined_variant_audio(
        "TestProject", "Chapter1", filename
    )
    assert path.read_bytes() == b"COMPRESSEDBYTES"


def test_get_combined_variant_audio_raises_for_missing_file(project_dir):
    with pytest.raises(EngineError):
        dialog_variants.get_combined_variant_audio(
            "TestProject", "Chapter1", "does-not-exist.wav"
        )


def test_cleanup_leaves_combined_variants_untouched_when_none_active(project_dir):
    first = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"FIRST")
    second = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"SECOND")

    # add_combined_variant now always activates its own result (see above),
    # so "no active index" can no longer arise from normal use -- simulate a
    # legacy chapter.json (written before that fix) to keep covering the
    # defensive branch in delete_inactive_variants that must not crash or
    # assume index 0 when activeCombinedIndex is invalid.
    path = project_dir / "TestProject" / "Chapter1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["activeCombinedIndex"] = -1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    dialog_variants.delete_inactive_variants("TestProject", "Chapter1")

    data = _read_chapter_json(project_dir)
    assert set(data["combinedVariants"]) == {first, second}
    assert data["activeCombinedIndex"] == -1

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "combined_variants"
    assert (variants_dir / first).exists()
    assert (variants_dir / second).exists()


def test_cleanup_prunes_combined_variants_down_to_the_active_one(project_dir):
    first = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"FIRST")
    second = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"SECOND")
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", second)

    dialog_variants.delete_inactive_variants("TestProject", "Chapter1")

    data = _read_chapter_json(project_dir)
    assert data["combinedVariants"] == [second]
    assert data["activeCombinedIndex"] == 0

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "combined_variants"
    assert not (variants_dir / first).exists()
    assert (variants_dir / second).exists()


def test_set_combined_variant_lock_sets_and_clears_flag(project_dir):
    filename = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"BYTES")

    dialog_variants.set_combined_variant_lock("TestProject", "Chapter1", filename, True)
    assert _read_chapter_json(project_dir)["combinedVariantLocks"] == {filename: True}

    dialog_variants.set_combined_variant_lock(
        "TestProject", "Chapter1", filename, False
    )
    assert _read_chapter_json(project_dir).get("combinedVariantLocks", {}) == {}


def test_delete_combined_variant_rejects_locked_variant(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"LOCKED"
    )
    dialog_variants.set_combined_variant_lock("TestProject", "Chapter1", filename, True)

    with pytest.raises(EngineError):
        dialog_variants.delete_combined_variant("TestProject", "Chapter1", filename)

    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert variant_path.exists()
    assert filename in _read_chapter_json(project_dir)["combinedVariants"]


def test_cleanup_keeps_locked_combined_variant_even_when_another_is_active(project_dir):
    first = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"FIRST")
    second = dialog_variants.add_combined_variant("TestProject", "Chapter1", b"SECOND")
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", second)
    dialog_variants.set_combined_variant_lock("TestProject", "Chapter1", first, True)

    dialog_variants.delete_inactive_variants("TestProject", "Chapter1")

    data = _read_chapter_json(project_dir)
    assert set(data["combinedVariants"]) == {first, second}
    assert data["combinedVariants"][data["activeCombinedIndex"]] == second

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "combined_variants"
    assert (variants_dir / first).exists()
    assert (variants_dir / second).exists()


def test_cleanup_still_prunes_box_variants_as_before(project_dir):
    chapter_json_path = project_dir / "TestProject" / "Chapter1.json"
    data = _read_chapter_json(project_dir)
    data["boxes"] = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_a.wav", "box_0_variant_b.wav"],
            "activeIndex": 1,
        }
    ]
    chapter_json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "box_0_variant_a.wav").write_bytes(b"A")
    (variants_dir / "box_0_variant_b.wav").write_bytes(b"B")

    dialog_variants.delete_inactive_variants("TestProject", "Chapter1")

    assert not (variants_dir / "box_0_variant_a.wav").exists()
    assert (variants_dir / "box_0_variant_b.wav").exists()

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["variants"] == ["box_0_variant_b.wav"]
    assert data_after["boxes"][0]["activeIndex"] == 0


def test_delete_box_variant_rejects_locked_variant(project_dir):
    chapter_json_path = project_dir / "TestProject" / "Chapter1.json"
    data = _read_chapter_json(project_dir)
    data["boxes"] = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_a.wav", "box_0_variant_b.wav"],
            "activeIndex": 1,
            "variantLocks": {"box_0_variant_a.wav": True},
        }
    ]
    chapter_json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "box_0_variant_a.wav").write_bytes(b"A")
    (variants_dir / "box_0_variant_b.wav").write_bytes(b"B")

    with pytest.raises(EngineError):
        dialog_variants.delete_box_variant(
            "TestProject", "Chapter1", 0, "box_0_variant_a.wav"
        )

    assert (variants_dir / "box_0_variant_a.wav").exists()
    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_a.wav",
        "box_0_variant_b.wav",
    ]


def test_cleanup_keeps_locked_box_variant_even_when_inactive(project_dir):
    chapter_json_path = project_dir / "TestProject" / "Chapter1.json"
    data = _read_chapter_json(project_dir)
    data["boxes"] = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_a.wav", "box_0_variant_b.wav"],
            "activeIndex": 1,
            "variantLocks": {"box_0_variant_a.wav": True},
        }
    ]
    chapter_json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    variants_dir = project_dir / "TestProject" / "Chapter1_audio" / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "box_0_variant_a.wav").write_bytes(b"A")
    (variants_dir / "box_0_variant_b.wav").write_bytes(b"B")

    dialog_variants.delete_inactive_variants("TestProject", "Chapter1")

    assert (variants_dir / "box_0_variant_a.wav").exists()
    assert (variants_dir / "box_0_variant_b.wav").exists()

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_a.wav",
        "box_0_variant_b.wav",
    ]
    assert data_after["boxes"][0]["activeIndex"] == 1


def test_add_box_variant_with_suffix_appends_it_to_filename(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    filename = dialog_variants.add_box_variant(
        "TestProject", "Chapter1", 0, b"COMPRESSEDBYTES", suffix="compressed"
    )

    assert filename.endswith("_compressed.wav")
    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "variants" / filename
    )
    assert variant_path.read_bytes() == b"COMPRESSEDBYTES"


def test_add_box_variant_without_suffix_is_unchanged(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    filename = dialog_variants.add_box_variant(
        "TestProject", "Chapter1", 0, b"PLAINBYTES"
    )

    assert not filename.endswith("_compressed.wav")
    assert filename.startswith("box_0_variant_")


def test_add_combined_variant_with_suffix_appends_it_to_filename(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES", suffix="compressed"
    )

    assert filename.endswith("_compressed.wav")
    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert variant_path.read_bytes() == b"COMPRESSEDBYTES"


def test_add_combined_variant_without_suffix_is_unchanged(project_dir):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"PLAINBYTES"
    )

    assert not filename.endswith("_compressed.wav")
    assert filename.startswith("combined_variant_")


def test_add_box_variant_preserves_original_audio(project_dir):
    # Set up directory and initial box audio on disk
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    box_audio_path = audio_dir / "box_0.wav"
    box_audio_path.write_bytes(b"ORIGINAL_AUDIO")

    # Set up chapter json with empty/missing variants
    json_path = project_dir / "TestProject" / "Chapter1.json"
    data = {"boxes": [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]}
    json_path.write_text(json.dumps(data), encoding="utf-8")

    # Add a new variant
    new_filename = dialog_variants.add_box_variant(
        "TestProject", "Chapter1", 0, b"NEW_VARIANT_AUDIO"
    )

    # Check that original audio was copied to variants folder
    variants_dir = audio_dir / "variants"
    orig_variant_path = variants_dir / "box_0_variant_original.wav"
    assert orig_variant_path.exists()
    assert orig_variant_path.read_bytes() == b"ORIGINAL_AUDIO"

    # Check json data has both variants, and the newly added one is active
    updated_data = json.loads(json_path.read_text(encoding="utf-8"))
    box = updated_data["boxes"][0]
    assert box["variants"] == ["box_0_variant_original.wav", new_filename]
    assert box["activeIndex"] == 1

    # box_0.wav (read by every later effect apply) reflects the new active variant
    assert box_audio_path.read_bytes() == b"NEW_VARIANT_AUDIO"


def test_add_box_variant_chains_onto_the_previous_active_variant(project_dir):
    # Regression test for a bug where a second effect apply (e.g. Reverb after
    # Compressor) silently re-processed the original audio instead of the
    # previously applied effect's result, because box_0.wav was only ever
    # updated on the very first add_box_variant() call.
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "box_0.wav").write_bytes(b"ORIGINAL_AUDIO")

    json_path = project_dir / "TestProject" / "Chapter1.json"
    data = {"boxes": [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]}
    json_path.write_text(json.dumps(data), encoding="utf-8")

    # Simulate "Compressor anwenden": reads box_0.wav (still the original here).
    source_for_compressor = (audio_dir / "box_0.wav").read_bytes()
    assert source_for_compressor == b"ORIGINAL_AUDIO"
    dialog_variants.add_box_variant(
        "TestProject", "Chapter1", 0, b"COMPRESSED_AUDIO", suffix="compressed"
    )

    # Simulate "Reverb anwenden": must read the just-produced compressed audio,
    # not the original — this is what was broken before the fix.
    source_for_reverb = (audio_dir / "box_0.wav").read_bytes()
    assert source_for_reverb == b"COMPRESSED_AUDIO"


def test_get_variant_audio_rejects_path_traversal_filename(project_dir):
    outside_file = project_dir.parent / "secret.txt"
    outside_file.write_text("do not read me")

    with pytest.raises(EngineError):
        dialog_variants.get_variant_audio(
            "TestProject", "Chapter1", 0, "..\\..\\secret.txt"
        )


def test_delete_box_variant_rejects_path_traversal_filename(project_dir):
    outside_file = project_dir.parent / "secret.txt"
    outside_file.write_bytes(b"must not be deleted")

    dialog_variants.delete_box_variant("TestProject", "Chapter1", 0, "../../secret.txt")

    assert outside_file.exists()
    assert outside_file.read_bytes() == b"must not be deleted"


def test_get_combined_variant_audio_rejects_path_traversal_filename(project_dir):
    outside_file = project_dir.parent / "secret.txt"
    outside_file.write_text("do not read me")

    with pytest.raises(EngineError):
        dialog_variants.get_combined_variant_audio(
            "TestProject", "Chapter1", "..\\..\\secret.txt"
        )


def test_delete_combined_variant_rejects_path_traversal_filename(project_dir):
    outside_file = project_dir.parent / "secret.txt"
    outside_file.write_bytes(b"must not be deleted")

    dialog_variants.delete_combined_variant(
        "TestProject", "Chapter1", "../../secret.txt"
    )

    assert outside_file.exists()
    assert outside_file.read_bytes() == b"must not be deleted"


def test_add_box_variant_ignores_negative_box_index(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    dialog_variants.add_box_variant("TestProject", "Chapter1", -1, b"SOMEBYTES")

    updated = _read_chapter_json(project_dir)
    assert updated["boxes"][0]["variants"] == []


def test_add_box_variant_extends_box_list_for_unsaved_new_box(project_dir):
    # Regression test: a box added in the browser after the chapter was last
    # explicitly saved doesn't exist in chapter.json yet. Generating audio for
    # it (or applying an effect afterward) used to silently skip writing
    # box_{index}.wav, because add_box_variant() only handled box_index values
    # already covered by the saved boxes list — see docs/FIXES.md.
    audio_dir = project_dir / "TestProject" / "Chapter1_audio"

    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    filename = dialog_variants.add_box_variant(
        "TestProject", "Chapter1", 3, b"NEW_BOX_AUDIO"
    )

    updated = _read_chapter_json(project_dir)
    boxes = updated["boxes"]
    assert len(boxes) == 4
    # The pre-existing box (index 0) is left untouched.
    assert boxes[0] == {"text": "hi", "voice": None, "variants": [], "activeIndex": -1}
    # The gap boxes (1, 2) are empty placeholders, not the generated box.
    assert boxes[1]["variants"] == []
    assert boxes[2]["variants"] == []
    # The actually-generated box (index 3) has the new variant active.
    assert boxes[3]["variants"] == [filename]
    assert boxes[3]["activeIndex"] == 0

    # box_3.wav (read by every later effect apply) exists immediately,
    # without requiring an explicit "Kapitel speichern" first.
    assert (audio_dir / "box_3.wav").read_bytes() == b"NEW_BOX_AUDIO"
