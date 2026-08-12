export const DELAY_LENGTHS_SECONDS = [
  0.004771345, 0.003595309, 0.012734787, 0.009307483,
  0.022579886, 0.149625349, 0.060481839, 0.1249958,
  0.030509727, 0.141695508, 0.089244313, 0.106280031,
];

export const TAP_OFFSETS_SECONDS = [
  0.008937872, 0.099929438, 0.064278754, 0.067067639, 0.066866033,
  0.006283391, 0.035818689, 0.011861161, 0.121870905, 0.041262054,
  0.08981553, 0.070931756, 0.011256342, 0.004065724,
];

export class ReverbDelayLine {
  constructor(length) {
    this.length = Math.max(length, 1);
    this.buffer = new Float64Array(this.length);
    this.writeIndex = 0;
  }

  peek() {
    return this.buffer[this.writeIndex];
  }

  peekAt(offset) {
    const readIndex = (this.writeIndex + offset) % this.length;
    return this.buffer[readIndex];
  }

  peekInterp(offset) {
    const base = Math.floor(offset);
    const frac = offset - base;
    const i0 = (this.writeIndex + base - 1 + this.length * 4) % this.length;
    const i1 = (this.writeIndex + base + this.length * 4) % this.length;
    const i2 = (this.writeIndex + base + 1 + this.length * 4) % this.length;
    const i3 = (this.writeIndex + base + 2 + this.length * 4) % this.length;
    const x0 = this.buffer[i0];
    const x1 = this.buffer[i1];
    const x2 = this.buffer[i2];
    const x3 = this.buffer[i3];
    const a = (3 * (x1 - x2) - x0 + x3) / 2;
    const b = 2 * x2 + x0 - (5 * x1 + x3) / 2;
    const c = (x2 - x0) / 2;
    return ((a * frac + b) * frac + c) * frac + x1;
  }

  push(value) {
    this.buffer[this.writeIndex] = value;
  }

  advance() {
    this.writeIndex = (this.writeIndex + 1) % this.buffer.length;
  }
}

export class ReverbTank {
  constructor(framerate) {
    this.framerate = framerate;
    this.delays = DELAY_LENGTHS_SECONDS.map(
      (seconds) => new ReverbDelayLine(Math.round(seconds * framerate))
    );
    this.tapOffsets = TAP_OFFSETS_SECONDS.map((seconds) => Math.round(seconds * framerate));
    this.preDelayLength = framerate + (128 - (framerate % 128));
    this.preDelayBuffer = new Float64Array(this.preDelayLength);
    this.preDelayWrite = 0;
    this.lp1 = 0.0;
    this.lp2 = 0.0;
    this.lp3 = 0.0;
    this.excPhase = 0.0;
    this.params = null;
  }

  setParams(params) {
    this.params = params;
  }

  process(inputChannels, outputLeft, outputRight) {
    const framerate = this.framerate;
    const params = this.params;
    const delays = this.delays;
    const tapOffsets = this.tapOffsets;
    const length = outputLeft.length;
    const channelCount = inputChannels.length;

    const bw = params.bandwidth;
    const fi = params.input_diffusion_1;
    const si = params.input_diffusion_2;
    const dc = params.decay;
    const ft = params.decay_diffusion_1;
    const st = params.decay_diffusion_2;
    const dp = 1.0 - params.damping;
    const ex = params.excursion_rate / framerate;
    const ed = (params.excursion_depth * framerate) / 1000.0;
    const dryGain = 1.0 - params.wet_dry_mix;
    const wetGain = params.wet_dry_mix * 0.6;
    const preDelaySamples = Math.round((params.pre_delay_ms / 1000.0) * framerate);

    for (let i = 0; i < length; i++) {
      let monoInput = 0;
      for (let c = 0; c < channelCount; c++) {
        monoInput += inputChannels[c][i];
      }
      monoInput /= channelCount;

      this.preDelayBuffer[this.preDelayWrite] = monoInput;
      const readPos =
        ((this.preDelayWrite - preDelaySamples) % this.preDelayLength + this.preDelayLength) %
        this.preDelayLength;
      const predelayed = this.preDelayBuffer[readPos];
      this.preDelayWrite = (this.preDelayWrite + 1) % this.preDelayLength;

      this.lp1 += bw * (predelayed - this.lp1);

      const old0 = delays[0].peek();
      const old1 = delays[1].peek();
      const old2 = delays[2].peek();
      const old3 = delays[3].peek();

      const new0 = this.lp1 - fi * old0;
      let pre = new0;
      const new1 = fi * (pre - old1) + old0;
      pre = new1;
      const new2 = fi * pre + old1 - si * old2;
      pre = new2;
      const new3 = si * (pre - old3) + old2;
      const split = si * new3 + old3;

      delays[0].push(new0);
      delays[1].push(new1);
      delays[2].push(new2);
      delays[3].push(new3);

      const exc = ed * (1 + Math.cos(this.excPhase * 6.28));
      const exc2 = ed * (1 + Math.sin(this.excPhase * 6.2847));

      const old4Interp = delays[4].peekInterp(exc);
      const old6 = delays[6].peek();
      const old7 = delays[7].peek();
      const old8Interp = delays[8].peekInterp(exc2);
      const old10 = delays[10].peek();
      const old11 = delays[11].peek();

      const new4 = split + dc * old11 + ft * old4Interp;
      const new5 = old4Interp - ft * new4;
      this.lp2 += dp * (delays[5].peek() - this.lp2);
      const new6 = dc * this.lp2 - st * old6;
      const new7 = old6 + st * new6;

      const new8 = split + dc * old7 + ft * old8Interp;
      const new9 = old8Interp - ft * new8;
      this.lp3 += dp * (delays[9].peek() - this.lp3);
      const new10 = dc * this.lp3 - st * old10;
      const new11 = old10 + st * new10;

      delays[4].push(new4);
      delays[5].push(new5);
      delays[6].push(new6);
      delays[7].push(new7);
      delays[8].push(new8);
      delays[9].push(new9);
      delays[10].push(new10);
      delays[11].push(new11);

      const lo =
        delays[9].peekAt(tapOffsets[0]) +
        delays[9].peekAt(tapOffsets[1]) -
        delays[10].peekAt(tapOffsets[2]) +
        delays[11].peekAt(tapOffsets[3]) -
        delays[5].peekAt(tapOffsets[4]) -
        delays[6].peekAt(tapOffsets[5]) -
        delays[7].peekAt(tapOffsets[6]);
      const ro =
        delays[5].peekAt(tapOffsets[7]) +
        delays[5].peekAt(tapOffsets[8]) -
        delays[6].peekAt(tapOffsets[9]) +
        delays[7].peekAt(tapOffsets[10]) -
        delays[9].peekAt(tapOffsets[11]) -
        delays[10].peekAt(tapOffsets[12]) -
        delays[11].peekAt(tapOffsets[13]);

      outputLeft[i] = monoInput * dryGain + lo * wetGain;
      outputRight[i] = monoInput * dryGain + ro * wetGain;

      this.excPhase += ex;
      for (const delayLine of delays) delayLine.advance();
    }
  }
}
