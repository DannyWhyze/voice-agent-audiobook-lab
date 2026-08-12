import math
import struct

import numpy as np
import pytest

from src.orchestrator.audio.pitch import pitch_shift_pcm16


def _make_sine_wav(
    frequency: float, framerate: int = 44100, duration_s: float = 1.0
) -> bytes:
    n_samples = int(framerate * duration_s)
    samples = [
        int(0.5 * 32767 * math.sin(2 * math.pi * frequency * i / framerate))
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *samples)


def _dominant_frequency(pcm16: bytes, framerate: int) -> float:
    samples = (
        np.array(struct.unpack(f"<{len(pcm16) // 2}h", pcm16), dtype=np.float64)
        / 32768.0
    )
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / framerate)
    return freqs[np.argmax(spectrum)]


def test_pitch_shift_up_one_octave_doubles_frequency():
    pcm16 = _make_sine_wav(frequency=440.0)
    result = pitch_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=12, cents=0.0
    )

    dominant = _dominant_frequency(result, 44100)
    assert dominant == pytest.approx(880.0, abs=10.0)


def test_pitch_shift_down_one_octave_halves_frequency():
    pcm16 = _make_sine_wav(frequency=440.0)
    result = pitch_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=-12, cents=0.0
    )

    dominant = _dominant_frequency(result, 44100)
    assert dominant == pytest.approx(220.0, abs=10.0)


def test_zero_shift_leaves_frequency_unchanged():
    pcm16 = _make_sine_wav(frequency=440.0)
    result = pitch_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=0, cents=0.0
    )

    dominant = _dominant_frequency(result, 44100)
    assert dominant == pytest.approx(440.0, abs=10.0)


def test_cents_contribute_fractional_semitones():
    pcm16 = _make_sine_wav(frequency=440.0)
    # 100 cents == 1 semitone, so semitones=0/cents=50 (n_steps=0.5) should
    # match semitones=1/cents=-50 (n_steps=1 - 0.5=0.5) -- both stay within
    # the +/-50 cents range validated by pitch_shift_pcm16 itself.
    result_a = pitch_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=0, cents=50.0
    )
    result_b = pitch_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=1, cents=-50.0
    )

    freq_a = _dominant_frequency(result_a, 44100)
    freq_b = _dominant_frequency(result_b, 44100)
    assert freq_a == pytest.approx(freq_b, abs=5.0)


def test_stereo_input_preserves_channel_count():
    mono = _make_sine_wav(frequency=440.0)
    mono_samples = struct.unpack(f"<{len(mono) // 2}h", mono)
    stereo_samples = []
    for sample in mono_samples:
        stereo_samples.extend([sample, sample])
    stereo_pcm16 = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)

    result = pitch_shift_pcm16(
        stereo_pcm16, channels=2, framerate=44100, semitones=12, cents=0.0
    )

    result_sample_count = len(result) // 2
    assert result_sample_count % 2 == 0
