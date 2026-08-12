from __future__ import annotations

import math
import struct

import numpy as np
from scipy.signal import lfilter

EQ_BAND_FREQUENCIES_HZ: list[float] = [
    31,
    62,
    125,
    250,
    500,
    1000,
    2000,
    4000,
    8000,
    16000,
]
EQ_BAND_Q = 1.4
EQ_GAIN_MIN_DB = -12.0
EQ_GAIN_MAX_DB = 12.0


def _validate_band_gains(band_gains_db: list[float]) -> None:
    if len(band_gains_db) != len(EQ_BAND_FREQUENCIES_HZ):
        raise ValueError(
            f"band_gains_db must have exactly {len(EQ_BAND_FREQUENCIES_HZ)} values, "
            f"got {len(band_gains_db)}"
        )
    for gain_db in band_gains_db:
        if not (EQ_GAIN_MIN_DB <= gain_db <= EQ_GAIN_MAX_DB):
            raise ValueError(
                f"band gain must be between {EQ_GAIN_MIN_DB} and {EQ_GAIN_MAX_DB}, "
                f"got {gain_db}"
            )


def _validate_framerate(framerate: int) -> None:
    # A peaking biquad above the Nyquist frequency (framerate/2) has poles
    # outside the unit circle and its output runs away to +/-inf. This is a
    # structural check on the band list vs. framerate, independent of which
    # gains are requested -- it must run even when every gain is 0 dB.
    nyquist_hz = framerate / 2.0
    for freq_hz in EQ_BAND_FREQUENCIES_HZ:
        if freq_hz >= nyquist_hz:
            raise ValueError(
                f"EQ band {freq_hz} Hz is at or above the Nyquist frequency "
                f"({nyquist_hz} Hz) for framerate={framerate} and cannot be filtered."
            )


def _peaking_biquad_coefficients(
    freq_hz: float, q: float, gain_db: float, framerate: int
) -> tuple[float, float, float, float, float]:
    # RBJ Audio EQ Cookbook peaking-EQ formula.
    a = 10 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq_hz / framerate
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)

    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a

    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def apply_eq_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    band_gains_db: list[float],
) -> bytes:
    _validate_band_gains(band_gains_db)
    _validate_framerate(framerate)
    if len(pcm16) == 0:
        raise ValueError("pcm16 must not be empty.")

    sample_count = len(pcm16) // 2
    frame_count = sample_count // channels
    usable_sample_count = frame_count * channels

    samples = struct.unpack(
        f"<{usable_sample_count}h", pcm16[: usable_sample_count * 2]
    )
    signal = (
        np.array(samples, dtype=np.float64).reshape(frame_count, channels) / 32768.0
    )

    for freq_hz, gain_db in zip(EQ_BAND_FREQUENCIES_HZ, band_gains_db):
        if gain_db == 0.0:
            continue
        b0, b1, b2, a1, a2 = _peaking_biquad_coefficients(
            freq_hz, EQ_BAND_Q, gain_db, framerate
        )
        b = [b0, b1, b2]
        a = [1.0, a1, a2]
        for c in range(channels):
            signal[:, c] = lfilter(b, a, signal[:, c])

    output = np.clip(np.round(signal.reshape(-1) * 32768.0), -32768, 32767).astype(
        np.int16
    )
    return struct.pack(f"<{len(output)}h", *output)
