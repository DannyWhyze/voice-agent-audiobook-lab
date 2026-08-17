import json
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from src.orchestrator.dialog import variants as dialog_variants
from src.orchestrator.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_combined_variant_route_returns_audio(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    response = client.get(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}"
    )

    assert response.status_code == 200
    assert response.content == b"COMPRESSEDBYTES"


def test_get_missing_combined_variant_route_returns_404(project_dir, client):
    response = client.get(
        "/projects/TestProject/chapters/Chapter1/combined-variants/does-not-exist.wav"
    )
    assert response.status_code == 404


def test_activate_combined_variant_route(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    response = client.put(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}/activate"
    )

    assert response.status_code == 200
    combined_path = project_dir / "TestProject" / "Chapter1_audio" / "combined.wav"
    assert combined_path.read_bytes() == b"COMPRESSEDBYTES"


def test_delete_combined_variant_route(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    response = client.delete(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}"
    )

    assert response.status_code == 200
    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert not variant_path.exists()


def test_lock_combined_variant_route_sets_flag(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    response = client.put(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}/lock",
        json={"locked": True},
    )

    assert response.status_code == 200
    chapter_json = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert chapter_json["combinedVariantLocks"] == {filename: True}


def test_delete_locked_combined_variant_route_returns_400(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    client.put(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}/lock",
        json={"locked": True},
    )

    response = client.delete(
        f"/projects/TestProject/chapters/Chapter1/combined-variants/{filename}"
    )

    assert response.status_code == 400
    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert variant_path.exists()


def test_chapters_with_audio_includes_combined_variants(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )

    response = client.get("/projects/TestProject/chapters-with-audio")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["combined_variants"] == [filename]
    assert body[0]["active_combined_index"] == 0


def test_chapters_with_audio_reflects_activated_variant(project_dir, client):
    filename = dialog_variants.add_combined_variant(
        "TestProject", "Chapter1", b"COMPRESSEDBYTES"
    )
    dialog_variants.activate_combined_variant("TestProject", "Chapter1", filename)

    response = client.get("/projects/TestProject/chapters-with-audio")

    body = response.json()
    assert body[0]["active_combined_index"] == 0


COMPRESSOR_PARAMS = {
    "threshold_db": -20.0,
    "ratio": 4.0,
    "attack_ms": 10.0,
    "release_ms": 100.0,
    "knee_db": 0.0,
    "makeup_gain_db": 0.0,
    "detector": "rms",
    "rms_window_ms": 10.0,
}


def _make_wav(sample_value: int, count: int = 2400) -> bytes:
    import struct
    import wave
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(24000)
        wav_out.writeframes(struct.pack(f"<{count}h", *([sample_value] * count)))
    return buffer.getvalue()


def _make_float32_wav(sample_value: float = 0.5, count: int = 2400) -> bytes:
    import struct

    pcm_data = struct.pack(f"<{count}f", *([sample_value] * count))
    fmt_chunk = struct.pack("<HHIIHH", 3, 1, 24000, 24000 * 4, 4, 32)
    riff_header = b"RIFF" + struct.pack("<I", 36 + len(pcm_data)) + b"WAVE"
    fmt_header = b"fmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk
    data_header = b"data" + struct.pack("<I", len(pcm_data)) + pcm_data
    return riff_header + fmt_header + data_header


def _make_wav_with_params(
    channels: int, framerate: int, sample_value: int = 1000, count: int = 100
) -> bytes:
    import struct
    import wave
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(
            struct.pack(f"<{count * channels}h", *([sample_value] * (count * channels)))
        )
    return buffer.getvalue()


def _setup_box0_with_existing_audio(project_dir, framerate: int) -> None:
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(
        _make_wav_with_params(channels=1, framerate=framerate)
    )


def test_reference_framerate_falls_back_when_no_audio_exists(project_dir, client):
    response = client.get("/projects/TestProject/chapters/Chapter1/reference-framerate")

    assert response.status_code == 200
    assert response.json() == {"framerate": 44100}


def test_reference_framerate_reads_existing_box_audio(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=24000)

    response = client.get("/projects/TestProject/chapters/Chapter1/reference-framerate")

    assert response.status_code == 200
    assert response.json() == {"framerate": 24000}


