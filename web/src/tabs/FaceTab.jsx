/**
 * tabs/FaceTab.jsx
 * Robot face display tab.
 *
 * Renders DORI's emotional expression as an animated SVG face.
 * Subscribes to /dori/hri/emotion via store.
 *
 * Emotions:
 *   CALM       - IDLE: half-closed eyes, slow blink
 *   ATTENTIVE  - LISTENING: wide open eyes, raised brows
 *   THINKING   - RESPONDING: asymmetric brows, scanning eyes
 *   HAPPY      - NAVIGATING: arc eyes (^_^), cheeks, big smile
 *
 * Extensible: add new emotion configs to EMOTION_CONFIG below.
 */

import { useEffect, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import './FaceTab.css';

// ── Single face color (always the same regardless of emotion) ─────────────────
const FACE_COLOR = '#e8eaf0';
const FACE_GLOW  = 'rgba(232,234,240,0.25)';

// ── Emotion configuration ─────────────────────────────────────────────────────
// Numeric fields are lerp-interpolated during transitions.
// Non-numeric fields (type, blink, scan, drift, cheeks) snap at 50% of transition.
const EMOTION_CONFIG = {
  CALM: {
    label: 'Calm',
    leftEye:  { type: 'ellipse', rx: 36, ry: 18, offsetY: 0 },
    rightEye: { type: 'ellipse', rx: 36, ry: 18, offsetY: 0 },
    leftBrow:  { dx1: -28, dy1: -34, dx2: 28, dy2: -34, curve: 0 },
    rightBrow: { dx1: -28, dy1: -34, dx2: 28, dy2: -34, curve: 0 },
    mouth: { type: 'curve', halfW: 38, startY: 0, endY: 0, curveY: 10 },
    blink: true,
    blinkInterval: 4000,
    drift: true,
    scan: false,
    cheeks: false,
  },
  ATTENTIVE: {
    label: 'Attentive',
    leftEye:  { type: 'ellipse', rx: 38, ry: 32, offsetY: -5 },
    rightEye: { type: 'ellipse', rx: 38, ry: 32, offsetY: -5 },
    leftBrow:  { dx1: -30, dy1: -48, dx2: 30, dy2: -54, curve: -4 },
    rightBrow: { dx1: -30, dy1: -54, dx2: 30, dy2: -48, curve: -4 },
    mouth: { type: 'curve', halfW: 32, startY: 2, endY: 2, curveY: 6 },
    blink: true,
    blinkInterval: 6000,
    drift: false,
    scan: false,
    cheeks: false,
  },
  THINKING: {
    label: 'Thinking',
    leftEye:  { type: 'ellipse', rx: 34, ry: 22, offsetY: 0 },
    rightEye: { type: 'ellipse', rx: 34, ry: 22, offsetY: 0 },
    leftBrow:  { dx1: -28, dy1: -32, dx2: 28, dy2: -32, curve: 0 },
    rightBrow: { dx1: -28, dy1: -48, dx2: 28, dy2: -38, curve: -6 },
    mouth: { type: 'flat', halfW: 30, startY: 4, endY: 4, curveY: 0 },
    blink: false,
    blinkInterval: 0,
    drift: true,
    scan: true,
    cheeks: false,
  },
  HAPPY: {
    label: 'Happy',
    leftEye:  { type: 'arc', rx: 38, ry: 26, offsetY: 0 },
    rightEye: { type: 'arc', rx: 38, ry: 26, offsetY: 0 },
    leftBrow:  { dx1: -28, dy1: -44, dx2: 28, dy2: -52, curve: -8 },
    rightBrow: { dx1: -28, dy1: -52, dx2: 28, dy2: -44, curve: -8 },
    mouth: { type: 'smile', halfW: 50, startY: 0, endY: 0, curveY: 26 },
    blink: true,
    blinkInterval: 3000,
    drift: false,
    scan: false,
    cheeks: true,
  },
};

const FALLBACK_EMOTION = 'CALM';

// ── SVG layout constants ──────────────────────────────────────────────────────
const W  = 320;
const H  = 280;
const CX = W / 2;
const CY = H / 2 - 10;

const LEFT_EYE_X  = CX - 78;
const RIGHT_EYE_X = CX + 78;
const EYE_Y       = CY - 22;
const MOUTH_Y     = CY + 58;

// ── Lerp ─────────────────────────────────────────────────────────────────────
const lerp = (a, b, t) => a + (b - a) * t;

function flattenNumerics(cfg) {
  return {
    le_rx: cfg.leftEye.rx,   le_ry: cfg.leftEye.ry,   le_oY: cfg.leftEye.offsetY,
    re_rx: cfg.rightEye.rx,  re_ry: cfg.rightEye.ry,  re_oY: cfg.rightEye.offsetY,
    lb_dx1: cfg.leftBrow.dx1, lb_dy1: cfg.leftBrow.dy1,
    lb_dx2: cfg.leftBrow.dx2, lb_dy2: cfg.leftBrow.dy2, lb_c: cfg.leftBrow.curve,
    rb_dx1: cfg.rightBrow.dx1, rb_dy1: cfg.rightBrow.dy1,
    rb_dx2: cfg.rightBrow.dx2, rb_dy2: cfg.rightBrow.dy2, rb_c: cfg.rightBrow.curve,
    m_halfW: cfg.mouth.halfW, m_startY: cfg.mouth.startY,
    m_endY: cfg.mouth.endY,   m_curveY: cfg.mouth.curveY,
  };
}

// ── SVG sub-components ────────────────────────────────────────────────────────

function EyeShape({ x, eyeY, rx, ry, type, blinkProgress, driftX, driftY }) {
  const ryFinal = Math.max(1, ry * (1 - blinkProgress));
  const cx = x + driftX;
  const cy = eyeY + driftY;

  if (type === 'arc') {
    return (
      <path
        d={`M ${cx - rx} ${cy} A ${rx} ${Math.max(1, ryFinal)} 0 0 1 ${cx + rx} ${cy}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
      />
    );
  }
  return (
    <ellipse cx={cx} cy={cy} rx={rx} ry={ryFinal} fill="currentColor" />
  );
}

function BrowShape({ eyeX, eyeY, dx1, dy1, dx2, dy2, curve }) {
  const x1 = eyeX + dx1, y1 = eyeY + dy1;
  const x2 = eyeX + dx2, y2 = eyeY + dy2;
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2 + curve;
  return (
    <path
      d={`M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="7"
      strokeLinecap="round"
    />
  );
}

function MouthShape({ type, halfW, startY, endY, curveY }) {
  const x1 = CX - halfW, x2 = CX + halfW;
  const y1 = MOUTH_Y + startY, y2 = MOUTH_Y + endY;
  const cy = MOUTH_Y + (startY + endY) / 2 + curveY;

  if (type === 'flat') {
    return (
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke="currentColor" strokeWidth="7" strokeLinecap="round"
      />
    );
  }
  return (
    <path
      d={`M ${x1} ${y1} Q ${CX} ${cy} ${x2} ${y2}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="7"
      strokeLinecap="round"
    />
  );
}

function ThinkingDots() {
  return (
    <g>
      {[0, 1, 2].map(i => (
        <circle
          key={i}
          cx={CX - 18 + i * 18}
          cy={CY + 90}
          r={5}
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
      <ellipse cx={LEFT_EYE_X + 12}  cy={EYE_Y + 58} rx={26} ry={12}
        fill="rgba(255,140,140,0.22)" />
      <ellipse cx={RIGHT_EYE_X - 12} cy={EYE_Y + 58} rx={26} ry={12}
        fill="rgba(255,140,140,0.22)" />
    </>
  );
}

// ── Face canvas with morph transition ────────────────────────────────────────
const TRANSITION_MS = 380;

function FaceCanvas({ emotion }) {
  const cfg = EMOTION_CONFIG[emotion] || EMOTION_CONFIG[FALLBACK_EMOTION];

  // Interpolated numeric values (what we render)
  const [vals, setVals] = useState(() => flattenNumerics(cfg));
  // Display emotion (type-fields snap at 50% of transition)
  const [displayEmotion, setDisplayEmotion] = useState(emotion);

  const animRef    = useRef(null);
  const fromVals   = useRef(vals);
  const startTime  = useRef(null);

  useEffect(() => {
    const to     = EMOTION_CONFIG[emotion] || EMOTION_CONFIG[FALLBACK_EMOTION];
    const toFlat = flattenNumerics(to);
    fromVals.current = { ...vals };
    startTime.current = null;
    let snapped = false;

    cancelAnimationFrame(animRef.current);

    const animate = (now) => {
      if (!startTime.current) startTime.current = now;
      const raw = Math.min((now - startTime.current) / TRANSITION_MS, 1);
      // Ease-out cubic
      const t = 1 - Math.pow(1 - raw, 3);

      const next = {};
      for (const k in toFlat) next[k] = lerp(fromVals.current[k], toFlat[k], t);
      setVals(next);

      if (!snapped && t >= 0.5) {
        snapped = true;
        setDisplayEmotion(emotion);
      }

      if (raw < 1) {
        animRef.current = requestAnimationFrame(animate);
      } else {
        setVals(toFlat);
        setDisplayEmotion(emotion);
      }
    };

    animRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emotion]);

  // Blink
  const [blinkProgress, setBlinkProgress] = useState(0);
  const blinkRef = useRef(null);

  useEffect(() => {
    if (!cfg.blink) { setBlinkProgress(0); return; }
    let mounted = true;

    const scheduleBlink = () => {
      blinkRef.current = setTimeout(() => {
        if (!mounted) return;
        let frame = 0;
        const frames = [0, 0.35, 0.75, 1.0, 0.75, 0.35, 0];
        const step = () => {
          if (!mounted || frame >= frames.length) {
            setBlinkProgress(0);
            scheduleBlink();
            return;
          }
          setBlinkProgress(frames[frame++]);
          blinkRef.current = setTimeout(step, 38);
        };
        step();
      }, cfg.blinkInterval || 4000);
    };

    scheduleBlink();
    return () => { mounted = false; clearTimeout(blinkRef.current); };
  }, [emotion, cfg.blink, cfg.blinkInterval]);

  // Drift / scan
  const [driftX, setDriftX] = useState(0);
  const [driftY, setDriftY] = useState(0);
  const driftRef = useRef(null);

  useEffect(() => {
    if (!cfg.drift && !cfg.scan) { setDriftX(0); setDriftY(0); return; }
    let mounted = true;
    let t = 0;

    const tick = () => {
      if (!mounted) return;
      t += 0.013;
      if (cfg.scan) {
        setDriftX(Math.sin(t * 1.3) * 14);
        setDriftY(0);
      } else {
        setDriftX(Math.sin(t) * 5);
        setDriftY(Math.sin(t * 0.7) * 3);
      }
      driftRef.current = requestAnimationFrame(tick);
    };

    driftRef.current = requestAnimationFrame(tick);
    return () => { mounted = false; cancelAnimationFrame(driftRef.current); };
  }, [emotion, cfg.drift, cfg.scan]);

  const dispCfg = EMOTION_CONFIG[displayEmotion] || EMOTION_CONFIG[FALLBACK_EMOTION];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      style={{ color: FACE_COLOR, filter: `drop-shadow(0 0 14px ${FACE_GLOW})` }}
      aria-label={`DORI face: ${dispCfg.label}`}
    >
      {/* Left eye */}
      <EyeShape
        x={LEFT_EYE_X} eyeY={EYE_Y + vals.le_oY}
        rx={vals.le_rx} ry={vals.le_ry}
        type={dispCfg.leftEye.type}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />
      {/* Right eye */}
      <EyeShape
        x={RIGHT_EYE_X} eyeY={EYE_Y + vals.re_oY}
        rx={vals.re_rx} ry={vals.re_ry}
        type={dispCfg.rightEye.type}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />

      {/* Brows */}
      <BrowShape
        eyeX={LEFT_EYE_X} eyeY={EYE_Y}
        dx1={vals.lb_dx1} dy1={vals.lb_dy1}
        dx2={vals.lb_dx2} dy2={vals.lb_dy2}
        curve={vals.lb_c}
      />
      <BrowShape
        eyeX={RIGHT_EYE_X} eyeY={EYE_Y}
        dx1={vals.rb_dx1} dy1={vals.rb_dy1}
        dx2={vals.rb_dx2} dy2={vals.rb_dy2}
        curve={vals.rb_c}
      />

      {/* Mouth */}
      <MouthShape
        type={dispCfg.mouth.type}
        halfW={vals.m_halfW}
        startY={vals.m_startY}
        endY={vals.m_endY}
        curveY={vals.m_curveY}
      />

      {/* Extras */}
      {dispCfg.cheeks && <Cheeks />}
      {displayEmotion === 'THINKING' && <ThinkingDots />}
    </svg>
  );
}

// ── Main Tab ──────────────────────────────────────────────────────────────────
export default function FaceTab() {
  const emotion       = useStore(s => s.emotion);
  const hriState      = useStore(s => s.hriState);
  const emotionSource = useStore(s => s.emotionSource);
  const cfg = EMOTION_CONFIG[emotion] || EMOTION_CONFIG[FALLBACK_EMOTION];

  return (
    <div className="face-layout">

      {/* ── Main display ── */}
      <div className="face-main">
        <Panel title="DORI Face" className="face-panel-main">
          <div className="face-canvas-wrap">
            <div className="face-canvas-inner">
              <FaceCanvas emotion={emotion} />
            </div>
            <div className="face-emotion-label">{cfg.label}</div>
          </div>
        </Panel>
      </div>

      {/* ── Side info ── */}
      <div className="face-side">

        <Panel title="Emotion Palette">
          <div className="face-palette">
            {Object.entries(EMOTION_CONFIG).map(([key, ecfg]) => (
              <button
                key={key}
                className={`face-palette-btn ${emotion === key ? 'active' : ''}`}
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

        <Panel title="Status">
          <div className="face-status-list">
            <div className="face-status-row">
              <span className="face-status-key">Emotion</span>
              <span className="face-status-val">{emotion}</span>
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
