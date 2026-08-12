from __future__ import annotations

import math
import struct

import numpy as np
from numba import njit

# Delay-line lengths and output-tap offsets, in seconds, exactly as published
# in Jon Dattorro's "Effect Design Part 1: Reverberator and Other Filters"
# (JAES, September 1997) and verified against khoin/DattorroReverbNode
# (https://github.com/khoin/DattorroReverbNode), a public-domain WebAudio port
# of the same algorithm. Indices 0-3 are the input diffusor chain, 4-7 are the
# left tank loop, 8-11 are the right tank loop.
_DELAY_LENGTHS_SECONDS = [
    0.004771345,
    0.003595309,
    0.012734787,
    0.009307483,
    0.022579886,
    0.149625349,
    0.060481839,
    0.1249958,
    0.030509727,
    0.141695508,
    0.089244313,
    0.106280031,
]
_TAP_OFFSETS_SECONDS = [
    0.008937872,
    0.099929438,
    0.064278754,
    0.067067639,
    0.066866033,
    0.006283391,
    0.035818689,
    0.011861161,
    0.121870905,
    0.041262054,
    0.08981553,
    0.070931756,
    0.011256342,
    0.004065724,
]

# Average of the left tank loop (delays 4-7) and right tank loop (delays 8-11)
# lengths -- roughly how long one signal "bounce" around the feedback loop
# takes, used to estimate how many bounces (and how much wall-clock time) it
# takes for the reverb tail to decay to inaudibility.
_TANK_LOOP_SECONDS = 0.36
# Upper bound on how much extra tail we'll ever render, regardless of how
# close `decay` gets to 1.0 (where the mathematical estimate below grows
# without bound).
_MAX_TAIL_SECONDS = 15.0


def _estimate_tail_seconds(
    decay: float, pre_delay_ms: float, wet_dry_mix: float
) -> float:
    """How much silence to append to the input so the reverb tail can ring out
    instead of being cut off at the original clip's length.

    At wet_dry_mix=0 the reverb is inaudible regardless of decay, so no tail
    is worth rendering. Otherwise, estimate how many loop bounces it takes for
    the tail to fall by 60dB (a standard "reverb time" definition) and convert
    that to seconds via the tank's approximate loop time, capped at
    _MAX_TAIL_SECONDS. Pre-delay is added on top since the reverb doesn't even
    start building up until pre_delay_ms into the signal.
    """
    if wet_dry_mix <= 0.0 or decay <= 0.0:
        decay_tail_seconds = 0.0
    elif decay >= 0.999:
        decay_tail_seconds = _MAX_TAIL_SECONDS
    else:
        bounces_to_silence = math.log(0.001) / math.log(decay)
        decay_tail_seconds = min(
            bounces_to_silence * _TANK_LOOP_SECONDS, _MAX_TAIL_SECONDS
        )
    return pre_delay_ms / 1000.0 + decay_tail_seconds


def _validate_params(
    pre_delay_ms: float,
    bandwidth: float,
    input_diffusion_1: float,
    input_diffusion_2: float,
    decay: float,
    decay_diffusion_1: float,
    decay_diffusion_2: float,
    damping: float,
    excursion_rate: float,
    excursion_depth: float,
    wet_dry_mix: float,
) -> None:
    if not (0.0 <= pre_delay_ms <= 1000.0):
        raise ValueError(f"pre_delay_ms must be between 0 and 1000, got {pre_delay_ms}")
    if not (0.0 <= bandwidth <= 1.0):
        raise ValueError(f"bandwidth must be between 0 and 1, got {bandwidth}")
    if not (0.0 <= input_diffusion_1 <= 1.0):
        raise ValueError(
            f"input_diffusion_1 must be between 0 and 1, got {input_diffusion_1}"
        )
    if not (0.0 <= input_diffusion_2 <= 1.0):
        raise ValueError(
            f"input_diffusion_2 must be between 0 and 1, got {input_diffusion_2}"
        )
    if not (0.0 <= decay <= 1.0):
        raise ValueError(f"decay must be between 0 and 1, got {decay}")
    if not (0.0 <= decay_diffusion_1 <= 0.999999):
        raise ValueError(
            f"decay_diffusion_1 must be between 0 and 0.999999, got {decay_diffusion_1}"
        )
    if not (0.0 <= decay_diffusion_2 <= 0.999999):
        raise ValueError(
            f"decay_diffusion_2 must be between 0 and 0.999999, got {decay_diffusion_2}"
        )
    if not (0.0 <= damping <= 1.0):
        raise ValueError(f"damping must be between 0 and 1, got {damping}")
    if not (0.0 <= excursion_rate <= 2.0):
        raise ValueError(
            f"excursion_rate must be between 0 and 2, got {excursion_rate}"
        )
    if not (0.0 <= excursion_depth <= 2.0):
        raise ValueError(
            f"excursion_depth must be between 0 and 2, got {excursion_depth}"
        )
    if not (0.0 <= wet_dry_mix <= 1.0):
        raise ValueError(f"wet_dry_mix must be between 0 and 1, got {wet_dry_mix}")