def test_upload_variant_accepts_recording_matching_existing_audio(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=24000)
    project_path = project_dir / "TestProject"

    recording = _make_wav_with_params(channels=1, framerate=24000)

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants/upload",
        files={"audio": ("recording.wav", recording, "audio/wav")},
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_recorded.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert filename in data_after["boxes"][0]["variants"]


def test_upload_variant_accepts_recording_at_fallback_when_no_existing_audio(
    project_dir, client
):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    recording = _make_wav_with_params(channels=1, framerate=44100)

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants/upload",
        files={"audio": ("recording.wav", recording, "audio/wav")},
    )

    assert response.status_code == 200


def test_upload_variant_rejects_wrong_framerate(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=24000)
    wrong_rate = _make_wav_with_params(channels=1, framerate=48000)

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants/upload",
        files={"audio": ("recording.wav", wrong_rate, "audio/wav")},
    )

    assert response.status_code == 400


def test_delete_locked_box_variant_route_returns_400(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [
        {
            "text": "hi",
            "voice": None,
            "variants": ["box_0_variant_a.wav"],
            "activeIndex": 0,
            "variantLocks": {"box_0_variant_a.wav": True},
        }
    ]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    variants_dir = project_path / "Chapter1_audio" / "variants"
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "box_0_variant_a.wav").write_bytes(b"A")

    response = client.delete(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants/box_0_variant_a.wav"
    )

    assert response.status_code == 400
    assert (variants_dir / "box_0_variant_a.wav").exists()


def test_generate_box_variant_route_empty_text_400(project_dir, client, monkeypatch):
    mock_post = MagicMock()
    monkeypatch.setattr(httpx, "post", mock_post)

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants",
        json={"text": "  ", "voice": None},
    )

    assert response.status_code == 400
    assert "Text must not be empty" in response.json()["detail"]
    mock_post.assert_not_called()


def test_upload_variant_rejects_stereo(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=24000)
    stereo = _make_wav_with_params(channels=2, framerate=24000)

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/variants/upload",
        files={"audio": ("recording.wav", stereo, "audio/wav")},
    )

    assert response.status_code == 400


def test_combine_applies_trailing_pause(client):
    clip = _make_wav(1000, count=2400)

    baseline = client.post(
        "/combine",
        data={"pauses": "[]", "gains": "[]"},
        files=[("clips", ("clip_0.wav", clip, "audio/wav"))],
    )
    with_pause = client.post(
        "/combine",
        data={"pauses": "[]", "gains": "[]", "trailing_pause_ms": "500"},
        files=[("clips", ("clip_0.wav", clip, "audio/wav"))],
    )

    assert baseline.status_code == 200
    assert with_pause.status_code == 200
    assert len(with_pause.content) > len(baseline.content)


def test_combine_route_accepts_pans_field(client):
    import struct
    import wave
    from io import BytesIO

    def make_wav_bytes(sample_value: int) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(24000)
            wav_out.writeframes(struct.pack("<100h", *([sample_value] * 100)))
        return buffer.getvalue()

    clip = make_wav_bytes(1000)
    response = client.post(
        "/combine",
        files={"clips": ("clip_0.wav", clip, "audio/wav")},
        data={
            "pauses": "[]",
            "gains": "[0.0]",
            "pans": "[-1.0]",
            "trailing_pause_ms": "0",
        },
    )
    assert response.status_code == 200

    with wave.open(BytesIO(response.content), "rb") as wav_in:
        assert wav_in.getnchannels() == 2


def test_save_chapter_persists_end_pause_ms(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={
            "boxes": "[]",
            "pause_ms": "400",
            "end_pause_ms": "800",
            "clip_indices": "[]",
        },
    )
    assert response.status_code == 200

    get_response = client.get("/projects/TestProject/chapters/Chapter1")
    assert get_response.json()["end_pause_ms"] == 800


def test_save_chapter_defaults_end_pause_ms_to_zero(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={"boxes": "[]", "pause_ms": "400", "clip_indices": "[]"},
    )
    assert response.status_code == 200

    get_response = client.get("/projects/TestProject/chapters/Chapter1")
    assert get_response.json()["end_pause_ms"] == 0


