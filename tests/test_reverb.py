import math
import struct

import pytest

from src.orchestrator.audio.reverb import (
    _estimate_tail_seconds,
    _validate_params,
    apply_reverb_pcm16,
)

VALID_PARAMS = {
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


def _make_tone_pcm16(framerate: int, seconds: float) -> bytes:
    count = int(framerate * seconds)
    samples = [
        int(20000 * math.sin(2 * math.pi * 440 * i / framerate)) for i in range(count)
    ]
    return struct.pack(f"<{count}h", *samples)


def test_accepts_valid_params():
    _validate_params(**VALID_PARAMS)


def test_rejects_decay_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, decay=1.5))


def test_rejects_wet_dry_mix_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, wet_dry_mix=-0.1))


def test_rejects_decay_diffusion_1_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, decay_diffusion_1=1.0))


def test_rejects_other_invalid_params():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, pre_delay_ms=-5.0))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, bandwidth=1.5))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, input_diffusion_1=1.2))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, input_diffusion_2=-0.1))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, decay_diffusion_2=1.0))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, damping=1.1))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, excursion_rate=3.0))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, excursion_depth=-0.1))


def test_output_is_stereo_and_extended_by_the_estimated_tail():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.1)
    input_frame_count = len(pcm16) // 2

    output = apply_reverb_pcm16(pcm16, 1, framerate, **VALID_PARAMS)

    expected_tail_frames = round(
        _estimate_tail_seconds(
            VALID_PARAMS["decay"],
            VALID_PARAMS["pre_delay_ms"],
            VALID_PARAMS["wet_dry_mix"],
        )
        * framerate
    )
    output_frame_count = len(output) // 2 // 2  # 2 bytes/sample, 2 channels
    assert output_frame_count == input_frame_count + expected_tail_frames


def test_output_stereo_input_channels_2_is_extended_by_the_estimated_tail():
    framerate = 24000
    seconds = 0.05
    mono_pcm = _make_tone_pcm16(framerate, seconds)
    mono_samples = struct.unpack(f"<{len(mono_pcm) // 2}h", mono_pcm)
    stereo_samples = []
    for s in mono_samples:
        stereo_samples.extend([s, s])
    stereo_pcm = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)
    input_frame_count = len(mono_samples)

    output = apply_reverb_pcm16(stereo_pcm, 2, framerate, **VALID_PARAMS)

    expected_tail_frames = round(
        _estimate_tail_seconds(
            VALID_PARAMS["decay"],
            VALID_PARAMS["pre_delay_ms"],
            VALID_PARAMS["wet_dry_mix"],
        )
        * framerate
    )
    output_frame_count = len(output) // 2 // 2
    assert output_frame_count == input_frame_count + expected_tail_frames


def test_tail_estimate_is_zero_when_fully_dry():
    assert _estimate_tail_seconds(decay=0.9, pre_delay_ms=0.0, wet_dry_mix=0.0) == 0.0


def test_tail_estimate_includes_pre_delay():
    tail_no_predelay = _estimate_tail_seconds(
        decay=0.0, pre_delay_ms=0.0, wet_dry_mix=1.0
    )
    tail_with_predelay = _estimate_tail_seconds(
        decay=0.0, pre_delay_ms=250.0, wet_dry_mix=1.0
    )
    assert tail_with_predelay == pytest.approx(tail_no_predelay + 0.25)


def test_tail_estimate_is_capped():
    assert (
        _estimate_tail_seconds(decay=0.999, pre_delay_ms=0.0, wet_dry_mix=1.0) == 15.0
    )


def test_wet_dry_mix_zero_reproduces_dry_signal_on_both_channels():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.05)
    input_samples = struct.unpack(f"<{len(pcm16) // 2}h", pcm16)

    output = apply_reverb_pcm16(
        pcm16, 1, framerate, **dict(VALID_PARAMS, wet_dry_mix=0.0)
    )
    output_samples = struct.unpack(f"<{len(output) // 2}h", output)

    for i, expected in enumerate(input_samples):
        assert output_samples[i * 2] == expected
        assert output_samples[i * 2 + 1] == expected


def test_higher_decay_produces_a_longer_tail():
    framerate = 24000
    seconds = 1.0
    count = int(framerate * seconds)
    samples = [
        int(20000 * math.sin(2 * math.pi * 440 * i / framerate)) if i < 200 else 0
        for i in range(count)
    ]
    pcm16 = struct.pack(f"<{count}h", *samples)

    def tail_rms(decay: float) -> float:
        output = apply_reverb_pcm16(
            pcm16, 1, framerate, **dict(VALID_PARAMS, decay=decay, wet_dry_mix=1.0)
        )
        output_samples = struct.unpack(f"<{len(output) // 2}h", output)
        tail = output_samples[int(0.9 * framerate) * 2 :]
        return math.sqrt(sum(v * v for v in tail) / len(tail))

    assert tail_rms(0.9) > tail_rms(0.1)


def test_rejects_empty_pcm16():
    with pytest.raises(ValueError):
        apply_reverb_pcm16(b"", 1, 24000, **VALID_PARAMS)


def test_reverb_output_matches_golden_hash_for_representative_wet_signal():
    import hashlib

    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.1)

    output = apply_reverb_pcm16(pcm16, 1, framerate, **VALID_PARAMS)

    assert len(output) == 354016
    assert (
        hashlib.sha256(output).hexdigest()
        == "0e03c22f10299715f92e46bab6d550164735036f6889e38cc496b4ff60ddbb0c"
    )
