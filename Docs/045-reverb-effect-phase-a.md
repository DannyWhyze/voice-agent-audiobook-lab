# Reverb Effect Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Dattorro plate reverb effect (box-level and combined-audio-level) with backend DSP, persistence, and a render-based "Vorhören"/"Anwenden" UI — the non-live-preview half of the reverb feature (Phase B, real-time Web Audio preview, is a separate future plan).

**Architecture:** `src/orchestrator/reverb.py` implements the Dattorro algorithm as a pure-Python, whole-buffer (offline) port of a verified public-domain reference implementation, always outputting stereo. Four new endpoints in `main.py` mirror the compressor's `/compress/preview`/`/compress/apply` pattern exactly. Settings persist in `chapter.json` (`reverb_params` per box, `combined_reverb_params` per chapter) exactly like Plan 044. Since reverb output is stereo while today's box audio is mono, `concat_wavs()` in `audio_utils.py` is extended to upmix mono clips to stereo when combining a mixed set.

**Tech Stack:** Pure Python (no numpy), FastAPI + Pydantic, vanilla JS ES modules, pytest.

## Global Constraints

- `apply_reverb_pcm16()` always returns 2-channel (stereo) PCM16, regardless of input channel count — Dattorro's algorithm is inherently mono-to-stereo.
- Settings are saved only when "Anwenden" (Apply) is clicked, never on preview alone — same as the compressor and Plan 044.
- A box/combined-audio with no saved reverb settings yet starts from the fixed defaults below — no cross-box inheritance.
- No JS/CSS test framework exists in this project — frontend verification is `node --input-type=module --check` plus a manual browser check.
- Python changes are verified with `uv run pytest -v`, `uv run ruff check`, and `uv run ruff format --check`.
- Reference algorithm source: [khoin/DattorroReverbNode](https://github.com/khoin/DattorroReverbNode) (public domain). The 12 delay-line lengths, 14 output tap offsets, and default coefficients below are taken directly from it and have been verified against a working Python prototype (output length matches input, wet_dry_mix=0 reproduces the dry signal bit-exactly on both channels, tail RMS decays smoothly with no instability, and higher `decay` produces an audibly/measurably longer tail).
- Reverb parameters, defaults, and ranges:

  | Parameter | Default | Range |
  |---|---|---|
  | `pre_delay_ms` | 0.0 | 0–1000 |
  | `bandwidth` | 0.9999 | 0.0–1.0 |
  | `input_diffusion_1` | 0.75 | 0.0–1.0 |
  | `input_diffusion_2` | 0.625 | 0.0–1.0 |
  | `decay` | 0.5 | 0.0–1.0 |
  | `decay_diffusion_1` | 0.7 | 0.0–0.999999 |
  | `decay_diffusion_2` | 0.5 | 0.0–0.999999 |
  | `damping` | 0.005 | 0.0–1.0 |
  | `excursion_rate` | 0.5 | 0.0–2.0 |
  | `excursion_depth` | 0.7 | 0.0–2.0 |
  | `wet_dry_mix` | 0.3 | 0.0–1.0 |

---

### Task 1: Mono/stereo upmixing in `concat_wavs`

**Files:**
- Modify: `src/orchestrator/audio_utils.py:65-107` (`concat_wavs`)
- Test: `tests/test_audio_utils.py` (new file)

**Interfaces:**
- Consumes: `_read_wav_as_pcm16`, `_apply_gain` (already in this file, unchanged)
- Produces: `concat_wavs(clips, pauses_ms, gains_db=None)` keeps its existing signature and return type (`bytes`), but no longer raises on a channel-count mismatch — only a framerate mismatch remains a hard error. Consumed by `main.py`'s `/combine` endpoint (unchanged caller).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio_utils.py`:

```python
import struct
import wave
from io import BytesIO

from src.orchestrator.audio_utils import concat_wavs


def _make_wav(channels: int, sample_value: int, count: int = 100, framerate: int = 24000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(channels)
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(struct.pack(f"<{count * channels}h", *([sample_value] * (count * channels))))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audio_utils.py -v`
Expected: `test_mixed_mono_and_stereo_clips_upmix_to_stereo` FAILS with a `ValueError` (current code rejects the channel mismatch); the other two tests already pass since they don't touch the new behavior.

- [ ] **Step 3: Implement the upmixing**

In `src/orchestrator/audio_utils.py`, add a new helper function right after `_apply_gain` (currently ending at line 62):

```python
def _upmix_mono_to_stereo(pcm16: bytes) -> bytes:
    sample_count = len(pcm16) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm16[: sample_count * 2])
    stereo = [0] * (sample_count * 2)
    for i, sample in enumerate(samples):
        stereo[i * 2] = sample
        stereo[i * 2 + 1] = sample
    return struct.pack(f"<{len(stereo)}h", *stereo)
```

Replace the body of `concat_wavs` (lines 65-107) with:

```python
def concat_wavs(
    clips: list[bytes],
    pauses_ms: list[int],
    gains_db: list[float] | None = None,
) -> bytes:
    if not clips:
        raise ValueError("No audio clips provided to concatenate.")
    if len(pauses_ms) != len(clips) - 1:
        raise ValueError("pauses_ms length must be one less than clips length.")
    if gains_db is None:
        gains_db = [0.0] * len(clips)
    elif len(gains_db) != len(clips):
        raise ValueError("gains_db length must match clips length.")

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
    target_channels = max(channels for channels, _, _ in parsed)

    frames = []
    for index, (clip_channels, _, clip_pcm) in enumerate(parsed):
        pcm = clip_pcm
        if clip_channels == 1 and target_channels == 2:
            pcm = _upmix_mono_to_stereo(pcm)
        frames.append(_apply_gain(pcm, gains_db[index]))

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

    return output.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audio_utils.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `uv run pytest -v && uv run ruff check src/orchestrator/audio_utils.py tests/test_audio_utils.py && uv run ruff format --check src/orchestrator/audio_utils.py tests/test_audio_utils.py`
Expected: all pass (this touches `concat_wavs`, used by the existing `/combine` endpoint and its tests — confirm nothing there breaks)

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/audio_utils.py tests/test_audio_utils.py
git commit -m "feat: upmix mono clips to stereo in concat_wavs for mixed mono/stereo chapters"
```

---

### Task 2: Dattorro reverb DSP core

**Files:**
- Create: `src/orchestrator/reverb.py`
- Test: `tests/test_reverb.py` (new file)

**Interfaces:**
- Consumes: nothing from this codebase (pure DSP, only stdlib `math`/`struct`)
- Produces: `apply_reverb_pcm16(pcm16: bytes, channels: int, framerate: int, *, pre_delay_ms, bandwidth, input_diffusion_1, input_diffusion_2, decay, decay_diffusion_1, decay_diffusion_2, damping, excursion_rate, excursion_depth, wet_dry_mix) -> bytes` — always returns 2-channel interleaved PCM16. Consumed by `main.py` in Task 4.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reverb.py`:

```python
import math
import struct

import pytest

from src.orchestrator.reverb import _validate_params, apply_reverb_pcm16

VALID_PARAMS = dict(
    pre_delay_ms=0.0,
    bandwidth=0.9999,
    input_diffusion_1=0.75,
    input_diffusion_2=0.625,
    decay=0.5,
    decay_diffusion_1=0.7,
    decay_diffusion_2=0.5,
    damping=0.005,
    excursion_rate=0.5,
    excursion_depth=0.7,
    wet_dry_mix=0.3,
)


def _make_tone_pcm16(framerate: int, seconds: float) -> bytes:
    count = int(framerate * seconds)
    samples = [int(20000 * math.sin(2 * math.pi * 440 * i / framerate)) for i in range(count)]
    return struct.pack(f"<{count}h", *samples)


def test_accepts_valid_params():
    _validate_params(**VALID_PARAMS)


def test_rejects_decay_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, decay=1.5))


