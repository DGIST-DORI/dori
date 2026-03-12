/**
 * tabs/HRITab.jsx
 * HRI Monitor tab layout.
 * Currently contains: EventLog (full)
 * Placeholders for: StateMachine, PersonTracker, ConversationFlow
 *
 * Adding a new panel:
 *   1. Create panels/MyPanel.jsx
 *   2. Import it here
 *   3. Place it in the grid
 */

import EventLog from '../panels/EventLog';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './HRITab.css';

// ── Placeholder for panels not yet implemented ───────────────────────────
function Placeholder({ label }) {
  return (
    <div className="hri-placeholder">
      <span className="hri-placeholder-icon">◻</span>
      <span>{label}</span>
      <span className="hri-placeholder-hint">— not yet implemented —</span>
    </div>
  );
}

export default function HRITab() {
  const log = useStore(s => s.log);

  return (
    <div className="hri-layout">

      {/* ── Column 1: State + Conversation ── */}
      <div className="hri-col hri-col-left">
        <Panel title="HRI State Machine" className="hri-panel-state">
          <Placeholder label="State Machine Visualizer" />
        </Panel>
        <Panel title="Conversation Flow" className="hri-panel-convo">
          <Placeholder label="STT → LLM → TTS Flow" />
        </Panel>
      </div>

      {/* ── Column 2: Event Log (main) ── */}
      <div className="hri-col hri-col-center">
        <Panel title="Event Log" badge={log.length} className="hri-panel-log">
          {/* EventLog manages its own scroll/filter internally */}
          <EventLog />
        </Panel>
      </div>

      {/* ── Column 3: Tracking + Gesture/Expr ── */}
      <div className="hri-col hri-col-right">
        <Panel title="Person Tracking" className="hri-panel-track">
          <Placeholder label="Camera View + BBox Overlay" />
        </Panel>
        <Panel title="Gesture / Expression" className="hri-panel-gesture">
          <Placeholder label="Gesture & Expression Badges" />
        </Panel>
      </div>

    </div>
  );
}
