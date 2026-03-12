import Panel from '../components/Panel';
import { useStore, TOPIC_META } from '../core/store';
import './SystemTab.css';

export default function SystemTab() {
  const topicHz  = useStore(s => s.topicHz);
  const connected = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);

  const topics = Object.keys(TOPIC_META);

  return (
    <div className="sys-layout">
      <Panel title="Topic Hz Monitor">
        <div className="sys-hz-list">
          {topics.map(topic => {
            const hz  = topicHz[topic] ?? 0;
            const meta = TOPIC_META[topic];
            const pct  = Math.min(hz / 30, 1) * 100;
            return (
              <div key={topic} className="sys-hz-row">
                <span className={`sys-hz-tag tag-${meta.tag}`}>{meta.tag}</span>
                <span className="sys-hz-topic">{topic}</span>
                <div className="sys-hz-bar-wrap">
                  <div className="sys-hz-bar" style={{ width: `${pct}%` }} />
                </div>
                <span className="sys-hz-val">{hz} Hz</span>
              </div>
            );
          })}
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
            <span>Transport</span>
            <span>rosbridge WebSocket</span>
          </div>
          <div className="sys-info-row">
            <span>Port</span>
            <span>9090</span>
          </div>
        </div>
      </Panel>
    </div>
  );
}
