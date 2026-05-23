import { useEffect, useRef, useState } from 'react';
import {
  Camera, CameraOff, Square, Play,
} from 'lucide-react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import { useI18n } from '../../core/i18n';
import { resolveProfileTopics } from '../../core/topicProfiles';
import './VisionPanel.css';

// ── Constants ─────────────────────────────────────────────────────────────────

const CAM_WIDTH     = 640;
const CAM_HEIGHT    = 480;
const CAM_FPS       = 10;      // publish rate when camera is running

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

// ── Vision Test Panel ─────────────────────────────────────────────────────────

function VisionPanel() {
  const { t } = useI18n();
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const addLog      = useStore(s => s.addLog);
  const executionProfile = useStore(s => s.executionProfile);
  const useClientCam = useStore(s => s.useClientCam);
  const canPublish  = connected || isDemoMode;

  const videoRef    = useRef(null);
  const canvasRef   = useRef(null);
  const intervalRef = useRef(null);

  const [camAvail,  setCamAvail]  = useState(false);
  const [camActive, setCamActive] = useState(false);
  const [camError,  setCamError]  = useState('');
  const profileTopics = resolveProfileTopics(executionProfile);
  const [topicOverride, setTopicOverride] = useState('');
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
      const topic = topicOverride.trim() || profileTopics.visionInputTopic;
      pub(topic, 'sensor_msgs/msg/CompressedImage', {
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
    <div className="panel-body">
      <SectionLabel>Camera → ROS CompressedImage ({profileTopics.visionInputTopic})</SectionLabel>

      <div className="row row-wrap">
        <Badge ok={camAvail}  label={camAvail  ? 'Camera available' : 'No camera'} />
        <Badge ok={camActive} label={camActive ? 'Preview active'   : 'Off'} />
        {isPublishing && <Badge ok={true} label={`Publishing ×${frameCount}`} />}
      </div>

      {camError && <div className="error-text">{camError}</div>}

      {/* Live preview */}
      <div className="hri-cam-preview">
        <video ref={videoRef} className="hri-cam-video" muted playsInline />
        <canvas ref={canvasRef} className="hri-cam-canvas" />
        {!camActive && (
          <div className="hri-cam-placeholder">
            <Camera size={28} strokeWidth={1.5} />
            <span>카메라 꺼짐</span>
          </div>
        )}
      </div>

      <div className="field field-full">
        <label className="field-label">Advanced: Target topic override</label>
        <input className="input input-full" value={topicOverride} onChange={e => setTopicOverride(e.target.value)} placeholder={profileTopics.visionInputTopic} />
      </div>

      <div className="row row-wrap">
        <div className="field">
          <label className="field-label">Publish Hz</label>
          <input className="input" type="number" min="1" max="30" step="1"
            value={fps} onChange={e => setFps(Number(e.target.value))} />
        </div>
        <div className="field">
          <label className="field-label">JPEG quality</label>
          <input className="input" type="number" min="0.1" max="1" step="0.1"
            value={quality} onChange={e => setQuality(Number(e.target.value))} />
        </div>
      </div>

      <div className="row">
        {!camActive ? (
          <button className="btn btn-sm btn-ok btn-icon" disabled={!camAvail || !useClientCam} onClick={startCamera}>
            <Camera size={12} /> Start Preview
          </button>
        ) : (
          <button className="btn btn-sm btn-danger btn-icon" onClick={stopCamera}>
            <CameraOff size={12} /> Stop Camera
          </button>
        )}

        {camActive && !isPublishing && (
          <button className="btn btn-sm btn-primary btn-icon" disabled={!canPublish} onClick={startPublish}>
            <Play size={12} /> Publish Frames
          </button>
        )}
        {isPublishing && (
          <button className="btn btn-sm btn-warn btn-icon" onClick={stopPublish}>
            <Square size={12} /> Stop Publishing
          </button>
        )}
      </div>

      <p className="hint-text">
        {t('panel.vision.hint')}
      </p>
    </div>
  );
}

export default VisionPanel;
export { VisionPanel };
