from __future__ import annotations

import math
import struct


def apply_fade_pcm16(
    pcm16: bytes,
    channels: int,
    framerate: int,
    *,
    fade_in_ms: float,
    fade_out_ms: float,
) -> bytes:
    if fade_in_ms < 0:
        raise ValueError(f"fade_in_ms must be >= 0, got {fade_in_ms}")
    if fade_out_ms < 0:
        raise ValueError(f"fade_out_ms must be >= 0, got {fade_out_ms}")

    sample_count = len(pcm16) // 2
    frame_count = sample_count // channels
    duration_ms = frame_count / framerate * 1000.0
    if fade_in_ms + fade_out_ms > duration_ms:
        raise ValueError(
            "fade_in_ms + fade_out_ms must be <= the clip's duration "
            f"({duration_ms:.1f}ms), got {fade_in_ms + fade_out_ms}"
        )

    samples = list(struct.unpack(f"<{sample_count}h", pcm16))
    fade_in_frames = round(fade_in_ms / 1000.0 * framerate)
    fade_out_frames = round(fade_out_ms / 1000.0 * framerate)

    for frame in range(fade_in_frames):
        t = frame / fade_in_frames
        gain = math.sin(t * math.pi / 2)
        for c in range(channels):
            idx = frame * channels + c
            samples[idx] = max(-32768, min(32767, round(samples[idx] * gain)))

    for frame in range(fade_out_frames):
        t = frame / fade_out_frames
        gain = math.cos(t * math.pi / 2)
        frame_index = frame_count - fade_out_frames + frame
        for c in range(channels):
            idx = frame_index * channels + c
            samples[idx] = max(-32768, min(32767, round(samples[idx] * gain)))

    return struct.pack(f"<{sample_count}h", *samples)
