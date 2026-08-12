import struct

import numpy as np
import pytest
import pyworld as pw

from src.orchestrator.audio.formant import formant_shift_pcm16


def _make_harmonic_wav(
    f0: float, framerate: int = 44100, duration_s: float = 1.0
) -> bytes:
    n_samples = int(framerate * duration_s)
    t = np.arange(n_samples) / framerate
    # Sum of harmonics (not a pure sine) so the signal has a formant-like
    # spectral shape for cheaptrick/d4c to actually work with.
    signal = sum((1.0 / k) * np.sin(2 * np.pi * f0 * k * t) for k in range(1, 8))
    signal = signal / np.max(np.abs(signal)) * 0.5
    int16_samples = (signal * 32767).astype(np.int16)
    return struct.pack(f"<{n_samples}h", *int16_samples)


def _pcm16_to_float(pcm16: bytes) -> np.ndarray:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16)
    return np.array(samples, dtype=np.float64) / 32768.0


def _estimate_mean_f0(pcm16: bytes, framerate: int) -> float:
    samples = _pcm16_to_float(pcm16)
    f0, t = pw.dio(samples, framerate)
    f0 = pw.stonemask(samples, f0, t, framerate)
    voiced = f0[f0 > 0]
    return float(np.mean(voiced)) if voiced.size else 0.0


def _spectral_centroid(pcm16: bytes, framerate: int) -> float:
    samples = _pcm16_to_float(pcm16)
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / framerate)
    return float(np.sum(freqs * spectrum) / np.sum(spectrum))


def test_formant_shift_preserves_f0():
    pcm16 = _make_harmonic_wav(f0=150.0)
    result = formant_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=6, cents=0.0
    )

    original_f0 = _estimate_mean_f0(pcm16, 44100)
    shifted_f0 = _estimate_mean_f0(result, 44100)
    assert shifted_f0 == pytest.approx(original_f0, rel=0.05)


def test_formant_shift_up_raises_spectral_centroid():
    pcm16 = _make_harmonic_wav(f0=150.0)
    result = formant_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=6, cents=0.0
    )

    original_centroid = _spectral_centroid(pcm16, 44100)
    shifted_centroid = _spectral_centroid(result, 44100)
    assert shifted_centroid > original_centroid


def test_formant_shift_down_lowers_spectral_centroid():
    # Compared against a zero-shift baseline that went through the same
    # WORLD analysis/resynthesis pipeline (not the raw pre-WORLD signal):
    # cheaptrick/d4c resynthesis alone already raises the spectral centroid
    # via its aperiodicity component, so comparing against the untouched
    # original would conflate that artifact with the formant warp itself.
    pcm16 = _make_harmonic_wav(f0=150.0)
    unshifted = formant_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=0, cents=0.0
    )
    result = formant_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=-6, cents=0.0
    )

    unshifted_centroid = _spectral_centroid(unshifted, 44100)
    shifted_centroid = _spectral_centroid(result, 44100)
    assert shifted_centroid < unshifted_centroid


def test_zero_shift_leaves_f0_unchanged():
    pcm16 = _make_harmonic_wav(f0=150.0)
    result = formant_shift_pcm16(
        pcm16, channels=1, framerate=44100, semitones=0, cents=0.0
    )

    original_f0 = _estimate_mean_f0(pcm16, 44100)
    shifted_f0 = _estimate_mean_f0(result, 44100)
    assert shifted_f0 == pytest.approx(original_f0, rel=0.05)


def test_stereo_input_preserves_channel_count():
    mono = _make_harmonic_wav(f0=150.0)
    mono_samples = struct.unpack(f"<{len(mono) // 2}h", mono)
    stereo_samples = []
    for sample in mono_samples:
        stereo_samples.extend([sample, sample])
    stereo_pcm16 = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)

    result = formant_shift_pcm16(
        stereo_pcm16, channels=2, framerate=44100, semitones=6, cents=0.0
    )

    result_sample_count = len(result) // 2
    assert result_sample_count % 2 == 0
