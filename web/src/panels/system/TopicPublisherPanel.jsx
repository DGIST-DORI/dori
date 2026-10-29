import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import './TopicPublisherPanel.css';

const ALLOWED_TOPICS = [
  '/dori/tts/text',
  '/dori/stt/result',
  '/dori/hri/interaction_trigger',
  '/dori/hri/gesture_command',
  '/dori/hri/expression_command',
];

export default function TopicPublisherPanel() {
  const connected = useStore((s) => s.connected);
  const isDemoMode = useStore((s) => s.isDemoMode);
  const isPublishing = useStore((s) => s.isPublishing);
  const lastPublishAt = useStore((s) => s.lastPublishAt);
  const publishError = useStore((s) => s.publishError);
  const addLog = useStore((s) => s.addLog);
  const setPublishState = useStore((s) => s.setPublishState);

  const [topic, setTopic] = useState('/dori/tts/text');
  const [msgType, setMsgType] = useState('std_msgs/msg/String');
  const [jsonPayload, setJsonPayload] = useState('{"data":"hello"}');
  const [mode, setMode] = useState('once');
  const [rateHz, setRateHz] = useState('1');
  const intervalRef = useRef(null);

  const canPublish = connected || isDemoMode;
  const rateValue = Number(rateHz);
  const isRateValid = Number.isFinite(rateValue) && rateValue > 0;
  const isTopicAllowed = useMemo(() => ALLOWED_TOPICS.includes(topic), [topic]);

  const stopPeriodic = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setPublishState({ isPublishing: false });
  }, [setPublishState]);

  const publishOnce = useCallback(() => {
    if (!isTopicAllowed) {
      const err = `Blocked by allowlist: ${topic}`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    let payload;
    try {
      payload = JSON.parse(jsonPayload);
    } catch (e) {
      const err = `Invalid JSON: ${e.message}`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
      const err = 'Payload must be a JSON object.';
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    if (!msgType.includes('/')) {
      const err = `Invalid message type: "${msgType}".`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    try {
      publishROS(topic, msgType, payload);
      setPublishState({ lastPublishAt: Date.now(), publishError: null });
      return true;
    } catch (e) {
      const err = `Publish failed: ${e.message}`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }
  }, [addLog, isTopicAllowed, jsonPayload, msgType, setPublishState, topic]);

  const startPeriodic = useCallback(() => {
    if (!isRateValid) {
      const err = `Invalid rateHz: ${rateHz}`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return;
    }

    stopPeriodic();
    setPublishState({ isPublishing: true, publishError: null });
    if (!publishOnce()) {
      stopPeriodic();
      return;
    }

    intervalRef.current = setInterval(() => {
      if (!publishOnce()) stopPeriodic();
    }, Math.max(20, Math.round(1000 / rateValue)));
  }, [addLog, isRateValid, publishOnce, rateHz, rateValue, setPublishState, stopPeriodic]);

  const handlePublishClick = () => {
    if (!canPublish) return;
    if (mode === 'once') {
      stopPeriodic();
      publishOnce();
      return;
    }
    if (isPublishing) {
      stopPeriodic();
      return;
    }
    startPeriodic();
  };

  useEffect(() => () => stopPeriodic(), [stopPeriodic]);

  return (
    <div className="tp-panel-root">
      <div className="tp-body">
        <div className="tp-row">
          <label htmlFor="tp-topic">Topic</label>
          <select id="tp-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
            {ALLOWED_TOPICS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="tp-row">
          <label htmlFor="tp-type">Msg type</label>
          <input id="tp-type" value={msgType} onChange={(e) => setMsgType(e.target.value)} placeholder="std_msgs/msg/String" />
        </div>
        <div className="tp-row">
          <label htmlFor="tp-json">JSON payload</label>
          <textarea id="tp-json" value={jsonPayload} onChange={(e) => setJsonPayload(e.target.value)} rows={8} spellCheck={false} />
        </div>
        <div className="tp-row tp-inline">
          <label>Mode</label>
          <div className="tp-seg">
            <button className={mode === 'once' ? 'active' : ''} onClick={() => setMode('once')}>Once</button>
            <button className={mode === 'periodic' ? 'active' : ''} onClick={() => setMode('periodic')}>Periodic</button>
          </div>
          {mode === 'periodic' && (
            <div className="tp-rate-wrap">
              <label htmlFor="tp-rate">Rate (Hz)</label>
              <input id="tp-rate" value={rateHz} onChange={(e) => setRateHz(e.target.value)} style={{ width: 80 }} />
            </div>
          )}
        </div>
        <div className="tp-footer">
          <button className="tp-publish-btn" onClick={handlePublishClick} disabled={!canPublish}>
            {mode === 'periodic' && isPublishing ? 'Stop' : 'Publish'}
          </button>
          <span className="tp-status">
            {!canPublish ? 'ROS not connected' : publishError ? `Error: ${publishError}` : lastPublishAt ? `Last publish: ${new Date(lastPublishAt).toLocaleTimeString()}` : 'Ready'}
          </span>
        </div>

      </div>
    </div>
  );
}
