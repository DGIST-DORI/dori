/**
 * tabs/SystemTab.jsx  (v3 — layout redesign + sortable/searchable diagnostics)
 *
 * Layout:
 *   Left  (flex:1) : Topic Diagnostics — tall, sortable, searchable
 *   Right (300px)  : Connection Info / System Metrics (stacked, scrollable)
 *
 * Topic Publisher moved to <TopicPublisher> floating global component in App.jsx.
 */

import { useEffect, useMemo, useState } from 'react';
import Panel from '../components/Panel';
import { TOPIC_META, useStore } from '../core/store';
import { parseWsUrl } from '../core/url';
import './SystemTab.css';

const fmt = (val, suffix = '') =>
  val === null || val === undefined ? 'N/A' : `${val}${suffix}`;

const pct    = (v) => `${Math.min(100, Math.max(0, v ?? 0))}%`;
const isWarn = (v, t) => v !== null && v !== undefined && v >= t;

const primaryClass = (v, warnAt) =>
  v == null ? 'sys-metric-primary'
  : v >= warnAt ? 'sys-metric-primary is-warning'
  : 'sys-metric-primary is-ok';

const valueClass = (v, warnAt) =>
  v == null ? 'sys-metric-value'
  : v >= warnAt ? 'sys-metric-value is-warning'
  : 'sys-metric-value';

// ── Sortable column config ────────────────────────────────────────────────────

const COLUMNS = [
  { key: 'topic',       label: 'Topic',    sortFn: (a, b) => a.topic.localeCompare(b.topic) },
  { key: 'msgType',     label: 'Type',     sortFn: (a, b) => (a.msgType ?? '').localeCompare(b.msgType ?? '') },
  { key: 'pubSub',      label: 'Pub/Sub',  sortFn: null },
  { key: 'avgHz',       label: 'Avg Hz',   sortFn: (a, b) => (a.avgHz ?? -1) - (b.avgHz ?? -1) },
  { key: 'jitterMs',    label: 'Jitter',   sortFn: (a, b) => (a.jitterMs ?? -1) - (b.jitterMs ?? -1) },
  { key: 'bwBps',       label: 'BW (B/s)', sortFn: (a, b) => (a.bwBps ?? -1) - (b.bwBps ?? -1) },
  { key: 'avgMsgBytes', label: 'Avg Msg',  sortFn: (a, b) => (a.avgMsgBytes ?? -1) - (b.avgMsgBytes ?? -1) },
  { key: 'qosSummary',  label: 'QoS',      sortFn: null },
  { key: 'lastSeen',    label: 'Last seen',sortFn: (a, b) => (b.lastSeenMs ?? 0) - (a.lastSeenMs ?? 0) },
];

const hzClass = (hz) =>
  hz == null ? 'hz-none' : hz >= 1 ? 'hz-ok' : 'hz-warn';

// ── MetricCard ────────────────────────────────────────────────────────────────

