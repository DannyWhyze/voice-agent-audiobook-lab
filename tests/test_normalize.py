import math
import struct

import numpy as np
import pytest

from src.orchestrator.audio.normalize import normalize_pcm16


def _make_sine_wav(
    amplitude: float, framerate: int = 44100, duration_s: float = 0.5
) -> bytes:
    n_samples = int(framerate * duration_s)
    samples = [
        int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / framerate))
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *samples)


def test_peak_normalize_reaches_target():
    pcm16 = _make_sine_wav(amplitude=0.1)
    result = normalize_pcm16(
        pcm16, channels=1, framerate=44100, mode="peak", target_db=-1.0
    )

    samples = (
        np.array(struct.unpack(f"<{len(result) // 2}h", result), dtype=np.float64)
        / 32768.0
    )
    peak_db = 20.0 * math.log10(np.max(np.abs(samples)))
    assert peak_db == pytest.approx(-1.0, abs=0.1)


def test_rms_normalize_reaches_target():
    pcm16 = _make_sine_wav(amplitude=0.1)
    result = normalize_pcm16(
        pcm16, channels=1, framerate=44100, mode="rms", target_db=-20.0
    )

    samples = (
        np.array(struct.unpack(f"<{len(result) // 2}h", result), dtype=np.float64)
        / 32768.0
    )
    rms_db = 20.0 * math.log10(np.sqrt(np.mean(samples**2)))
    assert rms_db == pytest.approx(-20.0, abs=0.1)


def test_lufs_normalize_reaches_target():
    pcm16 = _make_sine_wav(amplitude=0.1, duration_s=2.0)
    result = normalize_pcm16(
        pcm16, channels=1, framerate=44100, mode="lufs", target_db=-16.0
    )

    import pyloudnorm as pyln

    samples = (
        np.array(struct.unpack(f"<{len(result) // 2}h", result), dtype=np.float64)
        / 32768.0
    )
    meter = pyln.Meter(44100)
    loudness = meter.integrated_loudness(samples)
    assert loudness == pytest.approx(-16.0, abs=0.5)


def test_rejects_invalid_mode():
    pcm16 = _make_sine_wav(amplitude=0.1)
    with pytest.raises(ValueError, match="mode must be"):
        normalize_pcm16(
            pcm16, channels=1, framerate=44100, mode="invalid", target_db=-20.0
        )


def test_does_not_clip_above_zero_dbfs():
    pcm16 = _make_sine_wav(amplitude=0.9)
    result = normalize_pcm16(
        pcm16, channels=1, framerate=44100, mode="peak", target_db=0.0
    )

    samples = np.array(struct.unpack(f"<{len(result) // 2}h", result), dtype=np.int16)
    assert np.max(samples) <= 32767
    assert np.min(samples) >= -32768
