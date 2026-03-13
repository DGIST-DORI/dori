/**
 * tabs/FaceTab.jsx
 * Robot face display tab.
 *
 * Renders DORI's emotional expression as an animated SVG face.
 * Subscribes to /dori/hri/emotion via store.
 *
 * Emotions:
 *   CALM       - IDLE: soft eyes, slow blink
 *   ATTENTIVE  - LISTENING: wide open eyes, raised brows
 *   THINKING   - RESPONDING: one brow up, scanning eyes
 *   HAPPY      - NAVIGATING: arc eyes (^_^), cheeks
 *
 * Extensible: add new emotion configs to EMOTION_CONFIG below.
 */

import { useEffect, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './FaceTab.css';

// ── Emotion configuration ─────────────────────────────────────────────────────
// Each emotion defines SVG path params for the face renderer.
// Add new emotions here without touching render logic.
const EMOTION_CONFIG = {
  CALM: {
    label: 'Calm',
    color: '#7eb8d4',
    glowColor: 'rgba(126,184,212,0.35)',
    // Eyes: half-closed ellipse (rx, ry, offsetY)
    leftEye:  { type: 'ellipse', rx: 28, ry: 14, offsetY: 0 },
    rightEye: { type: 'ellipse', rx: 28, ry: 14, offsetY: 0 },
    // Brows: flat line (x1,y1,x2,y2 relative to eye center)
    leftBrow:  { dx1: -22, dy1: -30, dx2: 22, dy2: -30, curve: 0 },
    rightBrow: { dx1: -22, dy1: -30, dx2: 22, dy2: -30, curve: 0 },
    // Mouth: gentle curve
    mouth: { type: 'curve', y: 0, curve: 8 },
    blink: true,
    blinkInterval: 4000,
    // Subtle eye drift animation
    drift: true,
  },
  ATTENTIVE: {
    label: 'Attentive',
    color: '#7de8c8',
    glowColor: 'rgba(125,232,200,0.40)',
    leftEye:  { type: 'ellipse', rx: 30, ry: 26, offsetY: -4 },
    rightEye: { type: 'ellipse', rx: 30, ry: 26, offsetY: -4 },
    leftBrow:  { dx1: -24, dy1: -38, dx2: 24, dy2: -44, curve: -4 },
    rightBrow: { dx1: -24, dy1: -44, dx2: 24, dy2: -38, curve: -4 },
    mouth: { type: 'curve', y: 2, curve: 5 },
    blink: true,
    blinkInterval: 6000,
    drift: false,
  },
  THINKING: {
    label: 'Thinking',
    color: '#c4a8f5',
    glowColor: 'rgba(196,168,245,0.38)',
    leftEye:  { type: 'ellipse', rx: 26, ry: 18, offsetY: 0 },
    rightEye: { type: 'ellipse', rx: 26, ry: 18, offsetY: 0 },
    // Asymmetric brows — one raised
    leftBrow:  { dx1: -22, dy1: -28, dx2: 22, dy2: -28, curve: 0 },
    rightBrow: { dx1: -22, dy1: -40, dx2: 22, dy2: -32, curve: -5 },
    mouth: { type: 'flat', y: 4 },
    blink: false,
    drift: true,
    // Scanning: eyes move left-right
    scan: true,
  },
  HAPPY: {
    label: 'Happy',
    color: '#f5d96e',
    glowColor: 'rgba(245,217,110,0.42)',
    // Arc eyes (^_^)
    leftEye:  { type: 'arc', rx: 30, ry: 20, offsetY: 0 },
    rightEye: { type: 'arc', rx: 30, ry: 20, offsetY: 0 },
    leftBrow:  { dx1: -22, dy1: -36, dx2: 22, dy2: -42, curve: -6 },
    rightBrow: { dx1: -22, dy1: -42, dx2: 22, dy2: -36, curve: -6 },
    mouth: { type: 'smile', y: 0, curve: 20 },
    blink: true,
    blinkInterval: 3000,
    drift: false,
    cheeks: true,
  },
};

const FALLBACK_EMOTION = 'CALM';

// ── SVG Face Renderer ─────────────────────────────────────────────────────────
const W = 320;
const H = 280;
const CX = W / 2;
const CY = H / 2 - 10;

// Eye center positions
const LEFT_EYE_X  = CX - 72;
const RIGHT_EYE_X = CX + 72;
const EYE_Y = CY - 20;

function EyeShape({ x, y, cfg, blinkProgress, driftX = 0, driftY = 0 }) {
  const ry = cfg.type === 'arc'
    ? cfg.ry * (1 - blinkProgress)
    : cfg.ry * (1 - blinkProgress);
  const eyeY = y + cfg.offsetY + driftY;

  if (cfg.type === 'arc') {
    // Arc eye: top half only (^)
    const rx = cfg.rx;
    const ryA = Math.max(1, ry);
    return (
      <path
        d={`M ${x - rx} ${eyeY} A ${rx} ${ryA} 0 0 1 ${x + rx} ${eyeY}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
    );
  }

  // Ellipse eye (normal or blinking)
  const ryVal = Math.max(1, ry);
  return (
    <ellipse
      cx={x + driftX}
      cy={eyeY}
      rx={cfg.rx}
      ry={ryVal}
      fill="currentColor"
    />
  );
}

function BrowShape({ eyeX, eyeY, cfg }) {
  const x1 = eyeX + cfg.dx1;
  const y1 = eyeY + cfg.dy1;
  const x2 = eyeX + cfg.dx2;
  const y2 = eyeY + cfg.dy2;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2 + cfg.curve;
  return (
    <path
      d={`M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="4"
      strokeLinecap="round"
    />
  );
}

function MouthShape({ cfg }) {
  const mx = CX;
  const my = CY + 55;

  if (cfg.type === 'smile') {
    return (
      <path
        d={`M ${mx - 45} ${my} Q ${mx} ${my + cfg.curve} ${mx + 45} ${my}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
    );
  }
  if (cfg.type === 'curve') {
    const cy2 = my + cfg.y;
    return (
      <path
        d={`M ${mx - 35} ${cy2} Q ${mx} ${cy2 + cfg.curve} ${mx + 35} ${cy2}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
    );
  }
  // flat
  return (
    <line
      x1={mx - 28} y1={my + cfg.y}
      x2={mx + 28} y2={my + cfg.y}
      stroke="currentColor"
      strokeWidth="4"
      strokeLinecap="round"
    />
  );
}

function DotIndicator({ emotion }) {
  // Thinking: 3 animated dots
  if (emotion !== 'THINKING') return null;
  return (
    <g className="face-thinking-dots">
      {[0, 1, 2].map(i => (
        <circle
          key={i}
          cx={CX - 16 + i * 16}
          cy={CY + 82}
          r={4}
          fill="currentColor"
          className={`face-dot face-dot-${i}`}
        />
      ))}
    </g>
  );
}

function Cheeks() {
  return (
    <>
      <ellipse cx={LEFT_EYE_X + 10}  cy={EYE_Y + 46} rx={22} ry={10} fill="rgba(255,150,150,0.28)" />
      <ellipse cx={RIGHT_EYE_X - 10} cy={EYE_Y + 46} rx={22} ry={10} fill="rgba(255,150,150,0.28)" />
    </>
  );
}

function FaceCanvas({ emotion }) {
  const cfg = EMOTION_CONFIG[emotion] || EMOTION_CONFIG[FALLBACK_EMOTION];
  const color = cfg.color;

  // Blink state
  const [blinkProgress, setBlinkProgress] = useState(0);
  const blinkRef = useRef(null);

  // Drift / scan state
  const [driftX, setDriftX] = useState(0);
  const [driftY, setDriftY] = useState(0);
  const driftRef = useRef(null);

  // Animate blink
  useEffect(() => {
    if (!cfg.blink) { setBlinkProgress(0); return; }
    let mounted = true;

    const scheduleBlink = () => {
      blinkRef.current = setTimeout(() => {
        if (!mounted) return;
        // Quick close-open animation
        let frame = 0;
        const frames = [0, 0.3, 0.7, 1.0, 0.7, 0.3, 0];
        const step = () => {
          if (!mounted || frame >= frames.length) {
            setBlinkProgress(0);
            scheduleBlink();
            return;
          }
          setBlinkProgress(frames[frame++]);
          blinkRef.current = setTimeout(step, 40);
        };
        step();
      }, cfg.blinkInterval || 4000);
    };

    scheduleBlink();
    return () => {
      mounted = false;
      clearTimeout(blinkRef.current);
    };
  }, [emotion, cfg.blink, cfg.blinkInterval]);

  // Drift animation
  useEffect(() => {
    if (!cfg.drift && !cfg.scan) {
      setDriftX(0); setDriftY(0); return;
    }
    let mounted = true;
    let t = 0;

    const tick = () => {
      if (!mounted) return;
      t += 0.012;
      if (cfg.scan) {
        setDriftX(Math.sin(t * 1.4) * 12);
        setDriftY(0);
      } else {
        setDriftX(Math.sin(t) * 5);
        setDriftY(Math.sin(t * 0.7) * 3);
      }
      driftRef.current = requestAnimationFrame(tick);
    };

    driftRef.current = requestAnimationFrame(tick);
    return () => {
      mounted = false;
      cancelAnimationFrame(driftRef.current);
    };
  }, [emotion, cfg.drift, cfg.scan]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      style={{ color, filter: `drop-shadow(0 0 18px ${cfg.glowColor})` }}
      aria-label={`DORI face: ${cfg.label}`}
    >
      {/* Subtle face outline */}
      <ellipse
        cx={CX} cy={CY + 10}
        rx={120} ry={108}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        opacity="0.12"
      />

      {/* Left eye */}
      <EyeShape
        x={LEFT_EYE_X}  y={EYE_Y}
        cfg={cfg.leftEye}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />
      {/* Right eye */}
      <EyeShape
        x={RIGHT_EYE_X} y={EYE_Y}
        cfg={cfg.rightEye}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />

      {/* Brows */}
      <BrowShape eyeX={LEFT_EYE_X}  eyeY={EYE_Y} cfg={cfg.leftBrow} />
      <BrowShape eyeX={RIGHT_EYE_X} eyeY={EYE_Y} cfg={cfg.rightBrow} />

      {/* Mouth */}
      <MouthShape cfg={cfg.mouth} />

      {/* Emotion-specific extras */}
      {cfg.cheeks && <Cheeks />}
      <DotIndicator emotion={emotion} />
    </svg>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────────
export default function FaceTab() {
  const emotion  = useStore(s => s.emotion);
  const hriState = useStore(s => s.hriState);
  const emotionSource = useStore(s => s.emotionSource);

  const cfg = EMOTION_CONFIG[emotion] || EMOTION_CONFIG[FALLBACK_EMOTION];

  return (
    <div className="face-layout">

      {/* ── Main display ── */}
      <div className="face-main">
        <Panel title="DORI Face" className="face-panel-main">
          <div className="face-canvas-wrap">
            <div
              className="face-canvas-inner"
              style={{ '--emotion-color': cfg.color, '--emotion-glow': cfg.glowColor }}
            >
              <FaceCanvas emotion={emotion} />
            </div>

            {/* Emotion label */}
            <div className="face-emotion-label" style={{ color: cfg.color }}>
              {cfg.label}
            </div>
          </div>
        </Panel>
      </div>

      {/* ── Side info ── */}
      <div className="face-side">

        {/* Emotion selector (preview / manual override) */}
        <Panel title="Emotion Palette">
          <div className="face-palette">
            {Object.entries(EMOTION_CONFIG).map(([key, ecfg]) => (
              <button
                key={key}
                className={`face-palette-btn ${emotion === key ? 'active' : ''}`}
                style={{
                  '--btn-color': ecfg.color,
                  '--btn-glow':  ecfg.glowColor,
                }}
                onClick={() => useStore.getState().setEmotionOverride(key)}
                title={ecfg.label}
              >
                <span className="face-palette-dot" />
                <span className="face-palette-name">{ecfg.label}</span>
                {emotion === key && <span className="face-palette-active-mark">●</span>}
              </button>
            ))}
          </div>
        </Panel>

        {/* Status info */}
        <Panel title="Status">
          <div className="face-status-list">
            <div className="face-status-row">
              <span className="face-status-key">Emotion</span>
              <span className="face-status-val" style={{ color: cfg.color }}>{emotion}</span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">Source</span>
              <span className={`face-status-val face-source-${emotionSource}`}>
                {emotionSource === 'override' ? '⚡ override' : '⟳ state'}
              </span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">HRI State</span>
              <span className="face-status-val">{hriState}</span>
            </div>
          </div>
          {emotionSource === 'override' && (
            <button
              className="face-clear-override"
              onClick={() => useStore.getState().clearEmotionOverride()}
            >
              Clear Override
            </button>
          )}
        </Panel>

      </div>
    </div>
  );
}