function MetricCard({ title, usagePct, warnAt = 85, primary, details }) {
  const warn = isWarn(usagePct, warnAt);
  return (
    <div className="sys-metric-card">
      <div className="sys-metric-card-header">
        <span className="sys-metric-title">{title}</span>
        <span className={primaryClass(usagePct, warnAt)}>{primary}</span>
      </div>
      {usagePct != null && (
        <div className="sys-bar-wrap">
          <div className={`sys-bar-fill ${warn ? 'warn' : ''}`} style={{ width: pct(usagePct) }} />
        </div>
      )}
      <div className="sys-metric-details">
        {details.map(([label, value, extraCls]) => (
          <div key={label} className="sys-metric-row">
            <span>{label}</span>
            <span className={`sys-metric-value ${extraCls ?? ''}`}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────────────

export default function SystemTab() {
  const topicStats    = useStore((s) => s.topicStats);
  const connected     = useStore((s) => s.connected);
  const isDemoMode    = useStore((s) => s.isDemoMode);
  const wsUrl         = useStore((s) => s.wsUrl);
  const systemMetrics = useStore((s) => s.systemMetrics);

  const parsedWsUrl = parseWsUrl(wsUrl);
  const [nowMs, setNowMs] = useState(() => Date.now());

  // ── Diagnostics: sort + search state ─────────────────────────────────────
  const [search,    setSearch]    = useState('');
  const [sortKey,   setSortKey]   = useState('topic');
  const [sortDir,   setSortDir]   = useState(1); // 1 = asc, -1 = desc

  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  function handleSortClick(key) {
    if (COLUMNS.find(c => c.key === key)?.sortFn === null) return; // non-sortable
    setSortDir(prev => sortKey === key ? -prev : 1);
    setSortKey(key);
  }

  // Build row data
  const allRows = useMemo(() => Object.keys(TOPIC_META).map((t) => {
    const stat = topicStats[t] || {};
    return {
      topic:        t,
      msgType:      stat.msgType ?? null,
      pubCount:     stat.pubCount ?? null,
      subCount:     stat.subCount ?? null,
      pubSub:       `${fmt(stat.pubCount)}/${fmt(stat.subCount)}`,
      avgHz:        stat.avgHz ?? null,
      jitterMs:     stat.jitterMs ?? null,
      bwBps:        stat.bwBps ?? null,
      avgMsgBytes:  stat.avgMsgBytes ?? null,
      qosSummary:   stat.qosSummary ?? null,
      lastSeenMs:   stat.lastSeenMs ?? null,
    };
  }), [topicStats]);

  const filteredSorted = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q ? allRows.filter(r => r.topic.toLowerCase().includes(q)) : allRows;
    const col = COLUMNS.find(c => c.key === sortKey);
    if (!col?.sortFn) return filtered;
    return [...filtered].sort((a, b) => col.sortFn(a, b) * sortDir);
  }, [allRows, search, sortKey, sortDir]);

  // ── Derived metrics ───────────────────────────────────────────────────────
  const cpu  = systemMetrics?.cpu;
  const gpu  = systemMetrics?.gpu;
  const ram  = systemMetrics?.ram;
  const disk = systemMetrics?.disk;

  return (
    <div className="sys-layout">

      {/* ══ Left: Topic Diagnostics ══════════════════════════════════════ */}
      <Panel title="Topic Diagnostics" className="sys-panel-diag">
        <div className="sys-topic-diag">

          {/* Search + info bar */}
          <div className="sys-diag-toolbar">
            <input
              className="sys-diag-search"
              placeholder="Search topics…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <span className="sys-diag-count">
              {filteredSorted.length}/{allRows.length}
            </span>
            <span
              className="sys-tooltip"
              title="BW (B/s) = total JSON payload bytes ÷ rolling window. Avg Hz and jitter derived from inter-message timestamps."
            >ⓘ</span>
          </div>

          {/* Table */}
          <div className="sys-topic-diag-table-wrap">
            <table className="sys-topic-diag-table">
              <thead>
                <tr>
                  {COLUMNS.map((col) => {
                    const sortable = col.sortFn !== null;
                    const active   = sortKey === col.key;
                    return (
                      <th
                        key={col.key}
                        className={`${sortable ? 'sortable' : ''} ${active ? 'sorted' : ''}`}
                        onClick={() => handleSortClick(col.key)}
                        title={sortable ? `Sort by ${col.label}` : undefined}
                      >
                        {col.label}
                        {sortable && (
                          <span className="sys-sort-arrow">
                            {active ? (sortDir === 1 ? ' ↑' : ' ↓') : ' ↕'}
                          </span>
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {filteredSorted.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="sys-diag-empty">
                      No topics match "{search}"
                    </td>
                  </tr>
                ) : filteredSorted.map((row) => {
                  const lastSeenText = row.lastSeenMs
                    ? `${Math.max(0, Math.round((nowMs - row.lastSeenMs) / 1000))}s ago`
                    : 'N/A';
                  return (
                    <tr key={row.topic}>
                      <td className="sys-topic-cell" title={row.topic}>{row.topic}</td>
                      <td className="sys-type-cell">{fmt(row.msgType)}</td>
                      <td>{row.pubSub}</td>
                      <td className={hzClass(row.avgHz)}>{fmt(row.avgHz)}</td>
                      <td>{fmt(row.jitterMs, ' ms')}</td>
                      <td>{fmt(row.bwBps)}</td>
                      <td>{fmt(row.avgMsgBytes, ' B')}</td>
                      <td>{fmt(row.qosSummary)}</td>
                      <td>{lastSeenText}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </Panel>

      {/* ══ Right column ═════════════════════════════════════════════════ */}
      <div className="sys-col-right">

        {/* Connection Info */}
        <Panel title="Connection Info">
          <div className="sys-info">
            <div className="sys-info-row">
              <span>Status</span>
              <span style={{
                color: connected ? 'var(--green)'
                  : isDemoMode   ? 'var(--yellow)'
                  : 'var(--text-2)',
              }}>
                {connected ? 'ROS Connected' : isDemoMode ? 'Demo Mode' : 'Disconnected'}
              </span>
            </div>
            <div className="sys-info-row">
              <span>{connected ? 'Current URL' : 'Configured URL'}</span>
              <span>{wsUrl}</span>
            </div>
            {parsedWsUrl ? (
              <>
                <div className="sys-info-row"><span>Transport</span><span>{parsedWsUrl.protocol.toUpperCase()}</span></div>
                <div className="sys-info-row"><span>Host</span><span>{parsedWsUrl.host}</span></div>
                <div className="sys-info-row"><span>Port</span><span>{parsedWsUrl.port}</span></div>
                <div className="sys-info-row"><span>Path</span><span>{parsedWsUrl.path || '/'}</span></div>
              </>
            ) : (
              <div className="sys-info-row">
                <span>Transport</span>
                <span style={{ color: 'var(--red)' }}>Invalid URL</span>
              </div>
            )}
          </div>
        </Panel>

        {/* System Metrics */}
        <Panel title="System Metrics" className="sys-panel-metrics">
          <div className="sys-metrics-body">
            <MetricCard
              title="CPU"
              usagePct={cpu?.usage_pct}
              warnAt={85}
              primary={fmt(cpu?.usage_pct, '%')}
              details={[
                ['Logical',   fmt(cpu?.count_logical)],
                ['Physical',  fmt(cpu?.count_physical)],
                ['Load avg',  cpu?.load_avg_1_5_15?.join(' / ') ?? 'N/A'],
              ]}
            />
            <MetricCard
              title="RAM"
              usagePct={ram?.usage_pct}
              warnAt={85}
              primary={`${fmt(ram?.used_mb)} / ${fmt(ram?.total_mb)} MB`}
              details={[
                ['Usage',     fmt(ram?.usage_pct, '%'), valueClass(ram?.usage_pct, 85).replace('sys-metric-value','').trim()],
                ['Available', fmt(ram?.available_mb, ' MB')],
              ]}
            />
            <MetricCard
              title="GPU"
              usagePct={gpu?.utilization_pct}
              warnAt={90}
              primary={fmt(gpu?.utilization_pct, '%')}
              details={[
                ['Provider', fmt(gpu?.provider)],
                ['VRAM',     gpu?.memory_used_mb != null ? `${gpu.memory_used_mb} / ${gpu.memory_total_mb} MB` : 'N/A'],
                ['Temp',     fmt(gpu?.temperature_c, '°C'), valueClass(gpu?.temperature_c, 80).replace('sys-metric-value','').trim()],
              ]}
            />
            <MetricCard
              title="Disk"
              usagePct={disk?.usage_pct}
              warnAt={90}
              primary={`${fmt(disk?.used_gb)} / ${fmt(disk?.total_gb)} GB`}
              details={[
                ['Usage', fmt(disk?.usage_pct, '%'), valueClass(disk?.usage_pct, 90).replace('sys-metric-value','').trim()],
              ]}
            />
          </div>
        </Panel>

      </div>{/* end right col */}

    </div>
  );
}
