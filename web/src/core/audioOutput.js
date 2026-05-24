import { subscribeROS } from './ros';
import { AUDIO_OUTPUT_MODES, resolveProfileTopics } from './topicProfiles';
import { LOG_TAGS, useStore } from './store';
import { createBrowserTtsController } from './browserTts';

function parseIncomingAudioPayload(raw) {
  if (!raw) return null;
  if (typeof raw === 'string') return raw;
  if (typeof raw === 'object') {
    if (typeof raw.audio_url === 'string') return raw.audio_url;
    if (typeof raw.url === 'string') return raw.url;
    if (typeof raw.audio_b64 === 'string') return `data:audio/wav;base64,${raw.audio_b64}`;
    if (typeof raw.data === 'string') return raw.data;
  }
  return null;
}

function toAbsoluteTopic(topic) {
  if (!topic) return null;
  return topic.startsWith('/') ? topic : `/dori/${topic}`;
}

export function createAudioOutputRouter({ mode, executionProfile, addLog, setActiveAudioRoute }) {
  const cleanups = [];
  const profileTopics = resolveProfileTopics(executionProfile);

  addLog(LOG_TAGS.TTS, `[audio-route] activated: ${mode}`);
  setActiveAudioRoute?.(mode);

  if (mode === AUDIO_OUTPUT_MODES.BROWSER_TTS) {
    const tts = createBrowserTtsController({
      addLog,
      setUnlockWarning: (msg) => useStore.getState().setBrowserTtsWarning(msg),
      getAudioOutputMode: () => useStore.getState().audioOutputMode,
      browserTtsMode: AUDIO_OUTPUT_MODES.BROWSER_TTS,
    });

    const removeUnlockHandlers = tts.bindFirstGestureUnlock();
    const unsub = subscribeROS('/dori/tts/text', undefined, (payload, rawMsg) => {
      tts.speak({
        payload,
        messageId: rawMsg?.id || rawMsg?.header?.stamp,
        source: '/dori/tts/text',
      });
    });

    cleanups.push(() => {
      try { unsub(); } catch { return; }
      try { removeUnlockHandlers(); } catch { return; }
      tts.cancel();
    });
  }

  if (mode === AUDIO_OUTPUT_MODES.ROS_AUDIO) {
    let currentAudio = null;
    const rosAudioTopic = toAbsoluteTopic(profileTopics.rosAudioStreamTopic) || '/dori/audio/output';
    const unsub = subscribeROS(rosAudioTopic, undefined, (payload) => {
      const src = parseIncomingAudioPayload(payload);
      if (!src || typeof Audio === 'undefined') return;
      try {
        if (currentAudio) {
          currentAudio.pause();
          currentAudio = null;
        }
        currentAudio = new Audio(src);
        void currentAudio.play().catch(() => {
          addLog(LOG_TAGS.ERROR, '[audio-route] ros_audio play failed (autoplay blocked or invalid source)');
        });
        addLog(LOG_TAGS.TTS, `[audio-route] ros_audio play: ${rosAudioTopic}`);
      } catch (e) {
        addLog(LOG_TAGS.ERROR, `[audio-route] ros_audio error: ${e.message}`);
      }
    });

    cleanups.push(() => {
      try { unsub(); } catch { return; }
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }
    });
  }

  return () => {
    cleanups.forEach((fn) => fn());
    setActiveAudioRoute?.('none');
    addLog(LOG_TAGS.TTS, `[audio-route] deactivated: ${mode}`);
  };
}