def test_rejects_wet_dry_mix_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, wet_dry_mix=-0.1))


def test_rejects_decay_diffusion_1_out_of_range():
    with pytest.raises(ValueError):
        _validate_params(**dict(VALID_PARAMS, decay_diffusion_1=1.0))


def test_output_is_always_stereo_and_same_frame_count_as_input():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.1)
    input_frame_count = len(pcm16) // 2

    output = apply_reverb_pcm16(pcm16, 1, framerate, **VALID_PARAMS)

    output_frame_count = len(output) // 2 // 2  # 2 bytes/sample, 2 channels
    assert output_frame_count == input_frame_count


def test_wet_dry_mix_zero_reproduces_dry_signal_on_both_channels():
    framerate = 24000
    pcm16 = _make_tone_pcm16(framerate, 0.05)
    input_samples = struct.unpack(f"<{len(pcm16)//2}h", pcm16)

    output = apply_reverb_pcm16(pcm16, 1, framerate, **dict(VALID_PARAMS, wet_dry_mix=0.0))
    output_samples = struct.unpack(f"<{len(output)//2}h", output)

    for i, expected in enumerate(input_samples):
        assert output_samples[i * 2] == expected
        assert output_samples[i * 2 + 1] == expected


def test_higher_decay_produces_a_longer_tail():
    framerate = 24000
    seconds = 1.0
    count = int(framerate * seconds)
    samples = [int(20000 * math.sin(2 * math.pi * 440 * i / framerate)) if i < 200 else 0 for i in range(count)]
    pcm16 = struct.pack(f"<{count}h", *samples)

    def tail_rms(decay: float) -> float:
        output = apply_reverb_pcm16(
            pcm16, 1, framerate, **dict(VALID_PARAMS, decay=decay, wet_dry_mix=1.0)
        )
        output_samples = struct.unpack(f"<{len(output)//2}h", output)
        tail = output_samples[int(0.9 * framerate) * 2 :]
        return math.sqrt(sum(v * v for v in tail) / len(tail))

    assert tail_rms(0.9) > tail_rms(0.1)


