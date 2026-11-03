import { apiFetch } from '../../core/api';
import { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import './MenuParserPanel.css';

const API = '/api/knowledge';

function StatusBadge({ status }) {
  const map = {
    idle: ['badge', '—'],
    running: ['badge badge-running', 'RUNNING'],
    ok: ['badge badge-ok', 'OK'],
    error: ['badge badge-error', 'ERROR'],
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
    <div className="log-pane" ref={ref}>
      {lines.length === 0
        ? <span className="log-pane-empty">No output yet.</span>
        : lines.map((l, i) => <div key={i} className="log-pane-line">{l}</div>)}
    </div>
  );
}

function MenuParserPanel() {
  const [files, setFiles] = useState([]);
  const [status, setStatus] = useState('idle');
  const [log, setLog] = useState([]);
  const inputRef = useRef(null);

  function appendLog(msg) {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  async function handleUpload() {
    if (files.length === 0) return;
    setStatus('running');
    setLog([]);
    appendLog(`Uploading ${files.length} file(s)…`);

    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));

    try {
      const res = await apiFetch(`${API}/parse-menu`, { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      data.results.forEach((r) => {
        if (r.ok) {
          appendLog(`[OK] ${r.filename}  →  ${r.out_json}`);
          appendLog(`  └ ${r.out_txt}`);
        } else {
          appendLog(`[ERR] ${r.filename}  —  ${r.error}`);
        }
      });
      setStatus(data.results.every((r) => r.ok) ? 'ok' : 'error');
    } catch (e) {
      appendLog(`ERROR: ${e.message}`);
      setStatus('error');
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    const dropped = [...e.dataTransfer.files].filter(
      (f) => f.name.endsWith('.xlsx') || f.name.endsWith('.pdf'),
    );
    setFiles((prev) => [...prev, ...dropped]);
  }

  function removeFile(idx) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  return (
    <div className="layout-panel-body km-menu-parser-panel">
      <div className="panel-section">
        <p className="hint-text">
          Upload weekly menu files (<code>.xlsx</code> / <code>.pdf</code>).
          Parsed output is saved to <code>data/campus/processed/cafeteria/</code>.
        </p>

        <div
          className={`km-dropzone ${files.length > 0 ? 'has-files' : ''}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.pdf"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => setFiles((prev) => [...prev, ...[...e.target.files]])}
          />
          {files.length === 0
            ? <span className="km-dropzone-hint">Drop .xlsx / .pdf here or click to browse</span>
            : (
              <ul className="km-file-list" onClick={(e) => e.stopPropagation()}>
                {files.map((f, i) => (
                  <li key={i} className="km-file-item">
                    <span className="km-file-name">{f.name}</span>
                    <span className="km-file-size">{(f.size / 1024).toFixed(1)} KB</span>
                    <button className="km-file-remove" onClick={() => removeFile(i)} aria-label="Remove">
                      <X size={10} strokeWidth={2.5} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </div>

        <div className="row row-wrap">
          <button
            className="btn btn-sm btn-primary"
            disabled={files.length === 0 || status === 'running'}
            onClick={handleUpload}
          >
            {status === 'running' ? 'Parsing…' : 'Parse & Save'}
          </button>
          {files.length > 0 && status !== 'running' && (
            <button className="btn btn-sm" onClick={() => { setFiles([]); setLog([]); setStatus('idle'); }}>
              Clear
            </button>
          )}
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
      </div>
    </div>
  );
}

export default MenuParserPanel;
export { MenuParserPanel };
