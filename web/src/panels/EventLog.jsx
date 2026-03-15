/**
 * panels/EventLog.jsx
 * Real-time event log panel.
 * Shows all ROS messages as a timestamped stream with tag colors.
 *
 * Filter behaviour (v2):
 *  - Multi-select: click a tag to add/remove it from the active set.
 *  - ALL button: when active (no tags selected) click to select every tag;
 *                when every tag is selected click again to go back to ALL.
 *  - Deselecting all tags automatically falls back to ALL (show everything).
 *  - "Hide noisy" toggle: hides SYS + STATE tags that fire every second.
 */

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { LOG_TAG_ORDER, LOG_TAGS, useStore } from '../core/store';
import './EventLog.css';

// Tags that spam every ~1 s and can be hidden with the noise toggle
const NOISY_TAGS = new Set([LOG_TAGS.SYS, LOG_TAGS.STATE]);

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

  // ── Filter state ──────────────────────────────────────────────────────────
  // activeTags: Set of selected tag strings.
  // Empty set  → ALL mode (no filter applied, show everything).
  const [activeTags, setActiveTags] = useState(new Set()); // empty = ALL
  const [hideNoisy,  setHideNoisy]  = useState(false);

  const [paused,   setPaused]   = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [search,   setSearch]   = useState('');

  const listRef    = useRef(null);
  const frozenLog  = useRef([]);

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

  // ── Filter helpers ────────────────────────────────────────────────────────
  const isAllMode = activeTags.size === 0;

  const handleTagClick = useCallback((tag) => {
    if (tag === 'ALL') {
      // ALL clicked:
      //   - if already ALL mode → select every tag explicitly (toggle to multi)
      //   - if all tags selected → back to ALL
      setActiveTags(prev => {
        if (prev.size === 0) {
          // ALL → select all tags
          return new Set(LOG_TAG_ORDER);
        }
        // any state → back to ALL
        return new Set();
      });
      return;
    }

    setActiveTags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) {
        next.delete(tag);
      } else {
        next.add(tag);
      }
      // If nothing left selected, auto-revert to ALL
      return next; // empty set = ALL mode
    });
  }, []);

  // ── Derived display list ──────────────────────────────────────────────────
  const displayLog = paused ? frozenLog.current : log;

  const filtered = useMemo(() => {
    return displayLog.filter(e => {
      // Noisy-tag hide
      if (hideNoisy && NOISY_TAGS.has(e.tag)) return false;
      // Tag filter (ALL mode = show everything passing other checks)
      if (!isAllMode && !activeTags.has(e.tag)) return false;
      // Search
      if (search) {
        const q = search.toLowerCase();
        if (!e.text.toLowerCase().includes(q) && !e.tag.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [displayLog, hideNoisy, isAllMode, activeTags, search]);

  const toggleExpand = useCallback((id) => {
    setExpanded(prev => prev === id ? null : id);
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="el-root">
      {/* ── Toolbar ── */}
      <div className="el-toolbar">

        {/* Tag filter buttons */}
        <div className="el-filters">
          {/* ALL button */}
          <button
            className={`el-filter-btn tag-ALL ${isAllMode ? 'active' : ''}`}
            onClick={() => handleTagClick('ALL')}
            title={isAllMode ? 'Click to select all tags' : 'Click to clear all filters'}
          >
            ALL
          </button>

          {/* Individual tag buttons */}
          {LOG_TAG_ORDER.map(tag => (
            <button
              key={tag}
              className={`el-filter-btn tag-${tag} ${activeTags.has(tag) ? 'active' : ''}`}
              onClick={() => handleTagClick(tag)}
            >
              {tag}
            </button>
          ))}
        </div>

        {/* Actions row */}
        <div className="el-actions">
          {/* Hide noisy toggle */}
          <button
            className={`el-action-btn el-noise-btn ${hideNoisy ? 'active' : ''}`}
            onClick={() => setHideNoisy(p => !p)}
            title="Hide SYS / STATE entries (fire every ~1 s)"
          >
            {hideNoisy ? 'show SYS' : 'hide SYS'}
          </button>

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

      {/* ── Count / status bar ── */}
      <div className="el-meta">
        <span className="el-count">{filtered.length} entries</span>
        {(!isAllMode || hideNoisy) && (
          <span className="el-count dim"> / {displayLog.length} total</span>
        )}
        {hideNoisy && (
          <span className="el-noise-badge">SYS hidden</span>
        )}
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
                  ? (() => { try { return JSON.stringify(JSON.parse(entry.raw), null, 2); } catch { return entry.raw; } })()
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