def test_rejects_empty_pcm16():
    with pytest.raises(ValueError):
        apply_reverb_pcm16(b"", 1, 24000, **VALID_PARAMS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reverb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.orchestrator.reverb'`

- [ ] **Step 3: Implement `reverb.py`**

Create `src/orchestrator/reverb.py`:

```python
from __future__ import annotations

import math
import struct

# Delay-line lengths and output-tap offsets, in seconds, exactly as published
# in Jon Dattorro's "Effect Design Part 1: Reverberator and Other Filters"
# (JAES, September 1997) and verified against khoin/DattorroReverbNode
# (https://github.com/khoin/DattorroReverbNode), a public-domain WebAudio port
# of the same algorithm. Indices 0-3 are the input diffusor chain, 4-7 are the
# left tank loop, 8-11 are the right tank loop.
_DELAY_LENGTHS_SECONDS = [
    0.004771345, 0.003595309, 0.012734787, 0.009307483,
    0.022579886, 0.149625349, 0.060481839, 0.1249958,
    0.030509727, 0.141695508, 0.089244313, 0.106280031,
]
_TAP_OFFSETS_SECONDS = [
    0.008937872, 0.099929438, 0.064278754, 0.067067639, 0.066866033,
    0.006283391, 0.035818689, 0.011861161, 0.121870905, 0.041262054,
    0.08981553, 0.070931756, 0.011256342, 0.004065724,
]


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
        raise ValueError(f"excursion_rate must be between 0 and 2, got {excursion_rate}")
    if not (0.0 <= excursion_depth <= 2.0):
        raise ValueError(
            f"excursion_depth must be between 0 and 2, got {excursion_depth}"
        )
    if not (0.0 <= wet_dry_mix <= 1.0):
        raise ValueError(f"wet_dry_mix must be between 0 and 1, got {wet_dry_mix}")


class _DelayLine:
    """Fixed-length circular buffer for one Dattorro delay line.

    Call peek()/peek_at()/peek_interp() to read this sample's "old" (i.e.
    pre-this-sample) values -- do this for everything this delay line's math
    needs BEFORE calling push(), since push() overwrites the slot peek() reads
    from. advance() must be called once per sample, after every delay line's
    push() for that sample, never in between.
    """

    def __init__(self, length: int) -> None:
        self.length = max(length, 1)
        self.buffer = [0.0] * self.length
        self.index = 0

    def peek(self) -> float:
        return self.buffer[self.index]

    def peek_at(self, offset: int) -> float:
        return self.buffer[(self.index + offset) % self.length]

    def peek_interp(self, offset: float) -> float:
        # 4-point cubic interpolation (O. Niemitalo, musicdsp.org "Other/49:
        # Cubic Interpollation"), used for the two modulated/excursion taps.
        base = math.floor(offset)
        frac = offset - base
        i0 = (self.index + base - 1) % self.length
        i1 = (self.index + base) % self.length
        i2 = (self.index + base + 1) % self.length
        i3 = (self.index + base + 2) % self.length
        x0, x1, x2, x3 = self.buffer[i0], self.buffer[i1], self.buffer[i2], self.buffer[i3]
        a = (3 * (x1 - x2) - x0 + x3) / 2
        b = 2 * x2 + x0 - (5 * x1 + x3) / 2
        c = (x2 - x0) / 2
        return ((a * frac + b) * frac + c) * frac + x1

    def push(self, value: float) -> None:
        self.buffer[self.index] = value

    def advance(self) -> None:
        self.index = (self.index + 1) % self.length


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
        pre_delay_ms, bandwidth, input_diffusion_1, input_diffusion_2, decay,
        decay_diffusion_1, decay_diffusion_2, damping, excursion_rate,
        excursion_depth, wet_dry_mix,
    )
    if len(pcm16) == 0:
        raise ValueError("pcm16 must not be empty.")

    sample_count = len(pcm16) // 2
    samples = list(struct.unpack(f"<{sample_count}h", pcm16[: sample_count * 2]))
    frame_count = sample_count // channels

    mono_input = []
    for frame_index in range(frame_count):
        base = frame_index * channels
        frame = samples[base : base + channels]
        mono_input.append((sum(frame) / channels) / 32768.0)

    delays = [_DelayLine(round(seconds * framerate)) for seconds in _DELAY_LENGTHS_SECONDS]
    tap_offsets = [round(seconds * framerate) for seconds in _TAP_OFFSETS_SECONDS]

    pre_delay_length = framerate + (128 - framerate % 128)
    pre_delay_buffer = [0.0] * pre_delay_length
    pre_delay_write = 0
    pre_delay_samples = round(pre_delay_ms / 1000.0 * framerate)

    lp1 = 0.0  # bandwidth filter state
    lp2 = 0.0  # left-loop damping filter state
    lp3 = 0.0  # right-loop damping filter state
    exc_phase = 0.0

    bw = bandwidth
    fi = input_diffusion_1
    si = input_diffusion_2
    dc = decay
    ft = decay_diffusion_1
    st = decay_diffusion_2
    dp = 1.0 - damping
    ex = excursion_rate / framerate
    ed = excursion_depth * framerate / 1000.0

    # Our single wet_dry_mix knob (0=dry, 1=fully wet) is a simplification of
    # the reference's two independent wet/dry gains; this formula reproduces
    # its exact default output level at wet_dry_mix=0.3 (dry_gain=0.7,
    # wet_gain=0.18) and is fully dry/fully wet at the extremes.
    dry_gain = 1.0 - wet_dry_mix
    wet_gain = wet_dry_mix * 0.6

    left_out = [0.0] * frame_count
    right_out = [0.0] * frame_count

    for i in range(frame_count):
        pre_delay_buffer[pre_delay_write] = mono_input[i]
        read_pos = (pre_delay_write - pre_delay_samples) % pre_delay_length
        predelayed = pre_delay_buffer[read_pos]
        pre_delay_write = (pre_delay_write + 1) % pre_delay_length

        lp1 += bw * (predelayed - lp1)

        # Input diffusor chain -- cache every "old" value up front, since
        # readDelay(i) in the reference always returns the pre-this-sample
        # value regardless of call order (see _DelayLine's docstring).
        old0 = delays[0].peek()
        old1 = delays[1].peek()
        old2 = delays[2].peek()
        old3 = delays[3].peek()

        new0 = lp1 - fi * old0
        pre = new0
        new1 = fi * (pre - old1) + old0
        pre = new1
        new2 = fi * pre + old1 - si * old2
        pre = new2
        new3 = si * (pre - old3) + old2
        split = si * new3 + old3

        delays[0].push(new0)
        delays[1].push(new1)
        delays[2].push(new2)
        delays[3].push(new3)

        exc = ed * (1 + math.cos(exc_phase * 6.2800))
        exc2 = ed * (1 + math.sin(exc_phase * 6.2847))

        old4_interp = delays[4].peek_interp(exc)
        old6 = delays[6].peek()
        old7 = delays[7].peek()
        old8_interp = delays[8].peek_interp(exc2)
        old10 = delays[10].peek()
        old11 = delays[11].peek()

        new4 = split + dc * old11 + ft * old4_interp
        new5 = old4_interp - ft * new4
        lp2 += dp * (delays[5].peek() - lp2)
        new6 = dc * lp2 - st * old6
        new7 = old6 + st * new6

        new8 = split + dc * old7 + ft * old8_interp
        new9 = old8_interp - ft * new8
        lp3 += dp * (delays[9].peek() - lp3)
        new10 = dc * lp3 - st * old10
        new11 = old10 + st * new10

        delays[4].push(new4)
        delays[5].push(new5)
        delays[6].push(new6)
        delays[7].push(new7)
        delays[8].push(new8)
        delays[9].push(new9)
        delays[10].push(new10)
        delays[11].push(new11)

        lo = (
            delays[9].peek_at(tap_offsets[0])
            + delays[9].peek_at(tap_offsets[1])
            - delays[10].peek_at(tap_offsets[2])
            + delays[11].peek_at(tap_offsets[3])
            - delays[5].peek_at(tap_offsets[4])
            - delays[6].peek_at(tap_offsets[5])
            - delays[7].peek_at(tap_offsets[6])
        )
        ro = (
            delays[5].peek_at(tap_offsets[7])
            + delays[5].peek_at(tap_offsets[8])
            - delays[6].peek_at(tap_offsets[9])
            + delays[7].peek_at(tap_offsets[10])
            - delays[9].peek_at(tap_offsets[11])
            - delays[10].peek_at(tap_offsets[12])
            - delays[11].peek_at(tap_offsets[13])
        )

        dry_sample = mono_input[i]
        left_out[i] = dry_sample * dry_gain + lo * wet_gain
        right_out[i] = dry_sample * dry_gain + ro * wet_gain

        exc_phase += ex
        for delay_line in delays:
            delay_line.advance()

    output = [0] * (frame_count * 2)
    for i in range(frame_count):
        output[i * 2] = max(-32768, min(32767, round(left_out[i] * 32768.0)))
        output[i * 2 + 1] = max(-32768, min(32767, round(right_out[i] * 32768.0)))

    return struct.pack(f"<{len(output)}h", *output)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reverb.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Lint and format check**

Run: `uv run ruff check src/orchestrator/reverb.py tests/test_reverb.py && uv run ruff format --check src/orchestrator/reverb.py tests/test_reverb.py`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/reverb.py tests/test_reverb.py
git commit -m "feat: add Dattorro plate reverb DSP core"
```

---

### Task 3: Reverb settings persistence

**Files:**
- Modify: `src/orchestrator/dialog_projects.py` (append after `save_combined_compressor_params`, the last function in the file)
- Test: `tests/test_dialog_projects.py` (append after the last test in the file)

**Interfaces:**
- Consumes: `_project_dir(project)`, `sanitize_name(chapter)` (already defined in this file)
- Produces: `save_box_reverb_params(project: str, chapter: str, box_index: int, params: dict) -> None` and `save_combined_reverb_params(project: str, chapter: str, params: dict) -> None`, consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dialog_projects.py`:

```python
def test_save_box_reverb_params_writes_to_chapter_json(project_dir):
    data = _read_chapter_json(project_dir)
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_dir / "TestProject" / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    params = {"decay": 0.8, "wet_dry_mix": 0.5}
    dialog_projects.save_box_reverb_params("TestProject", "Chapter1", 0, params)

    data_after = _read_chapter_json(project_dir)
    assert data_after["boxes"][0]["reverb_params"] == params


def test_save_combined_reverb_params_writes_to_chapter_json(project_dir):
    params = {"decay": 0.8, "wet_dry_mix": 0.5}
    dialog_projects.save_combined_reverb_params("TestProject", "Chapter1", params)

    data_after = _read_chapter_json(project_dir)
    assert data_after["combined_reverb_params"] == params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dialog_projects.py -v -k reverb_params`
Expected: FAIL with `AttributeError: module 'src.orchestrator.dialog_projects' has no attribute 'save_box_reverb_params'`

- [ ] **Step 3: Write the implementation**

Append to `src/orchestrator/dialog_projects.py`:

```python
def save_box_reverb_params(
    project: str, chapter: str, box_index: int, params: dict
) -> None:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    json_path = project_dir / f"{safe_chapter}.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        boxes = data.get("boxes", [])
        if box_index < len(boxes):
            boxes[box_index]["reverb_params"] = params
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def save_combined_reverb_params(project: str, chapter: str, params: dict) -> None:
    safe_chapter = sanitize_name(chapter)
    project_dir = _project_dir(project)
    json_path = project_dir / f"{safe_chapter}.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        data["combined_reverb_params"] = params
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dialog_projects.py -v -k reverb_params`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint and format check**

Run: `uv run ruff check src/orchestrator/dialog_projects.py && uv run ruff format --check src/orchestrator/dialog_projects.py`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/dialog_projects.py tests/test_dialog_projects.py
git commit -m "feat: add reverb params persistence functions to dialog_projects"
```

---

### Task 4: Reverb endpoints in `main.py`

**Files:**
- Modify: `src/orchestrator/main.py:1-16` (imports), `main.py:17-42` (`dialog_projects` import block), `main.py:61-84` (add `ReverbParams`/`_apply_reverb` near `CompressorParams`/`_apply_compressor`), `main.py` after line 419 (new endpoints, before `/combine`)
- Test: `tests/test_main.py` (append after the last test in the file)

**Interfaces:**
- Consumes: `apply_reverb_pcm16` (Task 2), `save_box_reverb_params`/`save_combined_reverb_params` (Task 3), `get_chapter_audio`/`get_combined_audio`/`add_box_variant`/`add_combined_variant` (already imported in `main.py`)
- Produces: 4 new routes, consumed by the frontend in Tasks 7-8:
  - `POST /projects/{project}/chapters/{chapter}/boxes/{box_index}/reverb/preview`
  - `POST /projects/{project}/chapters/{chapter}/boxes/{box_index}/reverb/apply`
  - `POST /projects/{project}/chapters/{chapter}/reverb/preview`
  - `POST /projects/{project}/chapters/{chapter}/reverb/apply`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
REVERB_PARAMS = {
    "pre_delay_ms": 0.0,
    "bandwidth": 0.9999,
    "input_diffusion_1": 0.75,
    "input_diffusion_2": 0.625,
    "decay": 0.5,
    "decay_diffusion_1": 0.7,
    "decay_diffusion_2": 0.5,
    "damping": 0.005,
    "excursion_rate": 0.5,
    "excursion_depth": 0.7,
    "wet_dry_mix": 0.3,
}


def test_box_reverb_preview_returns_stereo_wav_and_does_not_persist(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/reverb/preview",
        json=REVERB_PARAMS,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    data_after = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    assert "reverb_params" not in data_after["boxes"][0]


def test_box_reverb_apply_persists_new_stereo_variant_and_params(project_dir, client):
    project_path = project_dir / "TestProject"
    data = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    data["boxes"] = [{"text": "hi", "voice": None, "variants": [], "activeIndex": -1}]
    (project_path / "Chapter1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (project_path / "Chapter1_audio" / "box_0.wav").write_bytes(_make_wav(1000))

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/boxes/0/reverb/apply",
        json=REVERB_PARAMS,
    )

    assert response.status_code == 200
    filename = response.headers["x-variant-filename"]
    assert filename.endswith("_reverb.wav")
    data_after = json.loads((project_path / "Chapter1.json").read_text(encoding="utf-8"))
    assert data_after["boxes"][0]["reverb_params"] == REVERB_PARAMS
    assert data_after["boxes"][0]["variants"] == ["box_0_variant_original.wav", filename]


def test_combined_reverb_apply_persists_params(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    response = client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/apply", json=REVERB_PARAMS
    )

    assert response.status_code == 200
    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert data_after["combined_reverb_params"] == REVERB_PARAMS


def test_combined_reverb_preview_does_not_persist(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/preview", json=REVERB_PARAMS
    )

    data_after = json.loads(
        (project_dir / "TestProject" / "Chapter1.json").read_text(encoding="utf-8")
    )
    assert "combined_reverb_params" not in data_after


def test_reverb_invalid_decay_returns_400(project_dir, client):
    (project_dir / "TestProject" / "Chapter1_audio" / "combined.wav").write_bytes(
        _make_wav(1000)
    )

    bad_params = dict(REVERB_PARAMS, decay=1.5)
    response = client.post(
        "/projects/TestProject/chapters/Chapter1/reverb/preview", json=bad_params
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main.py -v -k reverb`
Expected: FAIL with 404s (routes don't exist yet)

- [ ] **Step 3: Write the implementation**

In `src/orchestrator/main.py`, add to the import block at the top (after `from .compressor import compress_pcm16` at line 16):

```python
from .reverb import apply_reverb_pcm16
```

Update the `dialog_projects` import block (lines 17-42) to also import the two new functions, keeping alphabetical order:

```python
from .dialog_projects import (
    activate_box_variant,
    activate_combined_variant,
    add_box_variant,
    add_combined_variant,
    build_combined_audio_zip,
    delete_box_variant,
    delete_chapter,
    delete_combined_variant,
    delete_inactive_variants,
    delete_project,
    get_chapter_audio,
    get_combined_audio,
    get_combined_variant_audio,
    get_variant_audio,
    list_chapters,
    list_chapters_with_audio,
    list_projects,
    load_chapter,
    rename_chapter,
    save_box_compressor_params,
    save_box_reverb_params,
    save_chapter,
    save_chapter_order,
    save_combined_compressor_params,
    save_combined_reverb_params,
)
```

Add a `ReverbParams` model and `_apply_reverb` helper right after `_apply_compressor` (after line 84, before `class ReorderChaptersRequest`):

```python
class ReverbParams(BaseModel):
    pre_delay_ms: float
    bandwidth: float
    input_diffusion_1: float
    input_diffusion_2: float
    decay: float
    decay_diffusion_1: float
    decay_diffusion_2: float
    damping: float
    excursion_rate: float
    excursion_depth: float
    wet_dry_mix: float


def _apply_reverb(path: Path, params: ReverbParams) -> bytes:
    data = path.read_bytes()
    channels, framerate, pcm16 = _read_wav_as_pcm16(data)

    reverberated_pcm16 = apply_reverb_pcm16(pcm16, channels, framerate, **params.model_dump())

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_out:
        wav_out.setnchannels(2)  # apply_reverb_pcm16 always outputs stereo
        wav_out.setsampwidth(2)
        wav_out.setframerate(framerate)
        wav_out.writeframes(reverberated_pcm16)
    return output.getvalue()
```

Add the four new endpoints right after `project_combined_compress_apply` (after line 419, before `@app.post("/combine")`):

```python
@app.post("/projects/{project}/chapters/{chapter}/boxes/{box_index}/reverb/preview")
def project_box_reverb_preview(
    project: str, chapter: str, box_index: int, params: ReverbParams
) -> Response:
    try:
        path = get_chapter_audio(project, chapter, box_index)
        reverberated = _apply_reverb(path, params)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=reverberated, media_type="audio/wav")


@app.post("/projects/{project}/chapters/{chapter}/boxes/{box_index}/reverb/apply")
def project_box_reverb_apply(
    project: str, chapter: str, box_index: int, params: ReverbParams
) -> Response:
    try:
        path = get_chapter_audio(project, chapter, box_index)
        reverberated = _apply_reverb(path, params)
        filename = add_box_variant(
            project, chapter, box_index, reverberated, suffix="reverb"
        )
        save_box_reverb_params(project, chapter, box_index, params.model_dump())
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=reverberated,
        media_type="audio/wav",
        headers={"X-Variant-Filename": filename},
    )


@app.post("/projects/{project}/chapters/{chapter}/reverb/preview")
def project_combined_reverb_preview(
    project: str, chapter: str, params: ReverbParams
) -> Response:
    try:
        path = get_combined_audio(project, chapter)
        reverberated = _apply_reverb(path, params)
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=reverberated, media_type="audio/wav")


