import math
import struct

import pytest

from src.orchestrator.audio.compressor import (
    _detect_levels_db,
    _gain_reduction_db,
    _smooth_gain_reduction,
    _validate_params,
    compress_pcm16,
)


def test_accepts_valid_params():
    _validate_params(
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=10.0,
        release_ms=100.0,
        knee_db=0.0,
        detector="rms",
        rms_window_ms=10.0,
    )


def test_rejects_threshold_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=5.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=100.0,
            knee_db=0.0,
            detector="rms",
            rms_window_ms=10.0,
        )


def test_rejects_ratio_below_one():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=0.5,
            attack_ms=10.0,
            release_ms=100.0,
            knee_db=0.0,
            detector="rms",
            rms_window_ms=10.0,
        )


def test_rejects_zero_attack():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=0.0,
            release_ms=100.0,
            knee_db=0.0,
            detector="rms",
            rms_window_ms=10.0,
        )


def test_rejects_zero_release():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=0.0,
            knee_db=0.0,
            detector="rms",
            rms_window_ms=10.0,
        )


def test_rejects_negative_knee():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=100.0,
            knee_db=-1.0,
            detector="rms",
            rms_window_ms=10.0,
        )


def test_rejects_unknown_detector():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=100.0,
            knee_db=0.0,
            detector="loudness",
            rms_window_ms=10.0,
        )


def test_rejects_zero_rms_window():
    with pytest.raises(ValueError):
        _validate_params(
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=100.0,
            knee_db=0.0,
            detector="rms",
            rms_window_ms=0.0,
        )


def test_peak_detector_silence_hits_floor():
    levels = _detect_levels_db(
        [0] * 100, channels=1, framerate=24000, detector="peak", rms_window_ms=10.0
    )
    assert levels[0] == pytest.approx(-120.0)


def test_peak_detector_full_scale_is_near_zero_db():
    levels = _detect_levels_db(
        [32767] * 10, channels=1, framerate=24000, detector="peak", rms_window_ms=10.0
    )
    assert levels[0] == pytest.approx(0.0, abs=0.01)


def test_peak_detector_half_scale_is_about_minus_six_db():
    levels = _detect_levels_db(
        [16384] * 10, channels=1, framerate=24000, detector="peak", rms_window_ms=10.0
    )
    assert levels[0] == pytest.approx(-6.0206, abs=0.01)


def test_peak_detector_is_channel_linked():
    # Frame 0: channel 0 loud, channel 1 silent -> the linked level must follow the loud channel.
    levels = _detect_levels_db(
        [16384, 0], channels=2, framerate=24000, detector="peak", rms_window_ms=10.0
    )
    assert levels[0] == pytest.approx(-6.0206, abs=0.01)


def test_rms_detector_converges_to_constant_level():
    samples = [32767] * 5000
    levels = _detect_levels_db(
        samples, channels=1, framerate=24000, detector="rms", rms_window_ms=10.0
    )
    assert levels[-1] == pytest.approx(0.0, abs=0.05)


def test_hard_knee_below_threshold_no_reduction():
    reduction = _gain_reduction_db(
        level_db=-30.0, threshold_db=-20.0, ratio=4.0, knee_db=0.0
    )
    assert reduction == pytest.approx(0.0)


def test_hard_knee_above_threshold_matches_ratio_formula():
    # 8 dB over threshold at 4:1 -> only 2 dB over threshold -> 6 dB reduction.
    reduction = _gain_reduction_db(
        level_db=-12.0, threshold_db=-20.0, ratio=4.0, knee_db=0.0
    )
    assert reduction == pytest.approx(-6.0)


def test_ratio_one_is_always_identity():
    reduction = _gain_reduction_db(
        level_db=0.0, threshold_db=-20.0, ratio=1.0, knee_db=0.0
    )
    assert reduction == pytest.approx(0.0)


def test_soft_knee_start_matches_zero_reduction():
    # threshold=-20, knee=10 -> knee starts at -25, where reduction must still be ~0.
    reduction = _gain_reduction_db(
        level_db=-25.0, threshold_db=-20.0, ratio=4.0, knee_db=10.0
    )
    assert reduction == pytest.approx(0.0, abs=0.001)


def test_soft_knee_midpoint_partial_reduction():
    # threshold=-20, knee=10, level exactly at threshold: known closed-form result.
    reduction = _gain_reduction_db(
        level_db=-20.0, threshold_db=-20.0, ratio=4.0, knee_db=10.0
    )
    assert reduction == pytest.approx(-0.9375, abs=0.001)


def test_attack_reaches_63_percent_after_one_time_constant():
    framerate = 24000
    attack_ms = 10.0
    n_tc = round(framerate * attack_ms / 1000.0)  # 240 samples
    raw = [-12.0] * (n_tc + 1)
    smoothed = _smooth_gain_reduction(
        raw, framerate=framerate, attack_ms=attack_ms, release_ms=100.0
    )
    # After exactly one time constant: value = target * (1 - e^-1) = -12 * 0.632121
    assert smoothed[n_tc - 1] == pytest.approx(-7.5854, abs=0.01)


def test_release_decays_by_63_percent_after_one_time_constant():
    framerate = 24000
    attack_ms = 10.0
    release_ms = 50.0
    settle_samples = (
        3000  # far more than enough attack time constants to fully converge to -12 dB
    )
    n_tc_release = round(framerate * release_ms / 1000.0)  # 1200 samples
    raw = [-12.0] * settle_samples + [0.0] * (n_tc_release + 100)
    smoothed = _smooth_gain_reduction(
        raw, framerate=framerate, attack_ms=attack_ms, release_ms=release_ms
    )
    # One release time constant after the drop to 0: value = -12 * e^-1
    assert smoothed[settle_samples + n_tc_release - 1] == pytest.approx(
        -4.4145, abs=0.05
    )