def test_save_chapter_rejects_non_integer_clip_index(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={
            "boxes": json.dumps([{"text": "hi", "voice": None}]),
            "clip_indices": json.dumps(["../../../evil"]),
        },
        files=[("clips", ("clip.wav", b"FAKEWAV", "audio/wav"))],
    )
    assert response.status_code == 400

    audio_dir = project_dir / "TestProject" / "Chapter1_audio"
    if audio_dir.exists():
        assert not any(f.name.startswith("box_..") for f in audio_dir.iterdir())


def test_save_chapter_rejects_out_of_range_clip_index(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={
            "boxes": json.dumps([{"text": "hi", "voice": None}]),
            "clip_indices": json.dumps([5]),
        },
        files=[("clips", ("clip.wav", b"FAKEWAV", "audio/wav"))],
    )
    assert response.status_code == 400


def test_save_chapter_rejects_negative_clip_index(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={
            "boxes": json.dumps([{"text": "hi", "voice": None}]),
            "clip_indices": json.dumps([-1]),
        },
        files=[("clips", ("clip.wav", b"FAKEWAV", "audio/wav"))],
    )
    assert response.status_code == 400


def test_box_compress_preview_does_not_persist(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/preview",
        json=COMPRESSOR_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["variants"] == []


def test_box_compress_apply_persists_new_variant(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/apply",
        json=COMPRESSOR_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_compressed.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_compress_preview_does_not_persist(project_dir, client):
    # The conftest.py fixture's combined.wav is a placeholder byte string, not
    # a real WAV file (Plan 037's own tests never parse it) -- overwrite it
    # with a real one here, since _apply_compressor() needs to open it with
    # the stdlib `wave` module.
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/compress/preview",
        json=COMPRESSOR_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after.get("combinedVariants", []) == []


def test_combined_compress_apply_persists_new_variant_and_activates_it(
    project_dir, client
):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/compress/apply", json=COMPRESSOR_PARAMS
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_compressed.wav")
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combinedVariants"] == [filename]
    # A combined effect apply must activate its own result, so a second apply
    # chains onto it instead of silently reprocessing the pre-effect original
    # (the bug reported by Danny for repeated Normalize applies). See docs/FIXES.md.
    assert data_after["activeCombinedIndex"] == 0
    combined_path = project_dir / "TestProject" / "Chapter1_audio" / "combined.wav"
    variant_path = (
        project_dir / "TestProject" / "Chapter1_audio" / "combined_variants" / filename
    )
    assert combined_path.read_bytes() == variant_path.read_bytes()


def test_compress_invalid_ratio_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = dict(COMPRESSOR_PARAMS, ratio=0.5)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/compress/preview", json=bad_params
    )
    assert response.status_code == 400


def test_compress_missing_audio_returns_404(project_dir, client):
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/preview",
        json=COMPRESSOR_PARAMS,
    )
    assert response.status_code == 404


def test_compress_supports_float32_wav_format(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_float32_wav(0.5))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/preview",
        json=COMPRESSOR_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_box_compress_apply_persists_compressor_params(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/apply",
        json=COMPRESSOR_PARAMS,
    )

    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["compressor_params"] == COMPRESSOR_PARAMS


def test_box_compress_preview_does_not_persist_compressor_params(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/compress/preview",
        json=COMPRESSOR_PARAMS,
    )

    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "compressor_params" not in data_after["boxes"][0]


