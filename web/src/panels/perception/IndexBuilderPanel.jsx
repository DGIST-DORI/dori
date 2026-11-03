import { apiFetch } from '../../core/api';
import { useState, useEffect, useRef, useCallback } from 'react';
import './IndexBuilderPanel.css';
import { normalizePollLines } from './logUtils';

const API = '/api/knowledge';
const DEFAULT_INDEX_INFO = { total_vectors: null, total_docs: null, built_at: null };

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

function IndexBuilderPanel() {
  const [status, setStatus] = useState('idle');
  const [log, setLog] = useState([]);
  const [incremental, setIncremental] = useState(true);
  const [batchSize, setBatchSize] = useState(16);
  const [chunkBatchSize, setChunkBatchSize] = useState(512);
  const [indexInfo, setIndexInfo] = useState(DEFAULT_INDEX_INFO);
  const pollRef = useRef(null);
  const cursorRef = useRef(0);

  function appendLog(msg) {
    setLog((prev) => [...prev, `${new Date().toLocaleTimeString()}  ${msg}`]);
  }

  function appendPolledLines(lines) {
    const normalizedLines = normalizePollLines(lines, { dedupeWithinBatch: true });
    normalizedLines.forEach((line) => appendLog(line));
  }

  const fetchIndexInfo = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/index-info`);
      if (!res.ok) {
        setIndexInfo(DEFAULT_INDEX_INFO);
        return;
      }
      setIndexInfo(await res.json());
    } catch {
      /* backend might be offline */
      setIndexInfo(DEFAULT_INDEX_INFO);
    }
  }, []);

  useEffect(() => {
    fetchIndexInfo();
  }, [fetchIndexInfo]);

  async function handleBuild() {
    setStatus('running');
    setLog([]);
    cursorRef.current = 0;
    clearInterval(pollRef.current);
    appendLog(`Starting ${incremental ? 'incremental' : 'full'} index rebuild…`);

    try {
      const res = await apiFetch(`${API}/build-index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          incremental,
          batch_size: Number(batchSize),
          chunk_batch_size: Number(chunkBatchSize),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? res.statusText);

      const jobId = data.job_id;
      appendLog(`Job started: ${jobId}`);

      pollRef.current = setInterval(async () => {
        const currentCursor = cursorRef.current;
        const r = await apiFetch(`${API}/build-index/status/${jobId}?cursor=${currentCursor}`);
        const d = await r.json();
        appendPolledLines(d.new_lines);
        if (typeof d.next_cursor === 'number') {
          cursorRef.current = Math.max(currentCursor, d.next_cursor);
        } else {
          cursorRef.current = currentCursor + (d.new_lines?.length ?? 0);
        }
        if (d.status === 'done') {
          clearInterval(pollRef.current);
          // API contract: completion message always reflects chunk total from
          // build_index.py summary line "Total chunks  : <num>".
          const indexedChunks = Number.isFinite(d.total_chunks) ? d.total_chunks : 0;
          appendLog(`[OK] Done — ${indexedChunks} chunks indexed.`);
          setStatus('ok');
          fetchIndexInfo();
        } else if (d.status === 'error') {
          clearInterval(pollRef.current);
          appendLog(`[ERR] Build failed: ${d.error}`);
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
    <div className="layout-panel-body km-index-builder-panel">
      <div className="panel-section">
        <p className="hint-text">
          Embeds <code>data/campus/processed/**/*.txt</code> with
          MiniLM-L12 and saves a FAISS index for RAG retrieval.
        </p>

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

        <label className="km-checkbox-row">
          <input
            type="checkbox"
            checked={incremental}
            onChange={(e) => setIncremental(e.target.checked)}
          />
          <span>Incremental (skip unchanged files)</span>
        </label>

        <div className="row row-wrap">
          <label>
            <span>Embed batch size</span>
            <input
              type="number"
              min={1}
              value={batchSize}
              onChange={(e) => setBatchSize(Math.max(1, Number(e.target.value) || 1))}
            />
          </label>
          <label>
            <span>Chunk stream batch</span>
            <input
              type="number"
              min={1}
              value={chunkBatchSize}
              onChange={(e) => setChunkBatchSize(Math.max(1, Number(e.target.value) || 1))}
            />
          </label>
        </div>

        <div className="row row-wrap">
          <button
            className="btn btn-sm btn-primary"
            disabled={status === 'running'}
            onClick={handleBuild}
          >
            {status === 'running' ? 'Building…' : 'Build Index'}
          </button>
          <StatusBadge status={status} />
        </div>

        <LogPane lines={log} />
      </div>
    </div>
  );
}

export default IndexBuilderPanel;
export { IndexBuilderPanel };
