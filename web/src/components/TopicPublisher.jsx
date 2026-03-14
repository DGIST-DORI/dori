/**
 * components/TopicPublisher.jsx
 * Global floating Topic Publisher — accessible from any tab.
 *
 * Collapsed: small "PUB" button pinned to bottom-right.
 * Expanded:  panel slides up with full publisher UI.
 *
 * Logic extracted from SystemTab; SystemTab now imports this too.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { LOG_TAGS, useStore } from '../core/store';
import { publishROS } from '../core/ros';
import './TopicPublisher.css';

const DANGEROUS_TOPICS = new Set([
  '/cmd_vel',
  '/cmd_vel_mux/input/teleop',
  '/dori/nav/command',
]);

export const ALLOWED_TOPICS = [
  '/dori/nav/command',
  '/dori/hri/interaction_trigger',
  '/dori/hri/gesture_command',
  '/dori/hri/expression_command',
  '/dori/tts/text',
  '/dori/llm/query',
  '/cmd_vel',
];

export default function TopicPublisher() {
  const connected       = useStore((s) => s.connected);
  const isDemoMode      = useStore((s) => s.isDemoMode);
  const isPublishing    = useStore((s) => s.isPublishing);
  const lastPublishAt   = useStore((s) => s.lastPublishAt);
  const publishError    = useStore((s) => s.publishError);
  const addLog          = useStore((s) => s.addLog);
  const setPublishState = useStore((s) => s.setPublishState);

  const [open,        setOpen]        = useState(false);
  const [topic,       setTopic]       = useState('/dori/nav/command');
  const [msgType,     setMsgType]     = useState('std_msgs/String');
  const [jsonPayload, setJsonPayload] = useState('{"data":"hello"}');
  const [mode,        setMode]        = useState('once');
  const [rateHz,      setRateHz]      = useState('1');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const intervalRef = useRef(null);

  const canPublish     = connected || isDemoMode;
  const rateValue      = Number(rateHz);
  const isRateValid    = Number.isFinite(rateValue) && rateValue > 0;
  const isTopicAllowed = useMemo(() => ALLOWED_TOPICS.includes(topic), [topic]);

  const stopPeriodic = useCallback(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
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
    try { payload = JSON.parse(jsonPayload); }
    catch (e) {
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
    if (!publishOnce()) { stopPeriodic(); return; }
    intervalRef.current = setInterval(() => {
      if (!publishOnce()) stopPeriodic();
    }, Math.max(20, Math.round(1000 / rateValue)));
  }, [addLog, isRateValid, publishOnce, rateHz, rateValue, setPublishState, stopPeriodic]);

  const handlePublishClick = () => {
    if (!canPublish) return;
    if (DANGEROUS_TOPICS.has(topic) && !confirmOpen) { setConfirmOpen(true); return; }
    if (mode === 'once') { stopPeriodic(); publishOnce(); return; }
    if (isPublishing)   { stopPeriodic(); return; }
    startPeriodic();
  };

  useEffect(() => () => stopPeriodic(), [stopPeriodic]);

  return (
    <>
      {/* ── Floating trigger button ── */}
      <button
        className={`tp-fab ${open ? 'open' : ''} ${isPublishing ? 'publishing' : ''}`}
        onClick={() => setOpen(v => !v)}
        title="Topic Publisher"
        aria-label="Toggle Topic Publisher"
      >
        <span className="tp-fab-label">PUB</span>
        {isPublishing && <span className="tp-fab-dot" />}
      </button>

      {/* ── Slide-up panel ── */}
      <div className={`tp-panel ${open ? 'visible' : ''}`} role="complementary" aria-label="Topic Publisher">
        <div className="tp-panel-header">
          <span className="tp-panel-title">Topic Publisher</span>
          <button className="tp-panel-close" onClick={() => setOpen(false)} aria-label="Close">
            <X size={11} strokeWidth={2} />
          </button>
        </div>

        <div className="tp-body">
          <div className="tp-row">
            <label htmlFor="tp-topic">Topic</label>
            <select id="tp-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
              {ALLOWED_TOPICS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div className="tp-row">
            <label htmlFor="tp-type">Msg type</label>
            <input
              id="tp-type"
              value={msgType}
              onChange={(e) => setMsgType(e.target.value)}
              placeholder="std_msgs/String"
            />
          </div>

          <div className="tp-row tp-row-col">
            <label htmlFor="tp-payload">JSON payload</label>
            <textarea
              id="tp-payload"
              value={jsonPayload}
              onChange={(e) => setJsonPayload(e.target.value)}
              rows={4}
              spellCheck={false}
            />
          </div>

          <div className="tp-mode-row">
            <label>
              <input type="radio" name="tp-mode" checked={mode === 'once'}     onChange={() => setMode('once')} />
              Once
            </label>
            <label>
              <input type="radio" name="tp-mode" checked={mode === 'periodic'} onChange={() => setMode('periodic')} />
              Periodic
            </label>
            <span className="tp-hz-label">Hz</span>
            <input
              className="tp-hz-input"
              type="number" min="0.1" step="0.1"
              value={rateHz}
              onChange={(e) => setRateHz(e.target.value)}
              disabled={mode !== 'periodic'}
            />
          </div>

          <div className="tp-actions">
            <button
              type="button"
              className={`tp-btn ${isPublishing ? 'stop' : canPublish ? 'active' : ''}`}
              disabled={!canPublish}
              onClick={handlePublishClick}
            >
              {mode === 'periodic'
                ? (isPublishing ? 'Stop' : 'Start Publishing')
                : 'Publish Once'}
            </button>

            <div className="tp-status">
              <span className={`tp-status-dot ${isPublishing ? 'publishing' : publishError ? 'error' : ''}`} />
              {isPublishing && <span>publishing</span>}
              {lastPublishAt && !isPublishing && (
                <span>last: {new Date(lastPublishAt).toLocaleTimeString()}</span>
              )}
            </div>
          </div>

          {publishError && <div className="tp-error">{publishError}</div>}
        </div>
      </div>

      {/* ── Dangerous topic confirm ── */}
      {confirmOpen && (
        <div className="tp-confirm-overlay" role="dialog" aria-modal="true">
          <div className="tp-confirm-modal">
            <h4>Dangerous Topic</h4>
            <p>Publishing to <code>{topic}</code> may cause robot motion. Continue?</p>
            <div className="tp-confirm-actions">
              <button type="button" onClick={() => setConfirmOpen(false)}>Cancel</button>
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setConfirmOpen(false);
                  if (mode === 'once') { stopPeriodic(); publishOnce(); return; }
                  if (isPublishing)   { stopPeriodic(); return; }
                  startPeriodic();
                }}
              >Confirm</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