def test_combined_compress_apply_persists_compressor_params(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    client.post(
        "/projects/TestProject/chapters/Chapter1/compress/apply", json=COMPRESSOR_PARAMS
    )

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combined_compressor_params"] == COMPRESSOR_PARAMS


def test_combined_compress_preview_does_not_persist_compressor_params(
    project_dir, client
):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    client.post(
        "/projects/TestProject/chapters/Chapter1/compress/preview",
        json=COMPRESSOR_PARAMS,
    )

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "combined_compressor_params" not in data_after


REVERB_PARAMS = {
    "pre_delay_ms": 0.0,
    "bandwidth": 0.9999,
    "input_diffusion_1": 0.75,
    "input_diffusion_2": 0.625,
    "decay": 0.5,
    "decay_diffusion_1": 0.7,
    "decay_diffusion_2": 0.5,
    "damping": 0.005,
    "excursion_rate": 0.5,
    "excursion_depth": 0.7,
    "wet_dry_mix": 0.3,
}


def test_box_reverb_preview_returns_stereo_wav_and_does_not_persist(
    project_dir, client
):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/reverb/preview",
        json=REVERB_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "reverb_params" not in data_after["boxes"][0]


def test_box_reverb_apply_persists_new_stereo_variant_and_params(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/reverb/apply",
        json=REVERB_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_reverb.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["reverb_params"] == REVERB_PARAMS
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_reverb_apply_persists_params(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/apply", json=REVERB_PARAMS
    )

    assert response.status_code == 200
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combined_reverb_params"] == REVERB_PARAMS


def test_combined_reverb_preview_does_not_persist(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/preview", json=REVERB_PARAMS
    )

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "combined_reverb_params" not in data_after


def test_reverb_invalid_decay_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = dict(REVERB_PARAMS, decay=1.5)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/preview", json=bad_params
    )
    assert response.status_code == 400


EQ_PARAMS = {"band_gains_db": [0.0] * 10}


def _make_eq_test_wav(sample_value: int = 1000) -> bytes:
    # EQ_BAND_FREQUENCIES_HZ includes a 16000 Hz band, which needs Nyquist
    # (framerate/2) above 16000 Hz to stay stable -- 44100 Hz matches this
    # project's real engine output (see docs/ideas.md, 05.08.2026), unlike
    # the 24000 Hz used elsewhere in this file for effects with no such
    # top-band constraint.
    return _make_wav_with_params(
        channels=1, framerate=44100, sample_value=sample_value, count=2400
    )


def test_box_eq_preview_returns_wav_and_does_not_persist(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_eq_test_wav())

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/eq/preview",
        json=EQ_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "eq_params" not in data_after["boxes"][0]


def test_box_eq_apply_persists_new_variant_and_params(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_eq_test_wav())

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/eq/apply",
        json=EQ_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_eq.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["eq_params"] == EQ_PARAMS
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_eq_apply_persists_params(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_eq_test_wav()
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/eq/apply", json=EQ_PARAMS
    )

    assert response.status_code == 200
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combined_eq_params"] == EQ_PARAMS


def test_combined_eq_preview_does_not_persist(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_eq_test_wav()
    )

    client.post("/projects/TestProject/chapters/Chapter1/eq/preview", json=EQ_PARAMS)

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "combined_eq_params" not in data_after


def test_eq_invalid_band_count_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_eq_test_wav()
    )

    bad_params = {"band_gains_db": [0.0] * 8}
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/eq/preview", json=bad_params
    )
    assert response.status_code == 400


def test_eq_gain_out_of_range_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_eq_test_wav()
    )

    bad_params = {"band_gains_db": [13.0] + [0.0] * 9}
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/eq/preview", json=bad_params
    )
    assert response.status_code == 400


TRIM_PARAMS = {"start_ms": 0.0, "end_ms": 50.0}


def test_box_trim_apply_persists_new_variant(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/trim/apply",
        json=TRIM_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_trimmed.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_trim_apply_persists_new_variant(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/trim/apply", json=TRIM_PARAMS
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_trimmed.wav")
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combinedVariants"] == [filename]


def test_trim_invalid_range_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = {"start_ms": 50.0, "end_ms": 10.0}
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/trim/apply", json=bad_params
    )
    assert response.status_code == 400


def test_trim_missing_audio_returns_404(project_dir, client):
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/trim/apply",
        json=TRIM_PARAMS,
    )
    assert response.status_code == 404


FADE_PARAMS = {"fade_in_ms": 10.0, "fade_out_ms": 10.0}


def test_box_fade_apply_persists_new_variant(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/fade/apply",
        json=FADE_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_faded.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_fade_apply_persists_new_variant(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/fade/apply", json=FADE_PARAMS
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_faded.wav")
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combinedVariants"] == [filename]


def test_fade_invalid_range_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = {"fade_in_ms": -5.0, "fade_out_ms": 0.0}
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/fade/apply", json=bad_params
    )
    assert response.status_code == 400


def test_fade_missing_audio_returns_404(project_dir, client):
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/fade/apply",
        json=FADE_PARAMS,
    )
    assert response.status_code == 404


