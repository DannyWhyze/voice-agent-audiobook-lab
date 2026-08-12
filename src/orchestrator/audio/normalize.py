from __future__ import annotations

import math
import struct
from typing import Literal

import numpy as np
import pyloudnorm as pyln


def _validate_params(mode: Literal["peak", "rms", "lufs"], target_db: float) -> None:
    if mode not in ("peak", "rms", "lufs"):
        raise ValueError(f'mode must be "peak", "rms", or "lufs", got {mode!r}')


def _samples_as_float(pcm16: bytes) -> np.ndarray:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16)
    return np.array(samples, dtype=np.float64) / 32768.0


def _measure_peak_db(samples: np.ndarray) -> float:
    peak = np.max(np.abs(samples))
    if peak <= 0:
        return -120.0
    return 20.0 * math.log10(peak)


def _measure_rms_db(samples: np.ndarray) -> float:
    rms = np.sqrt(np.mean(samples**2))
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(rms)


def _measure_lufs(samples: np.ndarray, channels: int, framerate: int) -> float:
    if channels > 1:
        reshaped = samples.reshape(-1, channels)
    else:
        reshaped = samples
    meter = pyln.Meter(framerate)
    loudness = meter.integrated_loudness(reshaped)
    if loudness == float("-inf"):
        return -120.0
    return loudness


def normalize_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    mode: Literal["peak", "rms", "lufs"],
    target_db: float,
) -> bytes:
    _validate_params(mode, target_db)

    samples = _samples_as_float(pcm16)
    if samples.size == 0:
        return pcm16

    if mode == "peak":
        current_db = _measure_peak_db(samples)
    elif mode == "rms":
        current_db = _measure_rms_db(samples)
    else:
        current_db = _measure_lufs(samples, channels, framerate)

    gain_db = target_db - current_db
    gain_linear = 10.0 ** (gain_db / 20.0)

    normalized = np.clip(samples * gain_linear, -1.0, 0.999969) * 32768.0
    normalized_int16 = normalized.astype(np.int16)

    return struct.pack(f"<{len(normalized_int16)}h", *normalized_int16)
