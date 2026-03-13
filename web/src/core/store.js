/**
 * core/store.js
 * Zustand global store.
 * All ROS message handlers live here — panels just read state.
 *
 * Adding a new panel:
 *   1. Add a slice to the store (state + setter)
 *   2. Add a case in handleROSMessage()
 *   3. Done — panel imports useStore() and reads what it needs
 */

import { create } from 'zustand';
import {
  DEFAULT_EMOTION,
  resolveEmotionFromState,
  resolveROSOrStateEmotion,
} from './emotion';

const FACE_KEYS = ['U', 'R', 'F', 'D', 'L', 'B'];
const FACE_COLORS = Object.freeze({
  U: 'W',
  R: 'R',
  F: 'G',
  D: 'Y',
  L: 'O',
  B: 'B',
});

const rotateFaceCW = (face) => ([
  face[6], face[3], face[0],
  face[7], face[4], face[1],
  face[8], face[5], face[2],
]);

const createSolvedCube = () => Object.fromEntries(
  FACE_KEYS.map((k) => [k, new Array(9).fill(FACE_COLORS[k])]),
);

const applyMove = (cube, move) => {
  const next = Object.fromEntries(FACE_KEYS.map((k) => [k, [...cube[k]]]));

  const turn = () => {
    switch (move) {
      case 'U': {
        next.U = rotateFaceCW(next.U);
        const temp = [cube.F[0], cube.F[1], cube.F[2]];
        [next.F[0], next.F[1], next.F[2]] = [cube.L[0], cube.L[1], cube.L[2]];
        [next.L[0], next.L[1], next.L[2]] = [cube.B[0], cube.B[1], cube.B[2]];
        [next.B[0], next.B[1], next.B[2]] = [cube.R[0], cube.R[1], cube.R[2]];
        [next.R[0], next.R[1], next.R[2]] = temp;
        break;
      }
      case 'R': {
        next.R = rotateFaceCW(next.R);
        const temp = [cube.U[2], cube.U[5], cube.U[8]];
        [next.U[2], next.U[5], next.U[8]] = [cube.F[2], cube.F[5], cube.F[8]];
        [next.F[2], next.F[5], next.F[8]] = [cube.D[2], cube.D[5], cube.D[8]];
        [next.D[2], next.D[5], next.D[8]] = [cube.B[6], cube.B[3], cube.B[0]];
        [next.B[6], next.B[3], next.B[0]] = temp;
        break;
      }
      case 'L': {
        next.L = rotateFaceCW(next.L);
        const temp = [cube.U[0], cube.U[3], cube.U[6]];
        [next.U[0], next.U[3], next.U[6]] = [cube.B[8], cube.B[5], cube.B[2]];
        [next.B[8], next.B[5], next.B[2]] = [cube.D[6], cube.D[3], cube.D[0]];
        [next.D[6], next.D[3], next.D[0]] = [cube.F[0], cube.F[3], cube.F[6]];
        [next.F[0], next.F[3], next.F[6]] = temp;
        break;
      }
      case 'B': {
        next.B = rotateFaceCW(next.B);
        const temp = [cube.U[0], cube.U[1], cube.U[2]];
        [next.U[0], next.U[1], next.U[2]] = [cube.R[2], cube.R[5], cube.R[8]];
        [next.R[2], next.R[5], next.R[8]] = [cube.D[8], cube.D[7], cube.D[6]];
        [next.D[8], next.D[7], next.D[6]] = [cube.L[6], cube.L[3], cube.L[0]];
        [next.L[6], next.L[3], next.L[0]] = temp;
        break;
      }
      default:
        break;
    }
  };

  if (move.endsWith("'")) {
    const base = move[0];
    for (let i = 0; i < 3; i += 1) {
      Object.assign(next, applyMove(next, base));
    }
    return next;
  }

  turn();
  return next;
};

// ─── Constants ──────────────────────────────────────────────────────────────
export const HRI_STATES = ['IDLE', 'LISTENING', 'RESPONDING', 'NAVIGATING'];

export const LOG_TAGS = Object.freeze({
  STATE: 'STATE',
  WAKE: 'WAKE',
  STT: 'STT',
  LLM: 'LLM',
  TTS: 'TTS',
  GESTURE: 'GESTURE',
  EXPR: 'EXPR',
  TRACK: 'TRACK',
  NAV: 'NAV',
  SYS: 'SYS',
  DEMO: 'DEMO',
  ERROR: 'ERROR',
});

