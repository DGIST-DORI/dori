/**
 * tabs/HRITab.jsx  — HRI Test Console
 *
 * Panels:
 *   1. STT Test       — 텍스트 inject / 브라우저 마이크 녹음 → STT result publish
 *   2. Wake Word      — /dori/stt/wake_word_detected trigger
 *   3. Vision Test    — 브라우저 카메라 → CompressedImage → /dori/camera/color/image_raw
 *   4. LLM / TTS      — 직접 query / tts text inject
 *   5. State Monitor  — HRI 상태, STT 결과, LLM 응답, TTS 텍스트 실시간 스트림
 *   6. Event Log      — 기존 EventLog 패널
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Panel from '../components/Panel';
import EventLog from '../panels/EventLog';
import { LOG_TAGS, useStore } from '../core/store';
import { publishROS } from '../core/ros';
import './HRITab.css';

// ── Constants ─────────────────────────────────────────────────────────────────

const SAMPLE_RATE   = 16000;   // Whisper expects 16 kHz
const CAM_WIDTH     = 640;
const CAM_HEIGHT    = 480;
const CAM_FPS       = 10;      // publish rate when camera is running

// ── Helpers ───────────────────────────────────────────────────────────────────

function pub(topic, msgType, data) {
  try { publishROS(topic, msgType, data); return true; }
  catch (e) { return false; }
}

function ts() { return new Date().toLocaleTimeString(); }

// Status badge
function Badge({ ok, label }) {
  return (
    <span className={`hri-badge ${ok ? 'ok' : 'off'}`}>{label}</span>
  );
}

// Section divider label
function SectionLabel({ children }) {
  return <div className="hri-section-label">{children}</div>;
}

// ── STT Panel ─────────────────────────────────────────────────────────────────

function STTPanel() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog     = useStore(s => s.addLog);
  const canPublish = connected || isDemoMode;

  const [text,          setText]          = useState('');
  const [lang,          setLang]          = useState('ko');
  const [conf,          setConf]          = useState('0.95');
  const [lastResult,    setLastResult]    = useState(null);

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
    pub('/dori/stt/result', 'std_msgs/String', { data: JSON.stringify(payload) });
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

  // After recording stops: build a fake STT result from audio blob
  // (Actual transcription happens on Jetson. Here we publish a placeholder
  //  that tells the team mic input worked, with audio length info.)
  function handleMicStop() {
    const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
    const durationEstSec = (chunksRef.current.length * 200) / 1000;

    // Convert to base64 and publish as a custom diagnostic topic
    const reader = new FileReader();
    reader.onloadend = () => {
      const b64 = reader.result.split(',')[1];
      // Publish audio blob to a debug topic (ros-side can optionally pipe to Whisper)
      pub('/dori/debug/audio_blob', 'std_msgs/String', {
        data: JSON.stringify({ audio_b64: b64, mime: 'audio/webm', duration_est_sec: durationEstSec }),
      });
      addLog(LOG_TAGS.STT, `[mic] audio captured ~${durationEstSec.toFixed(1)}s — published to /dori/debug/audio_blob`);
      setMicStatus('idle');
    };
    reader.readAsDataURL(blob);
    chunksRef.current = [];
  }

  return (
    <div className="hri-test-panel">
      <SectionLabel>Text Inject → /dori/stt/result</SectionLabel>

      <textarea
        className="hri-input-text"
        rows={2}
        placeholder="테스트할 발화를 입력하세요 (예: 도서관 어디야)"
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTextInject(); } }}
      />

      <div className="hri-row hri-row-wrap">
        <div className="hri-field">
          <label>Language</label>
          <select value={lang} onChange={e => setLang(e.target.value)}>
            <option value="ko">ko</option>
            <option value="en">en</option>
            <option value="auto">auto</option>
          </select>
        </div>
        <div className="hri-field">
          <label>Confidence</label>
          <input type="number" min="0" max="1" step="0.01"
            value={conf} onChange={e => setConf(e.target.value)} />
        </div>
        <button
          className="hri-btn primary"
          disabled={!canPublish || !text.trim()}
          onClick={handleTextInject}
        >Inject STT</button>
      </div>

      {lastResult && (
        <div className="hri-result-row">
          <span className="hri-result-label">Last inject</span>
          <span className="hri-result-val">"{lastResult.text}"</span>
        </div>
      )}

      <SectionLabel>Microphone → /dori/debug/audio_blob</SectionLabel>

      <div className="hri-row">
        <Badge ok={micAvail} label={micAvail ? 'Mic available' : 'Mic unavailable'} />
        <Badge ok={micActive} label={micStatus} />
      </div>

      {micError && <div className="hri-error">{micError}</div>}

      <div className="hri-row">
        {!micActive ? (
          <button
            className="hri-btn accent"
            disabled={!micAvail || !canPublish}
            onClick={handleMicStart}
          >
            ● Start Recording
          </button>
        ) : (
          <button className="hri-btn danger" onClick={handleMicStopClick}>
            ■ Stop &amp; Send
          </button>
        )}
        {micActive && (
          <span className="hri-recording-dot" />
        )}
      </div>

      <p className="hri-hint">
        녹음된 오디오는 <code>/dori/debug/audio_blob</code>으로 publish됩니다.
        Jetson 측에서 이 토픽을 구독해 Whisper로 전달하면 실제 STT 테스트가 가능합니다.
      </p>
    </div>
  );
}

// ── Wake Word Panel ───────────────────────────────────────────────────────────

function WakeWordPanel() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const hriState   = useStore(s => s.hriState);
  const addLog     = useStore(s => s.addLog);
  const canPublish = connected || isDemoMode;
  const [lastTs, setLastTs] = useState(null);

  function fire() {
    pub('/dori/stt/wake_word_detected', 'std_msgs/Bool', { data: true });
    addLog(LOG_TAGS.WAKE, '[test] wake word triggered from dashboard');
    setLastTs(ts());
  }

  return (
    <div className="hri-test-panel">
      <SectionLabel>Wake Word → /dori/stt/wake_word_detected</SectionLabel>
      <div className="hri-state-row">
        <span className="hri-state-key">Current HRI state</span>
        <span className={`hri-state-val hri-state-${hriState}`}>{hriState}</span>
      </div>
      <div className="hri-row">
        <button className="hri-btn accent" disabled={!canPublish} onClick={fire}>
          ▶ Trigger Wake Word
        </button>
        {lastTs && <span className="hri-hint-inline">fired at {lastTs}</span>}
      </div>
      <p className="hri-hint">
        HRI Manager가 IDLE일 때만 반응합니다. LISTENING → RESPONDING → IDLE 사이클을 테스트할 수 있습니다.
      </p>
    </div>
  );
}

// ── Vision Test Panel ─────────────────────────────────────────────────────────

function VisionPanel() {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const addLog      = useStore(s => s.addLog);
  const canPublish  = connected || isDemoMode;

  const videoRef    = useRef(null);
  const canvasRef   = useRef(null);
  const intervalRef = useRef(null);

  const [camAvail,  setCamAvail]  = useState(false);
  const [camActive, setCamActive] = useState(false);
  const [camError,  setCamError]  = useState('');
  const [topic,     setTopic]     = useState('/dori/camera/color/image_raw');
  const [fps,       setFps]       = useState(CAM_FPS);
  const [frameCount, setFrameCount] = useState(0);
  const [quality,   setQuality]   = useState(0.6);

  useEffect(() => {
    navigator.mediaDevices?.getUserMedia({ video: true })
      .then(s => { s.getTracks().forEach(t => t.stop()); setCamAvail(true); })
      .catch(() => setCamAvail(false));
    return () => stopCamera();
  }, []);

  async function startCamera() {
    setCamError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: CAM_WIDTH, height: CAM_HEIGHT, frameRate: 30 },
      });
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      setCamActive(true);
    } catch (e) {
      setCamError(`카메라 접근 실패: ${e.message}`);
    }
  }

  function stopCamera() {
    clearInterval(intervalRef.current);
    intervalRef.current = null;
    const stream = videoRef.current?.srcObject;
    stream?.getTracks().forEach(t => t.stop());
    if (videoRef.current) videoRef.current.srcObject = null;
    setCamActive(false);
    setFrameCount(0);
  }

  // Start publishing frames to ROS
  function startPublish() {
    if (intervalRef.current) return;
    const ctx = canvasRef.current.getContext('2d');
    let count = 0;
    intervalRef.current = setInterval(() => {
      if (!videoRef.current?.srcObject) return;
      canvasRef.current.width  = CAM_WIDTH;
      canvasRef.current.height = CAM_HEIGHT;
      ctx.drawImage(videoRef.current, 0, 0, CAM_WIDTH, CAM_HEIGHT);
      const dataUrl = canvasRef.current.toDataURL('image/jpeg', quality);
      const b64 = dataUrl.split(',')[1];
      pub(topic, 'sensor_msgs/CompressedImage', {
        header: { stamp: { sec: Math.floor(Date.now() / 1000), nanosec: 0 }, frame_id: 'camera_color_frame' },
        format: 'jpeg',
        data:   b64,
      });
      count++;
      setFrameCount(count);
    }, Math.round(1000 / fps));
    addLog(LOG_TAGS.SYS, `[vision] publishing camera → ${topic} @ ${fps} Hz`);
  }

  function stopPublish() {
    clearInterval(intervalRef.current);
    intervalRef.current = null;
    addLog(LOG_TAGS.SYS, `[vision] stopped publishing (${frameCount} frames sent)`);
  }

  const isPublishing = !!intervalRef.current;

  return (
    <div className="hri-test-panel">
      <SectionLabel>Camera → ROS CompressedImage</SectionLabel>

      <div className="hri-row hri-row-wrap">
        <Badge ok={camAvail}  label={camAvail  ? 'Camera available' : 'No camera'} />
        <Badge ok={camActive} label={camActive ? 'Preview active'   : 'Off'} />
        {isPublishing && <Badge ok={true} label={`Publishing ×${frameCount}`} />}
      </div>

      {camError && <div className="hri-error">{camError}</div>}

      {/* Live preview */}
      <div className="hri-cam-preview">
        <video ref={videoRef} className="hri-cam-video" muted playsInline />
        <canvas ref={canvasRef} className="hri-cam-canvas" />
        {!camActive && (
          <div className="hri-cam-placeholder">
            <span>📷</span>
            <span>카메라 꺼짐</span>
          </div>
        )}
      </div>

      <div className="hri-field hri-field-full">
        <label>Target topic</label>
        <select value={topic} onChange={e => setTopic(e.target.value)}>
          <option value="/dori/camera/color/image_raw">/dori/camera/color/image_raw</option>
          <option value="/dori/camera/rear/color/image_raw">/dori/camera/rear/color/image_raw</option>
        </select>
      </div>

      <div className="hri-row hri-row-wrap">
        <div className="hri-field">
          <label>Publish Hz</label>
          <input type="number" min="1" max="30" step="1"
            value={fps} onChange={e => setFps(Number(e.target.value))} />
        </div>
        <div className="hri-field">
          <label>JPEG quality</label>
          <input type="number" min="0.1" max="1" step="0.1"
            value={quality} onChange={e => setQuality(Number(e.target.value))} />
        </div>
      </div>

      <div className="hri-row">
        {!camActive ? (
          <button className="hri-btn accent" disabled={!camAvail} onClick={startCamera}>
            📷 Start Preview
          </button>
        ) : (
          <button className="hri-btn danger" onClick={stopCamera}>
            ✕ Stop Camera
          </button>
        )}

        {camActive && !isPublishing && (
          <button className="hri-btn primary" disabled={!canPublish} onClick={startPublish}>
            ▶ Publish Frames
          </button>
        )}
        {isPublishing && (
          <button className="hri-btn warning" onClick={stopPublish}>
            ■ Stop Publishing
          </button>
        )}
      </div>

      <p className="hri-hint">
        프레임은 <code>sensor_msgs/CompressedImage</code>로 publish됩니다.
        person_detection, gesture, expression 노드가 구독 중이라면 실시간 비전 테스트가 가능합니다.
      </p>
    </div>
  );
}

