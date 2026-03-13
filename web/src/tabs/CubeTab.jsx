import { useMemo, useState } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './CubeTab.css';

const FACE_ORDER = ['U', 'R', 'F', 'D', 'L', 'B'];
const MOVE_BUTTONS = ['U', "U'", 'R', "R'", 'L', "L'", 'B', "B'"];
const STICKER_CLASS = {
  W: 'sticker-white',
  Y: 'sticker-yellow',
  G: 'sticker-green',
  B: 'sticker-blue',
  R: 'sticker-red',
  O: 'sticker-orange',
};

function CubeViewerPanel() {
  const cubeState = useStore((s) => s.cubeState);
  const [orbit, setOrbit] = useState({ x: -24, y: -32 });
  const [drag, setDrag] = useState(null);

  const transform = `rotateX(${orbit.x}deg) rotateY(${orbit.y}deg)`;

  const onPointerDown = (e) => {
    setDrag({ x: e.clientX, y: e.clientY, ox: orbit.x, oy: orbit.y });
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    setOrbit({
      x: Math.max(-75, Math.min(75, drag.ox - dy * 0.35)),
      y: drag.oy + dx * 0.45,
    });
  };

  const onPointerUp = () => setDrag(null);

  return (
    <div className="cube-viewer-panel">
      <div
        className="cube-viewport"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        role="presentation"
      >
        <div className="cube-3d" style={{ transform }}>
          {FACE_ORDER.map((face) => (
            <div key={face} className={`cube-face cube-face-${face}`}>
              {cubeState[face].map((sticker, i) => (
                <span
                  key={`${face}-${i}`}
                  className={`cube-sticker ${STICKER_CLASS[sticker] || ''}`}
                  title={`${face}${i + 1}: ${sticker}`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="cube-viewer-help">드래그해서 카메라 orbit</div>
    </div>
  );
}

function PieceStatePanel() {
  const cubeState = useStore((s) => s.cubeState);
  const rows = useMemo(
    () => FACE_ORDER.flatMap((face) =>
      cubeState[face].map((color, idx) => ({ face, index: idx + 1, color })),
    ),
    [cubeState],
  );

  return (
    <div className="piece-state-panel">
      <table className="piece-table">
        <thead>
          <tr>
            <th>Face</th>
            <th>Idx</th>
            <th>Color</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.face}-${row.index}`}>
              <td>{row.face}</td>
              <td>{row.index}</td>
              <td>
                <span className={`piece-chip ${STICKER_CLASS[row.color] || ''}`} />
                {row.color}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RotationControlPanel() {
  const rotateCube = useStore((s) => s.rotateCube);
  const resetCube = useStore((s) => s.resetCube);
  const cubeMoveHistory = useStore((s) => s.cubeMoveHistory);

  return (
    <div className="rotation-control-panel">
      <div className="rotation-grid">
        {MOVE_BUTTONS.map((move) => (
          <button key={move} className="rotation-button" type="button" onClick={() => rotateCube(move)}>
            {move}
          </button>
        ))}
      </div>
      <button className="rotation-reset" type="button" onClick={resetCube}>Reset</button>
      <div className="rotation-history" title={cubeMoveHistory.join(' ')}>
        {cubeMoveHistory.length ? cubeMoveHistory.join(' ') : 'No moves yet'}
      </div>
    </div>
  );
}

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
