/**
 * panels/EventLog.jsx
 * Real-time event log panel.
 * Shows all ROS messages as a timestamped stream with tag colors.
 */

import { useRef, useEffect, useState, useCallback } from 'react';
import { LOG_TAG_ORDER, useStore } from '../core/store';
import './EventLog.css';

const TAG_ORDER = ['ALL', ...LOG_TAG_ORDER];

function fmtTime(date) {
  const h  = String(date.getHours()).padStart(2, '0');
  const m  = String(date.getMinutes()).padStart(2, '0');
  const s  = String(date.getSeconds()).padStart(2, '0');
  const ms = String(date.getMilliseconds()).padStart(3, '0');
  return `${h}:${m}:${s}.${ms}`;
}

export default function EventLog() {
  const log      = useStore(s => s.log);
  const clearLog = useStore(s => s.clearLog);

  const [filter, setFilter]     = useState('ALL');
  const [paused, setPaused]     = useState(false);
  const [expanded, setExpanded] = useState(null); // entry id with raw shown
  const [search, setSearch]     = useState('');

  const listRef       = useRef(null);
  const pausedRef     = useRef(false);
  const frozenLog     = useRef([]);

  pausedRef.current = paused;

  // Auto-scroll to top (newest) unless paused
  useEffect(() => {
    if (!paused && listRef.current) {
      listRef.current.scrollTop = 0;
    }
    if (paused && frozenLog.current.length === 0) {
      frozenLog.current = log;
    }
    if (!paused) {
      frozenLog.current = [];
    }
  }, [log, paused]);

  const displayLog = paused ? frozenLog.current : log;

  const filtered = displayLog.filter(e => {
    if (filter !== 'ALL' && e.tag !== filter) return false;
    if (search && !e.text.toLowerCase().includes(search.toLowerCase()) &&
        !e.tag.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const toggleExpand = useCallback((id) => {
    setExpanded(prev => prev === id ? null : id);
  }, []);

  return (
    <div className="el-root">
      {/* ── Toolbar ── */}
      <div className="el-toolbar">
        <div className="el-filters">
          {TAG_ORDER.map(tag => (
            <button
              key={tag}
              className={`el-filter-btn ${filter === tag ? 'active' : ''} tag-${tag}`}
              onClick={() => setFilter(tag)}
            >
              {tag}
            </button>
          ))}
        </div>

        <div className="el-actions">
          <input
            className="el-search"
            placeholder="search…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <button
            className={`el-action-btn ${paused ? 'active' : ''}`}
            onClick={() => setPaused(p => !p)}
            title="Pause auto-scroll"
          >
            {paused ? '▶ resume' : '⏸ pause'}
          </button>
          <button
            className="el-action-btn danger"
            onClick={clearLog}
            title="Clear log"
          >
            ✕ clear
          </button>
        </div>
      </div>

      {/* ── Count ── */}
      <div className="el-meta">
        <span className="el-count">{filtered.length} entries</span>
        {filter !== 'ALL' && <span className="el-count dim"> / {displayLog.length} total</span>}
        {paused && <span className="el-paused-badge">PAUSED</span>}
      </div>

      {/* ── Log List ── */}
      <div className="el-list" ref={listRef}>
        {filtered.length === 0 && (
          <div className="el-empty">
            {search ? 'no matches' : 'waiting for messages…'}
          </div>
        )}

        {filtered.map(entry => (
          <div
            key={entry.id}
            className={`el-entry ${expanded === entry.id ? 'expanded' : ''}`}
            onClick={() => entry.raw != null && toggleExpand(entry.id)}
            style={{ cursor: entry.raw != null ? 'pointer' : 'default' }}
          >
            <span className="el-ts">{fmtTime(entry.ts)}</span>
            <span className={`el-tag tag-${entry.tag}`}>{entry.tag.padEnd(7)}</span>
            <span className="el-text">{entry.text}</span>
            {entry.raw != null && (
              <span className="el-expand-hint">{expanded === entry.id ? '▲' : '▼'}</span>
            )}

            {expanded === entry.id && entry.raw != null && (
              <div className="el-raw">
                <pre>{typeof entry.raw === 'string'
                  ? (() => { try { return JSON.stringify(JSON.parse(entry.raw), null, 2); } catch (_) { return entry.raw; } })()
                  : JSON.stringify(entry.raw, null, 2)
                }</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
