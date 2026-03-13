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
 *   HAPPY      - NAVIGATING: energetic square-ish eyes, blush marks
 *
 * Extensible: add new emotion configs to EMOTION_CONFIG below.
 */

import { useEffect, useRef, useState } from 'react';
import Panel from '../components/Panel';
import { useStore } from '../core/store';
import { DEFAULT_EMOTION } from '../core/emotion';
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
    leftEye:  { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: -2, upperLid: 0.9, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: 2, upperLid: 0.9, lowerLid: 1.0, pupilScale: 1, offsetY: 0 },
    mouth: { type: 'curve', halfW: 38, startY: 0, endY: 0, curveY: 10 },
    showMouth: false,
    blink: true,
    blinkInterval: 4000,
    blinkProfile: 'CALM',
    drift: true,
    scan: false,
    motionProfile: {
      x: [{ amp: 3.8, speed: 0.95 }, { amp: 1.9, speed: 1.74 }],
      y: [{ amp: 2.6, speed: 0.72 }, { amp: 1.2, speed: 1.28 }],
    },
    cheeks: false,
  },
  ATTENTIVE: {
    label: 'Attentive',
    leftEye:  { type: 'roundedRect', width: 114, height: 90, cornerRadius: 28, tilt: -1, upperLid: 1, lowerLid: 1, pupilScale: 1.1, offsetY: -8 },
    rightEye: { type: 'roundedRect', width: 114, height: 90, cornerRadius: 28, tilt: 1, upperLid: 1, lowerLid: 1, pupilScale: 1.1, offsetY: -8 },
    mouth: { type: 'curve', halfW: 32, startY: 2, endY: 2, curveY: 6 },
    showMouth: false,
    blink: true,
    blinkInterval: 6000,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.8, speed: 1.34 }, { amp: 0.45, speed: 2.18 }],
      y: [{ amp: 0.65, speed: 1.02 }, { amp: 0.3, speed: 1.87 }],
    },
    cheeks: false,
  },
  THINKING: {
    label: 'Thinking',
    leftEye:  { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: -3, upperLid: 0.94, lowerLid: 0.98, pupilScale: 0.96, offsetY: 0 },
    rightEye: { type: 'roundedRect', width: 102, height: 78, cornerRadius: 24, tilt: 3, upperLid: 0.94, lowerLid: 0.98, pupilScale: 0.96, offsetY: 0 },
    mouth: { type: 'flat', halfW: 30, startY: 4, endY: 4, curveY: 0 },
    showMouth: false,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: true,
    scan: true,
    motionProfile: {
      x: [{ amp: 12.5, speed: 1.18 }, { amp: 3.6, speed: 2.04 }],
      y: [{ amp: 0.75, speed: 1.12 }, { amp: 0.35, speed: 2.43 }],
    },
    cheeks: false,
  },
  HAPPY: {
    label: 'Happy',
    leftEye:  { type: 'roundedRect', width: 108, height: 84, cornerRadius: 30, tilt: -2, upperLid: 1, lowerLid: 1, pupilScale: 1.04, offsetY: -2 },
    rightEye: { type: 'roundedRect', width: 108, height: 84, cornerRadius: 30, tilt: 2, upperLid: 1, lowerLid: 1, pupilScale: 1.04, offsetY: -2 },
    mouth: { type: 'smile', halfW: 50, startY: 0, endY: 0, curveY: 26 },
    showMouth: false,
    blink: true,
    blinkInterval: 3000,
    blinkProfile: 'HAPPY',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 1.4, speed: 1.42 }, { amp: 0.9, speed: 2.36 }],
      y: [{ amp: 1.1, speed: 0.96 }, { amp: 0.65, speed: 1.68 }],
    },
    transitionEasing: 'overshoot',
    cheeks: true,
  },

  CURIOUS: {
    label: 'Curious',
    leftEye:  { type: 'roundedRect', width: 110, height: 86, cornerRadius: 28, tilt: -4, upperLid: 1, lowerLid: 0.96, pupilScale: 1.08, offsetY: -4 },
    rightEye: { type: 'roundedRect', width: 110, height: 86, cornerRadius: 28, tilt: 4, upperLid: 1, lowerLid: 0.96, pupilScale: 1.08, offsetY: -4 },
    mouth: { type: 'curve', halfW: 36, startY: 1, endY: -1, curveY: 7 },
    showMouth: false,
    blink: true,
    blinkInterval: 5200,
    blinkProfile: 'ATTENTIVE',
    drift: true,
    scan: true,
    motionProfile: {
      x: [{ amp: 7.8, speed: 1.15 }, { amp: 2.4, speed: 2.1 }],
      y: [{ amp: 1.1, speed: 1.0 }, { amp: 0.45, speed: 1.9 }],
    },
    cheeks: false,
  },
  SHY: {
    label: 'Shy',
    leftEye:  { type: 'roundedRect', width: 96, height: 72, cornerRadius: 24, tilt: -1, upperLid: 0.86, lowerLid: 1, pupilScale: 0.92, offsetY: 5 },
    rightEye: { type: 'roundedRect', width: 96, height: 72, cornerRadius: 24, tilt: 1, upperLid: 0.86, lowerLid: 1, pupilScale: 0.92, offsetY: 5 },
    mouth: { type: 'curve', halfW: 26, startY: 5, endY: 5, curveY: 4 },
    showMouth: false,
    blink: true,
    blinkInterval: 3200,
    blinkProfile: 'CALM',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.9, speed: 0.92 }, { amp: 0.5, speed: 1.55 }],
      y: [{ amp: 0.8, speed: 0.86 }, { amp: 0.42, speed: 1.34 }],
    },
    cheeks: true,
  },
  SURPRISED: {
    label: 'Surprised',
    leftEye:  { type: 'roundedRect', width: 118, height: 96, cornerRadius: 30, tilt: 0, upperLid: 1, lowerLid: 1, pupilScale: 1.14, offsetY: -10 },
    rightEye: { type: 'roundedRect', width: 118, height: 96, cornerRadius: 30, tilt: 0, upperLid: 1, lowerLid: 1, pupilScale: 1.14, offsetY: -10 },
    mouth: { type: 'wave', halfW: 68, startY: 7, endY: 7, curveY: 7 },
    showMouth: false,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.55, speed: 1.35 }, { amp: 0.32, speed: 2.2 }],
      y: [{ amp: 0.45, speed: 1.04 }, { amp: 0.24, speed: 1.76 }],
    },
    cheeks: false,
  },
  BUMPED: {
    label: 'Bumped',
    leftEye:  { type: 'chevronLeft', width: 80, height: 64, cornerRadius: 18, tilt: -4, upperLid: 1, lowerLid: 1, pupilScale: 1, offsetY: -2 },
    rightEye: { type: 'chevronRight', width: 80, height: 64, cornerRadius: 18, tilt: 4, upperLid: 1, lowerLid: 1, pupilScale: 1, offsetY: -2 },
    mouth: { type: 'zigzag', halfW: 56, startY: 9, endY: 9, curveY: 10 },
    showMouth: true,
    blink: false,
    blinkInterval: 0,
    blinkProfile: 'ATTENTIVE',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.9, speed: 1.8 }, { amp: 0.35, speed: 3.0 }],
      y: [{ amp: 0.6, speed: 1.2 }, { amp: 0.25, speed: 2.1 }],
    },
    cheeks: false,
  },
  RELIEVED: {
    label: 'Relieved',
    leftEye:  { type: 'roundedRect', width: 104, height: 80, cornerRadius: 28, tilt: -2, upperLid: 0.9, lowerLid: 1, pupilScale: 0.98, offsetY: 1 },
    rightEye: { type: 'roundedRect', width: 104, height: 80, cornerRadius: 28, tilt: 2, upperLid: 0.9, lowerLid: 1, pupilScale: 0.98, offsetY: 1 },
    mouth: { type: 'smile', halfW: 42, startY: 2, endY: 2, curveY: 14 },
    showMouth: false,
    blink: true,
    blinkInterval: 4300,
    blinkProfile: 'CALM',
    drift: true,
    scan: false,
    motionProfile: {
      x: [{ amp: 2.6, speed: 1.06 }, { amp: 1.4, speed: 1.82 }],
      y: [{ amp: 1.4, speed: 0.8 }, { amp: 0.62, speed: 1.24 }],
    },
    cheeks: false,
  },
  SLEEPY: {
    label: 'Sleepy',
    leftEye:  { type: 'roundedRect', width: 108, height: 62, cornerRadius: 26, tilt: -3, upperLid: 0.66, lowerLid: 0.95, pupilScale: 0.86, offsetY: 8 },
    rightEye: { type: 'roundedRect', width: 108, height: 62, cornerRadius: 26, tilt: 3, upperLid: 0.66, lowerLid: 0.95, pupilScale: 0.86, offsetY: 8 },
    mouth: { type: 'flat', halfW: 26, startY: 6, endY: 6, curveY: 0 },
    showMouth: false,
    blink: true,
    blinkInterval: 2500,
    blinkProfile: 'CALM',
    drift: false,
    scan: false,
    motionProfile: {
      x: [{ amp: 0.7, speed: 0.58 }, { amp: 0.25, speed: 0.9 }],
      y: [{ amp: 0.55, speed: 0.5 }, { amp: 0.2, speed: 0.82 }],
    },
    cheeks: false,
  },
};

