import struct
import wave
from io import BytesIO

from src.orchestrator.audio.mp3 import wav_to_mp3


def _make_wav(
    sample_value: int = 1000, count: int = 44100, framerate: int = 44100
) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(struct.pack(f"<{count}h", *([sample_value] * count)))
    return buffer.getvalue()


def test_wav_to_mp3_produces_valid_mp3_frame_sync():
    mp3_bytes = wav_to_mp3(_make_wav())

    assert mp3_bytes[0] == 0xFF
    assert mp3_bytes[1] & 0xE0 == 0xE0  # MPEG frame sync bits


def test_wav_to_mp3_defaults_to_320_kbps():
    framerate = 44100
    duration_s = 1.0
    mp3_bytes = wav_to_mp3(
        _make_wav(count=int(framerate * duration_s), framerate=framerate)
    )

    actual_bitrate = len(mp3_bytes) * 8 / duration_s
    assert 300_000 <= actual_bitrate <= 340_000


def test_wav_to_mp3_respects_explicit_bit_rate():
    framerate = 44100
    duration_s = 1.0
    mp3_bytes = wav_to_mp3(
        _make_wav(count=int(framerate * duration_s), framerate=framerate),
        bit_rate_kbps=128,
    )

    actual_bitrate = len(mp3_bytes) * 8 / duration_s
    assert 110_000 <= actual_bitrate <= 145_000


def test_wav_to_mp3_at_low_samplerate_clamps_below_320_kbps():
    """MPEG-2 (sample rates below 32 kHz) caps Layer III at 160 kbps -- 320 kbps
    is only reachable at MPEG-1 rates (32/44.1/48 kHz). Documents this real MP3
    format limitation rather than asserting an unreachable bitrate."""
    framerate = 24000
    duration_s = 1.0
    mp3_bytes = wav_to_mp3(
        _make_wav(count=int(framerate * duration_s), framerate=framerate)
    )

    actual_bitrate = len(mp3_bytes) * 8 / duration_s
    assert actual_bitrate < 300_000
