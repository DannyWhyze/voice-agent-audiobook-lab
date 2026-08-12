import json

import pytest

from src.orchestrator.dialog import effect_params as dialog_effect_params
from src.orchestrator.engine_client import EngineError


def _read_chapter_json(project_dir):
    path = project_dir / "TestProject" / "Chapter1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_box_compressor_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"threshold_db": -18.0, "ratio": 3.0}
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 0, "compressor_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["compressor_params"] == params


def test_save_box_compressor_params_ignores_out_of_range_index(project_dir):
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 5, "compressor_params", {"threshold_db": -18.0}
    )
    # No boxes exist yet in the fixture's Chapter1.json -- must not raise.
    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"] == []


def test_save_box_compressor_params_ignores_negative_box_index(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "box zero"}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", -1, "compressor_params", {"threshold_db": -10.0}
    )

    updated = _read_chapter_json(project_dir)
    assert "compressor_params" not in updated["boxes"][0]


def test_save_combined_compressor_params_writes_to_chapter_json(project_dir):
    params = {"threshold_db": -18.0, "ratio": 3.0}
    dialog_effect_params.save_combined_effect_params(
        "TestProject", "Chapter1", "combined_compressor_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_compressor_params"] == params


def test_save_box_reverb_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"decay": 0.8, "wet_dry_mix": 0.5}
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 0, "reverb_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["reverb_params"] == params


def test_save_combined_reverb_params_writes_to_chapter_json(project_dir):
    params = {"decay": 0.8, "wet_dry_mix": 0.5}
    dialog_effect_params.save_combined_effect_params(
        "TestProject", "Chapter1", "combined_reverb_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_reverb_params"] == params


def test_save_box_eq_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"band_gains_db": [0.0] * 9}
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 0, "eq_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["eq_params"] == params


def test_save_box_eq_params_ignores_negative_box_index(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "box zero"}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", -1, "eq_params", {"band_gains_db": [3.0] * 9}
    )

    updated = _read_chapter_json(project_dir)
    assert "eq_params" not in updated["boxes"][0]


def test_save_combined_eq_params_writes_to_chapter_json(project_dir):
    params = {"band_gains_db": [3.0] * 9}
    dialog_effect_params.save_combined_effect_params(
        "TestProject", "Chapter1", "combined_eq_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_eq_params"] == params


def test_save_box_pitch_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"semitones": 3, "cents": -10.0}
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 0, "pitch_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["pitch_params"] == params


def test_save_combined_pitch_params_writes_to_chapter_json(project_dir):
    params = {"semitones": -5, "cents": 25.0}
    dialog_effect_params.save_combined_effect_params(
        "TestProject", "Chapter1", "combined_pitch_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_pitch_params"] == params


def test_save_box_formant_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"semitones": 4, "cents": -15.0}
    dialog_effect_params.save_box_effect_params(
        "TestProject", "Chapter1", 0, "formant_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["formant_params"] == params


def test_save_combined_formant_params_writes_to_chapter_json(project_dir):
    params = {"semitones": -4, "cents": 20.0}
    dialog_effect_params.save_combined_effect_params(
        "TestProject", "Chapter1", "combined_formant_params", params
    )

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_formant_params"] == params


def test_list_presets_returns_empty_lists_when_no_file(project_dir):
    result = dialog_effect_params.list_presets("TestProject")
    assert result == {
        "compressor": [],
        "reverb": [],
        "eq": [],
        "normalize": [],
        "pitch": [],
        "formant": [],
        "delay": [],
    }


def test_list_presets_raises_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_effect_params.list_presets("NoSuchProject")


def test_save_preset_writes_and_is_returned_by_list(project_dir):
    dialog_effect_params.save_preset(
        "TestProject", "compressor", "Warm", {"threshold_db": -18.0}
    )

    result = dialog_effect_params.list_presets("TestProject")
    assert result["compressor"] == [{"name": "Warm", "params": {"threshold_db": -18.0}}]
    assert result["reverb"] == []
    assert result["eq"] == []


def test_save_preset_rejects_empty_name(project_dir):
    with pytest.raises(ValueError):
        dialog_effect_params.save_preset("TestProject", "compressor", "  ", {})


def test_save_preset_rejects_duplicate_name(project_dir):
    dialog_effect_params.save_preset("TestProject", "reverb", "Hall", {"decay": 0.5})
    with pytest.raises(ValueError):
        dialog_effect_params.save_preset(
            "TestProject", "reverb", "Hall", {"decay": 0.9}
        )


def test_save_preset_raises_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_effect_params.save_preset("NoSuchProject", "eq", "Bright", {})


def test_delete_preset_removes_it(project_dir):
    dialog_effect_params.save_preset(
        "TestProject", "eq", "Bright", {"band_gains_db": []}
    )
    dialog_effect_params.delete_preset("TestProject", "eq", "Bright")

    result = dialog_effect_params.list_presets("TestProject")
    assert result["eq"] == []


def test_delete_preset_missing_name_is_noop(project_dir):
    dialog_effect_params.delete_preset("TestProject", "compressor", "DoesNotExist")
    # Must not raise.


def test_delete_preset_raises_for_missing_project(project_dir):
    with pytest.raises(EngineError):
        dialog_effect_params.delete_preset("NoSuchProject", "compressor", "X")
