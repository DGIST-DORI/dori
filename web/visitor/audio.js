export function encodeWav(samples, rate) {
  const count = Math.min(160000, Math.floor(samples.length * 16000 / rate));
  const wav = new ArrayBuffer(44 + count * 2), view = new DataView(wav);
  const text = (at, value) => [...value].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
  text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const start = Math.floor(i * rate / 16000), end = Math.max(start + 1, Math.floor((i + 1) * rate / 16000));
    let sum = 0; for (let j = start; j < end; j++) sum += samples[j] || 0;
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Uint8Array(wav);
}
export function toBase64(bytes) {
  let string = ''; for (let i = 0; i < bytes.length; i += 8192) string += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(string);
}

// Measure audio time, not wall time: AudioWorklet messages can arrive in batches.
export class SpeechEndpoint {
  constructor(rate) {
    this.rate = rate;
    this.window = Math.round(rate * 0.02);
    this.samples = this.count = this.sum = this.squares = this.voiced = 0;
    this.firstVoice = null; this.lastVoice = 0; this.hasSpeech = false;
    this.noise = 0.002; this.reason = null;
  }
  push(samples) {
    if (this.reason) return this.reason;
    for (const sample of samples) {
      this.samples++; this.count++; this.sum += sample; this.squares += sample * sample;
      if (this.count < this.window) continue;
      // Ignore DC offset; only changing microphone energy counts as speech.
      const rms = Math.sqrt(Math.max(0, this.squares / this.count - (this.sum / this.count) ** 2));
      this.count = this.sum = this.squares = 0;
      if (rms > Math.max(0.008, this.noise * 3)) {
        this.firstVoice ??= this.samples - this.window;
        this.lastVoice = this.samples;
        this.voiced += this.window;
        this.hasSpeech ||= this.voiced >= this.rate * 0.12;
      } else {
        this.noise = 0.95 * this.noise + 0.05 * rms;
        if (!this.hasSpeech && this.samples - this.lastVoice >= this.rate * 0.3) {
          this.voiced = 0; this.firstVoice = null;
        }
      }
      if (this.hasSpeech && this.samples - this.lastVoice >= this.rate * 0.8) this.reason = 'speech_end';
      else if (!this.hasSpeech && this.samples >= this.rate * 5) this.reason = 'no_speech';
      else if (this.samples >= this.rate * 10) this.reason = 'limit';
      if (this.reason) return this.reason;
    }
    return null;
  }
  trim(samples) {
    const start = Math.max(0, (this.firstVoice ?? 0) - Math.round(this.rate * 0.2));
    const end = Math.min(samples.length, Math.max(start + Math.ceil(this.rate * 0.5), this.lastVoice + Math.round(this.rate * 0.2)));
    return samples.subarray(start, end);
  }
}

export class Microphone {
  constructor() { this.sequence = 0; }
  async start(onComplete) {
    this.cancel();
    const seq = this.sequence;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('HTTPS 연결에서 마이크를 사용할 수 있습니다.');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    if (seq !== this.sequence) { stream.getTracks().forEach(t => t.stop()); return false; }
    this.stream = stream;
    try {
      const context = new AudioContext();
      this.context = context;
      await context.resume();
      if (seq !== this.sequence) return false;
      await context.audioWorklet.addModule('/recorder.js');
      if (seq !== this.sequence) return false;
      this.chunks = []; this.length = 0;
      this.endpoint = new SpeechEndpoint(this.context.sampleRate);
      let completed = false;
      const complete = () => {
        if (seq !== this.sequence || completed) return;
        completed = true; onComplete();
      };
      this.node = new AudioWorkletNode(this.context, 'dori-recorder');
      this.node.port.onmessage = ({ data }) => {
        if (seq !== this.sequence || completed) return;
        this.chunks.push(data); this.length += data.length;
        if (this.endpoint.push(data)) complete();
      };
      this.source = this.context.createMediaStreamSource(stream);
      this.source.connect(this.node); this.node.connect(this.context.destination);
      this.timer = setTimeout(complete, 10000);
      return true;
    } catch (error) {
      if (seq !== this.sequence) return false;
      this.cancel(); throw error;
    }
  }
  finish() {
    const rate = this.context?.sampleRate || 16000;
    const samples = new Float32Array(this.length || 0); let offset = 0;
    for (const chunk of this.chunks || []) { samples.set(chunk, offset); offset += chunk.length; }
    const endpoint = this.endpoint;
    this.cancel();
    if (samples.length < rate * 0.5) throw new Error('0.5초 이상 말씀해 주세요.');
    if (!endpoint?.hasSpeech) throw new Error('음성이 감지되지 않았습니다. 마이크 가까이에서 다시 말씀해 주세요.');
    return toBase64(encodeWav(endpoint.trim(samples), rate));
  }
  cancel() {
    this.sequence++; clearTimeout(this.timer);
    this.stream?.getTracks().forEach(t => t.stop()); this.source?.disconnect(); this.node?.disconnect();
    this.context?.close().catch(() => {});
    this.stream = this.source = this.node = this.context = this.endpoint = null; this.chunks = []; this.length = 0;
  }
}

// Buffer source samples across AudioWorklet messages before resampling, so a
// 44.1/48 kHz microphone does not lose fractional samples on every 128-frame block.
export class PcmChunks {
  constructor(rate, emit) {
    this.rate = rate; this.emit = emit;
    this.frame = new Float32Array(Math.round(rate / 10)); this.used = 0;
  }
  push(samples) {
    let offset = 0;
    while (offset < samples.length) {
      const count = Math.min(samples.length - offset, this.frame.length - this.used);
      this.frame.set(samples.subarray(offset, offset + count), this.used);
      this.used += count; offset += count;
      if (this.used === this.frame.length) this.flush();
    }
  }
  flush() {
    if (!this.used) return;
    const pcm = encodeWav(this.frame.subarray(0, this.used), this.rate).subarray(44);
    this.used = 0;
    if (pcm.length) this.emit(pcm);
  }
}

export class StreamingMicrophone extends Microphone {
  async start(onChunk, onLimit) {
    this.cancel();
    const seq = this.sequence;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('마이크를 사용할 수 없습니다.');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    if (seq !== this.sequence) { stream.getTracks().forEach(t => t.stop()); return false; }
    this.stream = stream;
    try {
      this.context = new AudioContext();
      await this.context.resume();
      if (seq !== this.sequence) return false;
      await this.context.audioWorklet.addModule('/recorder.js');
      if (seq !== this.sequence) return false;
      this.pcm = new PcmChunks(this.context.sampleRate, onChunk);
      const maximum = this.context.sampleRate * 10;
      let received = 0, completed = false;
      const complete = () => {
        if (seq !== this.sequence || completed) return;
        completed = true; onLimit();
      };
      this.node = new AudioWorkletNode(this.context, 'dori-recorder');
      this.node.port.onmessage = ({ data }) => {
        if (seq !== this.sequence || completed) return;
        const usable = data.subarray(0, Math.max(0, maximum - received));
        received += usable.length; this.pcm.push(usable);
        if (received >= maximum) complete();
      };
      this.source = this.context.createMediaStreamSource(stream);
      this.source.connect(this.node); this.node.connect(this.context.destination);
      this.timer = setTimeout(complete, 10000);
      return true;
    } catch (error) {
      if (seq === this.sequence) this.cancel();
      throw error;
    }
  }
  finish() { this.pcm?.flush(); this.cancel(); }
  cancel() { super.cancel(); this.pcm = null; }
}
