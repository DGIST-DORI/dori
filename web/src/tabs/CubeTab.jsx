/**
 * tabs/CubeTab.jsx  —  Cube Simulator
 */
import { useMemo, useState, useRef, useCallback } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './CubeTab.css';

// ── Constants ──────────────────────────────────────────────────────────────────

const FACE_ORDER  = ['U', 'R', 'F', 'D', 'L', 'B'];
const VALID_MOVES = new Set(['U', "U'", 'R', "R'", 'L', "L'", 'B', "B'"]);

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
const MOVE_BUTTONS  = [['U',"U'"],['R',"R'"],['L',"L'"],['B',"B'"]];

// ── Axis indicator (SVG, orbit-aware) ─────────────────────────────────────────
// Projects X/Y/Z unit vectors given current orbit angles, draws arrows in SVG.
function AxisIndicator({ orbitX, orbitY }) {
  const SIZE   = 56;
  const ORIGIN = { x: SIZE / 2, y: SIZE / 2 };
  const LEN    = 20;

  // Convert orbit angles (deg) to radians (match cube transform direction).
  const rx = (orbitX * Math.PI) / 180;
  const ry = (orbitY * Math.PI) / 180;

  // Rotation matrix: Ry then Rx (same order as CSS transform)
  const project = ([wx, wy, wz]) => {
    // Rotate around Y
    const x1 =  wx * Math.cos(ry) + wz * Math.sin(ry);
    const y1 =  wy;
    const z1 = -wx * Math.sin(ry) + wz * Math.cos(ry);
    // Rotate around X
    const x2 =  x1;
    const y2 =  y1 * Math.cos(rx) - z1 * Math.sin(rx);
    // Project: just use x2, y2 (ignore z depth for 2D indicator)
    return { x: ORIGIN.x + x2 * LEN, y: ORIGIN.y - y2 * LEN };
  };

  const axes = [
    { vec: [1,0,0], color: '#f87171', label: 'X' },
    { vec: [0,1,0], color: '#4ade80', label: 'Y' },
    { vec: [0,0,1], color: '#60a5fa', label: 'Z' },
  ];

  return (
    <svg width={SIZE} height={SIZE} className="axis-svg" viewBox={`0 0 ${SIZE} ${SIZE}`}>
      {axes.map(({ vec, color, label }) => {
        const tip = project(vec);
        const dx  = tip.x - ORIGIN.x;
        const dy  = tip.y - ORIGIN.y;
        const len = Math.sqrt(dx*dx + dy*dy);
        const nx  = dx / len;
        const ny  = dy / len;
        // Arrow head
        const ah = 5;
        const aw = 3;
        const px1 = tip.x - nx * ah + ny * aw;
        const py1 = tip.y - ny * ah - nx * aw;
        const px2 = tip.x - nx * ah - ny * aw;
        const py2 = tip.y - ny * ah + nx * aw;
        return (
          <g key={label}>
            <line x1={ORIGIN.x} y1={ORIGIN.y} x2={tip.x} y2={tip.y}
              stroke={color} strokeWidth="1.8" strokeLinecap="round" />
            <polygon points={`${tip.x},${tip.y} ${px1},${py1} ${px2},${py2}`} fill={color} />
            <text x={tip.x + nx*6} y={tip.y + ny*6 + 3.5}
              fill={color} fontSize="9" fontWeight="700"
              textAnchor="middle" fontFamily="monospace">{label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Viewer ─────────────────────────────────────────────────────────────────────
function CubeViewerPanel() {
  const cubeState = useStore((s) => s.cubeState);

  const [orbit,      setOrbit]      = useState({ x: -24, y: -32 });
  const [drag,       setDrag]       = useState(null);
  const [zoom,       setZoom]       = useState(1.0);
  const [showLabels, setShowLabels] = useState(false);
  const [showAxes,   setShowAxes]   = useState(false);

  const transform  = `scale(${zoom}) rotateX(${orbit.x}deg) rotateY(${orbit.y}deg)`;
  const clampZoom  = (z) => Math.max(0.4, Math.min(2.2, z));
  const zoomPct    = Math.round(zoom * 100);
  const zoomToSlider = (value) => {
    if (value <= 1) return ((value - 0.4) / 0.6) * 50;
    return 50 + ((value - 1) / 1.2) * 50;
  };
  const sliderToZoom = (value) => {
    if (value <= 50) return 0.4 + (value / 50) * 0.6;
    return 1 + ((value - 50) / 50) * 1.2;
  };
  const sliderValue = Math.round(zoomToSlider(zoom));

  const onPointerDown = (e) => {
    setDrag({ x: e.clientX, y: e.clientY, ox: orbit.x, oy: orbit.y });
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!drag) return;
    setOrbit({
      x: Math.max(-75, Math.min(75, drag.ox - (e.clientY - drag.y) * 0.35)),
      y: drag.oy + (e.clientX - drag.x) * 0.45,
    });
  };
  const onPointerUp = () => setDrag(null);

  const onWheel = useCallback((e) => {
    e.preventDefault();
    setZoom(z => clampZoom(z - e.deltaY * 0.001));
  }, []);

  const viewportRefCb = useCallback((el) => {
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  return (
    <div className="cube-viewer-panel">
      <div
        ref={viewportRefCb}
        className="cube-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        role="presentation"
      >
        {/* 큐브 */}
        <div className="cube-3d" style={{ transform }}>
          {FACE_ORDER.map((face) => (
            <div key={face} className={`cube-face cube-face-${face}`}>
              {cubeState[face].map((sticker, i) => (
                <span key={`${face}-${i}`}
                  className={`cube-sticker ${STICKER_CLASS[sticker] || ''}`}
                  title={`${face}${i + 1}: ${sticker}`}
                />
              ))}
              {showLabels && <div className="cube-face-label">{face}</div>}
            </div>
          ))}
        </div>

        {/* 우측 상단 — 레이블 / 축 토글 버튼 */}
        <div className="vp-controls-tr" onPointerDown={e => e.stopPropagation()}>
          <button
            className={`vp-icon-btn ${showLabels ? 'active' : ''}`}
            onClick={() => setShowLabels(v => !v)}
            title="면 레이블 표시/숨기기"
          >
            <span className="vp-icon-text">LBL</span>
          </button>
          <button
            className={`vp-icon-btn ${showAxes ? 'active' : ''}`}
            onClick={() => setShowAxes(v => !v)}
            title="좌표축 표시/숨기기"
          >
            <span className="vp-icon-text">AXIS</span>
          </button>
        </div>

        {/* 좌측 하단 — 좌표축 인디케이터 */}
        {showAxes && (
          <div className="vp-axis-indicator" onPointerDown={e => e.stopPropagation()}>
            <AxisIndicator orbitX={orbit.x} orbitY={orbit.y} />
          </div>
        )}

        {/* 우측 하단 — 줌 컨트롤 바 */}
        <div className="vp-zoom-controls" onPointerDown={e => e.stopPropagation()}>
          <button className="vp-zoom-btn" onClick={() => setZoom(z => clampZoom(z + 0.15))} title="확대">＋</button>
          <div className="vp-zoom-track">
            <div className="vp-zoom-marker" title="100% 기준점" />
            <input
              type="range"
              className="vp-zoom-slider"
              min={0} max={100} step={1}
              value={sliderValue}
              onChange={e => setZoom(clampZoom(sliderToZoom(Number(e.target.value))))}
              title={`${zoomPct}%`}
            />
          </div>
          <button className="vp-zoom-btn" onClick={() => setZoom(z => clampZoom(z - 0.15))} title="축소">－</button>
          <button className="vp-zoom-reset" onClick={() => setZoom(1.0)} title="줌 리셋">{zoomPct}%</button>
        </div>
      </div>

      <div className="cube-viewer-help">드래그 orbit · 스크롤 zoom</div>
    </div>
  );
}

// ── Piece State ────────────────────────────────────────────────────────────────
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
  }, [cubeState, activeFaces, search, coordMode]);

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

// ── Rotation Control ───────────────────────────────────────────────────────────
function RotationControlPanel() {
  const rotateCube      = useStore((s) => s.rotateCube);
  const resetCube       = useStore((s) => s.resetCube);
  const cubeMoveHistory = useStore((s) => s.cubeMoveHistory);

  const [seqInput,  setSeqInput]  = useState('');
  const [copyFlash, setCopyFlash] = useState(false);

  const applySequence = () => {
    seqInput.trim().split(/\s+/).filter(t => VALID_MOVES.has(t)).forEach(m => rotateCube(m));
    setSeqInput('');
  };

  const copyHistory = () => {
    if (!cubeMoveHistory.length) return;
    navigator.clipboard.writeText(cubeMoveHistory.join(' ')).then(() => {
      setCopyFlash(true);
      setTimeout(() => setCopyFlash(false), 1200);
    });
  };

  return (
    <div className="rotation-control-panel">
      <div className="rotation-pairs">
        {MOVE_BUTTONS.map(([cw, ccw]) => (
          <div key={cw} className="rotation-pair">
            <button className="rot-btn cw"  onClick={() => rotateCube(cw)}>{cw}</button>
            <button className="rot-btn ccw" onClick={() => rotateCube(ccw)}>{ccw}</button>
          </div>
        ))}
      </div>

      <div className="rot-seq-row">
        <input className="rot-seq-input" placeholder="U R' L B …"
          value={seqInput} onChange={e => setSeqInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applySequence()} />
        <button className="rot-seq-run" onClick={applySequence} title="시퀀스 실행">▶</button>
      </div>

      <div className="rot-history-row">
        <div className="rot-history-text" title={cubeMoveHistory.join(' ')}>
          {cubeMoveHistory.length
            ? cubeMoveHistory.slice(-12).join(' ')
            : <span className="dim">No moves yet</span>}
        </div>
        <button className="rot-history-btn"
          onClick={() => setSeqInput(cubeMoveHistory.join(' '))}
          title="히스토리 불러오기" disabled={!cubeMoveHistory.length}>↑</button>
        <button className={`rot-history-btn ${copyFlash ? 'flash' : ''}`}
          onClick={copyHistory} title="히스토리 복사" disabled={!cubeMoveHistory.length}>⎘</button>
      </div>

      <button className="rotation-reset" onClick={resetCube}>↺ Reset</button>
    </div>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────────
export default function CubeTab() {
  return (
    <div className="cube-layout">
      <Panel title="3D Cube Viewer" className="cube-viewer">
        <CubeViewerPanel />
      </Panel>
      <div className="cube-side">
        <Panel title="Piece State" className="cube-side-panel">
          <PieceStatePanel />
        </Panel>
        <Panel title="Rotation Control" className="cube-side-panel">
          <RotationControlPanel />
        </Panel>
        <Panel title="Path Finder" className="cube-side-panel">
          <div className="cube-pathfinder-placeholder">미구현 (예정)</div>
        </Panel>
      </div>
    </div>
  );
}
