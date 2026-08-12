from __future__ import annotations

import struct

import librosa
import numpy as np


def _samples_as_float(pcm16: bytes) -> np.ndarray:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16)
    return np.array(samples, dtype=np.float64) / 32768.0


def _float_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 0.999969) * 32768.0
    int16_samples = clipped.astype(np.int16)
    return struct.pack(f"<{len(int16_samples)}h", *int16_samples)


def _validate_params(semitones: int, cents: float) -> None:
    if not (-12 <= semitones <= 12):
        raise ValueError("semitones must be between -12 and 12")
    if not (-50.0 <= cents <= 50.0):
        raise ValueError("cents must be between -50 and 50")


def pitch_shift_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    semitones: int,
    cents: float,
) -> bytes:
    _validate_params(semitones, cents)
    n_steps = semitones + cents / 100.0
    samples = _samples_as_float(pcm16)
    if samples.size == 0:
        return pcm16

    if channels == 1:
        shifted = librosa.effects.pitch_shift(samples, sr=framerate, n_steps=n_steps)
        return _float_to_pcm16(shifted)

    reshaped = samples.reshape(-1, channels)
    shifted_channels = [
        librosa.effects.pitch_shift(
            np.ascontiguousarray(reshaped[:, ch]), sr=framerate, n_steps=n_steps
        )
        for ch in range(channels)
    ]
    interleaved = np.empty(len(shifted_channels[0]) * channels, dtype=np.float64)
    for ch, channel_samples in enumerate(shifted_channels):
        interleaved[ch::channels] = channel_samples
    return _float_to_pcm16(interleaved)
