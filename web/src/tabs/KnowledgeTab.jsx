/**
 * tabs/KnowledgeTab.jsx
 * Knowledge Manager tab — GUI for RAG knowledge base management.
 *
 * Features:
 *   1. Menu Parser  — upload cafeteria xlsx/pdf → parse → save to processed/
 *   2. Index Builder — trigger incremental FAISS rebuild via backend API
 *   3. Document Browser — list indexed .txt chunks with source info
 *   4. Building Editor — inline edit campus_knowledge.json entries
 *
 * Requires: dashboard_api server running on port 3001
 *   POST /api/knowledge/parse-menu        multipart file upload
 *   POST /api/knowledge/build-index       trigger build_index.py
 *   GET  /api/knowledge/documents         list indexed docs
 *   GET  /api/knowledge/buildings         get campus_knowledge.json
 *   PUT  /api/knowledge/buildings/:key    update a single building entry
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import Panel from '../components/Panel';
import './KnowledgeTab.css';

const API = 'http://localhost:3001/api/knowledge';

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const map = {
    idle:    ['km-badge km-badge-idle',    '—'],
    running: ['km-badge km-badge-running', 'RUNNING'],
    ok:      ['km-badge km-badge-ok',      'OK'],
    error:   ['km-badge km-badge-error',   'ERROR'],
  };
  const [cls, label] = map[status] ?? map.idle;
  return <span className={cls}>{label}</span>;
}

function LogPane({ lines }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);
  return (
    <div className="km-log" ref={ref}>
      {lines.length === 0
        ? <span className="km-log-empty">No output yet.</span>
        : lines.map((l, i) => <div key={i} className="km-log-line">{l}</div>)
      }
    </div>
  );
}

// ── Section 1: Menu Parser ────────────────────────────────────────────────────

function MenuParserPanel() {
  const [files,   setFiles]   = useState([]);
  const [status,  setStatus]  = useState('idle');
  const [log,     setLog]     = useState([]);
  const inputRef = useRef(null);

  function appendLog(msg) {
    setLog(prev => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  async function handleUpload() {
    if (files.length === 0) return;
    setStatus('running');
    setLog([]);
    appendLog(`Uploading ${files.length} file(s)…`);

    const fd = new FormData();
    files.forEach(f => fd.append('files', f));

    try {
      const res = await fetch(`${API}/parse-menu`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      data.results.forEach(r => {
        if (r.ok) {
          appendLog(`✓ ${r.filename}  →  ${r.out_json}`);
          appendLog(`  └ ${r.out_txt}`);
        } else {
          appendLog(`✗ ${r.filename}  —  ${r.error}`);
        }
      });
      setStatus(data.results.every(r => r.ok) ? 'ok' : 'error');
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      setStatus('error');
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    const dropped = [...e.dataTransfer.files].filter(
      f => f.name.endsWith('.xlsx') || f.name.endsWith('.pdf')
    );
    setFiles(prev => [...prev, ...dropped]);
  }

  function removeFile(idx) {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  }

  return (
    <Panel title="Menu Parser" className="km-panel">
      <div className="km-section">
        <p className="km-hint">
          Upload weekly menu files (<code>.xlsx</code> / <code>.pdf</code>).
          Parsed output is saved to <code>data/campus/processed/cafeteria/</code>.
        </p>

        {/* Drop zone */}
        <div
          className={`km-dropzone ${files.length > 0 ? 'has-files' : ''}`}
          onDragOver={e => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.pdf"
            multiple
            style={{ display: 'none' }}
            onChange={e => setFiles(prev => [...prev, ...[...e.target.files]])}
          />
          {files.length === 0
            ? <span className="km-dropzone-hint">Drop .xlsx / .pdf here or click to browse</span>
            : (
              <ul className="km-file-list" onClick={e => e.stopPropagation()}>
                {files.map((f, i) => (
                  <li key={i} className="km-file-item">
                    <span className="km-file-name">{f.name}</span>
                    <span className="km-file-size">{(f.size / 1024).toFixed(1)} KB</span>
                    <button className="km-file-remove" onClick={() => removeFile(i)}>✕</button>
                  </li>
                ))}
              </ul>
            )
          }
        </div>

        <div className="km-actions">
          <button
            className="km-btn km-btn-primary"
            disabled={files.length === 0 || status === 'running'}
            onClick={handleUpload}
          >
            {status === 'running' ? 'Parsing…' : 'Parse & Save'}
          </button>
          {files.length > 0 && status !== 'running' && (
            <button className="km-btn" onClick={() => { setFiles([]); setLog([]); setStatus('idle'); }}>
              Clear
            </button>
          )}
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
      </div>
    </Panel>
  );
}

// ── Section 2: Index Builder ──────────────────────────────────────────────────

