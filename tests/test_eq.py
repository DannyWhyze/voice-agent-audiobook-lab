import math
import struct

import pytest

from src.orchestrator.audio.eq import EQ_BAND_FREQUENCIES_HZ, apply_eq_pcm16


def _sine_wave_pcm16(freq_hz, duration_s, framerate, amplitude=0.5):
    sample_count = int(duration_s * framerate)
    samples = [
        int(amplitude * 32767 * math.sin(2 * math.pi * freq_hz * i / framerate))
        for i in range(sample_count)
    ]
    return struct.pack(f"<{sample_count}h", *samples)


def _rms(pcm16):
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16)
    return math.sqrt(sum((s / 32768.0) ** 2 for s in samples) / sample_count)


def test_rejects_wrong_band_count():
    with pytest.raises(ValueError):
        apply_eq_pcm16(b"\x00\x00", 1, 44100, band_gains_db=[0.0] * 8)


def test_rejects_gain_above_max():
    gains = [0.0] * 10
    gains[0] = 12.1
    with pytest.raises(ValueError):
        apply_eq_pcm16(b"\x00\x00", 1, 44100, band_gains_db=gains)


def test_rejects_gain_below_min():
    gains = [0.0] * 10
    gains[0] = -12.1
    with pytest.raises(ValueError):
        apply_eq_pcm16(b"\x00\x00", 1, 44100, band_gains_db=gains)


def test_accepts_gain_at_exact_boundary():
    # Regression guard: at this project's real engine framerate (44100 Hz,
    # confirmed 05.08.2026 against s2_codec.cpp's hardcoded default -- see
    # docs/ideas.md), Nyquist is 22050 Hz, comfortably above every band
    # including the top 16000 Hz one. This must not raise.
    gains = [12.0] + [-12.0] * 9
    pcm16 = _sine_wave_pcm16(1000, 0.05, 44100)
    apply_eq_pcm16(pcm16, 1, 44100, band_gains_db=gains)  # must not raise


def test_rejects_top_band_above_nyquist_at_lower_framerate():
    # This project was originally built on a false assumption that the
    # engine always outputs 24000 Hz (Nyquist 12000 Hz) -- at that framerate
    # the 16000 Hz band is above Nyquist and the filter goes unstable
    # (matches the original OverflowError this guard was written to catch).
    # The real engine framerate turned out to be 44100 Hz (see above), but
    # this guard must still protect any framerate where it doesn't hold.
    with pytest.raises(ValueError):
        apply_eq_pcm16(
            _sine_wave_pcm16(1000, 0.05, 24000), 1, 24000, band_gains_db=[0.0] * 10
        )


def test_rejects_band_frequency_at_or_above_nyquist():
    # framerate=8000 -> Nyquist=4000 Hz, but the fixed band list includes
    # frequencies from 4000 Hz upward, all >= Nyquist at this (artificially
    # low) framerate -- proves the defensive guard itself works, independent
    # of the gains requested.
    with pytest.raises(ValueError):
        apply_eq_pcm16(
            _sine_wave_pcm16(500, 0.05, 8000), 1, 8000, band_gains_db=[0.0] * 10
        )


def test_rejects_empty_pcm16():
    with pytest.raises(ValueError):
        apply_eq_pcm16(b"", 1, 44100, band_gains_db=[0.0] * 10)


def test_all_zero_gains_is_identity():
    framerate = 44100
    pcm16 = _sine_wave_pcm16(1000, 0.05, framerate)
    result = apply_eq_pcm16(pcm16, 1, framerate, band_gains_db=[0.0] * 10)
    assert result == pcm16


def test_boosting_band_increases_rms_at_that_frequency():
    framerate = 44100
    band_index = EQ_BAND_FREQUENCIES_HZ.index(1000)
    pcm16 = _sine_wave_pcm16(1000, 0.3, framerate)
    gains = [0.0] * 10
    gains[band_index] = 6.0

    original_rms = _rms(pcm16)
    boosted = apply_eq_pcm16(pcm16, 1, framerate, band_gains_db=gains)
    boosted_rms = _rms(boosted)

    expected_factor = 10 ** (6.0 / 20.0)
    assert boosted_rms / original_rms == pytest.approx(expected_factor, rel=0.05)


def test_cutting_band_decreases_rms_at_that_frequency():
    framerate = 44100
    band_index = EQ_BAND_FREQUENCIES_HZ.index(1000)
    pcm16 = _sine_wave_pcm16(1000, 0.3, framerate)
    gains = [0.0] * 10
    gains[band_index] = -6.0

    original_rms = _rms(pcm16)
    cut = apply_eq_pcm16(pcm16, 1, framerate, band_gains_db=gains)
    cut_rms = _rms(cut)

    expected_factor = 10 ** (-6.0 / 20.0)
    assert cut_rms / original_rms == pytest.approx(expected_factor, rel=0.05)


def test_stereo_channels_processed_independently():
    framerate = 44100
    band_index = EQ_BAND_FREQUENCIES_HZ.index(1000)
    mono = _sine_wave_pcm16(1000, 0.1, framerate)
    mono_samples = struct.unpack(f"<{len(mono) // 2}h", mono)
    stereo_samples = []
    for s in mono_samples:
        stereo_samples.append(s)
        stereo_samples.append(s)
    stereo = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)

    gains = [0.0] * 10
    gains[band_index] = 6.0
    result_mono = apply_eq_pcm16(mono, 1, framerate, band_gains_db=gains)
    result_stereo = apply_eq_pcm16(stereo, 2, framerate, band_gains_db=gains)

    result_mono_samples = struct.unpack(f"<{len(result_mono) // 2}h", result_mono)
    result_stereo_samples = struct.unpack(f"<{len(result_stereo) // 2}h", result_stereo)
    left = result_stereo_samples[0::2]
    right = result_stereo_samples[1::2]
    assert list(left) == list(result_mono_samples)
    assert list(right) == list(result_mono_samples)


def test_output_length_matches_input_length():
    framerate = 44100
    pcm16 = _sine_wave_pcm16(500, 0.1, framerate)
    result = apply_eq_pcm16(pcm16, 1, framerate, band_gains_db=[3.0] * 10)
    assert len(result) == len(pcm16)
