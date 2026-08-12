import math
import struct

import pytest

from src.orchestrator.audio.fade import apply_fade_pcm16


def test_apply_fade_pcm16_fade_in_ramps_up_with_equal_power_curve():
    framerate = 1000  # 1 sample = 1ms, convenient for exact math
    frame_count = 20
    samples = [1000] * frame_count
    pcm16 = struct.pack(f"<{frame_count}h", *samples)

    faded = apply_fade_pcm16(pcm16, 1, framerate, fade_in_ms=10.0, fade_out_ms=0.0)

    faded_samples = struct.unpack(f"<{frame_count}h", faded)
    assert faded_samples[0] == 0
    assert faded_samples[5] == round(1000 * math.sin(0.5 * math.pi / 2))
    assert faded_samples[9] == round(1000 * math.sin(0.9 * math.pi / 2))
    assert faded_samples[10] == 1000  # first frame after the fade-in region, untouched


def test_apply_fade_pcm16_fade_out_ramps_down_with_equal_power_curve():
    framerate = 1000
    frame_count = 20
    samples = [1000] * frame_count
    pcm16 = struct.pack(f"<{frame_count}h", *samples)

    faded = apply_fade_pcm16(pcm16, 1, framerate, fade_in_ms=0.0, fade_out_ms=10.0)

    faded_samples = struct.unpack(f"<{frame_count}h", faded)
    assert faded_samples[9] == 1000  # last frame before the fade-out region, untouched
    assert faded_samples[10] == 1000  # t=0 -> cos(0) == 1
    assert faded_samples[15] == round(1000 * math.cos(0.5 * math.pi / 2))
    assert faded_samples[19] == round(1000 * math.cos(0.9 * math.pi / 2))


def test_apply_fade_pcm16_stereo_preserves_channel_interleaving():
    framerate = 1000
    frame_count = 10
    samples = []
    for _ in range(frame_count):
        samples.extend([1000, -1000])  # left=1000, right=-1000 every frame
    pcm16 = struct.pack(f"<{len(samples)}h", *samples)

    faded = apply_fade_pcm16(pcm16, 2, framerate, fade_in_ms=5.0, fade_out_ms=0.0)

    faded_samples = struct.unpack(f"<{len(samples)}h", faded)
    gain = math.sin(0.4 * math.pi / 2)  # frame 2 of a 5-frame fade-in, t=0.4
    assert faded_samples[4] == round(1000 * gain)
    assert faded_samples[5] == round(-1000 * gain)


def test_apply_fade_pcm16_no_fade_returns_input_unchanged():
    pcm16 = struct.pack("<10h", *range(10))
    faded = apply_fade_pcm16(pcm16, 1, 1000, fade_in_ms=0.0, fade_out_ms=0.0)
    assert faded == pcm16


def test_apply_fade_pcm16_rejects_negative_fade_in():
    pcm16 = struct.pack("<10h", *range(10))
    with pytest.raises(ValueError):
        apply_fade_pcm16(pcm16, 1, 1000, fade_in_ms=-1.0, fade_out_ms=0.0)


def test_apply_fade_pcm16_rejects_negative_fade_out():
    pcm16 = struct.pack("<10h", *range(10))
    with pytest.raises(ValueError):
        apply_fade_pcm16(pcm16, 1, 1000, fade_in_ms=0.0, fade_out_ms=-1.0)


def test_apply_fade_pcm16_rejects_fades_longer_than_duration():
    pcm16 = struct.pack("<10h", *range(10))  # 10ms at 1000Hz mono
    with pytest.raises(ValueError):
        apply_fade_pcm16(pcm16, 1, 1000, fade_in_ms=6.0, fade_out_ms=6.0)
