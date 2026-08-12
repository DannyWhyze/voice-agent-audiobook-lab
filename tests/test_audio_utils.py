import math
import struct
import wave
from io import BytesIO

from src.orchestrator.audio.combine import concat_wavs


def _make_wav(
    channels: int, sample_value: int, count: int = 100, framerate: int = 24000
) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(
            struct.pack(f"<{count * channels}h", *([sample_value] * (count * channels)))
        )
    return buffer.getvalue()


def _read_wav_samples(data: bytes) -> tuple[int, list[int]]:
    buffer = BytesIO(data)
    with wave.open(buffer, "rb") as wav_in:
        channels = wav_in.getnchannels()
        frames = wav_in.readframes(wav_in.getnframes())
    sample_count = len(frames) // 2
    return channels, list(struct.unpack(f"<{sample_count}h", frames))


def test_all_mono_clips_stay_mono():
    clip_a = _make_wav(1, 1000)
    clip_b = _make_wav(1, 2000)

    result = concat_wavs([clip_a, clip_b], [0])

    channels, _ = _read_wav_samples(result)
    assert channels == 1


def test_mixed_mono_and_stereo_clips_upmix_to_stereo():
    mono_clip = _make_wav(1, 1000)
    stereo_clip = _make_wav(2, 2000)

    result = concat_wavs([mono_clip, stereo_clip], [0])

    channels, samples = _read_wav_samples(result)
    assert channels == 2
    # The mono clip's single channel must be duplicated identically onto L and R.
    mono_part = samples[: 100 * 2]
    for i in range(100):
        assert mono_part[i * 2] == 1000
        assert mono_part[i * 2 + 1] == 1000


def test_framerate_mismatch_still_raises():
    clip_a = _make_wav(1, 1000, framerate=24000)
    clip_b = _make_wav(1, 1000, framerate=22050)

    try:
        concat_wavs([clip_a, clip_b], [0])
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_trailing_pause_appends_silence_at_end():
    clip_a = _make_wav(1, 1000, count=100, framerate=1000)

    result = concat_wavs([clip_a], [], trailing_pause_ms=50)

    channels, samples = _read_wav_samples(result)
    assert channels == 1
    assert len(samples) == 150
    assert samples[100:] == [0] * 50


def test_trailing_pause_default_is_zero():
    clip_a = _make_wav(1, 1000)
    clip_b = _make_wav(1, 2000)

    result = concat_wavs([clip_a, clip_b], [0])

    _, samples = _read_wav_samples(result)
    assert len(samples) == 200


def test_pan_full_left_silences_right_channel():
    clip = _make_wav(1, 1000)

    result = concat_wavs([clip], [], pans=[-1.0])

    channels, samples = _read_wav_samples(result)
    assert channels == 2
    assert samples[0] == 1000
    assert samples[1] == 0


def test_pan_full_right_silences_left_channel():
    clip = _make_wav(1, 1000)

    result = concat_wavs([clip], [], pans=[1.0])

    channels, samples = _read_wav_samples(result)
    assert channels == 2
    assert samples[0] == 0
    assert samples[1] == 1000


def test_pan_center_matches_unpanned_duplicate():
    clip = _make_wav(1, 1000)

    result = concat_wavs([clip], [], pans=[0.0])

    channels, samples = _read_wav_samples(result)
    assert channels == 1
    assert samples[0] == 1000


def test_single_panned_clip_forces_stereo_output_and_applies_equal_power_gain():
    mono_clip_a = _make_wav(1, 1000)
    mono_clip_b = _make_wav(1, 1000)

    result = concat_wavs([mono_clip_a, mono_clip_b], [0], pans=[-0.5, 0.0])

    channels, samples = _read_wav_samples(result)
    assert channels == 2

    angle = (-0.5 + 1) * math.pi / 4
    expected_gain_l = round(1000 * math.cos(angle))
    expected_gain_r = round(1000 * math.sin(angle))
    assert samples[0] == expected_gain_l
    assert samples[1] == expected_gain_r

    # Second clip has pan=0.0 -- unpanned, stays a plain mono-duplicated pair.
    second_clip_start = 100 * 2
    assert samples[second_clip_start] == 1000
    assert samples[second_clip_start + 1] == 1000


def test_pans_length_mismatch_raises():
    clip_a = _make_wav(1, 1000)
    clip_b = _make_wav(1, 1000)

    try:
        concat_wavs([clip_a, clip_b], [0], pans=[0.0])
        raised = False
    except ValueError:
        raised = True
    assert raised
