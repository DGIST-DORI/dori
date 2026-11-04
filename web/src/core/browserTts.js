const DEFAULT_LANG = 'ko-KR';
const DEFAULT_RATE = 1;
const NAME_PRONUNCIATIONS = {
  dori: { en: 'Dory', ko: '도리' },
  dgist: { en: 'dee jist', ko: '디지스트' },
};

// Keep the ko/en policy aligned with dori_hri.tts_speech for legacy events.
function detectLanguage(text) {
  if (/[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]/u.test(text)) return 'ko-KR';
  return /[A-Za-z]/.test(text) ? 'en-US' : DEFAULT_LANG;
}

function spokenText(text, lang) {
  // Web Speech has no portable IPA control. Avoid spelling names as acronyms.
  const language = lang.toLowerCase().startsWith('ko') ? 'ko' : 'en';
  return text.replace(/(?<![A-Za-z0-9_])(?:dori|dgist)(?![A-Za-z0-9_])/gi,
    name => NAME_PRONUNCIATIONS[name.toLowerCase()][language]);
}

function getSpeechSynthesis() {
  if (typeof window === 'undefined') return null;
  return window.speechSynthesis || null;
}

function normalizeText(payload) {
  if (!payload) return '';
  if (typeof payload === 'string') return payload;
  if (typeof payload?.data === 'string') return payload.data;
  if (typeof payload?.text === 'string') return payload.text;
  return '';
}

function buildDedupKey(messageId, text) {
  if (messageId) return `msg:${messageId}`;
  return `text:${text.trim()}`;
}

export function createBrowserTtsController({ addLog, setUnlockWarning, getAudioOutputMode, browserTtsMode }) {
  let lastSpokenKey = '';
  let unlocked = false;
  let unlockAttempted = false;

  const synth = getSpeechSynthesis();

  const ensureGuard = () => getAudioOutputMode?.() === browserTtsMode;

  const cancel = () => {
    if (!ensureGuard()) return;
    const s = getSpeechSynthesis();
    if (s) s.cancel();
  };

  const unlock = () => {
    if (unlockAttempted || unlocked) return;
    unlockAttempted = true;

    const s = getSpeechSynthesis();
    if (!s || !ensureGuard()) return;

    try {
      const utterance = new SpeechSynthesisUtterance(' ');
      utterance.volume = 0;
      utterance.rate = 1;
      utterance.onend = () => {
        unlocked = true;
        setUnlockWarning?.('');
      };
      utterance.onerror = () => {
        setUnlockWarning?.('브라우저 TTS가 잠겨 있습니다. 화면 터치 후 다시 시도하세요.');
      };
      s.speak(utterance);
    } catch {
      setUnlockWarning?.('브라우저 정책/권한으로 TTS를 시작할 수 없습니다.');
    }
  };

  const onFirstUserGesture = () => {
    unlock();
  };

  const speak = ({ payload, messageId, lang, speechText, rate = DEFAULT_RATE, source = 'unknown' }) => {
    if (!ensureGuard()) return false;

    const s = getSpeechSynthesis();
    if (!s || typeof SpeechSynthesisUtterance === 'undefined') return false;

    const text = normalizeText(payload).trim();
    if (!text) return false;

    const dedupKey = buildDedupKey(messageId, text);
    if (dedupKey === lastSpokenKey) return false;

    const language = lang || detectLanguage(text);
    const utterance = new SpeechSynthesisUtterance(speechText || spokenText(text, language));
    utterance.lang = language;
    // Prefer a matching installed voice; never force the OS's Korean default
    // onto English. A late-loading voice list can still use utterance.lang.
    const voices = s.getVoices();
    const locale = language.toLowerCase().replaceAll('_', '-');
    const voiceLocale = voice => voice.lang.toLowerCase().replaceAll('_', '-');
    const voice = voices.find(v => voiceLocale(v) === locale)
      || voices.find(v => voiceLocale(v).split('-')[0] === locale.split('-')[0]);
    if (voice) utterance.voice = voice;
    utterance.rate = Number.isFinite(rate) ? rate : DEFAULT_RATE;
    utterance.onerror = () => {
      setUnlockWarning?.('브라우저 TTS 재생이 차단되었습니다. 사용자 상호작용 후 다시 시도하세요.');
    };

    s.cancel();
    s.speak(utterance);
    lastSpokenKey = dedupKey;
    addLog?.('TTS', `[audio-route] browser_tts speak via ${source} (${text.length} chars)`);
    return true;
  };

  const bindFirstGestureUnlock = () => {
    if (typeof window === 'undefined') return () => {};

    const opts = { once: true, passive: true };
    window.addEventListener('pointerdown', onFirstUserGesture, opts);
    window.addEventListener('touchstart', onFirstUserGesture, opts);
    window.addEventListener('keydown', onFirstUserGesture, { once: true });

    return () => {
      window.removeEventListener('pointerdown', onFirstUserGesture);
      window.removeEventListener('touchstart', onFirstUserGesture);
      window.removeEventListener('keydown', onFirstUserGesture);
    };
  };

  return {
    synth,
    cancel,
    speak,
    bindFirstGestureUnlock,
  };
}
