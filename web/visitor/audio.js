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

export class Microphone {
  constructor() { this.sequence = 0; }
  async start(onLimit) {
    const seq = ++this.sequence;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('HTTPS 연결에서 마이크를 사용할 수 있습니다.');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    if (seq !== this.sequence) { stream.getTracks().forEach(t => t.stop()); return false; }
    this.stream = stream;
    try {
      this.context = new AudioContext();
      await this.context.resume();
      await this.context.audioWorklet.addModule('/recorder.js');
      if (seq !== this.sequence) return false;
      this.chunks = []; this.length = 0;
      this.node = new AudioWorkletNode(this.context, 'dori-recorder');
      this.node.port.onmessage = ({ data }) => {
        if (seq !== this.sequence) return;
        this.chunks.push(data); this.length += data.length;
        if (this.length >= this.context.sampleRate * 10) onLimit();
      };
      this.source = this.context.createMediaStreamSource(stream);
      this.source.connect(this.node); this.node.connect(this.context.destination);
      this.timer = setTimeout(onLimit, 10000);
      return true;
    } catch (error) { this.cancel(); throw error; }
  }
  finish() {
    const rate = this.context?.sampleRate || 16000;
    const samples = new Float32Array(this.length || 0); let offset = 0;
    for (const chunk of this.chunks || []) { samples.set(chunk, offset); offset += chunk.length; }
    this.cancel();
    if (samples.length < rate * 0.5) throw new Error('0.5초 이상 말씀해 주세요.');
    return toBase64(encodeWav(samples, rate));
  }
  cancel() {
    this.sequence++; clearTimeout(this.timer);
    this.stream?.getTracks().forEach(t => t.stop()); this.source?.disconnect(); this.node?.disconnect();
    this.context?.close().catch(() => {});
    this.stream = this.source = this.node = this.context = null; this.chunks = []; this.length = 0;
  }
}
