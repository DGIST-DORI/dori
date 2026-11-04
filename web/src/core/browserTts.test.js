import test from 'node:test';
import assert from 'node:assert/strict';
import { createBrowserTtsController } from './browserTts.js';

function harness(t, voices = [{ lang: 'ko-KR', default: true }, { lang: 'en-US' }]) {
  const oldWindow = globalThis.window;
  const oldUtterance = globalThis.SpeechSynthesisUtterance;
  const spoken = [];
  let mode = 'browser_tts';
  globalThis.window = { speechSynthesis: { getVoices: () => voices,
    cancel() {}, speak: utterance => spoken.push(utterance) } };
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  t.after(() => {
    globalThis.window = oldWindow;
    globalThis.SpeechSynthesisUtterance = oldUtterance;
  });
  const controller = createBrowserTtsController({
    getAudioOutputMode: () => mode, browserTtsMode: 'browser_tts',
  });
  return { controller, spoken, setMode: value => { mode = value; } };
}

test('English selects an English voice even with a Korean OS default', t => {
  const { controller, spoken } = harness(t);
  assert.equal(controller.speak({ payload: "Hello, I'm DORI. Dori's here!" }), true);
  assert.equal(spoken[0].lang, 'en-US');
  assert.equal(spoken[0].voice.lang, 'en-US');
  assert.equal(spoken[0].text, "Hello, I'm Dory. Dory's here!");
  controller.speak({ payload: 'DORI입니다. Dori가 안내할게요.' });
  assert.equal(spoken[1].lang, 'ko-KR');
  assert.equal(spoken[1].voice.lang, 'ko-KR');
  assert.equal(spoken[1].text, '도리입니다. 도리가 안내할게요.');
});

test('uses server pronunciation metadata and keeps output guard and deduplication', t => {
  const { controller, spoken, setMode } = harness(t);
  const event = { payload: '123 DORI', messageId: 'turn-1', lang: 'ko-KR', speechText: '123 도리' };
  controller.speak(event);
  assert.equal(spoken[0].lang, 'ko-KR');
  assert.equal(spoken[0].text, '123 도리');
  assert.equal(controller.speak(event), false);
  setMode('ros_audio');
  assert.equal(controller.speak({ payload: 'Next reply' }), false);
  assert.equal(spoken.length, 1);
});

test('DGIST pronunciation handles case and Korean particles without changing larger words', t => {
  const { controller, spoken } = harness(t);
  controller.speak({ payload: "DORI at DGIST. Dgist's campus, dgist, DGISTian, DGIST_id, DGIST2" });
  assert.equal(spoken[0].lang, 'en-US');
  assert.equal(spoken[0].text, "Dory at dee jist. dee jist's campus, dee jist, DGISTian, DGIST_id, DGIST2");
  controller.speak({ payload: 'Dori가 DGIST를 안내해요. Dgist의 캠퍼스입니다.' });
  assert.equal(spoken[1].lang, 'ko-KR');
  assert.equal(spoken[1].text, '도리가 디지스트를 안내해요. 디지스트의 캠퍼스입니다.');
});

test('same-language region fallback never chooses the Korean default for English', t => {
  const { controller, spoken } = harness(t, [{ lang: 'ko-KR' }, { lang: 'en_GB' }]);
  controller.speak({ payload: 'Dori, Doric, Midori, DORI_id, DORI2' });
  assert.equal(spoken[0].voice.lang, 'en_GB');
  assert.equal(spoken[0].text, 'Dory, Doric, Midori, DORI_id, DORI2');
});

test('empty or missing English voice lists leave language selection to the browser', t => {
  const voices = [];
  const { controller, spoken } = harness(t, voices);
  controller.speak({ payload: 'Hello, DORI!' });
  voices.push({ lang: 'ko-KR' });
  controller.speak({ payload: 'Welcome, Dori!' });
  for (const utterance of spoken) {
    assert.equal(utterance.lang, 'en-US');
    assert.equal(utterance.voice, undefined);
  }
  voices.push({ lang: 'en-US' });
  controller.speak({ payload: 'DORI can help.' });
  assert.equal(spoken[2].voice.lang, 'en-US');
});
