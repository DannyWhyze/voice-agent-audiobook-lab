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

const skip = 2048 - 512 + 512 * 3;

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
