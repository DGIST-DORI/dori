/**
 * tabs/SystemTab.jsx  (redesigned layout)
 * Layout: 2-column
 *   Left  : System Metrics + Topic Publisher
 *   Right : Topic Diagnostics (tall) + Connection Info
 *
 * Logic is unchanged — only JSX structure + classNames updated.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { LOG_TAGS, TOPIC_META, useStore } from '../core/store';
import { publishROS } from '../core/ros';
import { parseWsUrl } from '../core/url';
import './SystemTab.css';

const fmt = (val, suffix = '') =>
  val === null || val === undefined ? 'N/A' : `${val}${suffix}`;

const DANGEROUS_TOPICS = new Set([
  '/cmd_vel',
  '/cmd_vel_mux/input/teleop',
  '/dori/nav/command',
]);

const ALLOWED_TOPICS = [
  '/dori/nav/command',
  '/dori/hri/interaction_trigger',
  '/dori/hri/gesture_command',
  '/dori/hri/expression_command',
  '/dori/tts/text',
  '/dori/llm/query',
  '/cmd_vel',
];

// Returns CSS class for sys-metric-primary based on value vs threshold
const primaryClass = (value, warnThreshold) => {
  if (value === null || value === undefined) return 'sys-metric-primary';
  return value >= warnThreshold
    ? 'sys-metric-primary is-warning'
    : 'sys-metric-primary is-ok';
};

const thresholdClass = (value, warnThreshold) => {
  if (value === null || value === undefined) return 'sys-metric-value';
  return value >= warnThreshold ? 'sys-metric-value is-warning' : 'sys-metric-value';
};

// Clamp 0-100 for bar widths
const pct = (v) => `${Math.min(100, Math.max(0, v ?? 0))}%`;
const isWarn = (v, t) => v !== null && v !== undefined && v >= t;

// Hz column colouring
const hzClass = (hz) => {
  if (hz === null || hz === undefined) return 'hz-none';
  return hz >= 1 ? 'hz-ok' : 'hz-warn';
};

// ── Metric card with bar + detail rows ────────────────────────────────────────

function MetricCard({ title, usagePct, warnAt = 85, primary, details }) {
  const warn = isWarn(usagePct, warnAt);
  return (
    <div className="sys-metric-card">
      <div className="sys-metric-card-header">
        <span className="sys-metric-title">{title}</span>
        <span className={primaryClass(usagePct, warnAt)}>{primary}</span>
      </div>
      {usagePct !== null && usagePct !== undefined && (
        <div className="sys-bar-wrap">
          <div className={`sys-bar-fill ${warn ? 'warn' : ''}`} style={{ width: pct(usagePct) }} />
        </div>
      )}
      <div className="sys-metric-details">
        {details.map(([label, value, extraClass]) => (
          <div key={label} className="sys-metric-row">
            <span>{label}</span>
            <span className={`sys-metric-value ${extraClass ?? ''}`}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function SystemTab() {
  const topicStats    = useStore((s) => s.topicStats);
  const connected     = useStore((s) => s.connected);
  const isDemoMode    = useStore((s) => s.isDemoMode);
  const wsUrl         = useStore((s) => s.wsUrl);
  const systemMetrics = useStore((s) => s.systemMetrics);
  const isPublishing  = useStore((s) => s.isPublishing);
  const lastPublishAt = useStore((s) => s.lastPublishAt);
  const publishError  = useStore((s) => s.publishError);
  const addLog        = useStore((s) => s.addLog);
  const setPublishState = useStore((s) => s.setPublishState);

  const topics      = Object.keys(TOPIC_META);
  const parsedWsUrl = parseWsUrl(wsUrl);

  const [nowMs,       setNowMs]       = useState(() => Date.now());
  const [topic,       setTopic]       = useState('/dori/nav/command');
  const [msgType,     setMsgType]     = useState('std_msgs/String');
  const [jsonPayload, setJsonPayload] = useState('{"data":"hello"}');
  const [mode,        setMode]        = useState('once');
  const [rateHz,      setRateHz]      = useState('1');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const intervalRef = useRef(null);

  const canPublish   = connected || isDemoMode;
  const rateValue    = Number(rateHz);
  const isRateValid  = Number.isFinite(rateValue) && rateValue > 0;
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
      const err = 'Payload must be a JSON object.';
      setPublishState({ publishError: err, isPublishing: false });
      addLog(LOG_TAGS.ERROR, err);
      return false;
    }
    if (!msgType.includes('/')) {
      const err = `Invalid message type: "${msgType}". Use format pkg/Type.`;
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
    if (!publishOnce()) { stopPeriodic(); return; }
    intervalRef.current = setInterval(() => {
      if (!publishOnce()) stopPeriodic();
    }, tickMs);
  }, [addLog, isRateValid, publishOnce, rateHz, rateValue, setPublishState, stopPeriodic]);

  const handlePublishClick = () => {
    if (!canPublish) return;
    if (DANGEROUS_TOPICS.has(topic) && !confirmOpen) { setConfirmOpen(true); return; }
    if (mode === 'once') { stopPeriodic(); publishOnce(); return; }
    if (isPublishing) { stopPeriodic(); return; }
    startPeriodic();
  };

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => () => stopPeriodic(), [stopPeriodic]);

  // ── Derived metric display values ────────────────────────────────────────
  const cpu  = systemMetrics?.cpu;
  const gpu  = systemMetrics?.gpu;
  const ram  = systemMetrics?.ram;
  const disk = systemMetrics?.disk;

  return (
    <div className="sys-layout">

      {/* ══ Left column ══════════════════════════════════════════════════ */}
      <div className="sys-col">

        {/* System Metrics */}
        <Panel title="System Metrics">
          <div className="sys-metrics-body">

            <MetricCard
              title="CPU"
              usagePct={cpu?.usage_pct}
              warnAt={85}
              primary={fmt(cpu?.usage_pct, '%')}
              details={[
                ['Logical cores', fmt(cpu?.count_logical)],
                ['Physical cores', fmt(cpu?.count_physical)],
                ['Load avg', cpu?.load_avg_1_5_15?.join(' / ') ?? 'N/A'],
              ]}
            />

            <MetricCard
              title="RAM"
              usagePct={ram?.usage_pct}
              warnAt={85}
              primary={`${fmt(ram?.used_mb)} / ${fmt(ram?.total_mb)} MB`}
              details={[
                ['Usage', fmt(ram?.usage_pct, '%'), thresholdClass(ram?.usage_pct, 85).replace('sys-metric-value', '').trim() || null],
                ['Available', fmt(ram?.available_mb, ' MB')],
              ]}
            />

            <MetricCard
              title="GPU"
              usagePct={gpu?.utilization_pct}
              warnAt={90}
              primary={fmt(gpu?.utilization_pct, '%')}
              details={[
                ['Provider', fmt(gpu?.provider)],
                ['VRAM', gpu?.memory_used_mb != null ? `${gpu.memory_used_mb} / ${gpu.memory_total_mb} MB` : 'N/A'],
                ['Temp', fmt(gpu?.temperature_c, '°C'), thresholdClass(gpu?.temperature_c, 80).replace('sys-metric-value', '').trim() || null],
              ]}
            />

            <MetricCard
              title="Disk"
              usagePct={disk?.usage_pct}
              warnAt={90}
              primary={`${fmt(disk?.used_gb)} / ${fmt(disk?.total_gb)} GB`}
              details={[
                ['Usage', fmt(disk?.usage_pct, '%'), thresholdClass(disk?.usage_pct, 90).replace('sys-metric-value', '').trim() || null],
              ]}
            />

          </div>
        </Panel>

        {/* Topic Publisher */}
        <Panel title="Topic Publisher">
          <div className="sys-publisher">

            <div className="sys-pub-row">
              <label htmlFor="sys-pub-topic">Topic</label>
              <select id="sys-pub-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
                {ALLOWED_TOPICS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            <div className="sys-pub-row">
              <label htmlFor="sys-pub-type">Msg type</label>
              <input
                id="sys-pub-type"
                value={msgType}
                onChange={(e) => setMsgType(e.target.value)}
                placeholder="std_msgs/String"
              />
            </div>

            <div className="sys-pub-row sys-pub-row-column">
              <label htmlFor="sys-pub-payload">JSON payload</label>
              <textarea
                id="sys-pub-payload"
                value={jsonPayload}
                onChange={(e) => setJsonPayload(e.target.value)}
                rows={4}
                spellCheck={false}
              />
            </div>

            <div className="sys-pub-mode-row">
              <label>
                <input type="radio" name="sys-pub-mode" checked={mode === 'once'}     onChange={() => setMode('once')} />
                Once
              </label>
              <label>
                <input type="radio" name="sys-pub-mode" checked={mode === 'periodic'} onChange={() => setMode('periodic')} />
                Periodic
              </label>
              <label htmlFor="sys-pub-rate" style={{ marginLeft: 4 }}>Hz</label>
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
              <button
                type="button"
                className={`sys-pub-btn ${isPublishing ? 'stop' : canPublish ? 'active' : ''}`}
                disabled={!canPublish}
                onClick={handlePublishClick}
              >
                {mode === 'periodic'
                  ? (isPublishing ? 'Stop' : 'Start Publishing')
                  : 'Publish Once'}
              </button>

              <div className="sys-pub-status">
                <span
                  className={`sys-pub-status-dot ${isPublishing ? 'publishing' : publishError ? 'error' : ''}`}
                />
                {isPublishing && <span>publishing</span>}
                {lastPublishAt && !isPublishing && (
                  <span>last: {new Date(lastPublishAt).toLocaleTimeString()}</span>
                )}
                {publishError && (
                  <span className="sys-pub-error">{publishError}</span>
                )}
              </div>
            </div>

          </div>
        </Panel>

      </div>{/* end left col */}

      {/* ══ Right column ═════════════════════════════════════════════════ */}
      <div className="sys-col">

        {/* Topic Diagnostics */}
        <Panel title="Topic Diagnostics" style={{ flex: 1 }}>
          <div className="sys-topic-diag">
            <div className="sys-topic-diag-header">
              <span
                className="sys-tooltip"
                title="BW (B/s) = total JSON payload bytes ÷ rolling window. Avg Hz and jitter derived from inter-message timestamps."
              >ⓘ</span>
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
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.map((diagTopic) => {
                    const stat = topicStats[diagTopic] || {};
                    const lastSeenText = stat.lastSeenMs
                      ? `${Math.max(0, Math.round((nowMs - stat.lastSeenMs) / 1000))}s ago`
                      : 'N/A';
                    return (
                      <tr key={`diag-${diagTopic}`}>
                        <td className="sys-topic-cell">{diagTopic}</td>
                        <td>{fmt(stat.msgType)}</td>
                        <td>{`${fmt(stat.pubCount)}/${fmt(stat.subCount)}`}</td>
                        <td className={hzClass(stat.avgHz)}>{fmt(stat.avgHz)}</td>
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

        {/* Connection Info */}
        <Panel title="Connection Info">
          <div className="sys-info">
            <div className="sys-info-row">
              <span>Status</span>
              <span style={{
                color: connected
                  ? 'var(--green)'
                  : isDemoMode ? 'var(--yellow)' : 'var(--text-2)',
              }}>
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
              <div className="sys-info-row">
                <span>Transport</span>
                <span style={{ color: 'var(--red)' }}>Invalid URL</span>
              </div>
            )}
          </div>
        </Panel>

      </div>{/* end right col */}

      {/* ── Dangerous topic confirm dialog ────────────────────────────── */}
      {confirmOpen && (
        <div className="sys-confirm-overlay" role="dialog" aria-modal="true">
          <div className="sys-confirm-modal">
            <h4>Dangerous Topic</h4>
            <p>
              Publishing to <code>{topic}</code> may cause robot motion or unsafe behavior.
              Continue?
            </p>
            <div className="sys-confirm-actions">
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
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
