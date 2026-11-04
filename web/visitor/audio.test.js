import test from 'node:test';
import assert from 'node:assert/strict';
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