@njit(cache=True)
def _peek(buffers, lengths, indices, line):
    return buffers[line, indices[line]]


@njit(cache=True)
def _peek_at(buffers, lengths, indices, line, offset):
    return buffers[line, (indices[line] + offset) % lengths[line]]


@njit(cache=True)
def _peek_interp(buffers, lengths, indices, line, offset):
    length = lengths[line]
    idx = indices[line]
    base = math.floor(offset)
    frac = offset - base
    i0 = (idx + base - 1) % length
    i1 = (idx + base) % length
    i2 = (idx + base + 1) % length
    i3 = (idx + base + 2) % length
    x0 = buffers[line, i0]
    x1 = buffers[line, i1]
    x2 = buffers[line, i2]
    x3 = buffers[line, i3]
    a = (3 * (x1 - x2) - x0 + x3) / 2
    b = 2 * x2 + x0 - (5 * x1 + x3) / 2
    c = (x2 - x0) / 2
    return ((a * frac + b) * frac + c) * frac + x1


@njit(cache=True)
def _push(buffers, indices, line, value):
    buffers[line, indices[line]] = value


@njit(cache=True)
def _run_tank(
    mono_input,
    delay_buffers,
    delay_lengths,
    delay_indices,
    tap_offsets,
    pre_delay_buffer,
    pre_delay_length,
    pre_delay_samples,
    bw,
    fi,
    si,
    dc,
    ft,
    st,
    dp,
    ex,
    ed,
    dry_gain,
    wet_gain,
):
    frame_count = mono_input.shape[0]
    left_out = np.zeros(frame_count, dtype=np.float64)
    right_out = np.zeros(frame_count, dtype=np.float64)

    pre_delay_write = 0
    lp1 = 0.0
    lp2 = 0.0
    lp3 = 0.0
    exc_phase = 0.0

    for i in range(frame_count):
        pre_delay_buffer[pre_delay_write] = mono_input[i]
        read_pos = (pre_delay_write - pre_delay_samples) % pre_delay_length
        predelayed = pre_delay_buffer[read_pos]
        pre_delay_write = (pre_delay_write + 1) % pre_delay_length

        lp1 += bw * (predelayed - lp1)

        old0 = _peek(delay_buffers, delay_lengths, delay_indices, 0)
        old1 = _peek(delay_buffers, delay_lengths, delay_indices, 1)
        old2 = _peek(delay_buffers, delay_lengths, delay_indices, 2)
        old3 = _peek(delay_buffers, delay_lengths, delay_indices, 3)

        new0 = lp1 - fi * old0
        pre = new0
        new1 = fi * (pre - old1) + old0
        pre = new1
        new2 = fi * pre + old1 - si * old2
        pre = new2
        new3 = si * (pre - old3) + old2
        split = si * new3 + old3

        _push(delay_buffers, delay_indices, 0, new0)
        _push(delay_buffers, delay_indices, 1, new1)
        _push(delay_buffers, delay_indices, 2, new2)
        _push(delay_buffers, delay_indices, 3, new3)

        exc = ed * (1 + math.cos(exc_phase * 6.2800))
        exc2 = ed * (1 + math.sin(exc_phase * 6.2847))

        old4_interp = _peek_interp(delay_buffers, delay_lengths, delay_indices, 4, exc)
        old6 = _peek(delay_buffers, delay_lengths, delay_indices, 6)
        old7 = _peek(delay_buffers, delay_lengths, delay_indices, 7)
        old8_interp = _peek_interp(delay_buffers, delay_lengths, delay_indices, 8, exc2)
        old10 = _peek(delay_buffers, delay_lengths, delay_indices, 10)
        old11 = _peek(delay_buffers, delay_lengths, delay_indices, 11)

        new4 = split + dc * old11 + ft * old4_interp
        new5 = old4_interp - ft * new4
        lp2 += dp * (_peek(delay_buffers, delay_lengths, delay_indices, 5) - lp2)
        new6 = dc * lp2 - st * old6
        new7 = old6 + st * new6

        new8 = split + dc * old7 + ft * old8_interp
        new9 = old8_interp - ft * new8
        lp3 += dp * (_peek(delay_buffers, delay_lengths, delay_indices, 9) - lp3)
        new10 = dc * lp3 - st * old10
        new11 = old10 + st * new10

        _push(delay_buffers, delay_indices, 4, new4)
        _push(delay_buffers, delay_indices, 5, new5)
        _push(delay_buffers, delay_indices, 6, new6)
        _push(delay_buffers, delay_indices, 7, new7)
        _push(delay_buffers, delay_indices, 8, new8)
        _push(delay_buffers, delay_indices, 9, new9)
        _push(delay_buffers, delay_indices, 10, new10)
        _push(delay_buffers, delay_indices, 11, new11)

        lo = (
            _peek_at(delay_buffers, delay_lengths, delay_indices, 9, tap_offsets[0])
            + _peek_at(delay_buffers, delay_lengths, delay_indices, 9, tap_offsets[1])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 10, tap_offsets[2])
            + _peek_at(delay_buffers, delay_lengths, delay_indices, 11, tap_offsets[3])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 5, tap_offsets[4])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 6, tap_offsets[5])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 7, tap_offsets[6])
        )
        ro = (
            _peek_at(delay_buffers, delay_lengths, delay_indices, 5, tap_offsets[7])
            + _peek_at(delay_buffers, delay_lengths, delay_indices, 5, tap_offsets[8])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 6, tap_offsets[9])
            + _peek_at(delay_buffers, delay_lengths, delay_indices, 7, tap_offsets[10])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 9, tap_offsets[11])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 10, tap_offsets[12])
            - _peek_at(delay_buffers, delay_lengths, delay_indices, 11, tap_offsets[13])
        )

        dry_sample = mono_input[i]
        left_out[i] = dry_sample * dry_gain + lo * wet_gain
        right_out[i] = dry_sample * dry_gain + ro * wet_gain

        exc_phase += ex
        for line in range(12):
            delay_indices[line] = (delay_indices[line] + 1) % delay_lengths[line]

    return left_out, right_out


