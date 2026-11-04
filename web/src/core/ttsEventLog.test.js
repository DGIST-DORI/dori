import test from 'node:test';
import assert from 'node:assert/strict';
import { describeTtsEvent } from './ttsEventLog.js';

test('phone TTS includes spoken text and output metadata without retaining audio', () => {
  const event = {
    event_type: 'remote_audio', text: '안녕하세요! 도리입니다.',
    id: 'tts-action', timestamp: 100, playback_mode: 'local_only',
    audio_b64: 'private-mp3-payload', audio_bytes: 52800,
  };
  const result = describeTtsEvent(event);
  assert.equal(result.text, event.text);
  assert.equal(result.message, `speak: "${event.text}"`);
  assert.equal(result.raw.output, 'phone');
  assert.equal(result.raw.audio_bytes, 52800);
  assert.equal(result.raw.id, 'tts-action');
  assert.equal(JSON.stringify(result).includes('private-mp3-payload'), false);
  assert.equal('audio_b64' in result.raw, false);
});

test('existing local TTS and older phone TTS events still appear', () => {
  const local = { event_type: 'tts_text', text: '로봇 음성', engine: 'gtts' };
  assert.equal(describeTtsEvent(local).message, 'speak: "로봇 음성"');
  assert.deepEqual(describeTtsEvent(local).raw, local);
  const old = describeTtsEvent({ event_type: 'remote_audio', id: 'old', audio_b64: 'bXAz' });
  assert.match(old.message, /스마트폰/);
  assert.equal(old.text, '');
  assert.equal('audio_b64' in old.raw, false);
  for (const event of [null, {}, { event_type: 'cue' }]) {
    assert.equal(describeTtsEvent(event), null);
  }
});