export const LOG_TAG_ORDER = Object.freeze([
  LOG_TAGS.STATE,
  LOG_TAGS.WAKE,
  LOG_TAGS.STT,
  LOG_TAGS.LLM,
  LOG_TAGS.TTS,
  LOG_TAGS.GESTURE,
  LOG_TAGS.EXPR,
  LOG_TAGS.TRACK,
  LOG_TAGS.NAV,
  LOG_TAGS.SYS,
  LOG_TAGS.DEMO,
  LOG_TAGS.ERROR,
]);

export const TOPIC_META = {
  '/dori/hri/manager_state':       { tag: LOG_TAGS.STATE,   label: 'HRI State' },
  '/dori/stt/wake_word_detected':  { tag: LOG_TAGS.WAKE,    label: 'Wake Word' },
  '/dori/stt/result':              { tag: LOG_TAGS.STT,     label: 'STT Result' },
  '/dori/llm/query':               { tag: LOG_TAGS.LLM,     label: 'LLM Query' },
  '/dori/llm/response':            { tag: LOG_TAGS.LLM,     label: 'LLM Response' },
  '/dori/tts/text':                { tag: LOG_TAGS.TTS,     label: 'TTS Text' },
  '/dori/tts/speaking':            { tag: LOG_TAGS.TTS,     label: 'TTS Speaking' },
  '/dori/tts/done':                { tag: LOG_TAGS.TTS,     label: 'TTS Done' },
  '/dori/hri/interaction_trigger': { tag: LOG_TAGS.TRACK,   label: 'Interaction Trigger' },
  '/dori/hri/tracking_state':      { tag: LOG_TAGS.TRACK,   label: 'Tracking State' },
  '/dori/hri/persons':             { tag: LOG_TAGS.TRACK,   label: 'Persons' },
  '/dori/hri/gesture':             { tag: LOG_TAGS.GESTURE, label: 'Gesture' },
  '/dori/hri/gesture_command':     { tag: LOG_TAGS.GESTURE, label: 'Gesture Cmd' },
  '/dori/hri/emotion':             { tag: LOG_TAGS.EXPR,    label: 'Emotion' },
  '/dori/hri/expression':          { tag: LOG_TAGS.EXPR,    label: 'Expression' },
  '/dori/hri/expression_command':  { tag: LOG_TAGS.EXPR,    label: 'Expression Cmd' },
  '/dori/follow/target_offset':    { tag: LOG_TAGS.TRACK,   label: 'Follow Offset' },
  '/dori/nav/command':             { tag: LOG_TAGS.NAV,     label: 'Nav Command' },
  '/dori/landmark/context':        { tag: LOG_TAGS.NAV,     label: 'Landmark Context' },
  '/dori/system/metrics':         { tag: LOG_TAGS.SYS,     label: 'System Metrics' },
};

const MAX_LOG = 300;
const TOPIC_HZ_WINDOW_MS = 2000;
const TOPIC_STATS_WINDOW_MS = 10000;

const toNumberOrNull = (v) => (Number.isFinite(v) ? +v.toFixed(2) : null);

function computeTopicStats(samples) {
  if (!samples?.length) {
    return {
      avgHz: null,
      jitterMs: null,
      bwBps: null,
      avgMsgBytes: null,
    };
  }

  const firstTs = samples[0].ts;
  const lastTs = samples[samples.length - 1].ts;
  const durationSec = (lastTs - firstTs) / 1000;
  const totalBytes = samples.reduce((acc, s) => acc + s.size, 0);
  const avgMsgBytes = totalBytes / samples.length;

  const intervals = [];
  for (let i = 1; i < samples.length; i += 1) {
    intervals.push(samples[i].ts - samples[i - 1].ts);
  }

  const meanInterval = intervals.length
    ? intervals.reduce((acc, v) => acc + v, 0) / intervals.length
    : null;
  const variance = meanInterval && intervals.length > 1
    ? intervals.reduce((acc, v) => acc + ((v - meanInterval) ** 2), 0) / intervals.length
    : null;

  return {
    avgHz: durationSec > 0 ? toNumberOrNull(samples.length / durationSec) : null,
    jitterMs: variance !== null ? toNumberOrNull(Math.sqrt(variance)) : null,
    bwBps: durationSec > 0 ? toNumberOrNull(totalBytes / durationSec) : null,
    avgMsgBytes: toNumberOrNull(avgMsgBytes),
  };
}