def test_output_length_matches_input_length():
    raw = [0.0, -3.0, -6.0, 0.0]
    smoothed = _smooth_gain_reduction(
        raw, framerate=24000, attack_ms=10.0, release_ms=100.0
    )
    assert len(smoothed) == len(raw)


def test_silence_stays_silent():
    pcm16 = struct.pack("<2400h", *([0] * 2400))
    result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=10.0,
        release_ms=100.0,
    )
    assert result == pcm16


def test_below_threshold_unchanged():
    quiet_samples = [1000] * 2400  # about -30 dBFS, well below the threshold
    pcm16 = struct.pack("<2400h", *quiet_samples)
    result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-6.0,
        ratio=4.0,
        attack_ms=10.0,
        release_ms=100.0,
    )
    assert result == pcm16


def test_ratio_math_reaches_expected_steady_state():
    samples = [20000] * 5000
    pcm16 = struct.pack("<5000h", *samples)
    result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=5.0,
        release_ms=100.0,
        detector="peak",
    )
    output_samples = struct.unpack("<5000h", result)

    input_db = 20 * math.log10(20000 / 32768.0)
    expected_output_db = -20.0 + (input_db - (-20.0)) / 4.0
    expected_factor = 10 ** ((expected_output_db - input_db) / 20.0)
    expected_sample = round(20000 * expected_factor)
    assert output_samples[-1] == pytest.approx(expected_sample, abs=2)


def test_ratio_one_is_identity():
    samples = [25000] * 2000
    pcm16 = struct.pack("<2000h", *samples)
    result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=1.0,
        attack_ms=5.0,
        release_ms=50.0,
    )
    assert result == pcm16


def test_soft_knee_attenuates_more_than_hard_knee_below_threshold():
    amplitude = 2603  # approx -22 dBFS, 2 dB below a -20 dBFS threshold
    samples = [amplitude] * 3000
    pcm16 = struct.pack("<3000h", *samples)

    hard = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=5.0,
        release_ms=50.0,
        knee_db=0.0,
    )
    soft = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=5.0,
        release_ms=50.0,
        knee_db=10.0,
    )

    hard_samples = struct.unpack("<3000h", hard)
    soft_samples = struct.unpack("<3000h", soft)

    assert hard_samples[-1] == amplitude  # untouched below the hard-knee threshold
    assert abs(soft_samples[-1]) < amplitude  # soft knee already attenuating


def test_peak_reacts_faster_than_rms_to_short_transient():
    quiet = 500
    loud = 32000
    samples = [quiet] * 500 + [loud] * 5 + [quiet] * 500
    pcm16 = struct.pack(f"<{len(samples)}h", *samples)

    peak_result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-6.0,
        ratio=8.0,
        attack_ms=1.0,
        release_ms=50.0,
        detector="peak",
    )
    rms_result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-6.0,
        ratio=8.0,
        attack_ms=1.0,
        release_ms=50.0,
        detector="rms",
        rms_window_ms=50.0,
    )

    peak_samples = struct.unpack(f"<{len(samples)}h", peak_result)
    rms_samples = struct.unpack(f"<{len(samples)}h", rms_result)

    burst_index = 500 + 2
    assert abs(peak_samples[burst_index]) < loud
    assert abs(rms_samples[burst_index]) > abs(peak_samples[burst_index])


def test_linked_stereo_matches_mono_reference():
    frame_count = 3000
    interleaved = []
    for _ in range(frame_count):
        interleaved.extend([20000, 0])
    pcm16 = struct.pack(f"<{len(interleaved)}h", *interleaved)

    result = compress_pcm16(
        pcm16,
        channels=2,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=5.0,
        release_ms=50.0,
    )
    out = struct.unpack(f"<{len(interleaved)}h", result)
    last_left, last_right = out[-2], out[-1]

    assert last_right == 0  # silence stays silence regardless of linking

    mono_pcm16 = struct.pack(f"<{frame_count}h", *([20000] * frame_count))
    mono_result = compress_pcm16(
        mono_pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-20.0,
        ratio=4.0,
        attack_ms=5.0,
        release_ms=50.0,
    )
    mono_out = struct.unpack(f"<{frame_count}h", mono_result)
    assert last_left == pytest.approx(mono_out[-1], abs=1)


def test_output_never_exceeds_int16_range():
    samples = [30000] * 2000
    pcm16 = struct.pack("<2000h", *samples)
    result = compress_pcm16(
        pcm16,
        channels=1,
        framerate=24000,
        threshold_db=-40.0,
        ratio=2.0,
        attack_ms=5.0,
        release_ms=50.0,
        makeup_gain_db=24.0,
    )
    out = struct.unpack("<2000h", result)
    assert all(-32768 <= s <= 32767 for s in out)


def test_invalid_ratio_raises_at_public_api():
    pcm16 = struct.pack("<100h", *([0] * 100))
    with pytest.raises(ValueError):
        compress_pcm16(
            pcm16,
            channels=1,
            framerate=24000,
            threshold_db=-20.0,
            ratio=0.5,
            attack_ms=10.0,
            release_ms=100.0,
        )


def test_empty_pcm16_raises():
    with pytest.raises(ValueError):
        compress_pcm16(
            b"",
            channels=1,
            framerate=24000,
            threshold_db=-20.0,
            ratio=4.0,
            attack_ms=10.0,
            release_ms=100.0,
        )