@app.post("/projects/{project}/chapters/{chapter}/reverb/apply")
def project_combined_reverb_apply(
    project: str, chapter: str, params: ReverbParams
) -> Response:
    try:
        path = get_combined_audio(project, chapter)
        reverberated = _apply_reverb(path, params)
        filename = add_combined_variant(project, chapter, reverberated, suffix="reverb")
        save_combined_reverb_params(project, chapter, params.model_dump())
    except EngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=reverberated,
        media_type="audio/wav",
        headers={"X-Variant-Filename": filename},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main.py -v -k reverb`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full backend test suite**

Run: `uv run pytest -v && uv run ruff check && uv run ruff format --check`
Expected: all pass, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator/main.py tests/test_main.py
git commit -m "feat: add reverb preview/apply endpoints for boxes and combined audio"
```

---

### Task 5: Translation strings

**Files:**
- Modify: `src/orchestrator/static/js/i18n.js:86-97` (`de` block), `i18n.js:175-186` (`en` block)

**Interfaces:**
- Consumes: nothing
- Produces: new `t()` keys consumed by Task 6 (`openReverbOverlay`) and Task 7/8 (button labels).

- [ ] **Step 1: Add German strings**

In `src/orchestrator/static/js/i18n.js`, insert right after `compressorGainReduction: "Gain Reduction",` (line 96, still inside the `de` block, before its closing `},` at line 97):