const FALLBACK_EMOTION = DEFAULT_EMOTION;

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
  const leftEyeWidth = cfg.leftEye.width ?? 72;
  const leftEyeHeight = cfg.leftEye.height ?? 36;
  const rightEyeWidth = cfg.rightEye.width ?? 72;
  const rightEyeHeight = cfg.rightEye.height ?? 36;
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
  const type = eye.type || 'roundedRect';
  const width = eye.width ?? 72;
  const height = eye.height ?? 36;
  const cornerRadius = eye.cornerRadius ?? 14;
  const tilt = eye.tilt ?? 0;
  const upperLid = eye.upperLid ?? 1;
  const lowerLid = eye.lowerLid ?? 1;
  const pupilScale = eye.pupilScale ?? 1;

  const baseHeight = Math.max(2, height * (1 - blinkProgress));
  const lidAdjustedHeight = baseHeight * ((Math.max(0.2, upperLid) + Math.max(0.2, lowerLid)) / 2);
  const finalWidth = width * Math.max(0.3, pupilScale);
  const finalHeight = Math.max(2, lidAdjustedHeight * Math.max(0.3, pupilScale));
  const cx = x + driftX;
  const cy = eyeY + driftY;
  const transform = `rotate(${tilt} ${cx} ${cy})`;

  if (type === 'chevronRight' || type === 'chevronLeft') {
    const chevronW = finalWidth * 0.55;
    const chevronH = finalHeight * 0.7;
    const xEdge = type === 'chevronRight' ? cx + chevronW * 0.5 : cx - chevronW * 0.5;
    const xPoint = type === 'chevronRight' ? cx - chevronW * 0.5 : cx + chevronW * 0.5;
    return (
      <g transform={transform} stroke="currentColor" strokeWidth="8" strokeLinecap="round">
        <line x1={xEdge} y1={cy - chevronH / 2} x2={xPoint} y2={cy} />
        <line x1={xEdge} y1={cy + chevronH / 2} x2={xPoint} y2={cy} />
      </g>
    );
  }

  if (type !== 'roundedRect' && type !== 'squircle') return null;

  return (
    <path
      d={roundedRectPath(cx, cy, finalWidth, finalHeight, cornerRadius)}
      fill="currentColor"
      transform={transform}
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
  if (type === 'wave') {
    const seg = halfW * 0.9;
    const amp = Math.max(4, curveY);
    return (
      <path
        d={[
          `M ${CX - halfW} ${MOUTH_Y + startY}`,
          `Q ${CX - seg * 0.5} ${MOUTH_Y + startY + amp} ${CX} ${MOUTH_Y + startY}`,
          `Q ${CX + seg * 0.5} ${MOUTH_Y + startY + amp} ${CX + halfW} ${MOUTH_Y + endY}`,
        ].join(' ')}
        fill="none"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
      />
    );
  }
  if (type === 'zigzag') {
    const xStart = CX - halfW;
    const yBase = MOUTH_Y + startY;
    const width = halfW * 2;
    const amp = Math.max(4, curveY);
    const seg = width / 6;
    return (
      <path
        d={[
          `M ${xStart} ${yBase}`,
          `L ${xStart + seg} ${yBase + amp}`,
          `L ${xStart + seg * 2} ${yBase}`,
          `L ${xStart + seg * 3} ${yBase + amp}`,
          `L ${xStart + seg * 4} ${yBase}`,
          `L ${xStart + seg * 5} ${yBase + amp}`,
          `L ${xStart + seg * 6} ${MOUTH_Y + endY}`,
        ].join(' ')}
        fill="none"
        stroke="currentColor"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
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
  const stroke = 'rgba(255,140,140,0.42)';
  const leftCenterX = LEFT_EYE_X - 46;
  const rightCenterX = RIGHT_EYE_X + 46;
  const baseY = EYE_Y + 70;
  const lineGap = 12;
  const slashLen = 18;

  return (
    <g stroke={stroke} strokeWidth="5" strokeLinecap="round">
      {[0, 1, 2].map(i => (
        <line
          key={`l-${i}`}
          x1={leftCenterX + (i - 1) * lineGap}
          y1={baseY}
          x2={leftCenterX + (i - 1) * lineGap + slashLen}
          y2={baseY - slashLen}
        />
      ))}
      {[0, 1, 2].map(i => (
        <line
          key={`r-${i}`}
          x1={rightCenterX + (i - 1) * lineGap}
          y1={baseY}
          x2={rightCenterX + (i - 1) * lineGap + slashLen}
          y2={baseY - slashLen}
        />
      ))}
    </g>
  );
}

function EmotionSymbols({ displayEmotion, elapsedMs }) {
  if (displayEmotion === 'CURIOUS') {
    const bob = Math.sin(elapsedMs * 0.006) * 3;
    return (
      <text
        x={RIGHT_EYE_X + 72}
        y={EYE_Y - 64 + bob}
        fill="currentColor"
        fontSize="34"
        fontWeight="600"
      >
        ?
      </text>
    );
  }

  if (displayEmotion === 'SLEEPY' && elapsedMs > 3400) {
    const fade = Math.min(1, (elapsedMs - 3400) / 1800);
    return (
      <text
        x={RIGHT_EYE_X + 70}
        y={EYE_Y - 56}
        fill={`rgba(232,234,240,${0.35 + fade * 0.65})`}
        fontSize="26"
        fontWeight="500"
      >
        Zzz
      </text>
    );
  }
  return null;
}

// ── Face canvas with morph transition ────────────────────────────────────────
const TRANSITION_MS = 380;
const BLINK_INTERVAL_JITTER = 0.35;

const BLINK_PROFILES = {
  CALM: {
    frames: [0, 0.2, 0.55, 0.88, 1.0, 0.88, 0.55, 0.2, 0],
    frameMs: 52,
  },
  ATTENTIVE: {
    frames: [0, 0.45, 1.0, 0.4, 0],
    frameMs: 30,
  },
  HAPPY: {
    frames: [0, 0.5, 1.0, 0.42, 0, 0.25, 0.62, 0.22, 0],
    frameMs: 32,
  },
};

const easeOutCubic = (x) => 1 - Math.pow(1 - x, 3);
const easeOutBack = (x) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
};

const sumWave = (waves, t) => waves.reduce(
  (acc, wave, idx) => acc + Math.sin(t * wave.speed + idx * 1.618) * wave.amp,
  0,
);

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
      const useOvershoot = to.transitionEasing === 'overshoot';
      const t = useOvershoot ? easeOutBack(raw) : easeOutCubic(raw);

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
    const blinkProfile = BLINK_PROFILES[cfg.blinkProfile] || BLINK_PROFILES.CALM;
    const frames = blinkProfile.frames;
    const frameMs = blinkProfile.frameMs;

    const scheduleBlink = () => {
      const baseInterval = cfg.blinkInterval || 4000;
      const jitter = (Math.random() * 2 - 1) * BLINK_INTERVAL_JITTER;
      const delay = Math.max(250, baseInterval * (1 + jitter));
      blinkRef.current = setTimeout(() => {
        if (!mounted) return;
        let frame = 0;
        const step = () => {
          if (!mounted || frame >= frames.length) {
            setBlinkProgress(0);
            scheduleBlink();
            return;
          }
          setBlinkProgress(frames[frame++]);
          blinkRef.current = setTimeout(step, frameMs);
        };
        step();
      }, delay);
    };

    scheduleBlink();
    return () => { mounted = false; clearTimeout(blinkRef.current); };
  }, [emotion, cfg.blink, cfg.blinkInterval, cfg.blinkProfile]);

  // Drift / scan
  const [driftX, setDriftX] = useState(0);
  const [driftY, setDriftY] = useState(0);
  const [motionT, setMotionT] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const driftRef = useRef(null);
  const emotionStartRef = useRef(0);

  useEffect(() => {
    emotionStartRef.current = performance.now();
    setElapsedMs(0);
  }, [displayEmotion]);

  useEffect(() => {
    let mounted = true;
    let t = 0;
    const motion = cfg.motionProfile || {
      x: [{ amp: 5, speed: 1.0 }, { amp: 2.1, speed: 1.8 }],
      y: [{ amp: 3, speed: 0.7 }, { amp: 1.3, speed: 1.27 }],
    };

    const tick = () => {
      if (!mounted) return;
      t += 0.013;
      setMotionT(t);
      setElapsedMs(performance.now() - emotionStartRef.current);
      if (cfg.scan || cfg.drift) {
        setDriftX(sumWave(motion.x, t));
        setDriftY(sumWave(motion.y, t));
      } else {
        setDriftX(0);
        setDriftY(0);
      }
      driftRef.current = requestAnimationFrame(tick);
    };

    driftRef.current = requestAnimationFrame(tick);
    return () => { mounted = false; cancelAnimationFrame(driftRef.current); };
  }, [emotion, cfg.drift, cfg.scan, cfg.motionProfile]);

  const dispCfg = EMOTION_CONFIG[displayEmotion] || EMOTION_CONFIG[FALLBACK_EMOTION];

  const eyeFx = {
    headTilt: 0,
    headDrop: 0,
    ldx: 0, ldy: 0, rdx: 0, rdy: 0,
    lTilt: 0, rTilt: 0,
    lHeightMul: 1, rHeightMul: 1,
  };

  if (displayEmotion === 'HAPPY') {
    eyeFx.ldy = Math.sin(motionT * 2.8) * 2.8;
    eyeFx.rdy = Math.cos(motionT * 2.8) * 2.8;
  } else if (displayEmotion === 'SHY') {
    eyeFx.ldx = Math.sin(motionT * 1.7) * 2.5;
    eyeFx.rdx = -Math.sin(motionT * 1.7) * 2.5;
    eyeFx.lTilt = -2;
    eyeFx.rTilt = 2;
  } else if (displayEmotion === 'CURIOUS') {
    eyeFx.headTilt = Math.sin(motionT * 1.4) * 9;
    eyeFx.ldy = Math.sin(motionT * 2.1) * 2;
    eyeFx.rdy = -Math.sin(motionT * 2.1) * 2.6;
    eyeFx.lHeightMul = 0.94 + (Math.sin(motionT * 2.2) + 1) * 0.08;
    eyeFx.rHeightMul = 1.03;
  } else if (displayEmotion === 'SLEEPY') {
    const drowse = Math.min(1, elapsedMs / 7000);
    eyeFx.headDrop = drowse * 22 + Math.sin(motionT * 1.2) * 2;
    eyeFx.lHeightMul = 1 - drowse * 0.55;
    eyeFx.rHeightMul = 1 - drowse * 0.55;
  } else if (displayEmotion === 'BUMPED') {
    eyeFx.headTilt = Math.sin(motionT * 10.5) * 6;
    eyeFx.ldx = Math.sin(motionT * 15) * 2;
    eyeFx.rdx = -Math.sin(motionT * 15) * 2;
    eyeFx.ldy = Math.abs(Math.sin(motionT * 12)) * 1.4;
    eyeFx.rdy = Math.abs(Math.cos(motionT * 12)) * 1.4;
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height="100%"
      style={{ color: FACE_COLOR, filter: `drop-shadow(0 0 14px ${FACE_GLOW})` }}
      aria-label={`DORI face: ${dispCfg.label}`}
    >
      <g transform={`translate(0 ${eyeFx.headDrop}) rotate(${eyeFx.headTilt} ${CX} ${CY})`}>
        {/* Left eye */}
        <EyeShape
          x={LEFT_EYE_X + eyeFx.ldx} eyeY={EYE_Y + vals.le_oY + eyeFx.ldy}
          eye={{
            ...dispCfg.leftEye,
            width: vals.le_w,
            height: vals.le_h * eyeFx.lHeightMul,
            cornerRadius: vals.le_cr,
            tilt: vals.le_tilt + eyeFx.lTilt,
            upperLid: vals.le_uLid,
            lowerLid: vals.le_lLid,
            pupilScale: vals.le_pupil,
          }}
          blinkProgress={blinkProgress}
          driftX={driftX} driftY={driftY}
        />
        {/* Right eye */}
        <EyeShape
          x={RIGHT_EYE_X + eyeFx.rdx} eyeY={EYE_Y + vals.re_oY + eyeFx.rdy}
          eye={{
            ...dispCfg.rightEye,
            width: vals.re_w,
            height: vals.re_h * eyeFx.rHeightMul,
            cornerRadius: vals.re_cr,
            tilt: vals.re_tilt + eyeFx.rTilt,
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
        <EmotionSymbols displayEmotion={displayEmotion} elapsedMs={elapsedMs} />
      </g>
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
                {emotionSource === 'override' ? '⚡ override' : emotionSource === 'ros' ? '◎ ros' : '⟳ state'}
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
