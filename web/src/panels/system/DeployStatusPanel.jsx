import { apiFetch } from '../../core/api';
/**
 * DeployStatusPanel.jsx — Deploy pipeline status monitor
 *
 * Polls /api/deploy/status every 2s and displays per-step progress.
 * Allows manual deploy trigger via /api/deploy/trigger.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import './DeployStatusPanel.css';

const POLL_INTERVAL_MS   = 2000;
const POLL_ACTIVE_MS     = 500;  // faster poll while running
const STATUS_COLORS = {
  idle:    'var(--text-2)',
  running: 'var(--accent, #00c8ff)',
  done:    'var(--green,  #53c87a)',
  error:   'var(--red,    #d66b66)',
};

const STEP_ICONS = {
  idle:    '○',
  running: '◌',
  done:    '✓',
  error:   '✗',
};

function elapsed(start, end) {
  if (!start) return null;
  const ms = new Date(end ?? Date.now()) - new Date(start);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StatusBadge({ status }) {
  return (
    <span
      className={`dp-badge dp-badge-${status}`}
      style={{ color: STATUS_COLORS[status] ?? 'var(--text-2)' }}
    >
      {status.toUpperCase()}
    </span>
  );
}

function StepRow({ step }) {
  const [expanded, setExpanded] = useState(false);
  const hasLog = step.log && step.log.trim().length > 0;

  return (
    <div className={`dp-step dp-step-${step.status}`}>
      <div
        className="dp-step-header"
        onClick={() => hasLog && setExpanded(v => !v)}
        style={{ cursor: hasLog ? 'pointer' : 'default' }}
      >
        <span className={`dp-step-icon dp-step-icon-${step.status}`}>
          {STEP_ICONS[step.status] ?? '○'}
        </span>
        <span className="dp-step-name">{step.step}</span>
        {step.status === 'running' && (
          <span className="dp-step-spinner" />
        )}
        {hasLog && (
          <span className="dp-step-expand">{expanded ? '▲' : '▼'}</span>
        )}
      </div>
      {expanded && hasLog && (
        <pre className="dp-step-log">{step.log}</pre>
      )}
    </div>
  );
}

export function DeployStatusPanel({ className = '' }) {
  const [job, setJob]           = useState(null);
  const [triggering, setTrig]   = useState(false);
  const [triggerMsg, setTrigMsg] = useState(null);
  const intervalRef             = useRef(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await apiFetch('/api/deploy/status');
      if (!res.ok) return;
      const data = await res.json();
      setJob(data);
    } catch {
      // Network error — keep last known state
    }
  }, []);

  // Adaptive polling: faster while running
  useEffect(() => {
    fetchStatus();
    const tick = () => {
      fetchStatus();
      const interval = job?.status === 'running' ? POLL_ACTIVE_MS : POLL_INTERVAL_MS;
      intervalRef.current = setTimeout(tick, interval);
    };
    intervalRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    return () => clearTimeout(intervalRef.current);
  }, [fetchStatus, job?.status]);

  async function handleTrigger() {
    setTrig(true);
    setTrigMsg(null);
    try {
      const res = await apiFetch('/api/deploy/trigger', { method: 'POST' });
      const data = await res.json();
      if (res.status === 409) {
        setTrigMsg({ type: 'warn', text: 'Already running' });
      } else if (!res.ok) {
        setTrigMsg({ type: 'error', text: data?.error ?? 'Trigger failed' });
      } else {
        setTrigMsg({ type: 'ok', text: 'Deploy started' });
        fetchStatus();
      }
    } catch (e) {
      setTrigMsg({ type: 'error', text: e.message });
    } finally {
      setTrig(false);
      setTimeout(() => setTrigMsg(null), 4000);
    }
  }

  const status = job?.status ?? 'idle';
  const isRunning = status === 'running';

  return (
    <div className={`dp-root ${className}`.trim()}>

      {/* ── Header bar ── */}
      <div className="dp-toolbar">
        <div className="dp-toolbar-left">
          <span className="dp-title">Deploy Status</span>
          <StatusBadge status={status} />
        </div>
        <button
          className="dp-trigger-btn"
          onClick={handleTrigger}
          disabled={triggering || isRunning}
          title="Manually trigger git pull + build"
        >
          {isRunning ? 'Running…' : 'Deploy'}
        </button>
      </div>

      {/* ── Trigger feedback ── */}
      {triggerMsg && (
        <div className={`dp-feedback dp-feedback-${triggerMsg.type}`}>
          {triggerMsg.text}
        </div>
      )}

      {/* ── Meta row ── */}
      {job && (
        <div className="dp-meta">
          {job.started_at && (
            <span className="dp-meta-item">
              Started: <span className="dp-meta-val">{new Date(job.started_at).toLocaleTimeString()}</span>
            </span>
          )}
          {job.started_at && (
            <span className="dp-meta-item">
              Elapsed: <span className="dp-meta-val">{elapsed(job.started_at, job.finished_at)}</span>
            </span>
          )}
          {job.error && (
            <span className="dp-meta-item dp-meta-error">{job.error}</span>
          )}
        </div>
      )}

      {/* ── Steps ── */}
      <div className="dp-steps">
        {!job || job.steps.length === 0 ? (
          <div className="dp-empty">
            {status === 'idle' ? 'No deploy has run yet.' : 'Waiting for steps…'}
          </div>
        ) : (
          job.steps.map((step, i) => (
            <StepRow key={`${step.step}-${i}`} step={step} />
          ))
        )}
      </div>

      {/* ── Footer hint ── */}
      <div className="dp-footer">
        Auto-triggered on <code>main</code> push via GitHub Webhook
      </div>

    </div>
  );
}

export default DeployStatusPanel;