```javascript
    reverbBtn: "Reverb",
    reverbNeedProject: "Bitte speichere oder lade zuerst ein Kapitel/Projekt, um Reverb zu nutzen.",
    reverbPreDelay: "Pre-Delay",
    reverbBandwidth: "Bandwidth",
    reverbInputDiffusion1: "Input Diffusion 1",
    reverbInputDiffusion2: "Input Diffusion 2",
    reverbDecay: "Decay",
    reverbDecayDiffusion1: "Decay Diffusion 1",
    reverbDecayDiffusion2: "Decay Diffusion 2",
    reverbDamping: "Damping",
    reverbExcursionRate: "Excursion Rate",
    reverbExcursionDepth: "Excursion Depth",
    reverbWetDryMix: "Wet/Dry",
```

- [ ] **Step 2: Add English strings**

Insert right after `compressorGainReduction: "Gain Reduction",` (line 185, still inside the `en` block, before its closing `},` at line 186):

```javascript
    reverbBtn: "Reverb",
    reverbNeedProject: "Please load or save a chapter/project first to use reverb.",
    reverbPreDelay: "Pre-Delay",
    reverbBandwidth: "Bandwidth",
    reverbInputDiffusion1: "Input Diffusion 1",
    reverbInputDiffusion2: "Input Diffusion 2",
    reverbDecay: "Decay",
    reverbDecayDiffusion1: "Decay Diffusion 1",
    reverbDecayDiffusion2: "Decay Diffusion 2",
    reverbDamping: "Damping",
    reverbExcursionRate: "Excursion Rate",
    reverbExcursionDepth: "Excursion Depth",
    reverbWetDryMix: "Wet/Dry",
```

