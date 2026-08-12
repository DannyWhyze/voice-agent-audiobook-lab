from __future__ import annotations

import math
import struct

import numpy as np
from numba import njit

MAX_TAIL_SECONDS = 20.0


def _estimate_tail_seconds(
    feedback: float, delay_time_ms: float, wet_dry_mix: float
) -> float:
    """How much silence to append so repeats can ring out instead of being
    cut off at the original clip's length.

    At wet_dry_mix=0 or feedback=0 there's nothing audible to ring out, so no
    tail is worth rendering. Otherwise estimate how many repeats it takes for
    the signal to fall by 60dB (a standard "decay time" definition) and
    convert that to seconds via the delay time itself, capped at
    MAX_TAIL_SECONDS (delay times can already be up to 2 full seconds, so the
    cap is higher than the reverb's -- a single very long, very fed-back
    delay would otherwise render for minutes).
    """
    if wet_dry_mix <= 0.0 or feedback <= 0.0:
        return 0.0
    repeats_to_silence = math.log(0.001) / math.log(feedback)
    tail_seconds = repeats_to_silence * (delay_time_ms / 1000.0)
    return min(tail_seconds, MAX_TAIL_SECONDS)


def _validate_params(
    delay_time_ms: float,
    feedback: float,
    damping: float,
    saturation: float,
    wow_flutter_rate: float,
    wow_flutter_depth: float,
    wet_dry_mix: float,
) -> None:
    if not (1.0 <= delay_time_ms <= 2000.0):
        raise ValueError(
            f"delay_time_ms must be between 1 and 2000, got {delay_time_ms}"
        )
    if not (0.0 <= feedback <= 0.95):
        raise ValueError(f"feedback must be between 0 and 0.95, got {feedback}")
    if not (0.0 <= damping <= 1.0):
        raise ValueError(f"damping must be between 0 and 1, got {damping}")
    if not (0.0 <= saturation <= 1.0):
        raise ValueError(f"saturation must be between 0 and 1, got {saturation}")
    if not (0.0 <= wow_flutter_rate <= 2.0):
        raise ValueError(
            f"wow_flutter_rate must be between 0 and 2, got {wow_flutter_rate}"
        )
    if not (0.0 <= wow_flutter_depth <= 2.0):
        raise ValueError(
            f"wow_flutter_depth must be between 0 and 2, got {wow_flutter_depth}"
        )
    if not (0.0 <= wet_dry_mix <= 1.0):
        raise ValueError(f"wet_dry_mix must be between 0 and 1, got {wet_dry_mix}")


@njit(cache=True)
def _peek_interp(buffer, length, index, offset):
    # 4-point cubic interpolation (O. Niemitalo, musicdsp.org "Other/49:
    # Cubic Interpollation"), identical formula to audio/reverb.py's
    # _peek_interp -- offset is always >= 0 here (wow/flutter LFO never goes
    # negative), so no negative-modulo handling is needed.
    base = math.floor(offset)
    frac = offset - base
    i0 = int((index + base - 1) % length)
    i1 = int((index + base) % length)
    i2 = int((index + base + 1) % length)
    i3 = int((index + base + 2) % length)
    x0 = buffer[i0]
    x1 = buffer[i1]
    x2 = buffer[i2]
    x3 = buffer[i3]
    a = (3 * (x1 - x2) - x0 + x3) / 2
    b = 2 * x2 + x0 - (5 * x1 + x3) / 2
    c = (x2 - x0) / 2
    return ((a * frac + b) * frac + c) * frac + x1


@njit(cache=True)
def _run_delay_channel(
    input_samples,
    delay_time_ms,
    feedback,
    damping,
    saturation,
    wow_flutter_rate,
    wow_flutter_depth,
    wet_dry_mix,
    framerate,
):
    frame_count = input_samples.shape[0]
    delay_samples = max(round(delay_time_ms / 1000.0 * framerate), 1)
    buffer = np.zeros(delay_samples, dtype=np.float64)
    index = 0
    lp_state = 0.0
    exc_phase = 0.0

    wow_rate = wow_flutter_rate / framerate
    wow_depth = wow_flutter_depth * framerate / 1000.0
    dp = 1.0 - damping
    drive = 1.0 + saturation * 4.0
    dry_gain = 1.0 - wet_dry_mix

    output = np.zeros(frame_count, dtype=np.float64)

    for i in range(frame_count):
        x = input_samples[i]

        exc = wow_depth * (1.0 + math.cos(exc_phase * 6.283185307179586))
        raw_delayed = _peek_interp(buffer, delay_samples, index, exc)

        lp_state += dp * (raw_delayed - lp_state)
        saturated = math.tanh(lp_state * drive)
        processed = (1.0 - saturation) * lp_state + saturation * saturated

        buffer[index] = x + processed * feedback
        output[i] = x * dry_gain + processed * wet_dry_mix

        exc_phase += wow_rate
        index = (index + 1) % delay_samples

    return output


def apply_delay_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    delay_time_ms: float,
    feedback: float,
    damping: float,
    saturation: float,
    wow_flutter_rate: float,
    wow_flutter_depth: float,
    wet_dry_mix: float,
) -> bytes:
    _validate_params(
        delay_time_ms,
        feedback,
        damping,
        saturation,
        wow_flutter_rate,
        wow_flutter_depth,
        wet_dry_mix,
    )
    if len(pcm16) == 0:
        raise ValueError("pcm16 must not be empty.")

    sample_count = len(pcm16) // 2
    frame_count = sample_count // channels
    usable_sample_count = frame_count * channels
    samples = struct.unpack(
        f"<{usable_sample_count}h", pcm16[: usable_sample_count * 2]
    )
    frames = (
        np.array(samples, dtype=np.float64).reshape(frame_count, channels) / 32768.0
    )

    tail_seconds = _estimate_tail_seconds(feedback, delay_time_ms, wet_dry_mix)
    tail_frame_count = round(tail_seconds * framerate)
    if tail_frame_count > 0:
        frames = np.concatenate(
            [frames, np.zeros((tail_frame_count, channels), dtype=np.float64)]
        )

    output_frames = np.empty_like(frames)
    for ch in range(channels):
        output_frames[:, ch] = _run_delay_channel(
            np.ascontiguousarray(frames[:, ch]),
            delay_time_ms,
            feedback,
            damping,
            saturation,
            wow_flutter_rate,
            wow_flutter_depth,
            wet_dry_mix,
            framerate,
        )

    output = np.clip(np.round(output_frames * 32768.0), -32768, 32767).astype(np.int16)
    return struct.pack(f"<{output.size}h", *output.reshape(-1))
