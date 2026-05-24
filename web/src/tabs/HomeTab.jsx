/*
 * tabs/HomeTab.jsx
 * Default landing page shown on startup.
 * Shows quick status overview and getting-started hints.
 */

import { useEffect, useMemo, useState } from 'react';
import { publishROS } from '../core/ros';
import { LOG_TAGS, useStore } from '../core/store';
import './HomeTab.css';

const E2E_TIMEOUT_MS = 12000;
const E2E_SEQUENCE = [
  '/dori/stt/result',
  '/dori/llm/query',
  '/dori/llm/response',
  '/dori/tts/speaking',
  '/dori/tts/done',
];

export default function HomeTab() {
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const hriState   = useStore(s => s.hriState);
  const log        = useStore(s => s.log);
  const addLog     = useStore(s => s.addLog);
  const topicStats = useStore(s => s.topicStats);

  const [runState, setRunState] = useState({
    phase: 'idle', // idle | running | passed | failed
    startedAt: null,
    baseline: {},
    failedAt: null,
  });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (runState.phase !== 'running') return undefined;
    const id = setInterval(() => setTick(t => t + 1), 250);
    return () => clearInterval(id);
  }, [runState.phase]);

  const startedAt = runState.startedAt ?? 0;
  const elapsedMs = runState.phase === 'running' ? Math.max(0, Date.now() - startedAt) : 0;

  const stepStatuses = useMemo(() => {
    void tick;
    const result = [];
    let prevAt = startedAt;
    let firstFailed = null;

    for (const topic of E2E_SEQUENCE) {
      const lastSeenMs = topicStats?.[topic]?.lastSeenMs ?? 0;
      const baselineMs = runState.baseline?.[topic] ?? 0;
      const hitAt = lastSeenMs > baselineMs ? lastSeenMs : null;
      const done = !!hitAt;
      let status = 'pending';

      if (done) status = 'pass';
      else if (runState.phase === 'failed' && !firstFailed) {
        status = 'fail';
        firstFailed = topic;
      } else if (runState.phase === 'running' && elapsedMs >= E2E_TIMEOUT_MS && !firstFailed) {
        status = 'fail';
        firstFailed = topic;
      }

      if (!done && status !== 'fail' && firstFailed) status = 'skipped';

      result.push({ topic, status, hitAt, latencyMs: done ? hitAt - prevAt : null });
      if (done) prevAt = hitAt;
    }
    return result;
  }, [topicStats, runState, startedAt, elapsedMs, tick]);

  useEffect(() => {
    if (runState.phase !== 'running') return;

    const allPassed = stepStatuses.every(s => s.status === 'pass');
    if (allPassed) {
      addLog(LOG_TAGS.TEST, '[e2e] conversation pipeline PASSED');
      setRunState(s => ({ ...s, phase: 'passed' }));
      return;
    }

    const hasFailed = stepStatuses.some(s => s.status === 'fail');
    if (hasFailed || elapsedMs >= E2E_TIMEOUT_MS) {
      const failedStep = stepStatuses.find(s => s.status === 'fail' || s.status === 'pending')?.topic;
      addLog(LOG_TAGS.ERROR, `[e2e] conversation pipeline FAILED at ${failedStep || 'unknown step'}`);
      setRunState(s => ({ ...s, phase: 'failed', failedAt: failedStep || null }));
    }
  }, [stepStatuses, elapsedMs, runState.phase, addLog]);

  function startConversationE2E() {
    const baseline = E2E_SEQUENCE.reduce((acc, topic) => {
      acc[topic] = topicStats?.[topic]?.lastSeenMs ?? 0;
      return acc;
    }, {});
    const now = Date.now();

    setRunState({
      phase: 'running',
      startedAt: now,
      baseline,
      failedAt: null,
    });

    const payload = {
      text: 'Conversation E2E test 시작',
      confidence: 1.0,
      source: 'dashboard_e2e_test',
      timestamp: new Date(now).toISOString(),
    };
    publishROS('/dori/stt/result', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
    addLog(LOG_TAGS.TEST, '[e2e] conversation test triggered from dashboard');
  }

  const badgeClass = `home-e2e-badge ${runState.phase}`;
  const badgeText = runState.phase === 'passed'
    ? 'PIPELINE PASS'
    : runState.phase === 'failed'
      ? 'PIPELINE FAIL'
      : runState.phase === 'running'
        ? 'RUNNING'
        : 'NOT RUN';

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
      <div className="home-e2e">
        <div className="home-e2e-header">
          <h3>Conversation E2E Test</h3>
          <span className={badgeClass}>{badgeText}</span>
        </div>
        <p className="home-e2e-desc">한 번 클릭으로 STT → HRI → LLM → TTS 파이프라인 상태 전이를 검사합니다.</p>
        <button className="btn btn-primary" onClick={startConversationE2E} disabled={runState.phase === 'running'}>
          {runState.phase === 'running' ? 'Running…' : 'Run Conversation E2E Test'}
        </button>

        <div className="home-e2e-checklist">
          {stepStatuses.map(step => (
            <div key={step.topic} className={`home-e2e-step ${step.status}`}>
              <span className="status-dot" />
              <code>{step.topic}</code>
              <span className="status-text">{
                step.status === 'pass' ? `PASS (${step.latencyMs}ms)`
                  : step.status === 'fail' ? `FAIL ${runState.failedAt === step.topic ? '(timeout/missing)' : ''}`
                    : step.status === 'skipped' ? 'SKIPPED'
                      : 'PENDING'
              }</span>
            </div>
          ))}
        </div>
      </div>

      <div className="home-hint">
        <p>← 사이드바에서 탭을 선택하거나, 우측 상단에서 ROS에 연결하세요.</p>
        <p>ROS 없이 테스트하려면 <code>▶ demo</code> 버튼을 누르세요.</p>
      </div>

    </div>
  );
}
