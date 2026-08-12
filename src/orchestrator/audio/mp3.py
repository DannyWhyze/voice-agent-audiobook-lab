from __future__ import annotations

import lameenc

from .combine import _read_wav_as_pcm16

DEFAULT_BIT_RATE_KBPS = 320


def wav_to_mp3(wav_bytes: bytes, bit_rate_kbps: int = DEFAULT_BIT_RATE_KBPS) -> bytes:
    channels, framerate, pcm16 = _read_wav_as_pcm16(wav_bytes)

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bit_rate_kbps)
    encoder.set_in_sample_rate(framerate)
    encoder.set_channels(channels)
    encoder.set_quality(2)  # 2 = highest quality (lameenc scale: 2 best, 7 fastest)

    mp3_data = encoder.encode(pcm16)
    mp3_data += encoder.flush()
    return mp3_data
