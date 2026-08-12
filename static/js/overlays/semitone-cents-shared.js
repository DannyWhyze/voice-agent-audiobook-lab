export function buildSemitoneCentsRows({ t, panel, params, semitonesLabelKey, centsLabelKey, onChange }) {
  const semitonesRow = document.createElement("div");
  semitonesRow.className = "semitone-cents-row";

  const semitonesLabel = document.createElement("label");
  semitonesLabel.textContent = t(semitonesLabelKey);
  semitonesRow.appendChild(semitonesLabel);

  const semitonesInput = document.createElement("input");
  semitonesInput.type = "number";
  semitonesInput.min = "-12";
  semitonesInput.max = "12";
  semitonesInput.step = "1";
  semitonesInput.value = String(params.semitones);
  semitonesRow.appendChild(semitonesInput);
  panel.appendChild(semitonesRow);

  const centsRow = document.createElement("div");
  centsRow.className = "semitone-cents-row";

  const centsLabel = document.createElement("label");
  centsLabel.textContent = t(centsLabelKey);
  centsRow.appendChild(centsLabel);

  const centsInput = document.createElement("input");
  centsInput.type = "number";
  centsInput.min = "-50";
  centsInput.max = "50";
  centsInput.step = "1";
  centsInput.value = String(params.cents);
  centsRow.appendChild(centsInput);
  panel.appendChild(centsRow);

  semitonesInput.addEventListener("input", () => {
    params.semitones = Number(semitonesInput.value);
    onChange();
  });

  centsInput.addEventListener("input", () => {
    params.cents = Number(centsInput.value);
    onChange();
  });

  return { semitonesInput, centsInput };
}

export function createSemitoneRatioLiveAudio({ params, createShifter, setRatio }) {
  let audioCtx = null;
  let node = null;
  let sourceNode = null;
  let channelShifters = [];

  function currentRatio() {
    const nSteps = params.semitones + params.cents / 100.0;
    return 2 ** (nSteps / 12);
  }

  function initWebAudio(previewPlayer) {
    if (audioCtx) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    audioCtx = new AudioContextClass();
    const framerate = audioCtx.sampleRate;

    const bufferSize = 1024;
    const channels = 2;
    node = audioCtx.createScriptProcessor(bufferSize, channels, channels);
    channelShifters = [createShifter(framerate), createShifter(framerate)];
    channelShifters.forEach((shifter) => setRatio(shifter, currentRatio()));

    node.onaudioprocess = (audioProcessingEvent) => {
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
    sourceNode.connect(node);
    node.connect(audioCtx.destination);
  }

  function updateLiveWebAudioParams() {
    const ratio = currentRatio();
    channelShifters.forEach((shifter) => setRatio(shifter, ratio));
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
  }

  function closeAudioGraph() {
    if (audioCtx && audioCtx.state !== "closed") {
      audioCtx.close();
    }
  }

  return { initWebAudio, updateLiveWebAudioParams, closeAudioGraph };
}