- [ ] **Step 2: Verify syntax**

Run: `node --input-type=module --check < src/orchestrator/static/js/i18n.js`
Expected: no output (clean)

- [ ] **Step 3: Commit**

```bash
git add src/orchestrator/static/js/i18n.js
git commit -m "feat: add reverb translation strings"
```

---

### Task 6: Reverb button markup

**Files:**
- Modify: `src/orchestrator/static/index.html:109` (combined action row), `index.html:149` (box template)

**Interfaces:**
- Consumes: nothing
- Produces: `#combined-reverb-btn` and `.dialog-box-reverb-btn` elements, queried by Tasks 7 and 8.

- [ ] **Step 1: Add the combined-audio reverb button**

In `src/orchestrator/static/index.html`, right after the existing compressor button (line 109):

```html
            <button type="button" id="combined-compressor-btn" class="dialog-box-compressor-btn btn-compact" data-i18n="compressorBtn"></button>
            <button type="button" id="combined-reverb-btn" class="dialog-box-compressor-btn btn-compact" data-i18n="reverbBtn"></button>
```

(The `dialog-box-compressor-btn` class is a generic effect-button visual style, not compressor-specific despite the name — reused as-is, no new CSS class needed.)

- [ ] **Step 2: Add the per-box reverb button**

In the same file, inside `<template id="dialog-box-template">`, right after the existing box compressor button (line 149):

```html
          <button type="button" class="dialog-box-compressor-btn btn-compact" data-i18n="compressorBtn"></button>
          <button type="button" class="dialog-box-reverb-btn dialog-box-compressor-btn btn-compact" data-i18n="reverbBtn"></button>
```

- [ ] **Step 3: Manual check**

Start the server and confirm both new "Reverb" buttons render (Vorhören/Anwenden click handlers aren't wired yet until Tasks 7-8 — clicking them does nothing yet, that's expected at this point).

- [ ] **Step 4: Commit**

```bash
git add src/orchestrator/static/index.html
git commit -m "feat: add reverb button markup for boxes and combined audio"
```

---

### Task 7: `openReverbOverlay()` in `shared.js`

**Files:**
- Modify: `src/orchestrator/static/js/shared.js` (add new function; does not touch `openCompressorOverlay`)

**Interfaces:**
- Consumes: `t()` from `i18n.js` (already imported in this file)
- Produces: `openReverbOverlay({ t, previewUrl, applyUrl, onApplied, initialParams })`, consumed by Tasks 8 and 9. No live audio graph — "Vorhören" fetches a fully server-rendered preview and plays it back.

- [ ] **Step 1: Implement**