function IndexBuilderPanel() {
  const [status,    setStatus]    = useState('idle');
  const [log,       setLog]       = useState([]);
  const [incremental, setIncremental] = useState(true);
  const [indexInfo, setIndexInfo] = useState(null);
  const pollRef = useRef(null);

  function appendLog(msg) {
    setLog(prev => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  const fetchIndexInfo = useCallback(async () => {
    try {
      const res = await fetch(`${API}/index-info`);
      if (res.ok) setIndexInfo(await res.json());
    } catch { /* backend might be offline */ }
  }, []);

  useEffect(() => {
    fetchIndexInfo();
  }, [fetchIndexInfo]);

  async function handleBuild() {
    setStatus('running');
    setLog([]);
    appendLog(`Starting ${incremental ? 'incremental' : 'full'} index rebuild…`);

    try {
      const res = await fetch(`${API}/build-index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incremental }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      // Poll job status
      const jobId = data.job_id;
      appendLog(`Job started: ${jobId}`);

      pollRef.current = setInterval(async () => {
        const r = await fetch(`${API}/build-index/status/${jobId}`);
        const d = await r.json();
        d.new_lines?.forEach(l => appendLog(l));
        if (d.status === 'done') {
          clearInterval(pollRef.current);
          appendLog(`✓ Done — ${d.total_chunks} chunks indexed.`);
          setStatus('ok');
          fetchIndexInfo();
        } else if (d.status === 'error') {
          clearInterval(pollRef.current);
          appendLog(`✗ Build failed: ${d.error}`);
          setStatus('error');
        }
      }, 800);
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      setStatus('error');
    }
  }

  useEffect(() => () => clearInterval(pollRef.current), []);

  return (
    <Panel title="Index Builder" className="km-panel">
      <div className="km-section">
        <p className="km-hint">
          Embeds <code>data/campus/processed/**/*.txt</code> with
          MiniLM-L12 and saves a FAISS index for RAG retrieval.
        </p>

        {indexInfo && (
          <div className="km-index-info">
            <div className="km-info-row">
              <span>Vectors</span><span>{indexInfo.total_vectors ?? '—'}</span>
            </div>
            <div className="km-info-row">
              <span>Documents</span><span>{indexInfo.total_docs ?? '—'}</span>
            </div>
            <div className="km-info-row">
              <span>Built</span><span>{indexInfo.built_at ?? '—'}</span>
            </div>
          </div>
        )}

        <label className="km-checkbox-row">
          <input
            type="checkbox"
            checked={incremental}
            onChange={e => setIncremental(e.target.checked)}
          />
          <span>Incremental (skip unchanged files)</span>
        </label>

        <div className="km-actions">
          <button
            className="km-btn km-btn-primary"
            disabled={status === 'running'}
            onClick={handleBuild}
          >
            {status === 'running' ? 'Building…' : 'Build Index'}
          </button>
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
      </div>
    </Panel>
  );
}

// ── Section 3: Document Browser ───────────────────────────────────────────────

function DocumentBrowserPanel() {
  const [docs,    setDocs]    = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter,  setFilter]  = useState('');

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/documents`);
      if (res.ok) setDocs(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const filtered = docs.filter(d =>
    d.source.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <Panel title="Indexed Documents" badge={docs.length} className="km-panel">
      <div className="km-section">
        <div className="km-toolbar">
          <input
            className="km-search"
            placeholder="Filter by filename…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <button className="km-btn" onClick={fetchDocs} disabled={loading}>
            {loading ? '…' : '↻'}
          </button>
        </div>

        <div className="km-doc-list">
          {filtered.length === 0 && !loading && (
            <div className="km-empty">No documents found.</div>
          )}
          {filtered.map((doc, i) => (
            <div key={i} className="km-doc-item">
              <div className="km-doc-source">{doc.source}</div>
              <div className="km-doc-meta">
                <span>{doc.chunks} chunks</span>
                <span>{doc.size_kb} KB</span>
                <span className="km-doc-mtime">{doc.modified}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  );
}

// ── Section 4: Building Editor ────────────────────────────────────────────────

const EMPTY_BUILDING = {
  bldg_no: '', name_ko: '', name_en: '',
  description_ko: '', description_en: '',
  coordinates: [0.0, 0.0], floor: 1,
  keywords: [], hours: '', facilities: [], url: '',
};

function BuildingEditorPanel() {
  const [buildings, setBuildings]   = useState({});
  const [selected,  setSelected]    = useState(null);
  const [draft,     setDraft]       = useState(null);
  const [saving,    setSaving]      = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle');
  const [filter,    setFilter]      = useState('');

  const fetchBuildings = useCallback(async () => {
    try {
      const res = await fetch(`${API}/buildings`);
      if (res.ok) setBuildings(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchBuildings(); }, [fetchBuildings]);

  function selectBuilding(key) {
    setSelected(key);
    setDraft({ ...EMPTY_BUILDING, ...buildings[key] });
    setSaveStatus('idle');
  }

  function updateDraft(field, value) {
    setDraft(prev => ({ ...prev, [field]: value }));
  }

  async function handleSave() {
    if (!selected || !draft) return;
    setSaving(true);
    setSaveStatus('running');
    try {
      const res = await fetch(`${API}/buildings/${encodeURIComponent(selected)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      await fetchBuildings();
      setSaveStatus('ok');
    } catch (e) {
      setSaveStatus('error');
    }
    setSaving(false);
  }

  const keys = Object.keys(buildings).filter(k =>
    k.toLowerCase().includes(filter.toLowerCase()) ||
    (buildings[k].name_ko ?? '').includes(filter) ||
    (buildings[k].name_en ?? '').toLowerCase().includes(filter.toLowerCase())
  );

  const isEmpty = (b) => !b.name_ko && !b.name_en;

  return (
    <Panel title="Building Editor" className="km-panel km-panel-wide">
      <div className="km-building-layout">
        {/* Left: key list */}
        <div className="km-building-list">
          <input
            className="km-search"
            placeholder="Search…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <div className="km-building-keys">
            {keys.map(k => (
              <button
                key={k}
                className={`km-building-key ${selected === k ? 'active' : ''} ${isEmpty(buildings[k]) ? 'empty' : ''}`}
                onClick={() => selectBuilding(k)}
              >
                <span className="km-key-id">{k}</span>
                {isEmpty(buildings[k])
                  ? <span className="km-key-empty">unfilled</span>
                  : <span className="km-key-name">{buildings[k].name_ko}</span>
                }
              </button>
            ))}
          </div>
        </div>

        {/* Right: editor */}
        <div className="km-building-editor">
          {!draft
            ? <div className="km-empty km-empty-center">Select a building to edit</div>
            : (
              <>
                <div className="km-field-grid">
                  {[
                    ['Name (KO)',    'name_ko',          'text'],
                    ['Name (EN)',    'name_en',          'text'],
                    ['Hours',        'hours',             'text'],
                    ['URL',          'url',               'text'],
                    ['Floor',        'floor',             'number'],
                  ].map(([label, field, type]) => (
                    <label key={field} className="km-field">
                      <span className="km-field-label">{label}</span>
                      <input
                        type={type}
                        className="km-input"
                        value={draft[field] ?? ''}
                        onChange={e => updateDraft(field,
                          type === 'number' ? Number(e.target.value) : e.target.value
                        )}
                      />
                    </label>
                  ))}
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Description (KO)</span>
                    <textarea
                      className="km-input km-textarea"
                      value={draft.description_ko ?? ''}
                      onChange={e => updateDraft('description_ko', e.target.value)}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Description (EN)</span>
                    <textarea
                      className="km-input km-textarea"
                      value={draft.description_en ?? ''}
                      onChange={e => updateDraft('description_en', e.target.value)}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Keywords (comma-separated)</span>
                    <input
                      type="text"
                      className="km-input"
                      value={(draft.keywords ?? []).join(', ')}
                      onChange={e => updateDraft('keywords',
                        e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      )}
                    />
                  </label>
                  <label className="km-field km-field-full">
                    <span className="km-field-label">Facilities (comma-separated)</span>
                    <input
                      type="text"
                      className="km-input"
                      value={(draft.facilities ?? []).join(', ')}
                      onChange={e => updateDraft('facilities',
                        e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      )}
                    />
                  </label>
                  <label className="km-field">
                    <span className="km-field-label">Coord lat</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="km-input"
                      value={draft.coordinates?.[0] ?? 0}
                      onChange={e => updateDraft('coordinates',
                        [parseFloat(e.target.value), draft.coordinates?.[1] ?? 0]
                      )}
                    />
                  </label>
                  <label className="km-field">
                    <span className="km-field-label">Coord lng</span>
                    <input
                      type="number"
                      step="0.0001"
                      className="km-input"
                      value={draft.coordinates?.[1] ?? 0}
                      onChange={e => updateDraft('coordinates',
                        [draft.coordinates?.[0] ?? 0, parseFloat(e.target.value)]
                      )}
                    />
                  </label>
                </div>

                <div className="km-actions">
                  <button
                    className="km-btn km-btn-primary"
                    disabled={saving}
                    onClick={handleSave}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    className="km-btn"
                    onClick={() => { setDraft({ ...EMPTY_BUILDING, ...buildings[selected] }); setSaveStatus('idle'); }}
                  >
                    Reset
                  </button>
                  <StatusBadge status={saveStatus} />
                </div>
              </>
            )
          }
        </div>
      </div>
    </Panel>
  );
}

// ── Root tab ──────────────────────────────────────────────────────────────────

export default function KnowledgeTab() {
  return (
    <div className="km-layout">
      <div className="km-col km-col-left">
        <MenuParserPanel />
        <IndexBuilderPanel />
      </div>
      <div className="km-col km-col-right">
        <DocumentBrowserPanel />
        <BuildingEditorPanel />
      </div>
    </div>
  );
}
