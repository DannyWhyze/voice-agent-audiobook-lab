# Formant Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time Web Audio live preview to `overlays/formant-overlay.js`, the last effect still on the render-based "Vorhören"-then-play flow (Delay/Reverb/Compressor/Pitch already have it). See `docs/superpowers/specs/2026-08-09-formant-live-preview-design.md` for the full design rationale, including why this uses LPC-based envelope warping rather than a 1:1 port of the backend's `pyworld`/WORLD pipeline.

**Architecture:** New standalone module `static/js/dsp/formant-shifter.js` — the same hand-written radix-2 FFT used in `pitch-shifter.js`, plus a `FormantShifter` class: per-frame LPC analysis (autocorrelation + Levinson-Durbin) estimates the spectral envelope (formants), the envelope is warped along the frequency axis, and the spectrum is re-colored with the warped envelope while the original phase is left untouched (so pitch never moves). One `FormantShifter` instance per audio channel, wired into `formant-overlay.js` via the same `ScriptProcessorNode` lifecycle Pitch/Delay/Reverb already use. Does **not** touch `audio/formant.py`, `pyworld`, or any backend route.

**Tech Stack:** Vanilla JS, Web Audio API (`ScriptProcessorNode`), no new dependencies.

## Global Constraints

- Live preview is **not** expected to be bit-identical to `/formant/apply`'s server-rendered `pyworld` result (different algorithm — LPC envelope warping vs. WORLD's DIO/CheapTrick/D4C). It should be representative in direction/character: formants move, pitch stays put.
- No JS test framework in this project — verification is `node --input-type=module --check`, the permanent Node test written in Task 2, and manual browser listening tests (Task 4).
- `fftFrameSize = 2048`, `oversample = 4` (hop = 512 samples) are fixed internal constants, same as `pitch-shifter.js`, not user-facing knobs.
- `lpcOrder` defaults to `Math.round(2 + framerate / 1000)` (Makhoul's rule of thumb) unless overridden — not user-facing.
- The Overlap-Add gain constant (`4 / oversample`) is carried over from `pitch-shifter.js` but is **not** pre-verified for this algorithm — Task 2's automated test includes an explicit unity-ratio gain check specifically because of this (see spec).
- `tests/js/test_formant_shifter.mjs` is a permanent file, run manually (`node tests/js/test_formant_shifter.mjs`) — **not** wired into any automated/routine verify chain, same decision as `tests/js/test_pitch_shifter.mjs`.

---

### Task 1: FFT + LPC formant shifter module

**Files:**
- Create: `static/js/dsp/formant-shifter.js`

**Interfaces:**
- Consumes: nothing (self-contained DSP module, no imports)
- Produces: `export class FormantShifter { constructor(framerate, fftFrameSize, oversample, lpcOrder); setFormantRatio(ratio); process(inputSamples, outputSamples); }`, consumed by Task 2 and Task 3.

- [ ] **Step 1: Create the module with the FFT**

Create `static/js/dsp/formant-shifter.js`. Same textbook iterative radix-2 Cooley-Tukey FFT already used in `static/js/dsp/pitch-shifter.js` (no licensing concern, same category as the cubic-interpolation formula in `reverb.py`/`delay.py`):

```javascript
function fft(real, imag, invert) {
  const n = real.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) {
      j ^= bit;
    }
    j ^= bit;
    if (i < j) {
      [real[i], real[j]] = [real[j], real[i]];
      [imag[i], imag[j]] = [imag[j], imag[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (invert ? 1 : -1) * ((2 * Math.PI) / len);
    const wRe = Math.cos(ang);
    const wIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curRe = 1;
      let curIm = 0;
      const half = len / 2;
      for (let j = 0; j < half; j++) {
        const uRe = real[i + j];
        const uIm = imag[i + j];
        const vRe = real[i + j + half] * curRe - imag[i + j + half] * curIm;
        const vIm = real[i + j + half] * curIm + imag[i + j + half] * curRe;
        real[i + j] = uRe + vRe;
        imag[i + j] = uIm + vIm;
        real[i + j + half] = uRe - vRe;
        imag[i + j + half] = uIm - vIm;
        const nextRe = curRe * wRe - curIm * wIm;
        const nextIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
        curIm = nextIm;
      }
    }
  }
  if (invert) {
    for (let i = 0; i < n; i++) {
      real[i] /= n;
      imag[i] /= n;
    }
  }
}
```

- [ ] **Step 2: Implement `FormantShifter` construction, FIFO, and LPC analysis**

Append to the same file:

```javascript
const TWO_PI = 2 * Math.PI;

export class FormantShifter {
  constructor(framerate, fftFrameSize = 2048, oversample = 4, lpcOrder) {
    this.fftFrameSize = fftFrameSize;
    this.oversample = oversample;
    this.stepSize = fftFrameSize / oversample;
    this.inFifoLatency = fftFrameSize - this.stepSize;
    this.lpcOrder = lpcOrder || Math.round(2 + framerate / 1000);
    this.formantRatio = 1.0;

    this.inFifo = new Float64Array(fftFrameSize);
    this.outFifo = new Float64Array(fftFrameSize);
    this.outputAccum = new Float64Array(fftFrameSize * 2);
    this.fftReal = new Float64Array(fftFrameSize);
    this.fftImag = new Float64Array(fftFrameSize);
    this.windowed = new Float64Array(fftFrameSize);

    const halfPlusOne = fftFrameSize / 2 + 1;
    this.magnitude = new Float64Array(halfPlusOne);
    this.phase = new Float64Array(halfPlusOne);
    this.envelope = new Float64Array(halfPlusOne);
    this.warpedEnvelope = new Float64Array(halfPlusOne);

    this.autocorr = new Float64Array(this.lpcOrder + 1);
    this.lpcCoeffs = new Float64Array(this.lpcOrder + 1);
    this.lpcCoeffsTmp = new Float64Array(this.lpcOrder + 1);

    this.rover = this.inFifoLatency;
  }

  setFormantRatio(ratio) {
    this.formantRatio = ratio;
  }

  process(inputSamples, outputSamples) {
    const n = inputSamples.length;
    for (let i = 0; i < n; i++) {
      this.inFifo[this.rover] = inputSamples[i];
      outputSamples[i] = this.outFifo[this.rover - this.inFifoLatency];
      this.rover++;

      if (this.rover >= this.fftFrameSize) {
        this.rover = this.inFifoLatency;
        this._processFrame();
      }
    }
  }

  // Autocorrelation of the windowed frame, then Levinson-Durbin recursion.
  // Returns false (caller falls back to a flat envelope) if the frame is
  // silent or the recursion goes numerically unstable -- both are normal
  // for near-silent audio, not bugs.
  _computeLpc() {
    const order = this.lpcOrder;
    const windowed = this.windowed;
    const n = windowed.length;
    const r = this.autocorr;

    for (let lag = 0; lag <= order; lag++) {
      let sum = 0;
      for (let i = 0; i < n - lag; i++) {
        sum += windowed[i] * windowed[i + lag];
      }
      r[lag] = sum;
    }

    const a = this.lpcCoeffs;
    const tmp = this.lpcCoeffsTmp;
    a.fill(0);

    if (r[0] < 1e-9) {
      return false;
    }

    let error = r[0];
    for (let i = 1; i <= order; i++) {
      let acc = r[i];
      for (let j = 1; j < i; j++) {
        acc -= a[j] * r[i - j];
      }
      const k = acc / error;

      for (let j = 1; j < i; j++) {
        tmp[j] = a[j] - k * a[i - j];
      }
      for (let j = 1; j < i; j++) {
        a[j] = tmp[j];
      }
      a[i] = k;

      error *= 1 - k * k;
      if (error <= 0) {
        return false;
      }
    }
    return true;
  }

  // Frequency response of the LPC all-pole filter A(z) = 1 - sum(a_j * z^-j)
  // at each FFT bin; the envelope is 1/|A(w)| (the resonance peaks of the
  // all-pole model are the formants).
  _computeEnvelope() {
    const order = this.lpcOrder;
    const a = this.lpcCoeffs;
    const n = this.fftFrameSize;
    const half = n / 2;
    const envelope = this.envelope;

    for (let k = 0; k <= half; k++) {
      const w = (TWO_PI * k) / n;
      let re = 1;
      let im = 0;
      for (let j = 1; j <= order; j++) {
        re -= a[j] * Math.cos(w * j);
        im += a[j] * Math.sin(w * j);
      }
      const magA = Math.sqrt(re * re + im * im);
      envelope[k] = magA > 1e-9 ? 1 / magA : 1;
    }
  }

  // Same clamp-to-edge linear interpolation as `_warp_envelope` in
  // audio/formant.py: bin k of the warped envelope samples the original
  // envelope at k/ratio.
  _warpEnvelope() {
    const half = this.fftFrameSize / 2;
    const ratio = this.formantRatio;
    const envelope = this.envelope;
    const warped = this.warpedEnvelope;

    for (let k = 0; k <= half; k++) {
      const query = k / ratio;
      if (query <= 0) {
        warped[k] = envelope[0];
      } else if (query >= half) {
        warped[k] = envelope[half];
      } else {
        const lo = Math.floor(query);
        const hi = lo + 1;
        const frac = query - lo;
        warped[k] = envelope[lo] * (1 - frac) + envelope[hi] * frac;
      }
    }
  }
```

- [ ] **Step 3: Implement `_processFrame` (analysis, envelope warp, synthesis)**

Append inside the same class, right after `_warpEnvelope`:

```javascript
  _processFrame() {
    const fftFrameSize = this.fftFrameSize;
    const half = fftFrameSize / 2;

    for (let k = 0; k < fftFrameSize; k++) {
      const window = -0.5 * Math.cos((TWO_PI * k) / fftFrameSize) + 0.5;
      this.windowed[k] = this.inFifo[k] * window;
      this.fftReal[k] = this.windowed[k];
      this.fftImag[k] = 0;
    }

    fft(this.fftReal, this.fftImag, false);

    for (let k = 0; k <= half; k++) {
      const re = this.fftReal[k];
      const im = this.fftImag[k];
      this.magnitude[k] = Math.sqrt(re * re + im * im);
      this.phase[k] = Math.atan2(im, re);
    }

    const lpcOk = this._computeLpc();
    if (lpcOk) {
      this._computeEnvelope();
      this._warpEnvelope();
    } else {
      this.envelope.fill(1);
      this.warpedEnvelope.fill(1);
    }

    // Whiten by the original envelope, re-color with the warped one. Phase
    // is copied straight from analysis -- untouched -- which is what keeps
    // F0 structurally stable (no phase-vocoder tracking needed here, unlike
    // pitch-shifter.js).
    for (let k = 0; k <= half; k++) {
      const envAtK = this.envelope[k] > 1e-9 ? this.envelope[k] : 1e-9;
      const residual = this.magnitude[k] / envAtK;
      const newMagn = residual * this.warpedEnvelope[k];
      this.fftReal[k] = newMagn * Math.cos(this.phase[k]);
      this.fftImag[k] = newMagn * Math.sin(this.phase[k]);
    }
    for (let k = half + 1; k < fftFrameSize; k++) {
      this.fftReal[k] = this.fftReal[fftFrameSize - k];
      this.fftImag[k] = -this.fftImag[fftFrameSize - k];
    }

    fft(this.fftReal, this.fftImag, true);

    // Overlap-add gain: carried over from pitch-shifter.js's derivation for
    // the same window/hop/oversample combination. NEEDS EMPIRICAL
    // VERIFICATION for this algorithm specifically -- see Task 2's
    // unity-ratio gain check.
    const gain = 4 / this.oversample;
    for (let k = 0; k < fftFrameSize; k++) {
      const window = -0.5 * Math.cos((TWO_PI * k) / fftFrameSize) + 0.5;
      this.outputAccum[k] += window * this.fftReal[k] * gain;
    }

    for (let k = 0; k < this.stepSize; k++) {
      this.outFifo[k] = this.outputAccum[k];
    }
    this.outputAccum.copyWithin(0, this.stepSize, this.stepSize + fftFrameSize);
    for (let k = fftFrameSize; k < fftFrameSize + this.stepSize; k++) {
      this.outputAccum[k] = 0;
    }
    for (let k = 0; k < this.inFifoLatency; k++) {
      this.inFifo[k] = this.inFifo[k + this.stepSize];
    }
  }
}
```

- [ ] **Step 4: Verify syntax**

Run: `node --input-type=module --check < static/js/dsp/formant-shifter.js`
Expected: no output (clean)

- [ ] **Step 5: Commit**

```bash
git add static/js/dsp/formant-shifter.js
git commit -m "feat: add a real-time LPC-based formant shifter"
```

---

### Task 2: Permanent Node regression test

**Files:**
- Create: `tests/js/test_formant_shifter.mjs`

**Interfaces:**
- Consumes: `FormantShifter` (Task 1)
- Produces: nothing consumed elsewhere; this is the correctness gate for Task 1's algorithm before it gets wired into the browser.

- [ ] **Step 1: Write the test**

Create `tests/js/test_formant_shifter.mjs`:

```javascript
// Plain Node.js check for static/js/dsp/formant-shifter.js -- no test framework,
// run manually with: node tests/js/test_formant_shifter.mjs
//
// Mirrors tests/test_formant.py on the Python side: the core promise of formant
// shifting is that F0 (pitch) stays put while the spectral envelope (formants,
// perceived timbre) moves. A synthetic tone with multiple harmonics has both an
// F0 and an envelope "shape" to check.

import assert from "node:assert/strict";
import { FormantShifter } from "../../static/js/dsp/formant-shifter.js";

const FRAMERATE = 44100;
const F0 = 150;
const HARMONICS = 8;
const F0_TOLERANCE = 0.05;

function fft(real, imag, invert) {
  const n = real.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) {
      j ^= bit;
    }
    j ^= bit;
    if (i < j) {
      [real[i], real[j]] = [real[j], real[i]];
      [imag[i], imag[j]] = [imag[j], imag[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (invert ? 1 : -1) * ((2 * Math.PI) / len);
    const wRe = Math.cos(ang);
    const wIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curRe = 1;
      let curIm = 0;
      const half = len / 2;
      for (let j = 0; j < half; j++) {
        const uRe = real[i + j];
        const uIm = imag[i + j];
        const vRe = real[i + j + half] * curRe - imag[i + j + half] * curIm;
        const vIm = real[i + j + half] * curIm + imag[i + j + half] * curRe;
        real[i + j] = uRe + vRe;
        imag[i + j] = uIm + vIm;
        real[i + j + half] = uRe - vRe;
        imag[i + j + half] = uIm - vIm;
        const nextRe = curRe * wRe - curIm * wIm;
        const nextIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
        curIm = nextIm;
      }
    }
  }
  if (invert) {
    for (let i = 0; i < n; i++) {
      real[i] /= n;
      imag[i] /= n;
    }
  }
}

function makeHarmonicTone(f0, harmonics, seconds, framerate) {
  const n = Math.round(framerate * seconds);
  const buf = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sample = 0;
    for (let h = 1; h <= harmonics; h++) {
      sample += (1 / h) * Math.sin((2 * Math.PI * f0 * h * i) / framerate);
    }
    buf[i] = sample;
  }
  const peak = Math.max(...Array.from(buf, Math.abs));
  for (let i = 0; i < n; i++) {
    buf[i] = (buf[i] / peak) * 0.5;
  }
  return buf;
}

function estimateFreqAutocorr(signal, skip, framerate, minFreq, maxFreq) {
  const window = Math.min(8192, signal.length - skip);
  const tail = Array.from(signal.slice(skip, skip + window));
  const minLag = Math.floor(framerate / maxFreq);
  const maxLag = Math.ceil(framerate / minFreq);
  let bestLag = minLag;
  let bestCorr = -Infinity;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let sum = 0;
    for (let i = 0; i < tail.length - lag; i++) {
      sum += tail[i] * tail[i + lag];
    }
    if (sum > bestCorr) {
      bestCorr = sum;
      bestLag = lag;
    }
  }
  return framerate / bestLag;
}

function spectralCentroid(signal, skip, framerate) {
  const size = 8192;
  const real = new Float64Array(size);
  const imag = new Float64Array(size);
  for (let i = 0; i < size; i++) {
    real[i] = signal[skip + i] || 0;
  }
  fft(real, imag, false);

  const freqPerBin = framerate / size;
  let weightedSum = 0;
  let magnSum = 0;
  for (let k = 1; k < size / 2; k++) {
    const magn = Math.hypot(real[k], imag[k]);
    weightedSum += k * freqPerBin * magn;
    magnSum += magn;
  }
  return magnSum > 0 ? weightedSum / magnSum : 0;
}

function runShifter(semitones) {
  const ratio = 2 ** (semitones / 12);
  const shifter = new FormantShifter(FRAMERATE);
  shifter.setFormantRatio(ratio);

  const input = makeHarmonicTone(F0, HARMONICS, 2, FRAMERATE);
  const output = new Float64Array(input.length);
  shifter.process(input, output);
  return output;
}

// Skip the algorithm's startup latency (fftFrameSize - stepSize) plus a few
// extra frames so the LPC estimate is in steady state before measuring.
const skip = 2048 - 512 + 512 * 3;

// -- Gain calibration: at ratio 1, warpedEnvelope === envelope exactly, so
// the whole envelope-warp step is a no-op and the algorithm reduces to STFT
// analysis/resynthesis with unchanged magnitude and phase. Output level
// should match input level (peak 0.5). --
const unityOutput = runShifter(0);
const unityPeak = Math.max(...Array.from(unityOutput.slice(skip), Math.abs));
assert.ok(
  unityPeak > 0.3 && unityPeak < 0.7,
  `unity ratio: output peak ${unityPeak.toFixed(3)} should be close to the input peak (0.5) -- check the gain constant in formant-shifter.js`
);
console.log(`PASS unity ratio gain check: peak=${unityPeak.toFixed(3)} (input peak was 0.5)`);

const unityCentroid = spectralCentroid(unityOutput, skip, FRAMERATE);

function runCase(label, semitones) {
  const output = runShifter(semitones);

  const hasNaN = output.some((v) => Number.isNaN(v));
  const peak = Math.max(...Array.from(output.slice(skip), Math.abs));

  const f0 = estimateFreqAutocorr(output, skip, FRAMERATE, 50, 400);
  const f0Error = Math.abs(f0 - F0) / F0;

  const centroid = spectralCentroid(output, skip, FRAMERATE);

  assert.ok(!hasNaN, `${label}: output contains NaN`);
  assert.ok(peak > 0.05, `${label}: output is essentially silent (peak=${peak.toFixed(3)})`);
  assert.ok(peak < 2.0, `${label}: output peak implausibly large (peak=${peak.toFixed(3)})`);
  assert.ok(
    f0Error < F0_TOLERANCE,
    `${label}: F0 shifted -- expected ~${F0}Hz, measured ${f0.toFixed(1)}Hz (${(f0Error * 100).toFixed(1)}% error)`
  );

  if (semitones > 0) {
    assert.ok(
      centroid > unityCentroid,
      `${label}: spectral centroid should rise (unity=${unityCentroid.toFixed(1)}Hz, got ${centroid.toFixed(1)}Hz)`
    );
  } else if (semitones < 0) {
    assert.ok(
      centroid < unityCentroid,
      `${label}: spectral centroid should fall (unity=${unityCentroid.toFixed(1)}Hz, got ${centroid.toFixed(1)}Hz)`
    );
  }

  console.log(
    `PASS ${label}: f0=${f0.toFixed(1)}Hz (${(f0Error * 100).toFixed(2)}% err) centroid=${centroid.toFixed(1)}Hz peak=${peak.toFixed(3)}`
  );
}

const cases = [
  ["0 semitones", 0],
  ["+6 semitones", 6],
  ["-6 semitones", -6],
  ["+12 semitones", 12],
  ["-12 semitones", -12],
];

for (const [label, semitones] of cases) {
  runCase(label, semitones);
}

console.log(`\nAll ${cases.length + 1} formant-shifter checks passed.`);
```

- [ ] **Step 2: Run the test**

Run: `node tests/js/test_formant_shifter.mjs`
Expected: all 6 checks (`unity ratio gain check` + 5 semitone cases) print `PASS` and the script exits 0.

- [ ] **Step 3: If the unity-ratio gain check fails**

Adjust the `gain` constant in `formant-shifter.js`'s `_processFrame` (currently `4 / this.oversample`, carried over unverified from `pitch-shifter.js`) until `unityPeak` lands near 0.5. Re-run the test after each change. Document the actual root cause and fix in `docs/FIXES.md` once resolved (same format as the `Math.floor`/`Math.trunc` entry for Pitch).

- [ ] **Step 4: If any F0 or centroid-direction check fails**

Do not patch symptoms. Use the `superpowers:systematic-debugging` skill: instrument `_processFrame` to print `this.envelope`/`this.warpedEnvelope` for a single frame at a known ratio, compare against the expected shape by hand (envelope should have a smooth resonance peak near the harmonic that's loudest in the input; warped envelope should have that peak at `originalBinIndex * ratio`). Common suspects: sign error in `_computeEnvelope`'s real/imaginary accumulation, off-by-one in `_warpEnvelope`'s clamp bounds, Levinson-Durbin index error.

- [ ] **Step 5: Commit**

```bash
git add tests/js/test_formant_shifter.mjs
git commit -m "test: add a permanent Node regression test for the LPC formant shifter"
```

---

### Task 3: Wire the live preview into `formant-overlay.js`

**Files:**
- Modify: `static/js/overlays/formant-overlay.js`

**Interfaces:**
- Consumes: `FormantShifter` (Task 1)
- Produces: live audio while "Vorhören" plays and semitones/cents change, same lifecycle Pitch/Delay/Reverb already have.

- [ ] **Step 1: Import and live-audio state**

Add the import at the top of `formant-overlay.js`:

```javascript
import { FormantShifter } from "../dsp/formant-shifter.js";
```

Right after the `params`/`initialParams` setup near the top of `openFormantOverlay()`, add:

```javascript
  let audioCtx = null;
  let formantNode = null;
  let sourceNode = null;
  let channelShifters = [];

  function currentFormantRatio() {
    const nSteps = params.semitones + params.cents / 100.0;
    return 2 ** (nSteps / 12);
  }
```

- [ ] **Step 2: Web Audio graph**

Insert before the `presetsSection` block (same relative position `pitch-overlay.js` uses):

```javascript
  function initWebAudio() {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    const framerate = audioCtx.sampleRate;

    const bufferSize = 1024;
    const channels = 2;
    formantNode = audioCtx.createScriptProcessor(bufferSize, channels, channels);
    channelShifters = [new FormantShifter(framerate), new FormantShifter(framerate)];
    channelShifters.forEach((shifter) => shifter.setFormantRatio(currentFormantRatio()));

    formantNode.onaudioprocess = (audioProcessingEvent) => {
      const inputBuffer = audioProcessingEvent.inputBuffer;
      const outputBuffer = audioProcessingEvent.outputBuffer;
      const channelCount = inputBuffer.numberOfChannels;

      for (let c = 0; c < channelCount; c++) {
        const inputData = inputBuffer.getChannelData(c);
        const outputData = outputBuffer.getChannelData(c);
        channelShifters[c].process(inputData, outputData);
      }
    };

    sourceNode = audioCtx.createMediaElementSource(previewPlayer);
    sourceNode.connect(formantNode);
    formantNode.connect(audioCtx.destination);
  }

  function updateLiveWebAudioParams() {
    const ratio = currentFormantRatio();
    channelShifters.forEach((shifter) => shifter.setFormantRatio(ratio));
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
  }
```

- [ ] **Step 3: Call `updateLiveWebAudioParams()` from the existing input handlers**

Replace the existing `semitonesInput`/`centsInput` `"input"` listeners in `formant-overlay.js`:

```javascript
  semitonesInput.addEventListener("input", () => {
    params.semitones = Number(semitonesInput.value);
    updateLiveWebAudioParams();
  });

  centsInput.addEventListener("input", () => {
    params.cents = Number(centsInput.value);
    updateLiveWebAudioParams();
  });
```

And in `resetBtn`'s click handler, after the two `...Input.value = ...` lines, add:

```javascript
    updateLiveWebAudioParams();
```

- [ ] **Step 4: Start the graph on playback, clean up on close**

Right after `previewPlayer` is created:

```javascript
  previewPlayer.addEventListener("play", () => {
    initWebAudio();
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    updateLiveWebAudioParams();
  });
```

In `closeOverlay()`, add before `stopDragging()`:

```javascript
    if (audioCtx && audioCtx.state !== "closed") {
      audioCtx.close();
    }
```

- [ ] **Step 5: Verify syntax**

Run: `node --input-type=module --check < static/js/overlays/formant-overlay.js`
Expected: no output (clean)

- [ ] **Step 6: Commit**

```bash
git add static/js/overlays/formant-overlay.js
git commit -m "feat: wire the real-time LPC formant shifter into the formant overlay's live preview"
```

---

### Task 4: Manual verification

**Files:** none (verification only; fixes go back into Task 1/2/3's files if needed)

- [ ] **Step 1: Unity-ratio sanity check**

Open a box's Formant overlay, leave semitones/cents at 0, click "Vorhören". Output should sound essentially like the unmodified input.

- [ ] **Step 2: Directional check**

Set semitones to +6, "Vorhören" — should sound like a smaller/brighter-sounding voice, but at the **same pitch** as the dry signal (in contrast to Pitch, where the pitch itself moves). Set to -6 — bigger/darker-sounding voice, same pitch.

- [ ] **Step 3: Live-dragging check**

Start "Vorhören" playback, then move the semitones/cents inputs while it plays — timbre should audibly change in real time.

- [ ] **Step 4: Stability check**

Try extreme settings (+12/-12 semitones combined with ±50 cents) for at least 10 seconds of continuous playback — confirm no clipping, no runaway volume, no silence/dropout, no console errors.

- [ ] **Step 5: Regression check on Apply**

Confirm `applyBtn` still produces the same server-rendered `pyworld` result as before this plan (unaffected — `audio/formant.py` wasn't touched).

- [ ] **Step 6: Record findings**

If any bugs were found and fixed during this task that weren't already caught by Task 2's test, add a `docs/FIXES.md` entry documenting the root cause, following this project's existing FIXES.md format.

---

### Task 5: Documentation

**Files:**
- Modify: `docs/JOURNAL_8.md`, `docs/frontend-specification.md`, `plans/README.md`

- [ ] **Step 1: Update JOURNAL_8.md**

New dated entry: Formant live preview added, LPC-based envelope warping (autocorrelation + Levinson-Durbin), new `static/js/dsp/formant-shifter.js` module and `tests/js/test_formant_shifter.mjs` regression test, explicit note that it's representative-not-identical to the `pyworld`-based `/formant/apply` result. Note this closes the last open item from `docs/ideas.md:32`.

- [ ] **Step 2: Update frontend-specification.md**

Update the Formant overlay section to note live preview is now active during "Vorhören" (same phrasing style as the Pitch/Delay/Reverb sections' live-preview notes).

- [ ] **Step 3: Update plans/README.md**

Add status row `099 | Formant live Web Audio preview (LPC envelope warping) | P3 | L | none | TODO` (flip to DONE once merged) and a dependency note: independent of every other open plan, touches only `static/js/dsp/formant-shifter.js` (new), `tests/js/test_formant_shifter.mjs` (new), and `static/js/overlays/formant-overlay.js`.

- [ ] **Step 4: Commit**

```bash
git add docs/JOURNAL_8.md docs/frontend-specification.md plans/README.md
git commit -m "docs: document the formant live preview"
```

---

## STOP conditions

- If Task 2's Node test produces `NaN`, silence, or a crash — stop and debug the FFT/LPC math directly (console-log intermediate `envelope`/`warpedEnvelope` arrays for a single frame) before wiring anything into the browser overlay.
- If, after reasonable tuning (Task 2 Step 3, Task 4), formant direction is unmistakably wrong (up sounds down or vice versa) or the pitch itself audibly moves (defeating the whole point of the effect) — stop and re-derive the envelope computation/warp math from scratch against the spec, rather than continuing to patch symptoms.

## Maintenance notes

- `static/js/dsp/formant-shifter.js` is intentionally standalone (no imports), same convention as `pitch-shifter.js` — the two modules duplicate the same `fft()` function rather than sharing it, deliberately, so each DSP module stays self-contained and independently reasoned-about.
- If `audio/formant.py` is ever switched to a different backend, this plan's live preview would no longer match even in character — revisit then, not before.