def test_chapters_list_excludes_presets_file(project_dir, client):
    client.post(
        "/projects/TestProject/presets/compressor",
        json={"name": "Warm", "params": COMPRESSOR_PARAMS},
    )

    response = client.get("/projects/TestProject/chapters")

    assert response.status_code == 200
    assert response.json() == ["Chapter1"]


def test_presets_list_is_empty_by_default(project_dir, client):
    response = client.get("/projects/TestProject/presets")
    assert response.status_code == 200
    assert response.json() == {
        "compressor": [],
        "reverb": [],
        "eq": [],
        "normalize": [],
        "pitch": [],
        "formant": [],
        "delay": [],
    }


def test_presets_save_persists_and_is_listed(project_dir, client):
    response = client.post(
        "/projects/TestProject/presets/compressor",
        json={"name": "Warm", "params": COMPRESSOR_PARAMS},
    )
    assert response.status_code == 200

    listed = client.get("/projects/TestProject/presets").json()
    assert listed["compressor"] == [{"name": "Warm", "params": COMPRESSOR_PARAMS}]


def test_presets_save_duplicate_name_returns_400(project_dir, client):
    client.post(
        "/projects/TestProject/presets/reverb",
        json={"name": "Hall", "params": REVERB_PARAMS},
    )
    response = client.post(
        "/projects/TestProject/presets/reverb",
        json={"name": "Hall", "params": REVERB_PARAMS},
    )
    assert response.status_code == 400


def test_presets_save_invalid_params_returns_400(project_dir, client):
    response = client.post(
        "/projects/TestProject/presets/compressor",
        json={"name": "Broken", "params": {"threshold_db": "not a number"}},
    )
    assert response.status_code == 400


def test_presets_save_unknown_effect_type_returns_400(project_dir, client):
    response = client.post(
        "/projects/TestProject/presets/unknown",
        json={"name": "X", "params": {}},
    )
    assert response.status_code == 400


def test_presets_delete_removes_entry(project_dir, client):
    client.post(
        "/projects/TestProject/presets/eq",
        json={"name": "Bright", "params": EQ_PARAMS},
    )
    response = client.delete("/projects/TestProject/presets/eq/Bright")
    assert response.status_code == 200

    listed = client.get("/projects/TestProject/presets").json()
    assert listed["eq"] == []


def test_presets_delete_unknown_effect_type_returns_400(project_dir, client):
    response = client.delete("/projects/TestProject/presets/unknown/X")
    assert response.status_code == 400


@pytest.mark.parametrize(
    "effect_type,params",
    [
        ("normalize", {"mode": "rms", "target_db": -20.0}),
        ("pitch", {"semitones": 3, "cents": 10.0}),
        ("formant", {"semitones": 4, "cents": 10.0}),
        (
            "delay",
            {
                "delay_time_ms": 350.0,
                "feedback": 0.35,
                "damping": 0.3,
                "saturation": 0.2,
                "wow_flutter_rate": 0.3,
                "wow_flutter_depth": 0.15,
                "wet_dry_mix": 0.35,
            },
        ),
    ],
)
def test_presets_save_and_delete_for_normalize_pitch_formant(
    project_dir, client, effect_type, params
):
    # Regression test: EFFECT_PARAM_MODELS in routers/presets.py originally
    # only listed compressor/reverb/eq, so saving or deleting a preset for
    # any of these three effects always returned 400 "Unknown effect_type",
    # even though all six effect overlays offer preset saving in the UI.
    response = client.post(
        f"/projects/TestProject/presets/{effect_type}",
        json={"name": "MyPreset", "params": params},
    )
    assert response.status_code == 200

    listed = client.get("/projects/TestProject/presets").json()
    assert listed[effect_type] == [{"name": "MyPreset", "params": params}]

    response = client.delete(f"/projects/TestProject/presets/{effect_type}/MyPreset")
    assert response.status_code == 200


NORMALIZE_PARAMS = {"mode": "rms", "target_db": -20.0}


def test_normalize_box_apply_creates_variant(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/normalize/apply",
        json=NORMALIZE_PARAMS,
    )
    assert response.status_code == 200
    assert "X-Variant-Filename" in response.headers
    assert "_normalized" in response.headers["X-Variant-Filename"]


