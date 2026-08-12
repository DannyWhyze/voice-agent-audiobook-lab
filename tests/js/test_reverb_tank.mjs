// Plain Node.js check for static/js/dsp/reverb-tank.js -- no test framework,
// run manually with: node tests/js/test_reverb_tank.mjs
//
// Unlike test_pitch_shifter.mjs/test_formant_shifter.mjs (genuinely different
// algorithms from their Python counterparts, so those tests only check
// direction/character), the reverb tank is meant to be the SAME algorithm as
// audio/reverb.py's _run_tank, sample-for-sample (README.md:84 claims
// "bit-exact"). This test measures the actual divergence against a Python-
// generated reference fixture, rather than assuming it.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { ReverbTank } from "../../static/js/dsp/reverb-tank.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(__dirname, "fixtures", "reverb_tank_reference.json"), "utf8")
);

function makeTestSignal(framerate, durationSeconds) {
  const n = Math.round(framerate * durationSeconds);
  const signal = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / framerate;
    signal[i] =
      0.3 * Math.sin(2 * Math.PI * 220 * t) +
      0.2 * Math.sin(2 * Math.PI * 1000 * t) +
      0.1 * Math.sin(2 * Math.PI * 4000 * t);
  }
  return signal;
}

const { framerate, duration_seconds: durationSeconds, params, left_out: expectedLeft, right_out: expectedRight } =
  fixture;

const input = makeTestSignal(framerate, durationSeconds);
const tank = new ReverbTank(framerate);
tank.setParams(params);

const actualLeft = new Float64Array(input.length);
const actualRight = new Float64Array(input.length);
tank.process([input], actualLeft, actualRight);

assert.equal(actualLeft.length, expectedLeft.length, "output length mismatch (left)");
assert.equal(actualRight.length, expectedRight.length, "output length mismatch (right)");

function compare(label, actual, expected) {
  let maxAbsErr = 0;
  let sumSqErr = 0;
  let maxAbsErrIndex = -1;
  for (let i = 0; i < actual.length; i++) {
    const err = Math.abs(actual[i] - expected[i]);
    if (err > maxAbsErr) {
      maxAbsErr = err;
      maxAbsErrIndex = i;
    }
    sumSqErr += err * err;
  }
  const rmsErr = Math.sqrt(sumSqErr / actual.length);
  console.log(
    `${label}: maxAbsErr=${maxAbsErr.toExponential(3)} (at sample ${maxAbsErrIndex}/${actual.length}), rmsErr=${rmsErr.toExponential(3)}`
  );
  return { maxAbsErr, rmsErr };
}

const hasNaN =
  actualLeft.some((v) => Number.isNaN(v)) || actualRight.some((v) => Number.isNaN(v));
assert.ok(!hasNaN, "output contains NaN -- extraction likely introduced a bug, fix before measuring precision");

const leftStats = compare("left channel", actualLeft, expectedLeft);
const rightStats = compare("right channel", actualRight, expectedRight);

// Strict float64 tolerance check: verifies JS tank matches Python _run_tank to float precision.
const PRECISION_BOUND = 1e-12;
assert.ok(leftStats.maxAbsErr < PRECISION_BOUND, `left channel diverged (${leftStats.maxAbsErr})`);
assert.ok(rightStats.maxAbsErr < PRECISION_BOUND, `right channel diverged (${rightStats.maxAbsErr})`);

console.log("\nSample-for-sample float64 precision test passed!");
