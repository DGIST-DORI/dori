import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { LOG_TAGS, TOPIC_META, useStore } from '../core/store';
import { publishROS } from '../core/ros';
import { parseWsUrl } from '../core/url';
import './SystemTab.css';

const fmt = (val, suffix = '') => (val === null || val === undefined ? 'N/A' : `${val}${suffix}`);
const DANGEROUS_TOPICS = new Set(['/cmd_vel', '/cmd_vel_mux/input/teleop', '/dori/nav/command']);
const ALLOWED_TOPICS = [
  '/dori/nav/command',
  '/dori/hri/interaction_trigger',
  '/dori/hri/gesture_command',
  '/dori/hri/expression_command',
  '/dori/tts/text',
  '/dori/llm/query',
  '/cmd_vel',
];

const thresholdClass = (value, warningThreshold) => {
  if (value === null || value === undefined) return '';
  return value >= warningThreshold ? 'sys-metric-value is-warning' : 'sys-metric-value';
};

export default function SystemTab() {
  const topicStats = useStore((s) => s.topicStats);
  const connected = useStore((s) => s.connected);
  const isDemoMode = useStore((s) => s.isDemoMode);
  const wsUrl = useStore((s) => s.wsUrl);
  const systemMetrics = useStore((s) => s.systemMetrics);
  const isPublishing = useStore((s) => s.isPublishing);
  const lastPublishAt = useStore((s) => s.lastPublishAt);
  const publishError = useStore((s) => s.publishError);
  const addLog = useStore((s) => s.addLog);
  const setPublishState = useStore((s) => s.setPublishState);

  const topics = Object.keys(TOPIC_META);
  const parsedWsUrl = parseWsUrl(wsUrl);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [topic, setTopic] = useState('/dori/nav/command');
  const [msgType, setMsgType] = useState('std_msgs/String');
  const [jsonPayload, setJsonPayload] = useState('{"data":"hello"}');
  const [mode, setMode] = useState('once');
  const [rateHz, setRateHz] = useState('1');
  const [confirmOpen, setConfirmOpen] = useState(false);
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
      const err = `Invalid JSON payload: ${e.message}`;
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
      const err = 'Payload type mismatch: ROS message payload must be a JSON object.';
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }

    if (!msgType.includes('/')) {
      const err = `Message type mismatch: "${msgType}" is invalid. Use format like pkg/Type.`;
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
    const tickMs = Math.max(20, Math.round(1000 / rateValue));
    setPublishState({ isPublishing: true, publishError: null });

    const ok = publishOnce();
    if (!ok) {
      stopPeriodic();
      return;
    }

    intervalRef.current = setInterval(() => {
      const successful = publishOnce();
      if (!successful) stopPeriodic();
    }, tickMs);
  }, [addLog, isRateValid, publishOnce, rateHz, rateValue, setPublishState, stopPeriodic]);

  const handlePublishClick = () => {
    if (!canPublish) return;
    if (DANGEROUS_TOPICS.has(topic) && !confirmOpen) {
      setConfirmOpen(true);
      return;
    }
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

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => () => stopPeriodic(), [stopPeriodic]);

  return (
    <div className="sys-layout">
      <Panel title="System Metrics">
        <div className="sys-metrics-grid">
          <div className="sys-metric-card">
            <h4>CPU</h4>
            <div className="sys-metric-row"><span>Usage</span><span className={thresholdClass(systemMetrics?.cpu?.usage_pct, 85)}>{fmt(systemMetrics?.cpu?.usage_pct, '%')}</span></div>
            <div className="sys-metric-row"><span>Logical Cores</span><span className="sys-metric-value">{fmt(systemMetrics?.cpu?.count_logical)}</span></div>
            <div className="sys-metric-row"><span>Load Avg (1/5/15)</span><span className="sys-metric-value">{systemMetrics?.cpu?.load_avg_1_5_15?.join(' / ') || 'N/A'}</span></div>
          </div>

          <div className="sys-metric-card">
            <h4>GPU</h4>
            <div className="sys-metric-row"><span>Provider</span><span className="sys-metric-value">{fmt(systemMetrics?.gpu?.provider)}</span></div>
            <div className="sys-metric-row"><span>Usage</span><span className={thresholdClass(systemMetrics?.gpu?.utilization_pct, 90)}>{fmt(systemMetrics?.gpu?.utilization_pct, '%')}</span></div>
            <div className="sys-metric-row"><span>Memory</span><span className="sys-metric-value">{systemMetrics?.gpu?.memory_used_mb !== null && systemMetrics?.gpu?.memory_total_mb !== null ? `${systemMetrics?.gpu?.memory_used_mb} / ${systemMetrics?.gpu?.memory_total_mb} MB` : 'N/A'}</span></div>
            <div className="sys-metric-row"><span>Temp</span><span className={thresholdClass(systemMetrics?.gpu?.temperature_c, 80)}>{fmt(systemMetrics?.gpu?.temperature_c, '°C')}</span></div>
          </div>

          <div className="sys-metric-card">
            <h4>RAM</h4>
            <div className="sys-metric-row"><span>Usage</span><span className={thresholdClass(systemMetrics?.ram?.usage_pct, 85)}>{fmt(systemMetrics?.ram?.usage_pct, '%')}</span></div>
            <div className="sys-metric-row"><span>Used</span><span className="sys-metric-value">{fmt(systemMetrics?.ram?.used_mb, ' MB')}</span></div>
            <div className="sys-metric-row"><span>Total</span><span className="sys-metric-value">{fmt(systemMetrics?.ram?.total_mb, ' MB')}</span></div>
          </div>
        </div>
      </Panel>

      <Panel title="Topic Publisher">
        <div className="sys-publisher">
          <div className="sys-pub-row">
            <label htmlFor="sys-pub-topic">Topic</label>
            <select id="sys-pub-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
              {ALLOWED_TOPICS.map((allowed) => <option key={allowed} value={allowed}>{allowed}</option>)}
            </select>
          </div>

          <div className="sys-pub-row">
            <label htmlFor="sys-pub-type">msgType</label>
            <input id="sys-pub-type" value={msgType} onChange={(e) => setMsgType(e.target.value)} placeholder="std_msgs/String" />
          </div>

          <div className="sys-pub-row sys-pub-row-column">
            <label htmlFor="sys-pub-payload">JSON payload</label>
            <textarea
              id="sys-pub-payload"
              value={jsonPayload}
              onChange={(e) => setJsonPayload(e.target.value)}
              rows={6}
              spellCheck={false}
            />
          </div>

          <div className="sys-pub-mode-row">
            <label><input type="radio" name="sys-pub-mode" checked={mode === 'once'} onChange={() => setMode('once')} /> once</label>
            <label><input type="radio" name="sys-pub-mode" checked={mode === 'periodic'} onChange={() => setMode('periodic')} /> periodic</label>
            <label htmlFor="sys-pub-rate">rateHz</label>
            <input
              id="sys-pub-rate"
              type="number"
              min="0.1"
              step="0.1"
              value={rateHz}
              onChange={(e) => setRateHz(e.target.value)}
              disabled={mode !== 'periodic'}
            />
          </div>

          <div className="sys-pub-actions">
            <button type="button" disabled={!canPublish} onClick={handlePublishClick}>
              {mode === 'periodic' ? (isPublishing ? 'Stop Publishing' : 'Start Publishing') : 'Publish Once'}
            </button>
            <div className="sys-pub-status">
              <span>isPublishing: {isPublishing ? 'YES' : 'NO'}</span>
              <span>lastPublishAt: {lastPublishAt ? new Date(lastPublishAt).toLocaleTimeString() : 'N/A'}</span>
              <span style={{ color: publishError ? 'var(--red)' : 'var(--text-1)' }}>
                publishError: {publishError || 'none'}
              </span>
            </div>
          </div>
        </div>
      </Panel>

      <Panel title="Topic Diagnostics">
        <div className="sys-topic-diag">
          <div className="sys-topic-diag-header">
            <span
              className="sys-tooltip"
              title="Estimated bandwidth (B/s) = total JSON payload bytes / rolling window seconds. Payload bytes use JSON.stringify(msg).length."
            >
              ⓘ
            </span>
          </div>

          <div className="sys-topic-diag-table-wrap">
            <table className="sys-topic-diag-table">
              <thead>
                <tr>
                  <th>Topic</th>
                  <th>Type</th>
                  <th>Pub/Sub</th>
                  <th>Avg Hz</th>
                  <th>Jitter</th>
                  <th>BW (B/s)</th>
                  <th>Avg Msg</th>
                  <th>QoS</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {topics.map((diagTopic) => {
                  const stat = topicStats[diagTopic] || {};
                  const lastSeenText = stat.lastSeenMs ? `${Math.max(0, Math.round((nowMs - stat.lastSeenMs) / 1000))}s ago` : 'N/A';
                  return (
                    <tr key={`diag-${diagTopic}`}>
                      <td className="sys-topic-cell">{diagTopic}</td>
                      <td>{fmt(stat.msgType)}</td>
                      <td>{`${fmt(stat.pubCount)}/${fmt(stat.subCount)}`}</td>
                      <td>{fmt(stat.avgHz)}</td>
                      <td>{fmt(stat.jitterMs, ' ms')}</td>
                      <td>{fmt(stat.bwBps)}</td>
                      <td>{fmt(stat.avgMsgBytes, ' B')}</td>
                      <td>{fmt(stat.qosSummary)}</td>
                      <td>{lastSeenText}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </Panel>

      <Panel title="Connection Info">
        <div className="sys-info">
          <div className="sys-info-row">
            <span>Status</span>
            <span style={{ color: connected ? 'var(--green)' : isDemoMode ? 'var(--yellow)' : 'var(--text-2)' }}>
              {connected ? 'ROS Connected' : isDemoMode ? 'Demo Mode' : 'Disconnected'}
            </span>
          </div>
          <div className="sys-info-row">
            <span>{connected ? 'Current URL' : 'Configured URL'}</span>
            <span>{wsUrl}</span>
          </div>

          {parsedWsUrl ? (
            <>
              <div className="sys-info-row">
                <span>Transport</span>
                <span>{parsedWsUrl.protocol.toUpperCase()}</span>
              </div>
              <div className="sys-info-row">
                <span>Host</span>
                <span>{parsedWsUrl.host}</span>
              </div>
              <div className="sys-info-row">
                <span>Port</span>
                <span>{parsedWsUrl.port}</span>
              </div>
              <div className="sys-info-row">
                <span>Path</span>
                <span>{parsedWsUrl.path || '/'}</span>
              </div>
            </>
          ) : (
            <>
              <div className="sys-info-row">
                <span>Transport</span>
                <span style={{ color: 'var(--red)' }}>Invalid URL</span>
              </div>
              <div className="sys-info-row">
                <span>Raw URL</span>
                <span>{wsUrl || '(empty)'}</span>
              </div>
            </>
          )}
        </div>
      </Panel>

      {confirmOpen && (
        <div className="sys-confirm-overlay" role="dialog" aria-modal="true">
          <div className="sys-confirm-modal">
            <h4>Dangerous Topic Confirmation</h4>
            <p>
              Topic <code>{topic}</code> may cause robot motion or unsafe behavior. Continue publish?
            </p>
            <div className="sys-confirm-actions">
              <button type="button" onClick={() => setConfirmOpen(false)}>Cancel</button>
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setConfirmOpen(false);
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
                }}
              >
                Confirm Publish
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
