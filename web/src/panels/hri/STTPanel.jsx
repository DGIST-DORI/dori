import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff } from 'lucide-react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import { useI18n } from '../../core/i18n';
import { resolveProfileTopics } from '../../core/topicProfiles';
import './STTPanel.css';

// ── Constants ─────────────────────────────────────────────────────────────────

const SAMPLE_RATE   = 16000;   // Whisper expects 16 kHz

// ── Helpers ───────────────────────────────────────────────────────────────────

function pub(topic, msgType, data) {
  try {
    publishROS(topic, msgType, data);
    return true;
  } catch (e) {
    console.error('[pub] failed:', topic, e);
    return false;
  }
}

// Status badge
function Badge({ ok, label }) {
  return (
    <span className={`badge ${ok ? 'badge-ok' : 'off'}`}>{label}</span>
  );
}

// Section divider label
function SectionLabel({ children }) {
  return <div className="panel-section-label">{children}</div>;
}

// ── STT Panel ─────────────────────────────────────────────────────────────────

function STTPanel() {
  const { t } = useI18n();
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog     = useStore(s => s.addLog);
  const executionProfile = useStore(s => s.executionProfile);
  const useClientMic = useStore(s => s.useClientMic);
  const canPublish = connected || isDemoMode;

  const [text,          setText]          = useState('');
  const [lang,          setLang]          = useState('auto');
  const [conf,          setConf]          = useState('0.95');
  const [lastResult,    setLastResult]    = useState(null);
  const profileTopics = resolveProfileTopics(executionProfile);
  const [micTopicOverride, setMicTopicOverride] = useState('');

  // Mic state
  const [micAvail,      setMicAvail]      = useState(false);
  const [micActive,     setMicActive]     = useState(false);
  const [micError,      setMicError]      = useState('');
  const [micStatus,     setMicStatus]     = useState('idle'); // idle | requesting | recording | processing
  const mediaRecRef  = useRef(null);
  const streamRef    = useRef(null);
  const chunksRef    = useRef([]);

  // Check mic availability on mount
  useEffect(() => {
    navigator.mediaDevices?.getUserMedia({ audio: true })
      .then(s => { s.getTracks().forEach(t => t.stop()); setMicAvail(true); })
      .catch(() => setMicAvail(false));
  }, []);

  // Inject text manually
  function handleTextInject() {
    if (!text.trim()) return;
    const payload = {
      text:       text.trim(),
      language:   lang,
      confidence: parseFloat(conf) || 0.95,
      timestamp:  Date.now() / 1000,
      source:     'dashboard_inject',
    };
    pub('/dori/stt/result', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.STT, `[inject] "${text.trim()}" (${lang}, conf=${conf})`);
    setLastResult(payload);
    setText('');
  }

  // Start mic recording
  async function handleMicStart() {
    if (micActive) return;
    setMicError('');
    setMicStatus('requesting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: SAMPLE_RATE, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = () => handleMicStop();
      rec.start(200);
      mediaRecRef.current = rec;
      setMicActive(true);
      setMicStatus('recording');
    } catch (e) {
      setMicError(`마이크 접근 실패: ${e.message}`);
      setMicStatus('idle');
    }
  }

  function handleMicStopClick() {
    mediaRecRef.current?.stop();
    streamRef.current?.getTracks().forEach(t => t.stop());
    setMicActive(false);
    setMicStatus('processing');
  }

  // After recording stops: encode as WAV PCM16 (16k mono) and publish to STT input topic.
  async function handleMicStop() {
    const blob = new Blob(chunksRef.current, { type: 'audio/webm;codecs=opus' });
    const durationEstSec = (chunksRef.current.length * 200) / 1000;
    try {
      const wavB64 = await toWavBase64(blob);
      const micTopic = micTopicOverride.trim() || profileTopics.sttInputTopic;
      pub(micTopic, 'std_msgs/msg/String', {
        data: JSON.stringify({
          audio_b64: wavB64, format: 'wav_pcm16', sample_rate: SAMPLE_RATE, channels: 1, duration_est_sec: durationEstSec,
        }),
      });
      addLog(LOG_TAGS.STT, `[mic] audio captured ~${durationEstSec.toFixed(1)}s — published to ${micTopic} (wav_pcm16)`);
    } catch (e) {
      setMicError(`오디오 변환 실패: ${e.message}`);
    } finally {
      setMicStatus('idle');
    }
    chunksRef.current = [];
  }

  async function toWavBase64(blob) {
    const arrayBuffer = await blob.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx({ sampleRate: SAMPLE_RATE });
    const decoded = await audioCtx.decodeAudioData(arrayBuffer);
    const mono = decoded.numberOfChannels > 1 ? mixDownToMono(decoded) : decoded.getChannelData(0);
    const pcm16 = floatTo16BitPCM(mono);
    const wavBytes = buildWavBytes(pcm16, SAMPLE_RATE, 1);
    await audioCtx.close();
    return btoa(String.fromCharCode(...wavBytes));
  }

  function mixDownToMono(audioBuffer) {
    const out = new Float32Array(audioBuffer.length);
    for (let ch = 0; ch < audioBuffer.numberOfChannels; ch += 1) {
      const data = audioBuffer.getChannelData(ch);
      for (let i = 0; i < data.length; i += 1) out[i] += data[i] / audioBuffer.numberOfChannels;
    }
    return out;
  }
  function floatTo16BitPCM(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      const s = Math.max(-1, Math.min(1, input[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return out;
  }
  function buildWavBytes(pcm16, sampleRate, channels) {
    const buffer = new ArrayBuffer(44 + pcm16.length * 2);
    const view = new DataView(buffer);
    const writeStr = (offset, str) => { for (let i = 0; i < str.length; i += 1) view.setUint8(offset + i, str.charCodeAt(i)); };
    writeStr(0, 'RIFF'); view.setUint32(4, 36 + pcm16.length * 2, true); writeStr(8, 'WAVE');
    writeStr(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, channels, true); view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * channels * 2, true); view.setUint16(32, channels * 2, true); view.setUint16(34, 16, true);
    writeStr(36, 'data'); view.setUint32(40, pcm16.length * 2, true);
    let off = 44; for (let i = 0; i < pcm16.length; i += 1, off += 2) view.setInt16(off, pcm16[i], true);
    return new Uint8Array(buffer);
  }

  return (
    <div className="panel-body">
      <SectionLabel>Text Inject → /dori/stt/result</SectionLabel>

      <textarea
        className="input-text"
        rows={2}
        placeholder={t('panel.stt.placeholder')}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTextInject(); } }}
      />

      <div className="row row-wrap">
        <div className="field">
          <label className="field-label">Language</label>
          <select className="input" value={lang} onChange={e => setLang(e.target.value)}>
            <option value="ko">ko</option>
            <option value="en">en</option>
            <option value="auto">auto</option>
          </select>
        </div>
        <div className="field">
          <label className="field-label">Confidence</label>
          <input className="input" type="number" min="0" max="1" step="0.01"
            value={conf} onChange={e => setConf(e.target.value)} />
        </div>
        <button
          className="btn btn-sm btn-primary"
          disabled={!canPublish || !text.trim()}
          onClick={handleTextInject}
        >Inject STT</button>
      </div>

      {lastResult && (
        <div className="result-row">
          <span className="result-label">Last inject</span>
          <span className="result-value">"{lastResult.text}"</span>
        </div>
      )}

      <SectionLabel>Microphone → STT Input Topic ({profileTopics.sttInputTopic})</SectionLabel>
      <div className="row row-wrap">
        <div className="field" style={{ minWidth: 280 }}>
          <label className="field-label">Advanced: Mic Publish Topic Override</label>
          <input className="input" value={micTopicOverride} onChange={e => setMicTopicOverride(e.target.value)} placeholder={profileTopics.sttInputTopic} />
        </div>
      </div>

      <div className="row">
        <Badge ok={micAvail} label={micAvail ? 'Mic available' : 'Mic unavailable'} />
        <Badge ok={micActive} label={micStatus} />
      </div>

      {micError && <div className="error-text">{micError}</div>}

      <div className="row">
        {!micActive ? (
          <button
            className="btn btn-sm btn-ok btn-icon"
            disabled={!micAvail || !canPublish || !useClientMic}
            onClick={handleMicStart}
          >
            <Mic size={12} /> Start Recording
          </button>
        ) : (
          <button className="btn btn-sm btn-danger btn-icon" onClick={handleMicStopClick}>
            <MicOff size={12} /> Stop &amp; Send
          </button>
        )}
        {micActive && (
          <span className="recording-dot" />
        )}
      </div>

      <p className="hint-text">
        {t('panel.stt.hint')}
      </p>
    </div>
  );
}

export default STTPanel;
export { STTPanel };
