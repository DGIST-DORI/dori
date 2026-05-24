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

function decodeBase64ToUint8Array(base64Text) {
  if (!base64Text || typeof atob !== 'function') return null;
  try {
    const clean = base64Text.includes(',') ? base64Text.split(',').pop() : base64Text;
    const binary = atob(clean);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

function coerceAudioBytes(rawMsg) {
  const src = rawMsg?.data ?? rawMsg;
  if (!src) return null;
  if (src instanceof Uint8Array) return src;
  if (Array.isArray(src)) return Uint8Array.from(src);
  if (ArrayBuffer.isView(src)) return new Uint8Array(src.buffer, src.byteOffset, src.byteLength);
  if (src instanceof ArrayBuffer) return new Uint8Array(src);
  if (typeof src === 'string') return decodeBase64ToUint8Array(src);
  if (typeof src === 'object') {
    if (Array.isArray(src.data)) return Uint8Array.from(src.data);
    if (typeof src.data === 'string') return decodeBase64ToUint8Array(src.data);
  }
  return null;
}

function pcm16ToFloat32(bytes) {
  const usableLen = bytes.length - (bytes.length % 2);
  const view = new DataView(bytes.buffer, bytes.byteOffset, usableLen);
  const out = new Float32Array(usableLen / 2);
  for (let i = 0; i < out.length; i += 1) {
    const sample = view.getInt16(i * 2, true);
    out[i] = Math.max(-1, sample / 32768);
  }
  return out;
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

    let prevText = '';
    const unsubStore = useStore.subscribe((state) => {
      const text = state.lastTtsText;
      if (!text || text === prevText) return;
      prevText = text;
      tts.speak({
        payload: text,
        messageId: null,
        source: 'store/lastTtsText',
      });
    });

    cleanups.push(() => {
      try { unsubStore(); } catch { return; }
      try { removeUnlockHandlers(); } catch { return; }
      tts.cancel();
    });
  }

  if (mode === AUDIO_OUTPUT_MODES.ROS_AUDIO) {
    let audioContext = null;
    let scheduledTime = 0;
    let packetCount = 0;
    let underrunCount = 0;
    const minLeadSec = 0.08;
    const rosAudioTopic = toAbsoluteTopic(profileTopics.rosAudioStreamTopic) || '/dori/audio/output';

    useStore.getState().resetRosAudioDebug?.();

    const unsub = subscribeROS(rosAudioTopic, 'audio_common_msgs/msg/AudioData', (payload, rawMsg) => {
      if (useStore.getState().audioOutputMode !== AUDIO_OUTPUT_MODES.ROS_AUDIO) return;

      const bytes = coerceAudioBytes(rawMsg) || coerceAudioBytes(payload);
      if (!bytes?.length) {
        const src = parseIncomingAudioPayload(payload);
        if (!src) return;
      }

      try {
        if (!audioContext) {
          const Ctx = window.AudioContext || window.webkitAudioContext;
          if (!Ctx) throw new Error('AudioContext unsupported');
          audioContext = new Ctx({ sampleRate: 16000 });
        }

        if (audioContext.state === 'suspended') {
          void audioContext.resume().catch(() => {
            addLog(LOG_TAGS.ERROR, '[audio-route] ros_audio resume blocked (need user gesture)');
          });
        }

        const float32 = bytes?.length ? pcm16ToFloat32(bytes) : null;
        if (!float32?.length) return;

        const buffer = audioContext.createBuffer(1, float32.length, 16000);
        buffer.copyToChannel(float32, 0, 0);

        const now = audioContext.currentTime;
        if (scheduledTime < now) {
          underrunCount += 1;
          scheduledTime = now + minLeadSec;
        }

        const source = audioContext.createBufferSource();
        source.buffer = buffer;
        source.connect(audioContext.destination);
        source.start(scheduledTime);
        scheduledTime += buffer.duration;

        packetCount += 1;
        const queueLength = Math.max(0, Math.ceil((scheduledTime - now) / 0.02));
        useStore.getState().setRosAudioDebug?.({ packets: packetCount, queueLength, underruns: underrunCount });
        if (packetCount % 50 === 0) {
          addLog(LOG_TAGS.TTS, `[audio-route] ros_audio packets=${packetCount} queue=${queueLength} underrun=${underrunCount}`);
        }
      } catch (e) {
        addLog(LOG_TAGS.ERROR, `[audio-route] ros_audio error: ${e.message}`);
      }
    });

    cleanups.push(() => {
      try { unsub(); } catch { return; }
      scheduledTime = 0;
      useStore.getState().resetRosAudioDebug?.();
      if (audioContext) {
        void audioContext.close();
        audioContext = null;
      }
    });
  }

  return () => {
    cleanups.forEach((fn) => fn());
    setActiveAudioRoute?.('none');
    addLog(LOG_TAGS.TTS, `[audio-route] deactivated: ${mode}`);
  };
}
