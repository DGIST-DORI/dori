class Recorder extends AudioWorkletProcessor {
  process(inputs) {
    if (inputs[0]?.[0]) this.port.postMessage(inputs[0][0].slice());
    // Output remains silent; the microphone is never monitored to the speaker.
    return true;
  }
}
registerProcessor('dori-recorder', Recorder);