def apply_reverb_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    pre_delay_ms: float,
    bandwidth: float,
    input_diffusion_1: float,
    input_diffusion_2: float,
    decay: float,
    decay_diffusion_1: float,
    decay_diffusion_2: float,
    damping: float,
    excursion_rate: float,
    excursion_depth: float,
    wet_dry_mix: float,
) -> bytes:
    _validate_params(
        pre_delay_ms,
        bandwidth,
        input_diffusion_1,
        input_diffusion_2,
        decay,
        decay_diffusion_1,
        decay_diffusion_2,
        damping,
        excursion_rate,
        excursion_depth,
        wet_dry_mix,
    )
    if len(pcm16) == 0:
        raise ValueError("pcm16 must not be empty.")

    sample_count = len(pcm16) // 2
    input_frame_count = sample_count // channels
    usable_sample_count = input_frame_count * channels
    samples = struct.unpack(
        f"<{usable_sample_count}h", pcm16[: usable_sample_count * 2]
    )
    frames = np.array(samples, dtype=np.float64).reshape(input_frame_count, channels)
    mono_input = frames.mean(axis=1) / 32768.0

    tail_seconds = _estimate_tail_seconds(decay, pre_delay_ms, wet_dry_mix)
    tail_frame_count = round(tail_seconds * framerate)
    mono_input = np.concatenate(
        [mono_input, np.zeros(tail_frame_count, dtype=np.float64)]
    )

    delay_lengths = np.array(
        [max(round(seconds * framerate), 1) for seconds in _DELAY_LENGTHS_SECONDS],
        dtype=np.int64,
    )
    max_delay_length = int(delay_lengths.max())
    delay_buffers = np.zeros((12, max_delay_length), dtype=np.float64)
    delay_indices = np.zeros(12, dtype=np.int64)
    tap_offsets = np.array(
        [round(seconds * framerate) for seconds in _TAP_OFFSETS_SECONDS],
        dtype=np.int64,
    )

    pre_delay_length = framerate + (128 - framerate % 128)
    pre_delay_buffer = np.zeros(pre_delay_length, dtype=np.float64)
    pre_delay_samples = round(pre_delay_ms / 1000.0 * framerate)

    bw = bandwidth
    fi = input_diffusion_1
    si = input_diffusion_2
    dc = decay
    ft = decay_diffusion_1
    st = decay_diffusion_2
    dp = 1.0 - damping
    ex = excursion_rate / framerate
    ed = excursion_depth * framerate / 1000.0
    dry_gain = 1.0 - wet_dry_mix
    wet_gain = wet_dry_mix * 0.6

    left_out, right_out = _run_tank(
        mono_input,
        delay_buffers,
        delay_lengths,
        delay_indices,
        tap_offsets,
        pre_delay_buffer,
        pre_delay_length,
        pre_delay_samples,
        bw,
        fi,
        si,
        dc,
        ft,
        st,
        dp,
        ex,
        ed,
        dry_gain,
        wet_gain,
    )

    frame_count = mono_input.shape[0]
    output = np.empty(frame_count * 2, dtype=np.int16)
    output[0::2] = np.clip(np.round(left_out * 32768.0), -32768, 32767).astype(np.int16)
    output[1::2] = np.clip(np.round(right_out * 32768.0), -32768, 32767).astype(
        np.int16
    )
    return struct.pack(f"<{len(output)}h", *output)
