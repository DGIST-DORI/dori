/**
 * panels/EventLog.jsx
 * Real-time event log panel.
 *
 * Toolbar:
 *   Row 1 — Presets : VOICE · PERCEPTION · HRI · NAV · NOISY
 *   Row 2 — Tags    : ALL · STATE · WAKE · STT · …
 *   Row 3 — Actions : search · pause · clear
 *
 * Filter logic:
 *   activeTags (Set) : empty = ALL mode (show everything)
 *   Preset click     : add preset's tags to activeTags if any are missing;
 *                      remove them all if all are already selected
 *   Tag click        : toggle individual tag in/out of activeTags
 *   ALL active       : only when activeTags is empty OR equals all tags
 */

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { LOG_TAG_ORDER, LOG_TAGS, useStore } from '../core/store';
import './EventLog.css';

// ── Presets ───────────────────────────────────────────────────────────────────

const ALL_TAGS = new Set(LOG_TAG_ORDER);

const PRESETS = [
  {
    id: 'VOICE',
    label: 'VOICE',
    title: 'WAKE · STT · LLM · TTS',
    tags: new Set([LOG_TAGS.WAKE, LOG_TAGS.STT, LOG_TAGS.LLM, LOG_TAGS.TTS]),
  },
  {
    id: 'PERCEPTION',
    label: 'PERCEPTION',
    title: 'GESTURE · EXPR · TRACK',
    tags: new Set([LOG_TAGS.GESTURE, LOG_TAGS.EXPR, LOG_TAGS.TRACK]),
  },
  {
    id: 'HRI',
    label: 'HRI',
    title: 'STATE · WAKE · STT · LLM · TTS · GESTURE · EXPR · TRACK',
    tags: new Set([
      LOG_TAGS.STATE, LOG_TAGS.WAKE,
      LOG_TAGS.STT, LOG_TAGS.LLM, LOG_TAGS.TTS,
      LOG_TAGS.GESTURE, LOG_TAGS.EXPR, LOG_TAGS.TRACK,
    ]),
  },
  {
    id: 'NAV',
    label: 'NAV',
    title: 'NAV · STATE',
    tags: new Set([LOG_TAGS.NAV, LOG_TAGS.STATE]),
  },
  {
    id: 'NOISY',
    label: 'NOISY',
    title: 'SYS · STATE',
    tags: new Set([LOG_TAGS.SYS, LOG_TAGS.STATE]),
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** True if every tag in `preset` is present in `active` */
function presetActive(active, preset) {
  for (const t of preset) if (!active.has(t)) return false;
  return preset.size > 0;
}

function fmtTime(date) {
  const h  = String(date.getHours()).padStart(2, '0');
  const m  = String(date.getMinutes()).padStart(2, '0');
  const s  = String(date.getSeconds()).padStart(2, '0');
  const ms = String(date.getMilliseconds()).padStart(3, '0');
  return `${h}:${m}:${s}.${ms}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function EventLog() {
  const log      = useStore(s => s.log);
  const clearLog = useStore(s => s.clearLog);

  const [activeTags, setActiveTags] = useState(new Set()); // empty = show all
  const [paused,     setPaused]     = useState(false);
  const [expanded,   setExpanded]   = useState(null);
  const [search,     setSearch]     = useState('');

  const listRef   = useRef(null);
  const frozenLog = useRef([]);

  useEffect(() => {
    if (!paused && listRef.current) listRef.current.scrollTop = 0;
    if (paused && frozenLog.current.length === 0) frozenLog.current = log;
    if (!paused) frozenLog.current = [];
  }, [log, paused]);

  // ── Handlers ─────────────────────────────────────────────────────────────────

  /** ALL is visually active only when nothing is selected, or everything is selected */
  const isAllMode  = activeTags.size === 0;
  const isAllFull  = activeTags.size === ALL_TAGS.size;
  const allActive  = isAllMode || isAllFull;

  const handleTagClick = useCallback((tag) => {
    setActiveTags(prev => {
      const next = new Set(prev);
      next.has(tag) ? next.delete(tag) : next.add(tag);
      return next;
    });
  }, []);

  const handleAllClick = useCallback(() => {
    setActiveTags(prev => {
      // If nothing selected → select all; otherwise → clear all
      return prev.size === 0 ? new Set(ALL_TAGS) : new Set();
    });
  }, []);

  const handlePresetClick = useCallback((presetTags) => {
    setActiveTags(prev => {
      const next = new Set(prev);
      if (presetActive(prev, presetTags)) {
        // All preset tags currently selected → remove them
        for (const t of presetTags) next.delete(t);
      } else {
        // Some or none selected → add them all
        for (const t of presetTags) next.add(t);
      }
      return next;
    });
  }, []);

  // ── Filtering ─────────────────────────────────────────────────────────────────

  const displayLog = paused ? frozenLog.current : log;

  const filtered = useMemo(() => displayLog.filter(e => {
    if (!isAllMode && !activeTags.has(e.tag)) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!e.text.toLowerCase().includes(q) && !e.tag.toLowerCase().includes(q)) return false;
    }
    return true;
  }), [displayLog, isAllMode, activeTags, search]);

  const toggleExpand = useCallback((id) => {
    setExpanded(prev => prev === id ? null : id);
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="el-root">
      <div className="el-toolbar">

        {/* ── Row 1: Presets ── */}
        <div className="el-presets">
          <span className="el-row-label">PRESET</span>
          {PRESETS.map(preset => (
            <button
              key={preset.id}
              className={`el-preset-btn ${presetActive(activeTags, preset.tags) ? 'active' : ''}`}
              onClick={() => handlePresetClick(preset.tags)}
              title={preset.title}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* ── Row 2: Individual tag buttons ── */}
        <div className="el-filters">
          <span className="el-row-label">TAG</span>
          <button
            className={`el-filter-btn tag-ALL ${allActive ? 'active' : ''}`}
            onClick={handleAllClick}
            title="Toggle all tags"
          >
            ALL
          </button>
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

        {/* ── Row 3: Actions ── */}
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

      {/* ── Meta bar ── */}
      <div className="el-meta">
        <span className="el-count">{filtered.length} entries</span>
        {!isAllMode && (
          <span className="el-count dim"> / {displayLog.length} total</span>
        )}
        {paused && <span className="el-paused-badge">PAUSED</span>}
      </div>

      {/* ── Log list ── */}
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
