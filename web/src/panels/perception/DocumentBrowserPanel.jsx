import { apiFetch } from '../../core/api';
import { useState, useEffect, useCallback } from 'react';
import './DocumentBrowserPanel.css';

const API = '/api/knowledge';

function DocumentBrowserPanel() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('');

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${API}/documents`);
      if (res.ok) setDocs(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadDocs() {
      setLoading(true);
      try {
        const res = await apiFetch(`${API}/documents`);
        if (!cancelled && res.ok) setDocs(await res.json());
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    }

    loadDocs();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = docs.filter((d) =>
    d.source.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="layout-panel-body km-document-browser-panel">
      <div className="panel-section">
        <div className="km-toolbar km-toolbar-with-badge">
          <input
            className="input-search"
            placeholder="Filter by filename…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <span className="km-panel-badge">{docs.length}</span>
          <button className="btn btn-sm" onClick={fetchDocs} disabled={loading}>
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
    </div>
  );
}

export default DocumentBrowserPanel;
export { DocumentBrowserPanel };
