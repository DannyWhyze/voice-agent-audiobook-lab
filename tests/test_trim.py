import struct

import pytest

from src.orchestrator.audio.trim import trim_pcm16


def test_trim_pcm16_mono_returns_middle_slice():
    framerate = 1000  # 1 sample = 1ms, convenient for exact math
    samples = list(range(100))
    pcm16 = struct.pack("<100h", *samples)

    trimmed = trim_pcm16(pcm16, 1, framerate, start_ms=10.0, end_ms=20.0)

    trimmed_samples = struct.unpack(f"<{len(trimmed) // 2}h", trimmed)
    assert list(trimmed_samples) == list(range(10, 20))


def test_trim_pcm16_stereo_preserves_channel_interleaving():
    framerate = 1000
    frame_count = 50
    samples = []
    for i in range(frame_count):
        samples.extend([i, -i])  # left=i, right=-i per frame
    pcm16 = struct.pack(f"<{len(samples)}h", *samples)

    trimmed = trim_pcm16(pcm16, 2, framerate, start_ms=5.0, end_ms=10.0)

    trimmed_samples = struct.unpack(f"<{len(trimmed) // 2}h", trimmed)
    assert list(trimmed_samples) == [5, -5, 6, -6, 7, -7, 8, -8, 9, -9]


def test_trim_pcm16_rejects_negative_start():
    pcm16 = struct.pack("<10h", *range(10))
    with pytest.raises(ValueError):
        trim_pcm16(pcm16, 1, 1000, start_ms=-1.0, end_ms=5.0)


def test_trim_pcm16_rejects_end_before_start():
    pcm16 = struct.pack("<10h", *range(10))
    with pytest.raises(ValueError):
        trim_pcm16(pcm16, 1, 1000, start_ms=5.0, end_ms=5.0)


def test_trim_pcm16_rejects_end_beyond_duration():
    pcm16 = struct.pack("<10h", *range(10))  # 10ms at 1000Hz mono
    with pytest.raises(ValueError):
        trim_pcm16(pcm16, 1, 1000, start_ms=0.0, end_ms=20.0)
