/**
 * tabs/HomeTab.jsx
 * Default landing page shown on startup.
 * Shows quick status overview and getting-started hints.
 */

import { useStore } from '../core/store';
import './HomeTab.css';

export default function HomeTab() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const hriState   = useStore(s => s.hriState);
  const log        = useStore(s => s.log);

  return (
    <div className="home-root">

      {/* Hero */}
      <div className="home-hero">
        <div className="home-hero-title">DORI</div>
        <div className="home-hero-sub">Dual-shell Omnidirectional Robot for Interaction</div>
        <div className="home-hero-org">DGIST UGRP 2026</div>
      </div>

      {/* Status cards */}
      <div className="home-cards">
        <div className={`home-card ${connected ? 'ok' : isDemoMode ? 'demo' : ''}`}>
          <div className="home-card-label">ROS Connection</div>
          <div className="home-card-value">
            {connected ? 'CONNECTED' : isDemoMode ? 'DEMO MODE' : 'OFFLINE'}
          </div>
        </div>

        <div className="home-card">
          <div className="home-card-label">HRI State</div>
          <div className={`home-card-value hri-${hriState}`}>{hriState}</div>
        </div>

        <div className="home-card">
          <div className="home-card-label">Log Entries</div>
          <div className="home-card-value">{log.length}</div>
        </div>
      </div>

      {/* Hint */}
      <div className="home-hint">
        <p>← 사이드바에서 탭을 선택하거나, 우측 상단에서 ROS에 연결하세요.</p>
        <p>ROS 없이 테스트하려면 <code>▶ demo</code> 버튼을 누르세요.</p>
      </div>

    </div>
  );
}
