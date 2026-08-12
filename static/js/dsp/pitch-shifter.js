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

const TWO_PI = 2 * Math.PI;

export class PitchShifter {
  constructor(framerate, fftFrameSize = 2048, oversample = 4) {
    this.fftFrameSize = fftFrameSize;
    this.oversample = oversample;
    this.stepSize = fftFrameSize / oversample;
    this.freqPerBin = framerate / fftFrameSize;
    this.expct = (TWO_PI * this.stepSize) / fftFrameSize;
    this.inFifoLatency = fftFrameSize - this.stepSize;
    this.pitchRatio = 1.0;

    this.inFifo = new Float64Array(fftFrameSize);
    this.outFifo = new Float64Array(fftFrameSize);
    this.outputAccum = new Float64Array(fftFrameSize * 2);
    this.fftReal = new Float64Array(fftFrameSize);
    this.fftImag = new Float64Array(fftFrameSize);

    // Hann window only depends on fftFrameSize (constant for the object's
    // lifetime), so it's precomputed once instead of recomputed every frame.
    this.hannWindow = new Float64Array(fftFrameSize);
    for (let k = 0; k < fftFrameSize; k++) {
      this.hannWindow[k] = -0.5 * Math.cos((TWO_PI * k) / fftFrameSize) + 0.5;
    }

    const halfPlusOne = fftFrameSize / 2 + 1;
    this.lastPhase = new Float64Array(halfPlusOne);
    this.sumPhase = new Float64Array(halfPlusOne);
    this.anaFreq = new Float64Array(halfPlusOne);
    this.anaMagn = new Float64Array(halfPlusOne);
    this.synFreq = new Float64Array(halfPlusOne);
    this.synMagn = new Float64Array(halfPlusOne);

    this.rover = this.inFifoLatency;
  }

  setPitchRatio(ratio) {
    this.pitchRatio = ratio;
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

  _processFrame() {
    const fftFrameSize = this.fftFrameSize;
    const half = fftFrameSize / 2;
    const oversample = this.oversample;
    const freqPerBin = this.freqPerBin;
    const expct = this.expct;

    for (let k = 0; k < fftFrameSize; k++) {
      this.fftReal[k] = this.inFifo[k] * this.hannWindow[k];
      this.fftImag[k] = 0;
    }

    fft(this.fftReal, this.fftImag, false);

    for (let k = 0; k <= half; k++) {
      const re = this.fftReal[k];
      const im = this.fftImag[k];
      const magn = 2 * Math.sqrt(re * re + im * im);
      const phase = Math.atan2(im, re);

      let tmp = phase - this.lastPhase[k];
      this.lastPhase[k] = phase;
      tmp -= k * expct;

      let qpd = Math.trunc(tmp / Math.PI);
      if (qpd >= 0) {
        qpd += qpd & 1;
      } else {
        qpd -= qpd & 1;
      }
      tmp -= Math.PI * qpd;

      tmp = (oversample * tmp) / TWO_PI;
      tmp = k * freqPerBin + tmp * freqPerBin;

      this.anaFreq[k] = tmp;
      this.anaMagn[k] = magn;
    }

    this.synMagn.fill(0);
    this.synFreq.fill(0);

    for (let k = 0; k <= half; k++) {
      const index = Math.round(k * this.pitchRatio);
      if (index <= half && index >= 0) {
        this.synMagn[index] += this.anaMagn[k];
        this.synFreq[index] = this.anaFreq[k] * this.pitchRatio;
      }
    }

    for (let k = 0; k <= half; k++) {
      const magn = this.synMagn[k];
      let tmp = this.synFreq[k] - k * freqPerBin;
      tmp /= freqPerBin;
      tmp = (TWO_PI * tmp) / oversample;
      tmp += k * expct;
      this.sumPhase[k] += tmp;
      const phase = this.sumPhase[k];
      this.fftReal[k] = magn * Math.cos(phase);
      this.fftImag[k] = magn * Math.sin(phase);
    }
    for (let k = half + 1; k < fftFrameSize; k++) {
      this.fftReal[k] = 0;
      this.fftImag[k] = 0;
    }

    fft(this.fftReal, this.fftImag, true);

    const gain = 4 / oversample;
    for (let k = 0; k < fftFrameSize; k++) {
      this.outputAccum[k] += this.hannWindow[k] * this.fftReal[k] * gain;
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
