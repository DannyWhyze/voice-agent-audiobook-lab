from __future__ import annotations

import math
import struct
from typing import Literal

import numpy as np
from numba import njit
from scipy.signal import lfilter

MIN_AMPLITUDE = 1e-6  # dB floor to avoid math.log10(0) on silence; ~ -120 dBFS


def _validate_params(
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    knee_db: float,
    detector: str,
    rms_window_ms: float,
) -> None:
    if not (-60.0 <= threshold_db <= 0.0):
        raise ValueError(f"threshold_db must be between -60 and 0, got {threshold_db}")
    if ratio < 1.0:
        raise ValueError(f"ratio must be >= 1.0, got {ratio}")
    if attack_ms <= 0:
        raise ValueError(f"attack_ms must be > 0, got {attack_ms}")
    if release_ms <= 0:
        raise ValueError(f"release_ms must be > 0, got {release_ms}")
    if knee_db < 0:
        raise ValueError(f"knee_db must be >= 0, got {knee_db}")
    if detector not in ("peak", "rms"):
        raise ValueError(f'detector must be "peak" or "rms", got {detector!r}')
    if rms_window_ms <= 0:
        raise ValueError(f"rms_window_ms must be > 0, got {rms_window_ms}")


def _detect_levels_db(
    samples: list[int] | np.ndarray,
    channels: int,
    framerate: int,
    detector: Literal["peak", "rms"],
    rms_window_ms: float,
) -> np.ndarray:
    samples_array = np.asarray(samples, dtype=np.float64)
    frame_count = samples_array.shape[0] // channels
    frames = (
        samples_array[: frame_count * channels].reshape(frame_count, channels) / 32768.0
    )

    if detector == "peak":
        amplitude = np.abs(frames).max(axis=1)
        return 20.0 * np.log10(np.maximum(amplitude, MIN_AMPLITUDE))

    # RMS: one-pole low-pass smoothing of the squared, channel-linked signal
    # (a standard simplified RMS detector -- see spec's Algorithmus section).
    # y[n] = alpha*x[n] + (1-alpha)*y[n-1] is a first-order IIR filter with
    # a constant coefficient, so lfilter computes it directly (same
    # reasoning as the EQ vectorization in audio/eq.py).
    alpha = 1.0 - math.exp(-1.0 / (framerate * rms_window_ms / 1000.0))
    frame_sq = (frames**2).max(axis=1)
    smoothed_sq = lfilter([alpha], [1.0, -(1.0 - alpha)], frame_sq)
    amplitude = np.sqrt(np.maximum(smoothed_sq, 0.0))
    return 20.0 * np.log10(np.maximum(amplitude, MIN_AMPLITUDE))


def _gain_reduction_db(level_db, threshold_db: float, ratio: float, knee_db: float):
    target_db = threshold_db + (level_db - threshold_db) / ratio

    if knee_db == 0.0:
        return np.where(level_db <= threshold_db, 0.0, target_db - level_db)

    knee_start = threshold_db - knee_db / 2.0
    knee_end = threshold_db + knee_db / 2.0

    # Soft-knee interpolation (Giannoulis/Massberg/Reiss, "Digital Dynamic
    # Range Compressor Design", 2012) -- smooths the transition around the
    # threshold instead of a hard corner.
    knee_position = level_db - knee_start
    soft_result = ((1.0 / ratio - 1.0) * knee_position**2) / (2.0 * knee_db)

    return np.where(
        level_db <= knee_start,
        0.0,
        np.where(level_db >= knee_end, target_db - level_db, soft_result),
    )


@njit(cache=True)
def _smooth_gain_reduction_core(
    raw_reduction_db: np.ndarray, attack_coeff: float, release_coeff: float
) -> np.ndarray:
    n = raw_reduction_db.shape[0]
    smoothed = np.empty(n, dtype=np.float64)
    current = 0.0
    for i in range(n):
        raw = raw_reduction_db[i]
        if raw < current:
            # Reduction is getting stronger (more negative) -> attack.
            current = attack_coeff * current + (1.0 - attack_coeff) * raw
        else:
            # Reduction is easing off (less negative / back toward 0) -> release.
            current = release_coeff * current + (1.0 - release_coeff) * raw
        smoothed[i] = current
    return smoothed


def _smooth_gain_reduction(
    raw_reduction_db: list[float] | np.ndarray,
    framerate: int,
    attack_ms: float,
    release_ms: float,
) -> np.ndarray:
    attack_coeff = math.exp(-1.0 / (framerate * attack_ms / 1000.0))
    release_coeff = math.exp(-1.0 / (framerate * release_ms / 1000.0))
    raw_array = np.asarray(raw_reduction_db, dtype=np.float64)
    return _smooth_gain_reduction_core(raw_array, attack_coeff, release_coeff)


def compress_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    knee_db: float = 0.0,
    makeup_gain_db: float = 0.0,
    detector: Literal["peak", "rms"] = "rms",
    rms_window_ms: float = 10.0,
) -> bytes:
    _validate_params(
        threshold_db, ratio, attack_ms, release_ms, knee_db, detector, rms_window_ms
    )
    if len(pcm16) == 0:
        raise ValueError("pcm16 must not be empty.")

    sample_count = len(pcm16) // 2
    frame_count = sample_count // channels
    usable_sample_count = frame_count * channels
    samples = struct.unpack(
        f"<{usable_sample_count}h", pcm16[: usable_sample_count * 2]
    )
    samples_array = np.array(samples, dtype=np.float64)
    frames_raw = samples_array.reshape(frame_count, channels)

    levels_db = _detect_levels_db(
        samples_array, channels, framerate, detector, rms_window_ms
    )
    raw_reduction_db = _gain_reduction_db(levels_db, threshold_db, ratio, knee_db)
    smoothed_reduction_db = _smooth_gain_reduction(
        raw_reduction_db, framerate, attack_ms, release_ms
    )

    total_gain_db = smoothed_reduction_db + makeup_gain_db
    factor = 10.0 ** (total_gain_db / 20.0)
    frames_out = frames_raw * factor[:, np.newaxis]
    output = np.clip(np.round(frames_out), -32768, 32767).astype(np.int16).reshape(-1)

    return struct.pack(f"<{len(output)}h", *output)
