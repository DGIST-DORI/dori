import { useEffect, useState } from 'react';
import Panel from '../components/Panel';
import { useStore, TOPIC_META } from '../core/store';
import { parseWsUrl } from '../core/url';
import './SystemTab.css';

const fmt = (val, suffix = '') => (val === null || val === undefined ? 'N/A' : `${val}${suffix}`);

export default function SystemTab() {
  const topicStats = useStore((s) => s.topicStats);
  const connected = useStore((s) => s.connected);
  const isDemoMode = useStore((s) => s.isDemoMode);
  const wsUrl = useStore((s) => s.wsUrl);

  const topics = Object.keys(TOPIC_META);
  const parsedWsUrl = parseWsUrl(wsUrl);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="sys-layout">
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
