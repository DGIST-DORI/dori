import Panel from '../components/Panel';
import './CubeTab.css';

export default function CubeTab() {
  return (
    <div className="cube-layout">
      <Panel title="3D Cube Viewer" className="cube-viewer">
        <div className="cube-placeholder">
          <span style={{ fontSize: 48, opacity: 0.2 }}>⬛</span>
          <span>Cube Simulator</span>
          <span style={{ fontSize: 10, color: 'var(--text-2)' }}>Three.js viewer — coming next</span>
        </div>
      </Panel>
      <div className="cube-side">
        <Panel title="Piece State" className="cube-side-panel">
          <div className="cube-placeholder" style={{ fontSize: 11 }}>Piece table</div>
        </Panel>
        <Panel title="Rotation Control" className="cube-side-panel">
          <div className="cube-placeholder" style={{ fontSize: 11 }}>U / R / L / B buttons</div>
        </Panel>
        <Panel title="Path Finder" className="cube-side-panel">
          <div className="cube-placeholder" style={{ fontSize: 11 }}>A→B wheel algorithm</div>
        </Panel>
      </div>
    </div>
  );
}
