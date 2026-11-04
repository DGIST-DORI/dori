import test from 'node:test';
import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { encodeWav } from './audio.js';
test('48kHz microphone becomes bounded mono 16kHz PCM WAV', () => {
  const bytes = encodeWav(new Float32Array(48000).fill(.5), 48000);
  const view = new DataView(bytes.buffer);
  assert.equal(bytes.length, 32044);
  assert.equal(view.getUint32(24, true), 16000);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getInt16(44, true), 16384);
});
test('long recording is capped at ten seconds and clipped to PCM range', () => {
  const bytes = encodeWav(new Float32Array(16000 * 12).fill(-2), 16000);
  assert.equal(bytes.length, 320044);
  assert.equal(new DataView(bytes.buffer).getInt16(44, true), -32768);
});

import { SpeechEndpoint, Microphone } from './audio.js';

function signal(rate, seconds, amplitude = 0.08) {
  return Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amplitude * Math.sin(2 * Math.PI * 220 * i / rate));
}
function feed(endpoint, samples, block = 128) {
  let reason = null;
  for (let i = 0; i < samples.length && !reason; i += block) reason = endpoint.push(samples.subarray(i, i + block));
  return reason;
}
for (const rate of [16000, 44100, 48000]) {
  test(`speech ends after 800ms silence at ${rate}Hz and trims dead air`, () => {
    const detector = new SpeechEndpoint(rate);
    const recording = new Float32Array(rate * 4);
    recording.set(signal(rate, 0.6), rate);
    assert.equal(feed(detector, recording, 4096), 'speech_end');
    assert.ok(detector.samples / rate >= 2.38 && detector.samples / rate <= 2.44);
    const trimmed = detector.trim(recording);
    assert.ok(trimmed.length / rate >= 0.98 && trimmed.length / rate <= 1.04);
    const wav = encodeWav(trimmed, rate);
    assert.ok(wav.length >= 16044 && wav.length <= 34000);
  });
}
test('pauses within a sentence do not end recording', () => {
  const detector = new SpeechEndpoint(16000);
  assert.equal(feed(detector, signal(16000, 0.4)), null);
  assert.equal(feed(detector, signal(16000, 0.6, 0.001)), null);
  assert.equal(feed(detector, signal(16000, 0.4)), null);
  assert.equal(feed(detector, new Float32Array(16000)), 'speech_end');
});
test('silence, low background noise, DC offset and a click are not utterances', () => {
  for (const kind of ['silence', 'noise', 'dc', 'click']) {
    const detector = new SpeechEndpoint(16000);
    const samples = kind === 'noise' ? signal(16000, 6, 0.002) : new Float32Array(16000 * 6);
    if (kind === 'dc') samples.fill(0.1);
    if (kind === 'click') samples.set(signal(16000, 0.04), 1600);
    assert.equal(feed(detector, samples), 'no_speech', kind);
    assert.equal(detector.hasSpeech, false, kind);
  }
});
test('continuous speech is bounded and endpoint completion is stable', () => {
  const detector = new SpeechEndpoint(16000);
  assert.equal(feed(detector, signal(16000, 11)), 'limit');
  assert.equal(detector.samples, 160000);
  assert.equal(detector.push(signal(16000, 1)), 'limit');
  assert.equal(detector.samples, 160000);
});
test('short greeting keeps at least the server minimum WAV duration', () => {
  const detector = new SpeechEndpoint(16000);
  const samples = new Float32Array(16000);
  samples.set(signal(16000, 0.14));
  assert.equal(feed(detector, samples), 'speech_end');
  assert.equal(encodeWav(detector.trim(samples), 16000).length, 16044);
});
test('microphone auto-submits once, releases resources and ignores stale messages', async t => {
  const track = { stop: t.mock.fn() };
  const stream = { getTracks: () => [track] };
  const source = { connect() {}, disconnect: t.mock.fn() };
  const context = { sampleRate: 16000, resume: async () => {}, audioWorklet: { addModule: async () => {} },
    createMediaStreamSource: () => source, close: t.mock.fn(async () => {}) };
  const node = { port: {}, connect() {}, disconnect: t.mock.fn() };
  const originals = ['navigator', 'AudioContext', 'AudioWorkletNode'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: async () => stream } } });
  globalThis.AudioContext = function () { return context; };
  globalThis.AudioWorkletNode = function () { return node; };
  const microphone = new Microphone();
  try {
    const submitted = [];
    assert.equal(await microphone.start(() => submitted.push(microphone.finish())), true);
    node.port.onmessage({ data: signal(16000, 0.6) });
    node.port.onmessage({ data: new Float32Array(16000) });
    node.port.onmessage({ data: signal(16000, 1) });
    assert.equal(submitted.length, 1);
    assert.ok(Buffer.from(submitted[0], 'base64').length >= 16044);
    assert.equal(track.stop.mock.callCount(), 1);
    assert.equal(context.close.mock.callCount(), 1);
    assert.equal(microphone.context, null);
  } finally {
    microphone.cancel();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  }
});
