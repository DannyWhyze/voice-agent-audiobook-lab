from __future__ import annotations

import io
import math
import struct
import wave


def _read_wav_as_pcm16(data: bytes) -> tuple[int, int, bytes]:
    """Parse a RIFF/WAVE file and return (channels, framerate, pcm16_bytes).

    s2.cpp emits 32-bit IEEE-float WAV (format tag 3), which Python's
    stdlib `wave` module cannot open at all -- it only supports integer
    PCM (format tag 1). Samples are converted to 16-bit PCM here so the
    rest of the pipeline (and `wave` for writing the combined output)
    can stay on plain PCM16.
    """
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("Not a RIFF/WAVE file.")

    pos = 12
    fmt_chunk: bytes | None = None
    audio_data: bytes | None = None
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        chunk_body = data[pos + 8 : pos + 8 + chunk_size]
        if chunk_id == b"fmt ":
            fmt_chunk = chunk_body
        elif chunk_id == b"data":
            audio_data = chunk_body
        pos += 8 + chunk_size + (chunk_size % 2)  # chunks are word-aligned

    if fmt_chunk is None or audio_data is None:
        raise ValueError("WAV file is missing a fmt or data chunk.")

    format_tag, channels, framerate, _, _, bits_per_sample = struct.unpack(
        "<HHIIHH", fmt_chunk[:16]
    )

    if format_tag == 1 and bits_per_sample == 16:
        pcm16 = audio_data
    elif format_tag == 3 and bits_per_sample == 32:
        sample_count = len(audio_data) // 4
        floats = struct.unpack(f"<{sample_count}f", audio_data[: sample_count * 4])
        samples = [max(-32768, min(32767, round(f * 32767))) for f in floats]
        pcm16 = struct.pack(f"<{len(samples)}h", *samples)
    else:
        raise ValueError(
            f"Unsupported WAV format (tag={format_tag}, bits_per_sample={bits_per_sample})."
        )

    return channels, framerate, pcm16


def _apply_gain(pcm16: bytes, gain_db: float) -> bytes:
    if gain_db == 0:
        return pcm16
    factor = 10 ** (gain_db / 20)
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16[: sample_count * 2])
    adjusted = [max(-32768, min(32767, round(s * factor))) for s in samples]
    return struct.pack(f"<{len(adjusted)}h", *adjusted)


def _apply_pan(pcm16: bytes, pan: float) -> bytes:
    """Apply equal-power stereo panning to already-interleaved stereo PCM16.

    Uses the same formula as the Web Audio API's StereoPannerNode (mono-input
    equal-power law) so the server-side render matches the browser's live
    preview: angle = (pan + 1) * pi/4, gainL = cos(angle), gainR = sin(angle).
    """
    if pan == 0:
        return pcm16
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16[: sample_count * 2])
    angle = (pan + 1) * math.pi / 4
    gain_l = math.cos(angle)
    gain_r = math.sin(angle)
    adjusted = list(samples)
    for i in range(0, sample_count, 2):
        adjusted[i] = max(-32768, min(32767, round(samples[i] * gain_l)))
        adjusted[i + 1] = max(-32768, min(32767, round(samples[i + 1] * gain_r)))
    return struct.pack(f"<{len(adjusted)}h", *adjusted)


def _upmix_mono_to_stereo(pcm16: bytes) -> bytes:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16[: sample_count * 2])
    stereo = [0] * (sample_count * 2)
    for i, sample in enumerate(samples):
        stereo[i * 2] = sample
        stereo[i * 2 + 1] = sample
    return struct.pack(f"<{len(stereo)}h", *stereo)


def concat_wavs(
    clips: list[bytes],
    pauses_ms: list[int],
    gains_db: list[float] | None = None,
    trailing_pause_ms: int = 0,
    pans: list[float] | None = None,
) -> bytes:
    if not clips:
        raise ValueError("No audio clips provided to concatenate.")
    if len(pauses_ms) != len(clips) - 1:
        raise ValueError("pauses_ms length must be one less than clips length.")
    if gains_db is None:
        gains_db = [0.0] * len(clips)
    elif len(gains_db) != len(clips):
        raise ValueError("gains_db length must match clips length.")
    if pans is None:
        pans = [0.0] * len(clips)
    elif len(pans) != len(clips):
        raise ValueError("pans length must match clips length.")

    parsed = [_read_wav_as_pcm16(clip) for clip in clips]
    framerate = parsed[0][1]
    for index, (_, clip_framerate, _) in enumerate(parsed[1:], start=1):
        if clip_framerate != framerate:
            raise ValueError(
                f"Clip {index} has a different framerate than clip 0 "
                f"({clip_framerate} vs {framerate})"
            )

    # A reverbed clip is stereo while its siblings may still be mono -- upmix
    # any mono clip (duplicate its single channel onto L and R, which does not
    # cause phase cancellation since the channels are identical, not inverted)
    # instead of rejecting the mix, so mixed mono/stereo chapters can still be
    # combined. An all-mono set stays mono, unchanged from prior behavior.
    # A clip with a nonzero pan also forces stereo output for the whole set,
    # same reasoning -- panning is meaningless on a mono-only render.
    target_channels = max(channels for channels, _, _ in parsed)
    if any(pan != 0 for pan in pans):
        target_channels = 2

    frames = []
    for index, (clip_channels, _, clip_pcm) in enumerate(parsed):
        pcm = clip_pcm
        if clip_channels == 1 and target_channels == 2:
            pcm = _upmix_mono_to_stereo(pcm)
        pcm = _apply_gain(pcm, gains_db[index])
        if target_channels == 2:
            pcm = _apply_pan(pcm, pans[index])
        frames.append(pcm)

    sampwidth = 2  # bytes, always 16-bit PCM after _read_wav_as_pcm16

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_out:
        wav_out.setnchannels(target_channels)
        wav_out.setsampwidth(sampwidth)
        wav_out.setframerate(framerate)
        for index, frame_data in enumerate(frames):
            if index > 0:
                pause_ms = pauses_ms[index - 1]
                silence_samples = int(framerate * pause_ms / 1000)
                if silence_samples > 0:
                    wav_out.writeframes(
                        b"\x00" * (silence_samples * target_channels * sampwidth)
                    )
            wav_out.writeframes(frame_data)

        if trailing_pause_ms > 0:
            silence_samples = int(framerate * trailing_pause_ms / 1000)
            if silence_samples > 0:
                wav_out.writeframes(
                    b"\x00" * (silence_samples * target_channels * sampwidth)
                )

    return output.getvalue()
