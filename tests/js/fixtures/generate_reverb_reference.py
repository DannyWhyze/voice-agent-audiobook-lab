"""One-off script: regenerate tests/js/fixtures/reverb_tank_reference.json.

Only needs to be re-run if audio/reverb.py's _run_tank algorithm or the
_DELAY_LENGTHS_SECONDS/_TAP_OFFSETS_SECONDS constants ever change. Not part
of any automated test run -- the committed JSON output is the actual fixture
tests/js/test_reverb_tank.mjs reads.

Run: .venv/Scripts/python.exe tests/js/fixtures/generate_reverb_reference.py
"""

import json
from pathlib import Path

import numpy as np

from src.orchestrator.audio.reverb import (
    _DELAY_LENGTHS_SECONDS,
    _TAP_OFFSETS_SECONDS,
    _run_tank,
)

FRAMERATE = 44100
DURATION_SECONDS = 0.5


def make_test_signal(framerate, duration_seconds):
    n = round(framerate * duration_seconds)
    t = np.arange(n) / framerate
    signal = (
        0.3 * np.sin(2 * np.pi * 220 * t)
        + 0.2 * np.sin(2 * np.pi * 1000 * t)
        + 0.1 * np.sin(2 * np.pi * 4000 * t)
    )
    return signal.astype(np.float64)


PARAMS = {
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


def main():
    mono_input = make_test_signal(FRAMERATE, DURATION_SECONDS)

    delay_lengths = np.array(
        [max(round(seconds * FRAMERATE), 1) for seconds in _DELAY_LENGTHS_SECONDS],
        dtype=np.int64,
    )
    max_delay_length = int(delay_lengths.max())
    delay_buffers = np.zeros((12, max_delay_length), dtype=np.float64)
    delay_indices = np.zeros(12, dtype=np.int64)
    tap_offsets = np.array(
        [round(seconds * FRAMERATE) for seconds in _TAP_OFFSETS_SECONDS], dtype=np.int64
    )

    pre_delay_length = FRAMERATE + (128 - FRAMERATE % 128)
    pre_delay_buffer = np.zeros(pre_delay_length, dtype=np.float64)
    pre_delay_samples = round(PARAMS["pre_delay_ms"] / 1000.0 * FRAMERATE)

    dp = 1.0 - PARAMS["damping"]
    ex = PARAMS["excursion_rate"] / FRAMERATE
    ed = PARAMS["excursion_depth"] * FRAMERATE / 1000.0
    dry_gain = 1.0 - PARAMS["wet_dry_mix"]
    wet_gain = PARAMS["wet_dry_mix"] * 0.6

    left_out, right_out = _run_tank(
        mono_input,
        delay_buffers,
        delay_lengths,
        delay_indices,
        tap_offsets,
        pre_delay_buffer,
        pre_delay_length,
        pre_delay_samples,
        PARAMS["bandwidth"],
        PARAMS["input_diffusion_1"],
        PARAMS["input_diffusion_2"],
        PARAMS["decay"],
        PARAMS["decay_diffusion_1"],
        PARAMS["decay_diffusion_2"],
        dp,
        ex,
        ed,
        dry_gain,
        wet_gain,
    )

    out_path = Path(__file__).parent / "reverb_tank_reference.json"
    out_path.write_text(
        json.dumps(
            {
                "framerate": FRAMERATE,
                "duration_seconds": DURATION_SECONDS,
                "params": PARAMS,
                "left_out": left_out.tolist(),
                "right_out": right_out.tolist(),
            }
        )
    )
    print(f"Wrote {out_path} ({len(left_out)} samples/channel)")


if __name__ == "__main__":
    main()
