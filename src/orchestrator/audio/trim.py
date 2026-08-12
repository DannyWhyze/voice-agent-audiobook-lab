from __future__ import annotations


def trim_pcm16(
    pcm16: bytes, channels: int, framerate: int, start_ms: float, end_ms: float
) -> bytes:
    if start_ms < 0:
        raise ValueError(f"start_ms must be >= 0, got {start_ms}")
    if end_ms <= start_ms:
        raise ValueError(
            f"end_ms must be greater than start_ms, got end_ms={end_ms}, "
            f"start_ms={start_ms}"
        )

    sample_count = len(pcm16) // 2
    frame_count = sample_count // channels
    duration_ms = frame_count / framerate * 1000.0
    if end_ms > duration_ms:
        raise ValueError(
            f"end_ms must be <= the clip's duration ({duration_ms:.1f}ms), got {end_ms}"
        )

    start_frame = round(start_ms / 1000.0 * framerate)
    end_frame = round(end_ms / 1000.0 * framerate)

    start_byte = start_frame * channels * 2
    end_byte = end_frame * channels * 2
    return pcm16[start_byte:end_byte]