Add to `src/orchestrator/static/js/shared.js`, after `openCompressorOverlay` (after its closing `}` and the file's final line):

```javascript
export function openReverbOverlay({ t, previewUrl, applyUrl, onApplied, initialParams }) {
  const params = {
    pre_delay_ms: 0.0,
    bandwidth: 0.9999,
    input_diffusion_1: 0.75,
    input_diffusion_2: 0.625,
    decay: 0.5,
    decay_diffusion_1: 0.7,
    decay_diffusion_2: 0.5,
    damping: 0.005,
    excursion_rate: 0.5,
    excursion_depth: 0.7,
    wet_dry_mix: 0.3,
  };
  if (initialParams) {
    Object.assign(params, initialParams);
  }

  const backdrop = document.createElement("div");
  backdrop.className = "compressor-overlay-backdrop";

  const panel = document.createElement("div");
  panel.className = "compressor-overlay-panel";
  backdrop.appendChild(panel);

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "compressor-overlay-close-btn";
  closeBtn.textContent = "✕";
  panel.appendChild(closeBtn);

  const knobGrid = document.createElement("div");
  knobGrid.className = "compressor-stepper-grid";
  panel.appendChild(knobGrid);

  const knobDefs = [
    { key: "pre_delay_ms", label: t("reverbPreDelay"), step: 10, min: 0, max: 1000, unit: "ms", decimals: 0 },
    { key: "bandwidth", label: t("reverbBandwidth"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "input_diffusion_1", label: t("reverbInputDiffusion1"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "input_diffusion_2", label: t("reverbInputDiffusion2"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "decay", label: t("reverbDecay"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "decay_diffusion_1", label: t("reverbDecayDiffusion1"), step: 0.01, min: 0, max: 0.99, unit: "", decimals: 2 },
    { key: "decay_diffusion_2", label: t("reverbDecayDiffusion2"), step: 0.01, min: 0, max: 0.99, unit: "", decimals: 2 },
    { key: "damping", label: t("reverbDamping"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
    { key: "excursion_rate", label: t("reverbExcursionRate"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    { key: "excursion_depth", label: t("reverbExcursionDepth"), step: 0.1, min: 0, max: 2, unit: "", decimals: 1 },
    { key: "wet_dry_mix", label: t("reverbWetDryMix"), step: 0.01, min: 0, max: 1, unit: "", decimals: 2 },
  ];

  const KNOB_DRAG_RANGE_PX = 150;

  for (const def of knobDefs) {
    const unit = document.createElement("div");
    unit.className = "compressor-knob-unit";

    const label = document.createElement("div");
    label.className = "compressor-stepper-label";
    label.textContent = def.label;
    unit.appendChild(label);

    const knob = document.createElement("div");
    knob.className = "compressor-knob";
    knob.tabIndex = 0;

    const pointer = document.createElement("div");
    pointer.className = "compressor-knob-pointer";
    knob.appendChild(pointer);
    unit.appendChild(knob);

    const valueSpan = document.createElement("span");
    valueSpan.className = "compressor-stepper-value";
    unit.appendChild(valueSpan);

    function angleForValue(value) {
      const fraction = (value - def.min) / (def.max - def.min);
      return -135 + fraction * 270;
    }

    function refreshValue() {
      valueSpan.textContent = params[def.key].toFixed(def.decimals) + def.unit;
      pointer.style.transform = `translateX(-50%) rotate(${angleForValue(params[def.key])}deg)`;
    }
    refreshValue();

    function setValue(newValue) {
      const clamped = Math.max(def.min, Math.min(def.max, newValue));
      const snapped = Math.round(clamped / def.step) * def.step;
      params[def.key] = Math.round(snapped * 1000) / 1000;
      refreshValue();
    }

    let dragStartY = 0;
    let dragStartValue = 0;

    knob.addEventListener("pointerdown", (event) => {
      knob.setPointerCapture(event.pointerId);
      knob.classList.add("dragging");
      dragStartY = event.clientY;
      dragStartValue = params[def.key];
      event.preventDefault();
    });

    knob.addEventListener("pointermove", (event) => {
      if (!knob.classList.contains("dragging")) return;
      const deltaY = dragStartY - event.clientY;
      const fraction = deltaY / KNOB_DRAG_RANGE_PX;
      setValue(dragStartValue + fraction * (def.max - def.min));
    });

    function endDrag(event) {
      if (knob.classList.contains("dragging")) {
        knob.classList.remove("dragging");
        knob.releasePointerCapture(event.pointerId);
      }
    }
    knob.addEventListener("pointerup", endDrag);
    knob.addEventListener("pointercancel", endDrag);

    knob.addEventListener("keydown", (event) => {
      if (event.key === "ArrowUp" || event.key === "ArrowRight") {
        event.preventDefault();
        setValue(params[def.key] + def.step);
      } else if (event.key === "ArrowDown" || event.key === "ArrowLeft") {
        event.preventDefault();
        setValue(params[def.key] - def.step);
      }
    });

    knobGrid.appendChild(unit);
  }

  const actionsRow = document.createElement("div");
  actionsRow.className = "compressor-actions-row";

  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.className = "compressor-preview-btn";
  previewBtn.textContent = t("compressorPreview");

  const previewPlayer = document.createElement("audio");
  previewPlayer.controls = true;
  previewPlayer.className = "compressor-preview-player";
  previewPlayer.hidden = true;

  const applyBtn = document.createElement("button");
  applyBtn.type = "button";
  applyBtn.className = "compressor-apply-btn";
  applyBtn.textContent = t("compressorApply");

  function closeOverlay() {
    if (previewPlayer.src) {
      URL.revokeObjectURL(previewPlayer.src);
    }
    backdrop.remove();
  }

  closeBtn.addEventListener("click", closeOverlay);

  previewBtn.addEventListener("click", async () => {
    previewBtn.disabled = true;
    applyBtn.disabled = true;
    try {
      const response = await fetch(previewUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (response.ok) {
        const blob = await response.blob();
        if (previewPlayer.src) URL.revokeObjectURL(previewPlayer.src);
        previewPlayer.src = URL.createObjectURL(blob);
        previewPlayer.hidden = false;
        previewPlayer.play();
      }
    } finally {
      previewBtn.disabled = false;
      applyBtn.disabled = false;
    }
  });

  applyBtn.addEventListener("click", async () => {
    previewBtn.disabled = true;
    applyBtn.disabled = true;
    try {
      const response = await fetch(applyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (response.ok) {
        closeOverlay();
        await onApplied(response);
      }
    } finally {
      previewBtn.disabled = false;
      applyBtn.disabled = false;
    }
  });

  actionsRow.appendChild(previewBtn);
  actionsRow.appendChild(previewPlayer);
  actionsRow.appendChild(applyBtn);
  panel.appendChild(actionsRow);

  document.body.appendChild(backdrop);
}
```

- [ ] **Step 2: Verify syntax**

Run: `node --input-type=module --check < src/orchestrator/static/js/shared.js`
Expected: no output (clean)

- [ ] **Step 3: Commit**

```bash
git add src/orchestrator/static/js/shared.js
git commit -m "feat: add render-based reverb overlay (openReverbOverlay)"
```

---

### Task 8: Box-level reverb wiring

**Files:**
- Modify: `src/orchestrator/static/js/dialog-boxes.js:1-17` (imports), `dialog-boxes.js:113-118` (`setLoadedBoxVariants`, if not already updated — check current state first, since Plan 044 already added a `compressorParams` field here), `dialog-boxes.js:358-476` (`addDialogBox`: add `reverbBtn` query, initial hydration, click handler)

**Interfaces:**
- Consumes: `openReverbOverlay` (Task 7), `getBoxCompressorParams`-style pattern (already established by Plan 044) — add an analogous `getBoxReverbParams(box)`.
- Produces: nothing new for other modules.

- [ ] **Step 1: Read the current file to confirm exact line numbers**

Since Plan 044 already modified this file, read `src/orchestrator/static/js/dialog-boxes.js` in full before editing — the `boxAudioBlobs` WeakMap entry already has a `compressorParams` field (from Plan 044); this task adds a sibling `reverbParams` field the same way.

- [ ] **Step 2: Implement**

Update the import from `./shared.js` to include `openReverbOverlay`:

```javascript
import {
  attachWaveform,
  measureLoudnessDb,
  openCompressorOverlay,
  openReverbOverlay,
  voiceAccentColor,
} from "./shared.js";
```

Update `setLoadedBoxVariants` to also carry `reverbParams`, and add a getter right after it:

```javascript
export function setLoadedBoxVariants(box, variants, activeIndex, compressorParams, reverbParams) {
  boxAudioBlobs.set(box, {
    variants: (variants || []).map((f) => ({ blob: null, filename: f })),
    activeIndex: activeIndex !== undefined ? activeIndex : -1,
    compressorParams: compressorParams || null,
    reverbParams: reverbParams || null,
  });
}

export function getBoxReverbParams(box) {
  return boxAudioBlobs.get(box)?.reverbParams || null;
}
```

Update both existing call sites of `setLoadedBoxVariants` to pass the box's `reverb_params` as the 5th argument — the initial-load site (inside `addDialogBox`, `if (initial.variants) { ... }`):

```javascript
  if (initial.variants) {
    setLoadedBoxVariants(box, initial.variants, initial.activeIndex, initial.compressor_params, initial.reverb_params);
    renderVariantsList(box);
  }
```

And the compressor's `onApplied` re-fetch site (this file already has this from Plan 044 — extend its `setLoadedBoxVariants` call the same way):

```javascript
          setLoadedBoxVariants(box, boxData.variants, boxData.activeIndex, boxData.compressor_params, boxData.reverb_params);
```

In `addDialogBox`, add a `reverbBtn` query right after the existing `compressorBtn` query:

```javascript
  const compressorBtn = box.querySelector(".dialog-box-compressor-btn");
  const reverbBtn = box.querySelector(".dialog-box-reverb-btn");
```

Add a new click handler right after the existing `compressorBtn.addEventListener(...)` block:

```javascript
  reverbBtn.addEventListener("click", () => {
    if (!getCurrentProject() || !getCurrentChapterName()) {
      alert(t("reverbNeedProject"));
      return;
    }
    const boxes = Array.from(dialogBoxesContainer.querySelectorAll(".dialog-box"));
    const boxIndex = boxes.indexOf(box);

    openReverbOverlay({
      t,
      previewUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/reverb/preview`,
      applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/boxes/${boxIndex}/reverb/apply`,
      initialParams: getBoxReverbParams(box),
      onApplied: async (applyResponse) => {
        const response = await fetch(
          `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}`
        );
        if (response.ok) {
          const data = await response.json();
          const boxData = data.boxes[boxIndex];
          setLoadedBoxVariants(box, boxData.variants, boxData.activeIndex, boxData.compressor_params, boxData.reverb_params);

          if (applyResponse) {
            const blob = await applyResponse.blob();
            setLoadedBoxBlob(box, blob);

            const player = box.querySelector(".dialog-box-player");
            const downloadLink = box.querySelector(".dialog-box-download");
            if (player.src) {
              URL.revokeObjectURL(player.src);
            }
            player.src = URL.createObjectURL(blob);
            downloadLink.href = player.src;
            downloadLink.download = `fishaudio_box_${Date.now()}.wav`;
            downloadLink.hidden = false;
            updateLoudnessLabel(box, blob);
          }

          renderVariantsList(box);
          saveDialogDraft();
        }
      },
    });
  });
```

