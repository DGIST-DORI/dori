/**
 * tabs/FaceTab.jsx
 * Robot face display tab.
 *
 * Renders DORI's emotional expression as an animated SVG face.
 * Subscribes to /dori/hri/emotion via store.
 *
 * Emotions:
 *   CALM       - IDLE: half-closed eyes, slow blink
 *   ATTENTIVE  - LISTENING: wide open eyes
 *   THINKING   - RESPONDING: focused eyes, scanning eyes
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
// Non-numeric fields (type, blink, scan, drift, cheeks, showMouth) snap at 50% of transition.
const EMOTION_CONFIG = {
  CALM: {
    label: 'Calm',
    leftEye:  { type: 'roundedRect', width: 92, height: 44, cornerRadius: 16, tilt: -2, upperLid: 0.85, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 92, height: 44, cornerRadius: 16, tilt: 2, upperLid: 0.85, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    mouth: { type: 'curve', halfW: 38, startY: 0, endY: 0, curveY: 10 },
    showMouth: false,
    blink: true,
    blinkInterval: 4000,
    drift: true,
    scan: false,
    cheeks: false,
  },
  ATTENTIVE: {
    label: 'Attentive',
    leftEye:  { type: 'roundedRect', width: 98, height: 78, cornerRadius: 24, tilt: -1, upperLid: 1, lowerLid: 1, pupilScale: 1.08, offsetY: -6 },
    rightEye: { type: 'roundedRect', width: 98, height: 78, cornerRadius: 24, tilt: 1, upperLid: 1, lowerLid: 1, pupilScale: 1.08, offsetY: -6 },
    mouth: { type: 'curve', halfW: 32, startY: 2, endY: 2, curveY: 6 },
    showMouth: false,
    blink: true,
    blinkInterval: 6000,
    drift: false,
    scan: false,
    cheeks: false,
  },
  THINKING: {
    label: 'Thinking',
    leftEye:  { type: 'roundedRect', width: 88, height: 52, cornerRadius: 20, tilt: -3, upperLid: 0.92, lowerLid: 0.98, pupilScale: 0.95, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 88, height: 52, cornerRadius: 20, tilt: 3, upperLid: 0.92, lowerLid: 0.98, pupilScale: 0.95, offsetY: 0 },
    mouth: { type: 'flat', halfW: 30, startY: 4, endY: 4, curveY: 0 },
    showMouth: false,
    blink: false,
    blinkInterval: 0,
    drift: true,
    scan: true,
    cheeks: false,
  },
  HAPPY: {
    label: 'Happy',
    leftEye:  { type: 'arc', width: 92, height: 58, tilt: -2, upperLid: 1, lowerLid: 1, pupilScale: 1.05, offsetY: 0 },
    rightEye: { type: 'arc', width: 92, height: 58, tilt: 2, upperLid: 1, lowerLid: 1, pupilScale: 1.05, offsetY: 0 },
    mouth: { type: 'smile', halfW: 50, startY: 0, endY: 0, curveY: 26 },
    showMouth: true,
    blink: true,
    blinkInterval: 3000,
    drift: false,
    scan: false,
    cheeks: true,
  },
};

const FALLBACK_EMOTION = 'CALM';

// ── SVG layout constants ──────────────────────────────────────────────────────
const W  = 400;
const H  = 300;
const CX = W / 2;
const CY = H / 2 - 4;

const LEFT_EYE_X  = CX - 98;
const RIGHT_EYE_X = CX + 98;
const EYE_Y       = CY - 16;
const MOUTH_Y     = CY + 62;

// ── Lerp ─────────────────────────────────────────────────────────────────────
const lerp = (a, b, t) => a + (b - a) * t;

function flattenNumerics(cfg) {
  const leftEyeWidth = cfg.leftEye.width ?? (cfg.leftEye.rx ? cfg.leftEye.rx * 2 : 72);
  const leftEyeHeight = cfg.leftEye.height ?? (cfg.leftEye.ry ? cfg.leftEye.ry * 2 : 36);
  const rightEyeWidth = cfg.rightEye.width ?? (cfg.rightEye.rx ? cfg.rightEye.rx * 2 : 72);
  const rightEyeHeight = cfg.rightEye.height ?? (cfg.rightEye.ry ? cfg.rightEye.ry * 2 : 36);
  return {
    le_w: leftEyeWidth,
    le_h: leftEyeHeight,
    le_cr: cfg.leftEye.cornerRadius ?? 14,
    le_tilt: cfg.leftEye.tilt ?? 0,
    le_uLid: cfg.leftEye.upperLid ?? 1,
    le_lLid: cfg.leftEye.lowerLid ?? 1,
    le_pupil: cfg.leftEye.pupilScale ?? 1,
    le_oY: cfg.leftEye.offsetY ?? 0,
    re_w: rightEyeWidth,
    re_h: rightEyeHeight,
    re_cr: cfg.rightEye.cornerRadius ?? 14,
    re_tilt: cfg.rightEye.tilt ?? 0,
    re_uLid: cfg.rightEye.upperLid ?? 1,
    re_lLid: cfg.rightEye.lowerLid ?? 1,
    re_pupil: cfg.rightEye.pupilScale ?? 1,
    re_oY: cfg.rightEye.offsetY ?? 0,
    m_halfW: cfg.mouth.halfW, m_startY: cfg.mouth.startY,
    m_endY: cfg.mouth.endY,   m_curveY: cfg.mouth.curveY,
  };
}

// ── SVG sub-components ────────────────────────────────────────────────────────

function roundedRectPath(cx, cy, width, height, cornerRadius) {
  const halfW = width / 2;
  const halfH = height / 2;
  const r = Math.max(0, Math.min(cornerRadius, halfW, halfH));
  return [
    `M ${cx - halfW + r} ${cy - halfH}`,
    `H ${cx + halfW - r}`,
    `Q ${cx + halfW} ${cy - halfH} ${cx + halfW} ${cy - halfH + r}`,
    `V ${cy + halfH - r}`,
    `Q ${cx + halfW} ${cy + halfH} ${cx + halfW - r} ${cy + halfH}`,
    `H ${cx - halfW + r}`,
    `Q ${cx - halfW} ${cy + halfH} ${cx - halfW} ${cy + halfH - r}`,
    `V ${cy - halfH + r}`,
    `Q ${cx - halfW} ${cy - halfH} ${cx - halfW + r} ${cy - halfH}`,
    'Z',
  ].join(' ');
}

function EyeShape({ x, eyeY, eye, blinkProgress, driftX, driftY }) {
  const type = eye.type || 'ellipse';
  const width = eye.width ?? (eye.rx ? eye.rx * 2 : 72);
  const height = eye.height ?? (eye.ry ? eye.ry * 2 : 36);
  const cornerRadius = eye.cornerRadius ?? 14;
  const tilt = eye.tilt ?? 0;
  const upperLid = eye.upperLid ?? 1;
  const lowerLid = eye.lowerLid ?? 1;
  const pupilScale = eye.pupilScale ?? 1;

  const baseHeight = Math.max(2, height * (1 - blinkProgress));
  const lidAdjustedHeight = baseHeight * ((Math.max(0.2, upperLid) + Math.max(0.2, lowerLid)) / 2);
  const finalWidth = width * Math.max(0.3, pupilScale);
  const finalHeight = Math.max(2, lidAdjustedHeight * Math.max(0.3, pupilScale));
  const rx = finalWidth / 2;
  const ry = finalHeight / 2;
  const ryFinal = Math.max(1, ry);
  const cx = x + driftX;
  const cy = eyeY + driftY;
  const transform = `rotate(${tilt} ${cx} ${cy})`;

  if (type === 'arc') {
    return (
      <path
        d={`M ${cx - rx} ${cy} A ${rx} ${ryFinal} 0 0 1 ${cx + rx} ${cy}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
        transform={transform}
      />
    );
  }

  if (type === 'roundedRect' || type === 'squircle') {
    return (
      <path
        d={roundedRectPath(cx, cy, finalWidth, finalHeight, cornerRadius)}
        fill="currentColor"
        transform={transform}
      />
    );
  }

  return (
    <ellipse cx={cx} cy={cy} rx={rx} ry={ryFinal} fill="currentColor" transform={transform} />
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
        eye={{
          ...dispCfg.leftEye,
          width: vals.le_w,
          height: vals.le_h,
          cornerRadius: vals.le_cr,
          tilt: vals.le_tilt,
          upperLid: vals.le_uLid,
          lowerLid: vals.le_lLid,
          pupilScale: vals.le_pupil,
        }}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />
      {/* Right eye */}
      <EyeShape
        x={RIGHT_EYE_X} eyeY={EYE_Y + vals.re_oY}
        eye={{
          ...dispCfg.rightEye,
          width: vals.re_w,
          height: vals.re_h,
          cornerRadius: vals.re_cr,
          tilt: vals.re_tilt,
          upperLid: vals.re_uLid,
          lowerLid: vals.re_lLid,
          pupilScale: vals.re_pupil,
        }}
        blinkProgress={blinkProgress}
        driftX={driftX} driftY={driftY}
      />

      {/* Mouth */}
      {dispCfg.showMouth && (
        <MouthShape
          type={dispCfg.mouth.type}
          halfW={vals.m_halfW}
          startY={vals.m_startY}
          endY={vals.m_endY}
          curveY={vals.m_curveY}
        />
      )}

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
