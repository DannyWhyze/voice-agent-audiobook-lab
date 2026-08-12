// Plain Node.js check for static/js/dsp/pitch-shifter.js -- no test framework,
// run manually with: node tests/js/test_pitch_shifter.mjs
//
// Unlike the rest of the frontend (UI wiring, needs a browser/DOM), the pitch
// shifter is pure DSP: a frequency and a ratio go in, a shifted frequency
// comes out. That's verifiable with a synthetic tone and no framework at all.
// This exact test would have caught the Math.floor/Math.trunc phase-unwrap
// bug fixed 2026-08-09 (see docs/FIXES.md) -- run it again after any change
// to pitch-shifter.js.

import assert from "node:assert/strict";
import { PitchShifter } from "../../static/js/dsp/pitch-shifter.js";

const FRAMERATE = 24000;
const INPUT_FREQ = 220;
const TOLERANCE = 0.02; // 2% frequency error allowed

function makeTone(freq, seconds, framerate) {
  const n = Math.round(framerate * seconds);
  const buf = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    buf[i] = 0.5 * Math.sin((2 * Math.PI * freq * i) / framerate);
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

function runCase(label, semitones) {
  const ratio = 2 ** (semitones / 12);
  const shifter = new PitchShifter(FRAMERATE);
  shifter.setPitchRatio(ratio);

  const input = makeTone(INPUT_FREQ, 2, FRAMERATE);
  const output = new Float64Array(input.length);
  shifter.process(input, output);

  const hasNaN = output.some((v) => Number.isNaN(v));
  const peak = Math.max(...Array.from(output, Math.abs));

  // Skip the algorithm's inherent startup latency (fftFrameSize - stepSize)
  // plus a few extra frames so the phase vocoder is in steady state before
  // measuring.
  const skip = (2048 - 512) + 512 * 3;
  const expectedFreq = INPUT_FREQ * ratio;
  const measuredFreq = estimateFreqAutocorr(output, skip, FRAMERATE, 50, 900);
  const relativeError = Math.abs(measuredFreq - expectedFreq) / expectedFreq;

  assert.ok(!hasNaN, `${label}: output contains NaN`);
  assert.ok(peak > 0.05, `${label}: output is essentially silent (peak=${peak.toFixed(3)})`);
  assert.ok(
    peak < 2.0,
    `${label}: output peak is implausibly large (peak=${peak.toFixed(3)}) -- likely a runaway/instability bug`
  );
  assert.ok(
    relativeError < TOLERANCE,
    `${label}: expected ~${expectedFreq.toFixed(1)}Hz, measured ${measuredFreq.toFixed(1)}Hz ` +
      `(${(relativeError * 100).toFixed(1)}% error, tolerance ${(TOLERANCE * 100).toFixed(0)}%)`
  );

  console.log(
    `PASS ${label}: expected=${expectedFreq.toFixed(1)}Hz measured=${measuredFreq.toFixed(1)}Hz ` +
      `error=${(relativeError * 100).toFixed(2)}% peak=${peak.toFixed(3)}`
  );
}

const cases = [
  ["unity (0 semitones)", 0],
  ["+12 semitones (octave up)", 12],
  ["-12 semitones (octave down)", -12],
  ["+7 semitones (fifth up)", 7],
  ["-5 semitones (fourth down)", -5],
  ["+3.5 semitones (with cents)", 3.5],
  ["-9.25 semitones (with cents)", -9.25],
];

for (const [label, semitones] of cases) {
  runCase(label, semitones);
}

console.log(`\nAll ${cases.length} pitch-shifter checks passed.`);