- [ ] **Step 3: Verify syntax**

Run: `node --input-type=module --check < src/orchestrator/static/js/dialog-boxes.js`
Expected: no output (clean)

- [ ] **Step 4: Commit**

```bash
git add src/orchestrator/static/js/dialog-boxes.js
git commit -m "feat: wire up per-box reverb button"
```

---

### Task 9: Combined-audio reverb wiring

**Files:**
- Modify: `src/orchestrator/static/js/dialog-combined.js:1-13` (imports/element lookup), `dialog-combined.js:171-194` (combined compressor click handler area — add a sibling handler for reverb)

**Interfaces:**
- Consumes: `openReverbOverlay` (Task 7)
- Produces: nothing new for other modules

- [ ] **Step 1: Read the current file to confirm exact line numbers**

Read `src/orchestrator/static/js/dialog-combined.js` in full before editing — Plan 044 already made `combinedCompressorBtn`'s click handler `async` and added a chapter-data fetch for `initialParams`; mirror that exact pattern for reverb.

- [ ] **Step 2: Implement**

Update the import from `./shared.js`:

```javascript
import { attachWaveform, openCompressorOverlay, openReverbOverlay } from "./shared.js";
```

Add an element lookup right after `combinedCompressorBtn`'s:

```javascript
const combinedCompressorBtn = document.getElementById("combined-compressor-btn");
const combinedReverbBtn = document.getElementById("combined-reverb-btn");
```

Add a new click handler right after the existing `combinedCompressorBtn.addEventListener(...)` block:

```javascript
combinedReverbBtn.addEventListener("click", async () => {
  if (!getCurrentProject() || !getCurrentChapterName()) {
    alert(t("reverbNeedProject"));
    return;
  }
  let initialParams = null;
  const response = await fetch(
    `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}`
  );
  if (response.ok) {
    const data = await response.json();
    initialParams = data.combined_reverb_params || null;
  }
  openReverbOverlay({
    t,
    previewUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/reverb/preview`,
    applyUrl: `/projects/${encodeURIComponent(getCurrentProject())}/chapters/${encodeURIComponent(getCurrentChapterName())}/reverb/apply`,
    initialParams,
    onApplied: refreshCombinedVariantsList,
  });
});
```

- [ ] **Step 3: Verify syntax**

Run: `node --input-type=module --check < src/orchestrator/static/js/dialog-combined.js`
Expected: no output (clean)

- [ ] **Step 4: Commit**

```bash
git add src/orchestrator/static/js/dialog-combined.js
git commit -m "feat: wire up combined-audio reverb button"
```

---

### Task 10: Manual end-to-end verification

**Files:** none (verification only)

**Interfaces:**
- Consumes: the complete feature from Tasks 1-9
- Produces: nothing — this is the acceptance check before the plan is considered done

- [ ] **Step 1: Run the full automated test suite one more time**

Run: `uv run pytest -v && uv run ruff check && uv run ruff format --check`
Expected: all pass

- [ ] **Step 2: Manual browser check — box-level reverb**

1. Start the server, open a project/chapter with at least one generated box.
2. Click that box's "Reverb" button. Confirm the overlay opens with 11 knobs at their default positions (Decay=0.50, Damping=0.01, etc.).
3. Drag a few knobs (e.g. Decay up, Wet/Dry up), click "Vorhören" — confirm it renders and plays back a noticeably reverberant version of the box's audio.
4. Click "Anwenden" — confirm the overlay closes, a new variant appears, and the box's player now plays stereo reverberated audio.
5. Reload the page, reopen the same box's reverb overlay — confirm the knobs show the values from step 3, not the defaults.

- [ ] **Step 3: Manual browser check — mixed mono/stereo recombine**

1. In a chapter with at least 2 boxes, apply reverb to only one box (making it stereo) — leave the other box(es) untouched (mono).
2. Click "Neu kombinieren" (recombine) — confirm it succeeds without error and produces a combined stereo file (previously this would have raised a channel-mismatch error).

- [ ] **Step 4: Manual browser check — combined-level reverb**

1. Click the combined-audio "Reverb" button, adjust knobs, "Vorhören", then "Anwenden".
2. Reload the page, reopen the combined reverb overlay — confirm saved values persisted.

- [ ] **Step 5: Manual browser check — untouched box still shows defaults**

1. Open a different box that has never had reverb applied — confirm its knobs still show the fixed defaults (no cross-box inheritance).
