/**
 * components/Panel.jsx
 * Generic panel wrapper with title bar.
 * Usage: <Panel title="Event Log" badge={count}> ... </Panel>
 */
import './Panel.css';

export default function Panel({ title, badge, children, className = '', style }) {
  return (
    <div className={`panel ${className}`} style={style}>
      <div className="panel-header">
        <span className="panel-title">{title}</span>
        {badge != null && <span className="panel-badge">{badge}</span>}
      </div>
      <div className="panel-body">
        {children}
      </div>
    </div>
  );
}
