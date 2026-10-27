import { useMemo, useState } from 'react';
import { useStore } from '../../core/store';
import './PieceStatePanel.css';

// ── Constants ──────────────────────────────────────────────────────────────────

const FACE_ORDER  = ['U', 'R', 'F', 'D', 'L', 'B'];

const FACE_COORD = {
  U: [ [-1,1,-1],[0,1,-1],[1,1,-1], [-1,1,0],[0,1,0],[1,1,0], [-1,1,1],[0,1,1],[1,1,1] ],
  D: [ [-1,-1,1],[0,-1,1],[1,-1,1], [-1,-1,0],[0,-1,0],[1,-1,0], [-1,-1,-1],[0,-1,-1],[1,-1,-1] ],
  F: [ [-1,1,1],[0,1,1],[1,1,1],   [-1,0,1],[0,0,1],[1,0,1],   [-1,-1,1],[0,-1,1],[1,-1,1] ],
  B: [ [1,1,-1],[0,1,-1],[-1,1,-1],[1,0,-1],[0,0,-1],[-1,0,-1],[1,-1,-1],[0,-1,-1],[-1,-1,-1] ],
  R: [ [1,1,1],[1,1,0],[1,1,-1],   [1,0,1],[1,0,0],[1,0,-1],   [1,-1,1],[1,-1,0],[1,-1,-1] ],
  L: [ [-1,1,-1],[-1,1,0],[-1,1,1],[-1,0,-1],[-1,0,0],[-1,0,1],[-1,-1,-1],[-1,-1,0],[-1,-1,1] ],
};

const STICKER_CLASS = { W:'sticker-white', Y:'sticker-yellow', G:'sticker-green', B:'sticker-blue', R:'sticker-red', O:'sticker-orange' };
const COLOR_LABEL   = { W:'White', Y:'Yellow', G:'Green', B:'Blue', R:'Red', O:'Orange' };


function PieceStatePanel() {
  const cubeState = useStore((s) => s.cubeState);

  const [activeFaces, setActiveFaces] = useState(new Set(FACE_ORDER));
  const [search,      setSearch]      = useState('');
  const [coordMode,   setCoordMode]   = useState(false);

  const toggleFace = (face) => setActiveFaces(prev => {
    const next = new Set(prev);
    if (next.has(face)) { if (next.size > 1) next.delete(face); }
    else next.add(face);
    return next;
  });

  const rows = useMemo(() => {
    const q = search.trim().toUpperCase();
    return FACE_ORDER.flatMap((face) =>
      cubeState[face].map((color, idx) => ({ face, index: idx + 1, color, coord: FACE_COORD[face][idx] }))
    ).filter(row =>
      activeFaces.has(row.face) &&
      (!q || row.face.includes(q) || COLOR_LABEL[row.color]?.toUpperCase().includes(q) ||
        row.color.includes(q) || String(row.index).includes(q) ||
        row.coord.join(',').includes(q))
    );
  }, [cubeState, activeFaces, search]);

  return (
    <div className="piece-state-panel">
      <div className="piece-filter-row">
        {FACE_ORDER.map(f => (
          <button key={f} className={`piece-face-btn ${activeFaces.has(f) ? 'active' : ''}`}
            onClick={() => toggleFace(f)} title={`${f} 면 필터`}>{f}
          </button>
        ))}
      </div>

      <div className="piece-search-row">
        <input className="piece-search-input" placeholder="search…"
          value={search} onChange={e => setSearch(e.target.value)} />
        <button
          className="piece-mode-btn"
          onClick={() => setCoordMode(v => !v)}
          title="Face&Idx / 좌표 전환"
        >
          {coordMode ? 'xyz' : 'F&I'}
        </button>
      </div>

      <div className="piece-table-wrap">
        <table className="piece-table">
          <colgroup>
            <col className="col-face" />
            <col className="col-mid" />
            <col className="col-color" />
          </colgroup>
          <thead>
            <tr>
              <th>Face</th>
              {coordMode ? <th>x,y,z</th> : <th>Idx</th>}
              <th>Color</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.face}-${row.index}`}>
                <td>{row.face}</td>
                {coordMode
                  ? <td className="coord-cell">{row.coord.join(',')}</td>
                  : <td>{row.index}</td>}
                <td>
                  <span className={`piece-chip ${STICKER_CLASS[row.color] || ''}`} />
                  {row.color}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={3} className="piece-empty">결과 없음</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default PieceStatePanel;
export { PieceStatePanel };