function normalizePayload(rawVal) {
  const payload = rawVal && typeof rawVal === 'object' && 'data' in rawVal
    ? rawVal.data
    : rawVal;

  if (typeof payload !== 'string') {
    return { payload, parsed: payload };
  }

  try {
    return { payload, parsed: JSON.parse(payload) };
  } catch {
    return { payload, parsed: payload };
  }
}

function parseBoolPayload(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true;
    if (['false', '0', 'no', 'off', ''].includes(normalized)) return false;
  }
  if (value && typeof value === 'object' && 'data' in value) {
    return parseBoolPayload(value.data);
  }
  return false;
}

// ─── Store ───────────────────────────────────────────────────────────────────
export const useStore = create((set, get) => ({

  // ── Connection ──────────────────────────────────────────────────────────
  connected: false,
  isDemoMode: false,
  wsUrl: 'ws://localhost:9090',

  setConnected: (v) => set({ connected: v }),
  setDemoMode:  (v) => set({ isDemoMode: v }),
  setWsUrl:     (v) => set({ wsUrl: v }),

  // ── Cube Sim ────────────────────────────────────────────────────────────
  cubeState: createSolvedCube(),
  cubeMoveHistory: [],
  resetCube: () => set({ cubeState: createSolvedCube(), cubeMoveHistory: [] }),
  rotateCube: (move) => set((s) => {
    const normalized = (move || '').trim().toUpperCase();
    if (!['U', "U'", 'R', "R'", 'L', "L'", 'B', "B'"].includes(normalized)) {
      return s;
    }
    return {
      cubeState: applyMove(s.cubeState, normalized),
      cubeMoveHistory: [...s.cubeMoveHistory, normalized].slice(-100),
    };
  }),

  // ── HRI State Machine ───────────────────────────────────────────────────
  hriState: 'IDLE',
  hriStateElapsed: 0,
  hriTargetId: null,
  hriLocationContext: '',

  // ── Conversation ────────────────────────────────────────────────────────
  lastSttText: '',
  lastLlmResponse: '',
  lastTtsText: '',
  ttsActive: false,

  // ── Tracking ────────────────────────────────────────────────────────────
  trackingState: null,   // { state, target_id, lost_elapsed_sec, last_distance_m }
  persons: null,         // { count, target_id, detections[], state }

  // ── Gesture & Expression ─────────────────────────────────────────────────
  gesture: 'NONE',
  gestureDirection: null,
  expression: 'NEUTRAL',

  // ── System Metrics ──────────────────────────────────────────────────────
  systemMetrics: {
    timestamp: null,
    cpu: null,
    ram: null,
    disk: null,
    gpu: null,
  },

  // ── Emotion (robot display face) ─────────────────────────────────────────
  emotion: DEFAULT_EMOTION,
  emotionSource: 'state',   // 'state' | 'ros' | 'override'
  _emotionOverride: null,   // manually set from FaceTab palette

  setEmotionOverride: (em) => set({ emotion: em, emotionSource: 'override', _emotionOverride: em }),
  clearEmotionOverride: () => {
    // Revert to state-driven emotion
    const { hriState } = get();
    set({ emotion: resolveEmotionFromState(hriState), emotionSource: 'state', _emotionOverride: null });
  },

  // ── Event Log ────────────────────────────────────────────────────────────
  // Each entry: { id, ts, tag, text, raw? }
  log: [],

  // ── Topic Publisher Status ───────────────────────────────────────────────
  isPublishing: false,
  lastPublishAt: null,
  publishError: null,

  addLog: (tag, text, raw = null) => {
    const entry = {
      id:  Date.now() + Math.random(),
      ts:  new Date(),
      tag,
      text,
      raw,
    };
    set(s => ({ log: [entry, ...s.log].slice(0, MAX_LOG) }));
  },

  clearLog: () => set({ log: [] }),

  setPublishState: ({ isPublishing, lastPublishAt, publishError } = {}) => set((s) => ({
    isPublishing: typeof isPublishing === 'boolean' ? isPublishing : s.isPublishing,
    lastPublishAt: lastPublishAt === undefined ? s.lastPublishAt : lastPublishAt,
    publishError: publishError === undefined ? s.publishError : publishError,
  })),

  // ── Topic Hz tracking ───────────────────────────────────────────────────
  topicHz: {},   // topic -> number (msgs/sec, rolling 2s)
  _topicTimes: {}, // topic -> timestamp[]
  topicStats: {}, // topic -> diagnostics info
  _topicSamples: {}, // topic -> [{ ts, size }] (rolling 10s)

  setTopicMeta: (topic, meta = {}) => {
    set((s) => ({
      topicStats: {
        ...s.topicStats,
        [topic]: {
          msgType: meta.msgType ?? s.topicStats[topic]?.msgType ?? null,
          pubCount: meta.pubCount ?? s.topicStats[topic]?.pubCount ?? null,
          subCount: meta.subCount ?? s.topicStats[topic]?.subCount ?? null,
          qosSummary: meta.qosSummary ?? s.topicStats[topic]?.qosSummary ?? 'N/A (rosbridge)',
          ...s.topicStats[topic],
          ...meta,
        },
      },
    }));
  },

  recordTopicHit: (topic, msgPayload) => {
    const now = Date.now();
    const times = [...(get()._topicTimes[topic] || []), now]
      .filter(t => now - t < TOPIC_HZ_WINDOW_MS);
    const msgBytes = JSON.stringify(msgPayload ?? null)?.length ?? 0;
    const samples = [...(get()._topicSamples[topic] || []), { ts: now, size: msgBytes }]
      .filter(({ ts }) => now - ts < TOPIC_STATS_WINDOW_MS);
    const stats = computeTopicStats(samples);

    set(s => ({
      _topicTimes: { ...s._topicTimes, [topic]: times },
      _topicSamples: { ...s._topicSamples, [topic]: samples },
      topicHz:     { ...s.topicHz, [topic]: +(times.length / 2).toFixed(1) },
      topicStats: {
        ...s.topicStats,
        [topic]: {
          msgType: s.topicStats[topic]?.msgType ?? null,
          pubCount: s.topicStats[topic]?.pubCount ?? null,
          subCount: s.topicStats[topic]?.subCount ?? null,
          qosSummary: s.topicStats[topic]?.qosSummary ?? 'N/A (rosbridge)',
          ...stats,
          lastSeenMs: now,
        },
      },
    }));
  },

  // ── Master message handler ───────────────────────────────────────────────
  handleROSMessage: (topic, rawVal) => {
    const { addLog, recordTopicHit } = get();
    recordTopicHit(topic, rawVal);

    const { payload, parsed } = normalizePayload(rawVal);

    const meta = TOPIC_META[topic] || { tag: LOG_TAGS.SYS, label: topic };

    // ── Per-topic handling ──────────────────────────────────────────────
    try {
      switch (topic) {

        case '/dori/hri/manager_state': {
          const d = parsed && typeof parsed === 'object' ? parsed : {};
          set({
            hriState: d.state || 'IDLE',
            hriStateElapsed: d.state_elapsed_sec ?? 0,
            hriTargetId: d.target_id ?? null,
            hriLocationContext: d.location_context || '',
          });
          // Auto-update emotion from state (only if not overriding)
          if (!get()._emotionOverride) {
            const nextEmotion = resolveEmotionFromState(d.state);
            set({ emotion: nextEmotion, emotionSource: 'state' });
          }
          addLog(LOG_TAGS.STATE, `manager_state: state=${d.state || 'IDLE'} elapsed=${(d.state_elapsed_sec ?? 0).toFixed(1)}s target=${d.target_id ?? '-'} text=${d.text ?? '-'}`, rawVal);
          break;
        }

        case '/dori/stt/wake_word_detected': {
          const detected = parseBoolPayload(parsed);
          if (detected) {
            addLog(LOG_TAGS.WAKE, 'Wake word detected!', rawVal);
          }
          break;
        }

        case '/dori/stt/result': {
          const text = parsed?.text || payload;
          set({ lastSttText: text });
          addLog(LOG_TAGS.STT, `stt_result: text="${text}" conf=${parsed?.confidence?.toFixed(2) ?? '?'}`, rawVal);
          break;
        }

        case '/dori/llm/query':
          addLog(LOG_TAGS.LLM, `llm_query: user_text="${parsed?.user_text || payload}"`, rawVal);
          break;

        case '/dori/llm/response': {
          const text = typeof parsed === 'string' ? parsed : JSON.stringify(parsed);
          set({ lastLlmResponse: text });
          addLog(LOG_TAGS.LLM, `response: "${text.slice(0, 80)}${text.length > 80 ? '…' : ''}"`, rawVal);
          break;
        }

        case '/dori/tts/text': {
          const text = typeof parsed === 'string' ? parsed : JSON.stringify(parsed);
          set({ lastTtsText: text });
          addLog(LOG_TAGS.TTS, `speak: "${text.slice(0, 80)}${text.length > 80 ? '…' : ''}"`, rawVal);
          break;
        }

        case '/dori/tts/speaking':
        {
          const speaking = parseBoolPayload(parsed);
          set({ ttsActive: speaking });
          if (speaking) addLog(LOG_TAGS.TTS, 'tts_speaking: true', rawVal);
          break;
        }

        case '/dori/tts/done': {
          const done = parseBoolPayload(parsed);
          if (done) addLog(LOG_TAGS.TTS, 'tts_done: true', rawVal);
          break;
        }

        case '/dori/hri/tracking_state': {
          set({ trackingState: parsed });
          addLog(LOG_TAGS.TRACK, `tracking_state: state=${parsed?.state ?? '-'} target=${parsed?.target_id ?? '-'} text=${parsed?.text ?? '-'}`, rawVal);
          if (parsed?.state === 'lost') addLog(LOG_TAGS.TRACK, `Target lost (id:${parsed?.target_id})`, rawVal);
          break;
        }

        case '/dori/hri/persons':
          set({ persons: parsed });
          break;

        case '/dori/hri/gesture': {
          const g = parsed?.gesture || 'NONE';
          set({ gesture: g, gestureDirection: parsed?.direction || null });
          if (g !== 'NONE') addLog(LOG_TAGS.GESTURE, g, rawVal);
          break;
        }

        case '/dori/hri/expression': {
          const expr = parsed?.expression || 'NEUTRAL';
          set({ expression: expr });
          if (expr !== 'NEUTRAL') addLog(LOG_TAGS.EXPR, expr, rawVal);
          break;
        }

        case '/dori/hri/emotion': {
          const { _emotionOverride, hriState } = get();
          // Priority policy:
          // 1) Manual palette override is highest and blocks ROS emotion updates.
          // 2) Without override, accept only valid ROS emotion keys.
          // 3) Invalid/missing ROS emotion falls back to HRI-state derived emotion.
          if (_emotionOverride) {
            addLog(LOG_TAGS.EXPR, `emotion ignored (manual override active): ${_emotionOverride}`, rawVal);
            break;
          }

          const { emotion, source } = resolveROSOrStateEmotion(parsed, hriState);
          set({ emotion, emotionSource: source });
          addLog(LOG_TAGS.EXPR, `emotion: ${emotion} [${source}]`, rawVal);
          break;
        }

        case '/dori/landmark/context':
          set({ hriLocationContext: typeof parsed === 'string' ? parsed : JSON.stringify(parsed) });
          break;

        case '/dori/system/metrics': {
          if (parsed && typeof parsed === 'object') {
            set({
              systemMetrics: {
                timestamp: parsed.timestamp ?? null,
                cpu: parsed.cpu ?? null,
                ram: parsed.ram ?? null,
                disk: parsed.disk ?? null,
                gpu: parsed.gpu ?? null,
              },
            });
            addLog(LOG_TAGS.SYS, `system_metrics: cpu=${parsed?.cpu ?? '-'} ram=${parsed?.ram ?? '-'} disk=${parsed?.disk ?? '-'} gpu=${parsed?.gpu ?? '-'}`, rawVal);
          }
          break;
        }

        case '/dori/nav/command':
          addLog(LOG_TAGS.NAV, `cmd: ${typeof parsed === 'string' ? parsed : JSON.stringify(parsed)}`, rawVal);
          break;

        default:
          addLog(meta.tag, `${meta.label}: ${typeof parsed === 'string' ? parsed.slice(0, 60) : JSON.stringify(parsed).slice(0, 60)}`, rawVal);
      }
    } catch (e) {
      addLog(LOG_TAGS.ERROR, `Parse error on ${topic}: ${e.message}`);
    }
  },
}));
