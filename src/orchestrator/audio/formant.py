from __future__ import annotations

import struct

import numpy as np
import pyworld as pw


def _samples_as_float(pcm16: bytes) -> np.ndarray:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16)
    return np.array(samples, dtype=np.float64) / 32768.0


def _float_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 0.999969) * 32768.0
    int16_samples = clipped.astype(np.int16)
    return struct.pack(f"<{len(int16_samples)}h", *int16_samples)


def _warp_envelope(sp: np.ndarray, ratio: float) -> np.ndarray:
    """Warp a WORLD spectral envelope (frames x freq bins) along the frequency
    axis by `ratio`. ratio > 1 shifts formants up (smaller-sounding voice),
    ratio < 1 shifts them down (bigger-sounding voice). F0 is untouched by
    this — only the envelope that `cheaptrick` extracted is remapped.
    """
    num_frames, num_bins = sp.shape
    bins = np.arange(num_bins, dtype=np.float64)
    # To build the warped envelope at output bin f, sample the original
    # envelope at f / ratio (np.interp clamps to the edge value outside range).
    query = bins / ratio
    warped = np.empty_like(sp)
    for i in range(num_frames):
        warped[i] = np.interp(query, bins, sp[i])
    return warped


def _formant_shift_mono(
    samples: np.ndarray, framerate: int, ratio: float
) -> np.ndarray:
    f0, t = pw.dio(samples, framerate)
    f0 = pw.stonemask(samples, f0, t, framerate)
    sp = pw.cheaptrick(samples, f0, t, framerate)
    ap = pw.d4c(samples, f0, t, framerate)
    warped_sp = _warp_envelope(sp, ratio)
    return pw.synthesize(f0, warped_sp, ap, framerate)


def _validate_params(semitones: int, cents: float) -> None:
    if not (-12 <= semitones <= 12):
        raise ValueError("semitones must be between -12 and 12")
    if not (-50.0 <= cents <= 50.0):
        raise ValueError("cents must be between -50 and 50")


def formant_shift_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    semitones: int,
    cents: float,
) -> bytes:
    _validate_params(semitones, cents)
    ratio = 2 ** ((semitones + cents / 100.0) / 12)
    samples = _samples_as_float(pcm16)
    if samples.size == 0:
        return pcm16

    if channels == 1:
        shifted = _formant_shift_mono(samples, framerate, ratio)
        return _float_to_pcm16(shifted)

    reshaped = samples.reshape(-1, channels)
    shifted_channels = [
        _formant_shift_mono(np.ascontiguousarray(reshaped[:, ch]), framerate, ratio)
        for ch in range(channels)
    ]
    # pyworld's synthesize can return a slightly different sample count per
    # channel (frame-based resynthesis) — trim to the shortest before
    # interleaving so the result stays well-defined.
    min_len = min(len(ch) for ch in shifted_channels)
    interleaved = np.empty(min_len * channels, dtype=np.float64)
    for ch, channel_samples in enumerate(shifted_channels):
        interleaved[ch::channels] = channel_samples[:min_len]
    return _float_to_pcm16(interleaved)