// ── LLM / TTS Panel ───────────────────────────────────────────────────────────

function LLMTTSPanel() {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const addLog      = useStore(s => s.addLog);
  const canPublish  = connected || isDemoMode;
  const lastLlmResp = useStore(s => s.lastLlmResponse);
  const lastTts     = useStore(s => s.lastTtsText);

  const [llmQuery,  setLlmQuery]  = useState('');
  const [ttsText,   setTtsText]   = useState('');
  const [locCtx,    setLocCtx]    = useState('');
  const [mode,      setMode]      = useState('llm'); // 'llm' | 'tts'

  function handleLLM() {
    if (!llmQuery.trim()) return;
    const payload = {
      user_text:        llmQuery.trim(),
      location_context: locCtx.trim(),
      hri_state:        'RESPONDING',
      timestamp:        Date.now() / 1000,
      source:           'dashboard_inject',
    };
    pub('/dori/llm/query', 'std_msgs/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.LLM, `[inject] "${llmQuery.trim()}"`);
    setLlmQuery('');
  }

  function handleTTS() {
    if (!ttsText.trim()) return;
    pub('/dori/tts/text', 'std_msgs/String', { data: ttsText.trim() });
    addLog(LOG_TAGS.TTS, `[inject] "${ttsText.trim()}"`);
    setTtsText('');
  }

  return (
    <div className="hri-test-panel">
      <div className="hri-tab-row">
        <button className={`hri-tab-btn ${mode === 'llm' ? 'active' : ''}`} onClick={() => setMode('llm')}>LLM Query</button>
        <button className={`hri-tab-btn ${mode === 'tts' ? 'active' : ''}`} onClick={() => setMode('tts')}>TTS Direct</button>
      </div>

      {mode === 'llm' && (
        <>
          <SectionLabel>LLM Query → /dori/llm/query</SectionLabel>
          <textarea
            className="hri-input-text"
            rows={2}
            placeholder="질문 (예: 학생식당 어디에 있어요?)"
            value={llmQuery}
            onChange={e => setLlmQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleLLM(); } }}
          />
          <div className="hri-field hri-field-full">
            <label>Location context (optional)</label>
            <input
              type="text"
              placeholder="예: E7 건물 앞"
              value={locCtx}
              onChange={e => setLocCtx(e.target.value)}
            />
          </div>
          <button className="hri-btn primary" disabled={!canPublish || !llmQuery.trim()} onClick={handleLLM}>
            Send to LLM
          </button>
          {lastLlmResp && (
            <div className="hri-result-row hri-result-multiline">
              <span className="hri-result-label">LLM response</span>
              <span className="hri-result-val">{typeof lastLlmResp === 'string' ? lastLlmResp : JSON.stringify(lastLlmResp)}</span>
            </div>
          )}
        </>
      )}

      {mode === 'tts' && (
        <>
          <SectionLabel>TTS Direct → /dori/tts/text</SectionLabel>
          <textarea
            className="hri-input-text"
            rows={3}
            placeholder="로봇이 말할 텍스트 (예: 안녕하세요, 도리입니다.)"
            value={ttsText}
            onChange={e => setTtsText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTTS(); } }}
          />
          <button className="hri-btn primary" disabled={!canPublish || !ttsText.trim()} onClick={handleTTS}>
            Speak
          </button>
          {lastTts && (
            <div className="hri-result-row">
              <span className="hri-result-label">Last TTS</span>
              <span className="hri-result-val">"{lastTts}"</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── State Monitor Panel ───────────────────────────────────────────────────────

function StateMonitorPanel() {
  const hriState      = useStore(s => s.hriState);
  const hriElapsed    = useStore(s => s.hriStateElapsed);
  const lastStt       = useStore(s => s.lastSttText);
  const lastLlm       = useStore(s => s.lastLlmResponse);
  const lastTts       = useStore(s => s.lastTtsText);
  const ttsActive     = useStore(s => s.ttsActive);
  const gesture       = useStore(s => s.gesture);
  const expression    = useStore(s => s.expression);
  const trackState    = useStore(s => s.trackingState);

  const STATE_COLOR = {
    IDLE:       'var(--text-2)',
    LISTENING:  'var(--accent)',
    RESPONDING: 'var(--yellow)',
    NAVIGATING: 'var(--green)',
  };

  function Row({ label, value, color }) {
    return (
      <div className="hri-monitor-row">
        <span className="hri-monitor-key">{label}</span>
        <span className="hri-monitor-val" style={color ? { color } : {}}>{value || '—'}</span>
      </div>
    );
  }

  return (
    <div className="hri-monitor-panel">
      {/* HRI State — big indicator */}
      <div className="hri-state-indicator" style={{ borderColor: STATE_COLOR[hriState] || 'var(--border)' }}>
        <span className="hri-state-indicator-label">HRI STATE</span>
        <span className="hri-state-indicator-value" style={{ color: STATE_COLOR[hriState] || 'var(--text-0)' }}>
          {hriState}
        </span>
        <span className="hri-state-indicator-elapsed">{hriElapsed?.toFixed(1)}s</span>
      </div>

      <Row label="STT result"   value={lastStt} />
      <Row label="LLM response" value={typeof lastLlm === 'string' ? lastLlm.slice(0, 80) + (lastLlm.length > 80 ? '…' : '') : ''} />
      <Row label="TTS text"     value={lastTts} color={ttsActive ? 'var(--orange)' : undefined} />
      <Row label="TTS active"   value={ttsActive ? '● speaking' : '○ silent'} color={ttsActive ? 'var(--orange)' : 'var(--text-2)'} />
      <Row label="Gesture"      value={gesture} />
      <Row label="Expression"   value={expression} />
      <Row label="Tracking"     value={trackState ? `${trackState.state} (target: ${trackState.target_id ?? '—'}, ${trackState.last_distance_m ?? '?'}m)` : '—'} />
    </div>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────────

export default function HRITab() {
  const log = useStore(s => s.log);

  return (
    <div className="hri-layout">

      {/* ── Col 1: STT + Wake Word ── */}
      <div className="hri-col">
        <Panel title="STT Test">
          <STTPanel />
        </Panel>
        <Panel title="Wake Word">
          <WakeWordPanel />
        </Panel>
      </div>

      {/* ── Col 2: Vision + LLM/TTS ── */}
      <div className="hri-col">
        <Panel title="Vision Test">
          <VisionPanel />
        </Panel>
        <Panel title="LLM / TTS Inject">
          <LLMTTSPanel />
        </Panel>
      </div>

      {/* ── Col 3: State Monitor + Event Log ── */}
      <div className="hri-col hri-col-right">
        <Panel title="HRI State Monitor">
          <StateMonitorPanel />
        </Panel>
        <Panel title="Event Log" badge={log.length} className="hri-panel-log">
          <EventLog />
        </Panel>
      </div>

    </div>
  );
}
