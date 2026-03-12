import { useStore } from '../core/store';
import SidebarIcon from '../assets/icons/icon-sidebar.svg?react';
import CloseIcon   from '../assets/icons/icon-close.svg?react';
import './Sidebar.css';

export default function Sidebar({ expanded, onExpand, onCollapse, activeTab, onTabChange, tabs }) {
  const connected   = useStore(s => s.connected);
  const isDemoMode  = useStore(s => s.isDemoMode);
  const statusLabel = connected ? 'LIVE' : isDemoMode ? 'DEMO' : 'OFF';
  const statusClass = connected ? 'connected' : isDemoMode ? 'demo' : '';

  return (
    <aside
      className={`sidebar ${expanded ? 'expanded' : 'collapsed'}`}
      onClick={() => !expanded && onExpand()}
    >
      {/* ── Top cell ── */}
      <div className="sb-top">
        {expanded ? (
          <>
            <div className="sb-logo">
              <span className="sb-logo-mark">◎</span>
              <span className="sb-logo-text">DORI</span>
            </div>
            <button
              className="sb-close"
              onClick={e => { e.stopPropagation(); onCollapse(); }}
              title="Close sidebar"
            >
              <CloseIcon />
            </button>
          </>
        ) : (
          <button
            className="sb-open"
            onClick={e => { e.stopPropagation(); onExpand(); }}
          >
            <SidebarIcon />
            <span className="sb-tooltip">Open sidebar</span>
          </button>
        )}
      </div>

      {/* ── Nav items ── */}
      <nav className="sb-nav">
        {tabs.map(tab => {
          const isActive = activeTab === tab.id;
          const icon = isActive && tab.iconActive ? tab.iconActive : tab.icon;
          return (
            <button
              key={tab.id}
              className={`sb-item ${isActive ? 'active' : ''}`}
              onClick={e => { e.stopPropagation(); onTabChange(tab.id); }}
            >
              <span className="sb-icon">{icon}</span>
              {expanded  && <span className="sb-label">{tab.label}</span>}
              {!expanded && <span className="sb-tooltip">{tab.label}</span>}
              {isActive && <span className="sb-active-bar" />}
            </button>
          );
        })}
      </nav>

      {/* ── Bottom: connection status ── */}
      <div className="sb-bottom">
        <div className={`sb-status ${statusClass}`}>
          <div className="sb-status-dot" />
          {expanded  && <span className="sb-status-label">{statusLabel}</span>}
          {!expanded && <span className="sb-tooltip sb-tooltip-status">{statusLabel}</span>}
        </div>
      </div>
    </aside>
  );
}
