import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  User, Bot, Bell, Volume2, Check, GitCommitHorizontal,
  Hand, Map, RotateCcw, Navigation,
} from 'lucide-react';
import Panel from '../../components/Panel';
import { LOG_TAGS, useStore } from '../../core/store';
import { publishROS } from '../../core/ros';
import './ConversationPanel.css';

// ── Session parsing ───────────────────────────────────────────────────────────

/**
 * log 배열(newest-first)을 대화 세션 배열로 파싱.
 * 세션 경계: WAKE 이벤트
 * 세션 종료: 다음 WAKE 직전 또는 STATE→IDLE
 *
 * Returns sessions newest-first.
 */
function parseSessions(log) {
  if (!log?.length) return [];

  const entries = [...log].reverse(); // oldest-first
  const sessions = [];
  let current = null;

  const flush = () => {
    if (current && current.rawEntries.length > 0) {
      current.endTs = current.rawEntries[current.rawEntries.length - 1].ts;
      sessions.push({ ...current });
    }
    current = null;
  };

  const newSession = (entry) => {
    flush();
    current = { id: entry.id, startTs: entry.ts, endTs: entry.ts, turns: [], rawEntries: [] };
  };

  for (const entry of entries) {
    const { tag, text, ts, id } = entry;

    if (tag === LOG_TAGS.WAKE) {
      newSession(entry);
      current.rawEntries.push(entry);
      current.turns.push({ id, type: 'context', text: 'Wake word detected', ts, tag, color: 'wake', icon: 'bell' });
      continue;
    }

    // IDLE state transition closes session
    if (tag === LOG_TAGS.STATE && text.includes('→ IDLE')) {
      if (current) {
        current.rawEntries.push(entry);
        current.turns.push({ id, type: 'context', text, ts, tag, color: 'state', icon: 'commit' });
        flush();
      }
      continue;
    }

    // STT without prior wake word → auto-start session
    if (!current && tag === LOG_TAGS.STT) {
      newSession({ ...entry, id: `auto-${entry.id}` });
    }

    if (!current) continue;

    current.rawEntries.push(entry);

    switch (tag) {
      case LOG_TAGS.STT: {
        const match = text.match(/"(.+?)"\s*\[conf/);
        const spokenText = match ? match[1] : text.replace(/^"(.*)"$/, '$1');
        const confMatch = text.match(/conf:\s*([\d.]+)/);
        const conf = confMatch ? parseFloat(confMatch[1]) : null;
        current.turns.push({ id, type: 'user', text: spokenText, ts, tag, meta: { conf } });
        break;
      }
      case LOG_TAGS.TTS: {
        if (text.startsWith('speak:')) {
          const m = text.match(/speak:\s*"(.+?)(?:"$|"…$|…)/s);
          const spoken = m ? m[1] : text.replace(/^speak:\s*"?/, '').replace(/"$/, '');
          current.turns.push({ id, type: 'dori', text: spoken, ts, tag });
        } else if (text === 'TTS speaking…') {
          current.turns.push({ id, type: 'context', text: 'Speaking…', ts, tag, color: 'tts', icon: 'volume' });
        } else if (text === 'TTS done') {
          current.turns.push({ id, type: 'context', text: 'TTS done', ts, tag, color: 'tts', icon: 'check' });
        }
        break;
      }
      case LOG_TAGS.STATE:
        current.turns.push({ id, type: 'context', text, ts, tag, color: 'state', icon: 'commit' });
        break;
      case LOG_TAGS.GESTURE:
        current.turns.push({ id, type: 'context', text: `Gesture: ${text}`, ts, tag, color: 'gesture', icon: 'hand' });
        break;
      case LOG_TAGS.NAV:
        current.turns.push({ id, type: 'context', text, ts, tag, color: 'nav', icon: 'map' });
        break;
      case LOG_TAGS.TRACK:
        if (text.startsWith('Target lost')) {
          current.turns.push({ id, type: 'context', text, ts, tag, color: 'track', icon: 'user' });
        }
        break;
      default:
        break;
    }
  }

  flush();
  return sessions.reverse(); // newest-first
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTime(date) {
  if (!(date instanceof Date)) date = new Date(date);
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtDuration(a, b) {
  const ms = Math.abs(new Date(b) - new Date(a));
  const s  = Math.floor(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function downloadJSON(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function serializeSession(s) {
  const ts = (d) => d instanceof Date ? d.toISOString() : d;
  return {
    ...s,
    startTs:    ts(s.startTs),
    endTs:      ts(s.endTs),
    turns:      s.turns.map(t => ({ ...t, ts: ts(t.ts) })),
    rawEntries: s.rawEntries.map(e => ({ ...e, ts: ts(e.ts) })),
  };
}

function deserializeSession(s) {
  return {
    ...s,
    startTs:    new Date(s.startTs),
    endTs:      new Date(s.endTs),
    turns:      s.turns.map(t => ({ ...t, ts: new Date(t.ts) })),
    rawEntries: s.rawEntries.map(e => ({ ...e, ts: new Date(e.ts) })),
  };
}

// ── Timeline ──────────────────────────────────────────────────────────────────

const TAG_DOT_COLOR = {
  [LOG_TAGS.WAKE]:    'var(--yellow)',
  [LOG_TAGS.STT]:     'var(--green)',
  [LOG_TAGS.LLM]:     'var(--purple)',
  [LOG_TAGS.TTS]:     'var(--orange)',
  [LOG_TAGS.STATE]:   'var(--accent)',
  [LOG_TAGS.GESTURE]: 'var(--accent)',
  [LOG_TAGS.NAV]:     'var(--yellow)',
  [LOG_TAGS.TRACK]:   'var(--text-2)',
};

function Timeline({ session }) {
  if (!session?.rawEntries?.length) return null;
  const startMs = new Date(session.startTs).getTime();
  const endMs   = new Date(session.endTs).getTime();
  const span    = Math.max(endMs - startMs, 500);

  return (
    <div className="cr-timeline">
      <div className="cr-timeline-track">
        {session.rawEntries.map(e => (
          <div
            key={e.id}
            className="cr-timeline-dot"
            style={{
              left:       `${((new Date(e.ts).getTime() - startMs) / span) * 100}%`,
              background: TAG_DOT_COLOR[e.tag] || 'var(--text-2)',
            }}
            title={`[${e.tag}] ${fmtTime(e.ts)}\n${e.text}`}
          />
        ))}
      </div>
      <div className="cr-timeline-labels">
        <span>{fmtTime(session.startTs)}</span>
        <span>{fmtDuration(session.startTs, session.endTs)}</span>
        <span>{fmtTime(session.endTs)}</span>
      </div>

      {/* Legend */}
      <div className="cr-timeline-legend">
        {[
          ['WAKE', 'var(--yellow)'],
          ['STT',  'var(--green)'],
          ['LLM',  'var(--purple)'],
          ['TTS',  'var(--orange)'],
          ['STATE','var(--accent)'],
        ].map(([label, color]) => (
          <span key={label} className="cr-legend-item">
            <span className="cr-legend-dot" style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Session List Item ─────────────────────────────────────────────────────────

function SessionItem({ session, active, onClick }) {
  const userTurns = session.turns.filter(t => t.type === 'user');
  const doriTurns = session.turns.filter(t => t.type === 'dori');
  const preview   = userTurns[0]?.text || '(utterance 없음)';

  return (
    <button className={`cr-session-item ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="cr-session-time">{fmtTime(session.startTs)}</div>
      <div className="cr-session-preview">{preview}</div>
      <div className="cr-session-meta">
        <span><User size={9} strokeWidth={2} style={{display:'inline',verticalAlign:'middle'}} /> {userTurns.length} · <Bot size={9} strokeWidth={2} style={{display:'inline',verticalAlign:'middle'}} /> {doriTurns.length}</span>
        <span>{fmtDuration(session.startTs, session.endTs)}</span>
      </div>
    </button>
  );
}

// ── Context icon map ──────────────────────────────────────────────────────────

const CTX_ICONS = {
  bell:   <Bell   size={10} strokeWidth={2} />,
  volume: <Volume2 size={10} strokeWidth={2} />,
  check:  <Check  size={10} strokeWidth={2.5} />,
  commit: <GitCommitHorizontal size={10} strokeWidth={2} />,
  hand:   <Hand   size={10} strokeWidth={2} />,
  map:    <Map    size={10} strokeWidth={2} />,
  user:   <User   size={10} strokeWidth={2} />,
  nav:    <Navigation size={10} strokeWidth={2} />,
};

// ── Chat Bubble ───────────────────────────────────────────────────────────────

function ChatBubble({ turn, canReplay, onReplay }) {
  const [showMeta, setShowMeta] = useState(false);

  if (turn.type === 'context') {
    return (
      <div className={`cr-ctx-event cr-ctx-${turn.color || 'default'}`}>
        {turn.icon && <span className="cr-ctx-icon">{CTX_ICONS[turn.icon]}</span>}
        <span className="cr-ctx-time">{fmtTime(turn.ts)}</span>
        <span className="cr-ctx-text">{turn.text}</span>
      </div>
    );
  }

  const isUser = turn.type === 'user';

  return (
    <div className={`cr-bubble-wrap ${isUser ? 'user' : 'dori'}`}>
      <div className="cr-bubble-avatar">
        {isUser
          ? <User size={14} strokeWidth={1.8} />
          : <Bot  size={14} strokeWidth={1.8} />}
      </div>
      <div className="cr-bubble-content">
        <div className="cr-bubble" onClick={() => setShowMeta(m => !m)}>
          <div className="cr-bubble-text">{turn.text}</div>
        </div>
        {showMeta && (
          <div className="cr-bubble-meta">
            {fmtTime(turn.ts)}
            {isUser && turn.meta?.conf != null && ` · conf: ${turn.meta.conf.toFixed(2)}`}
          </div>
        )}
        {isUser && canReplay && (
          <button
            className="cr-replay-btn"
            title="이 발화를 STT로 재주입"
            onClick={() => onReplay(turn)}
          >
            <RotateCcw size={10} strokeWidth={2.5} /> Replay
          </button>
        )}
      </div>
    </div>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────────

function ConversationTabContent() {
  const log        = useStore(s => s.log);
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);
  const addLog     = useStore(s => s.addLog);
  const canPublish = connected || isDemoMode;

  const liveSessions = useMemo(() => parseSessions(log), [log]);
  const [importedSessions, setImportedSessions] = useState([]);
  const [source,     setSource]     = useState('live');
  const [selectedId, setSelectedId] = useState(null);
  const [replayMsg,  setReplayMsg]  = useState('');
  const chatRef = useRef(null);
  const fileRef = useRef(null);

  const sessions = source === 'live' ? liveSessions : importedSessions;

  // Scroll chat to top on session change
  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = 0;
  }, [selectedId]);

  const selected = sessions.find(s => s.id === selectedId) ?? sessions[0] ?? null;

  // ── Replay ─────────────────────────────────────────────────────────────────
  const handleReplay = useCallback((turn) => {
    const payload = {
      text:       turn.text,
      language:   'ko',
      confidence: turn.meta?.conf ?? 0.95,
      timestamp:  Date.now() / 1000,
      source:     'dashboard_replay',
    };
    try {
      publishROS('/dori/stt/result', 'std_msgs/msg/String', { data: JSON.stringify(payload) });
      addLog(LOG_TAGS.STT, `[replay] "${turn.text}"`);
      setReplayMsg(`Replayed: "${turn.text.slice(0, 50)}${turn.text.length > 50 ? '…' : ''}"`);
      setTimeout(() => setReplayMsg(''), 3000);
    } catch (e) {
      setReplayMsg(`Error: ${e.message}`);
    }
  }, [addLog]);

  // ── Export ─────────────────────────────────────────────────────────────────
  function exportSession() {
    if (!selected) return;
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    downloadJSON({ exported_at: new Date().toISOString(), session: serializeSession(selected) },
      `dori-session-${ts}.json`);
  }

  function exportAll() {
    if (!sessions.length) return;
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    downloadJSON({
      exported_at: new Date().toISOString(),
      session_count: sessions.length,
      sessions: sessions.map(serializeSession),
    }, `dori-sessions-${ts}.json`);
  }

  // ── Import ─────────────────────────────────────────────────────────────────
  function handleImport(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const json = JSON.parse(ev.target.result);
        let raw = json.sessions ?? (json.session ? [json.session] : []);
        const parsed = raw.map(deserializeSession);
        setImportedSessions(parsed);
        setSource('imported');
        setSelectedId(parsed[0]?.id ?? null);
      } catch (err) {
        alert(`Import 실패: ${err.message}`);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="layout-conversation">

      {/* ══ Left: Session list ══════════════════════════════════════════════ */}
      <Panel title="Sessions" className="slot-sessions">
        <div className="cr-session-panel">

          {/* Toolbar */}
          <div className="cr-toolbar">
            <div className="cr-source-toggle">
              <button
                className={`cr-src-btn ${source === 'live' ? 'active' : ''}`}
                onClick={() => { setSource('live'); setSelectedId(null); }}
              >Live <span className="cr-src-count">{liveSessions.length}</span></button>
              <button
                className={`cr-src-btn ${source === 'imported' ? 'active' : ''}`}
                onClick={() => setSource('imported')}
                disabled={!importedSessions.length}
              >Imported <span className="cr-src-count">{importedSessions.length}</span></button>
            </div>

            <div className="cr-toolbar-btns">
              <button className="cr-action-btn" onClick={() => fileRef.current?.click()} title="Import JSON">
                ↑ Import
              </button>
              <button className="cr-action-btn" onClick={exportAll} disabled={!sessions.length} title="Export all">
                ↓ All
              </button>
            </div>
            <input ref={fileRef} type="file" accept=".json" style={{ display: 'none' }} onChange={handleImport} />
          </div>

          {/* List */}
          <div className="cr-session-list">
            {sessions.length === 0 ? (
              <div className="cr-empty">
                {source === 'live'
                  ? 'Wake word 트리거 또는\nDemo 모드를 실행하세요.'
                  : 'JSON 파일을 Import하세요.'}
              </div>
            ) : sessions.map(s => (
              <SessionItem
                key={s.id}
                session={s}
                active={s.id === selected?.id}
                onClick={() => setSelectedId(s.id)}
              />
            ))}
          </div>

        </div>
      </Panel>

      {/* ══ Right: Chat view ════════════════════════════════════════════════ */}
      <div className="slot-chat">

        {/* Chat header */}
        <div className="cr-chat-header">
          {selected ? (
            <>
              <div className="cr-chat-header-info">
                <span className="cr-chat-ts">{fmtTime(selected.startTs)}</span>
                <span className="cr-chat-dur">{fmtDuration(selected.startTs, selected.endTs)}</span>
                <span className="cr-chat-count">
                  {selected.turns.filter(t => t.type === 'user').length} utterances
                </span>
              </div>
              <button className="cr-action-btn" onClick={exportSession}>↓ Export</button>
            </>
          ) : (
            <span className="cr-chat-placeholder">← 세션을 선택하세요</span>
          )}
        </div>

        {/* Timeline */}
        {selected && <Timeline session={selected} />}

        {/* Bubbles */}
        <div className="cr-chat-area" ref={chatRef}>
          {!selected ? (
            <div className="cr-empty cr-empty-center">세션을 선택하면 대화가 표시됩니다</div>
          ) : selected.turns.length === 0 ? (
            <div className="cr-empty cr-empty-center">이 세션에 대화 내용이 없습니다</div>
          ) : selected.turns.map(turn => (
            <ChatBubble
              key={turn.id}
              turn={turn}
              canReplay={canPublish && turn.type === 'user'}
              onReplay={handleReplay}
            />
          ))}
        </div>

        {/* Replay toast */}
        {replayMsg && (
          <div className="cr-toast">{replayMsg}</div>
        )}

      </div>
    </div>
  );
}

function SessionListPanel() {
  return <ConversationTabContent />;
}

export default SessionListPanel;
export { SessionListPanel };
