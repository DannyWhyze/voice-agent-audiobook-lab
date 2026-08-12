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

export class FormantShifter {
  constructor(framerate, fftFrameSize = 2048, oversample = 4, lpcOrder) {
    this.fftFrameSize = fftFrameSize;
    this.oversample = oversample;
    this.stepSize = fftFrameSize / oversample;
    this.inFifoLatency = fftFrameSize - this.stepSize;
    // LPC order cap (max 24): Makhoul's rule of thumb (2 + fs/1000) yields order 46 at 44.1kHz.
    // At order 46, LPC overfits individual pitch harmonics (F0) rather than smooth vocal tract formants,
    // causing pitch-tracking distortion during envelope warping. Capping at 24 ensures a smooth
    // formant-only envelope (approx. 12 pole-pairs) while keeping Levinson-Durbin CPU load low in Web Audio.
    this.lpcOrder = lpcOrder || Math.min(Math.round(2 + framerate / 1000), 24);
    this.formantRatio = 1.0;

    this.inFifo = new Float64Array(fftFrameSize);
    this.outFifo = new Float64Array(fftFrameSize);
    this.outputAccum = new Float64Array(fftFrameSize * 2);
    this.fftReal = new Float64Array(fftFrameSize);
    this.fftImag = new Float64Array(fftFrameSize);
    this.windowed = new Float64Array(fftFrameSize);

    // Hann window only depends on fftFrameSize (constant for the object's
    // lifetime), so it's precomputed once instead of recomputed every frame.
    this.hannWindow = new Float64Array(fftFrameSize);
    for (let k = 0; k < fftFrameSize; k++) {
      this.hannWindow[k] = -0.5 * Math.cos((TWO_PI * k) / fftFrameSize) + 0.5;
    }

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
        im -= a[j] * Math.sin(w * j);
      }
      const magA = Math.sqrt(re * re + im * im);
      envelope[k] = magA > 1e-9 ? 1 / magA : 1;
    }
  }

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

  _processFrame() {
    const fftFrameSize = this.fftFrameSize;
    const half = fftFrameSize / 2;

    for (let k = 0; k < fftFrameSize; k++) {
      this.windowed[k] = this.inFifo[k] * this.hannWindow[k];
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

    // Overlap-add gain: calibrated for Hann window squared sum (3/8 * 8 = 3)
    // to bring unity-ratio peak output to match peak input.
    const gain = 2.667 / this.oversample;
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