def test_normalize_rejects_invalid_mode(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/normalize/preview",
        json={"mode": "invalid", "target_db": -20.0},
    )
    assert response.status_code == 422  # Pydantic Literal validation


PITCH_PARAMS = {"semitones": 3, "cents": 10.0}


def test_pitch_box_apply_creates_variant(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/pitch/apply",
        json=PITCH_PARAMS,
    )
    assert response.status_code == 200
    assert "X-Variant-Filename" in response.headers
    assert "_pitch_shifted" in response.headers["X-Variant-Filename"]


def test_pitch_box_preview_returns_audio(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/pitch/preview",
        json=PITCH_PARAMS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_pitch_rejects_out_of_range_semitones(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/pitch/preview",
        json={"semitones": 99, "cents": 0.0},
    )
    assert response.status_code == 400


FORMANT_PARAMS = {"semitones": 4, "cents": 10.0}


def test_formant_box_apply_creates_variant(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/formant/apply",
        json=FORMANT_PARAMS,
    )
    assert response.status_code == 200
    assert "X-Variant-Filename" in response.headers
    assert "_formant_shifted" in response.headers["X-Variant-Filename"]


def test_formant_box_preview_returns_audio(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/formant/preview",
        json=FORMANT_PARAMS,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"


def test_formant_rejects_out_of_range_semitones(project_dir, client):
    _setup_box0_with_existing_audio(project_dir, framerate=44100)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/formant/preview",
        json={"semitones": 99, "cents": 0.0},
    )
    assert response.status_code == 400


def test_combine_rejects_malformed_pauses_json(client):
    clip = _make_wav(1000, count=2400)
    response = client.post(
        "/combine",
        data={"pauses": "not valid json", "gains": "[]"},
        files=[("clips", ("clip_0.wav", clip, "audio/wav"))],
    )
    assert response.status_code == 400
    assert "pauses" in response.json()["detail"]


def test_combine_rejects_malformed_gains_json(client):
    clip = _make_wav(1000, count=2400)
    response = client.post(
        "/combine",
        data={"pauses": "[]", "gains": "{invalid"},
        files=[("clips", ("clip_0.wav", clip, "audio/wav"))],
    )
    assert response.status_code == 400
    assert "gains" in response.json()["detail"]


def test_save_chapter_rejects_malformed_boxes_json(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={"boxes": "not valid json", "pause_ms": "400", "clip_indices": "[]"},
    )
    assert response.status_code == 400
    assert "boxes" in response.json()["detail"]


def test_save_chapter_rejects_malformed_clip_indices_json(project_dir, client):
    response = client.put(
        "/projects/TestProject/chapters/Chapter1",
        data={"boxes": "[]", "pause_ms": "400", "clip_indices": "{invalid"},
    )
    assert response.status_code == 400
    assert "clip_indices" in response.json()["detail"]


DELAY_PARAMS = {
    "delay_time_ms": 350.0,
    "feedback": 0.35,
    "damping": 0.3,
    "saturation": 0.2,
    "wow_flutter_rate": 0.3,
    "wow_flutter_depth": 0.15,
    "wet_dry_mix": 0.35,
}


def test_box_delay_preview_does_not_persist(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/delay/preview",
        json=DELAY_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "delay_params" not in data_after["boxes"][0]


def test_box_delay_apply_persists_new_variant_and_params_and_stays_mono(
    project_dir, client
):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/delay/apply",
        json=DELAY_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_delay.wav")
    data_after = json.loads(
        (project_path / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["boxes"][0]["delay_params"] == DELAY_PARAMS
    assert data_after["boxes"][0]["variants"] == [
        "box_0_variant_original.wav",
        filename,
    ]


def test_combined_delay_apply_persists_params(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/delay/apply", json=DELAY_PARAMS
    )

    assert response.status_code == 200
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combined_delay_params"] == DELAY_PARAMS


def test_combined_delay_preview_does_not_persist(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    client.post(
        "/projects/TestProject/chapters/Chapter1/delay/preview", json=DELAY_PARAMS
    )

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "combined_delay_params" not in data_after


def test_delay_invalid_feedback_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = dict(DELAY_PARAMS, feedback=1.5)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/delay/preview", json=bad_params
    )
    assert response.status_code == 400
