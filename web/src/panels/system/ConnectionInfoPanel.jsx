import { useStore } from '../../core/store';
import { parseWsUrl } from '../../core/url';
import './ConnectionInfoPanel.css';

function ConnectionInfoPanel() {
  const connected  = useStore(s => s.connected);
  const wsUrl      = useStore(s => s.wsUrl);

  const parsedWsUrl = parseWsUrl(wsUrl);

  const statusColor = connected
    ? 'var(--color-ok)'
    : 'var(--text-muted)';

  return (
    <div className="layout-panel-body">
      <div className="sys-info">
        <div className="sys-info-row">
          <span>Status</span>
          <span style={{ color: statusColor }}>
            {connected ? 'ROS Connected' : 'Disconnected'}
          </span>
        </div>
        <div className="sys-info-row">
          <span>{connected ? 'Current URL' : 'Configured URL'}</span>
          <span>{wsUrl}</span>
        </div>
        {parsedWsUrl ? (
          <>
            <div className="sys-info-row"><span>Transport</span><span>{parsedWsUrl.protocol.toUpperCase()}</span></div>
            <div className="sys-info-row"><span>Host</span><span>{parsedWsUrl.host}</span></div>
            <div className="sys-info-row"><span>Port</span><span>{parsedWsUrl.port}</span></div>
            <div className="sys-info-row"><span>Path</span><span>{parsedWsUrl.path || '/'}</span></div>
          </>
        ) : (
          <div className="sys-info-row">
            <span>Transport</span>
            <span style={{ color: 'var(--color-error)' }}>Invalid URL</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default ConnectionInfoPanel;
export { ConnectionInfoPanel };
