import { useEffect, useState } from 'react';
import Panel from '../components/Panel';
import { useStore, TOPIC_META } from '../core/store';
import { parseWsUrl } from '../core/url';
import './SystemTab.css';

const fmt = (val, suffix = '') => (val === null || val === undefined ? 'N/A' : `${val}${suffix}`);

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

  const topics = Object.keys(TOPIC_META);
  const parsedWsUrl = parseWsUrl(wsUrl);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

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
            <div className="sys-metric-row"><span>Memory</span><span className="sys-metric-value">{systemMetrics?.gpu?.memory_used_mb !== null && systemMetrics?.gpu?.memory_total_mb !== null ? `${systemMetrics.gpu.memory_used_mb} / ${systemMetrics.gpu.memory_total_mb} MB` : 'N/A'}</span></div>
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
                {topics.map((topic) => {
                  const stat = topicStats[topic] || {};
                  const lastSeenText = stat.lastSeenMs ? `${Math.max(0, Math.round((nowMs - stat.lastSeenMs) / 1000))}s ago` : 'N/A';
                  return (
                    <tr key={`diag-${topic}`}>
                      <td className="sys-topic-cell">{topic}</td>
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
    </div>
  );
}
