import { useState } from 'react';
import { Zap } from 'lucide-react';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import { useI18n } from '../../core/i18n';
import './WakeWordPanel.css';

// ── Helpers ───────────────────────────────────────────────────────────────────

function pub(topic, msgType, data) {
  try {
    publishROS(topic, msgType, data);
    return true;
  } catch (e) {
    console.error('[pub] failed:', topic, e);
    return false;
  }
}

function ts() { return new Date().toLocaleTimeString(); }

// Section divider label
function SectionLabel({ children }) {
  return <div className="panel-section-label">{children}</div>;
}

// ── Wake Word Panel ───────────────────────────────────────────────────────────

function WakeWordPanel() {
  const { t } = useI18n();
  const connected  = useStore(s => s.connected);
  const hriState   = useStore(s => s.hriState);
  const addLog     = useStore(s => s.addLog);
  const [lastTs, setLastTs] = useState(null);

  function fire() {
    const ok = pub('/dori/stt/wake_word_detected', 'std_msgs/msg/Bool', { data: true });
    if (ok) {
      addLog(LOG_TAGS.WAKE, '[test] wake word triggered from dashboard');
      setLastTs(ts());
    } else {
      addLog(LOG_TAGS.ERROR, '[test] wake word publish failed — ROS not connected?');
    }
  }

  return (
    <div className="panel-body">
      <SectionLabel>Wake Word → /dori/stt/wake_word_detected</SectionLabel>
      <div className="hri-state-row">
        <span className="hri-state-key">Current HRI state</span>
        <span className={`hri-state-val hri-state-${hriState}`}>{hriState}</span>
      </div>
      <div className="row">
        <button className="btn btn-sm btn-ok btn-icon" disabled={!connected} onClick={fire}>
          <Zap size={12} /> Trigger Wake Word
        </button>
        {lastTs && <span className="hint-inline">fired at {lastTs}</span>}
      </div>
      <p className="hint-text">
        {t('panel.wakeword.hint')}
      </p>
    </div>
  );
}

export default WakeWordPanel;
export { WakeWordPanel };
