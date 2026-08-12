import math
import struct

import pytest

from src.orchestrator.audio.delay import (
    _estimate_tail_seconds,
    _validate_params,
    apply_delay_pcm16,
)

VALID_PARAMS = {
    "delay_time_ms": 350.0,
    "feedback": 0.35,
    "damping": 0.3,
    "saturation": 0.2,
    "wow_flutter_rate": 0.3,
    "wow_flutter_depth": 0.15,
    "wet_dry_mix": 0.35,
}


def _make_impulse_pcm16(framerate: int, seconds: float) -> bytes:
    count = int(framerate * seconds)
    samples = [0] * count
    samples[0] = 20000
    return struct.pack(f"<{count}h", *samples)


def _make_tone_pcm16(framerate: int, seconds: float) -> bytes:
    count = int(framerate * seconds)
    samples = [
        int(20000 * math.sin(2 * math.pi * 440 * i / framerate)) for i in range(count)
    ]
    return struct.pack(f"<{count}h", *samples)


def test_accepts_valid_params():
    _validate_params(**VALID_PARAMS)


def test_rejects_delay_time_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, delay_time_ms=0.0))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, delay_time_ms=2001.0))


def test_rejects_feedback_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, feedback=0.96))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, feedback=-0.1))


def test_rejects_other_invalid_params():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, damping=1.1))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, saturation=-0.1))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, wow_flutter_rate=3.0))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, wow_flutter_depth=-0.1))
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, wet_dry_mix=1.5))


def test_rejects_empty_pcm16():
    with pytest.raises(ValueError):
        apply_delay_pcm16(b"", 1, 24000, **VALID_PARAMS)


def test_mono_input_stays_mono():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.1)

    output = apply_delay_pcm16(pcm16, 1, framerate, **VALID_PARAMS)

    tail_frames = round(
        _estimate_tail_seconds(
            VALID_PARAMS["feedback"],
            VALID_PARAMS["delay_time_ms"],
            VALID_PARAMS["wet_dry_mix"],
        )
        * framerate
    )
    input_frame_count = len(pcm16) // 2
    output_frame_count = len(output) // 2  # mono: 2 bytes/sample, 1 channel
    assert output_frame_count == input_frame_count + tail_frames


def test_stereo_input_stays_stereo():
    framerate = 24000
    seconds = 0.05
    mono_pcm = _make_tone_pcm16(framerate, seconds)
    mono_samples = struct.unpack(f"<{len(mono_pcm) // 2}h", mono_pcm)
    stereo_samples = []
    for s in mono_samples:
        stereo_samples.extend([s, s])
    stereo_pcm = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)
    input_frame_count = len(mono_samples)

    output = apply_delay_pcm16(stereo_pcm, 2, framerate, **VALID_PARAMS)

    tail_frames = round(
        _estimate_tail_seconds(
            VALID_PARAMS["feedback"],
            VALID_PARAMS["delay_time_ms"],
            VALID_PARAMS["wet_dry_mix"],
        )
        * framerate
    )
    output_frame_count = len(output) // 2 // 2  # 2 bytes/sample, 2 channels
    assert output_frame_count == input_frame_count + tail_frames


def test_wet_dry_mix_zero_reproduces_dry_signal():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.05)
    input_samples = struct.unpack(f"<{len(pcm16) // 2}h", pcm16)

    output = apply_delay_pcm16(
        pcm16, 1, framerate, **dict(VALID_PARAMS, wet_dry_mix=0.0)
    )
    output_samples = struct.unpack(f"<{len(output) // 2}h", output)

    for i, expected in enumerate(input_samples):
        assert output_samples[i] == expected


def test_echo_appears_near_the_expected_delay_offset():
    framerate = 24000
    seconds = 1.0
    pcm16 = _make_impulse_pcm16(framerate, seconds)

    output = apply_delay_pcm16(
        pcm16,
        1,
        framerate,
        **dict(VALID_PARAMS, wet_dry_mix=1.0, wow_flutter_depth=0.0),
    )
    output_samples = struct.unpack(f"<{len(output) // 2}h", output)

    delay_samples = round(VALID_PARAMS["delay_time_ms"] / 1000.0 * framerate)
    window = output_samples[delay_samples - 5 : delay_samples + 5]
    assert max(abs(v) for v in window) > 500


def test_higher_feedback_produces_a_longer_tail():
    framerate = 24000
    seconds = 2.0
    pcm16 = _make_impulse_pcm16(framerate, seconds)

    def tail_rms(feedback: float) -> float:
        output = apply_delay_pcm16(
            pcm16,
            1,
            framerate,
            **dict(VALID_PARAMS, feedback=feedback, wet_dry_mix=1.0),
        )
        output_samples = struct.unpack(f"<{len(output) // 2}h", output)
        tail = output_samples[int(1.5 * framerate) :]
        return math.sqrt(sum(v * v for v in tail) / len(tail))

    assert tail_rms(0.9) > tail_rms(0.1)


def test_tail_estimate_is_zero_when_fully_dry():
    assert (
        _estimate_tail_seconds(feedback=0.9, delay_time_ms=350.0, wet_dry_mix=0.0)
        == 0.0
    )


def test_tail_estimate_is_zero_when_no_feedback():
    assert (
        _estimate_tail_seconds(feedback=0.0, delay_time_ms=350.0, wet_dry_mix=1.0)
        == 0.0
    )


def test_tail_estimate_is_capped():
    assert (
        _estimate_tail_seconds(feedback=0.94, delay_time_ms=2000.0, wet_dry_mix=1.0)
        == 20.0
    )
