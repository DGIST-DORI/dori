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
  '/dori/hri/expression':          { tag: LOG_TAGS.EXPR,    label: 'Expression' },
  '/dori/hri/expression_command':  { tag: LOG_TAGS.EXPR,    label: 'Expression Cmd' },
  '/dori/follow/target_offset':    { tag: LOG_TAGS.TRACK,   label: 'Follow Offset' },
  '/dori/nav/command':             { tag: LOG_TAGS.NAV,     label: 'Nav Command' },
  '/dori/landmark/context':        { tag: LOG_TAGS.NAV,     label: 'Landmark Context' },
};

const MAX_LOG = 300;

// ─── Store ───────────────────────────────────────────────────────────────────
export const useStore = create((set, get) => ({

  // ── Connection ──────────────────────────────────────────────────────────
  connected: false,
  isDemoMode: false,
  wsUrl: 'ws://localhost:9090',

  setConnected: (v) => set({ connected: v }),
  setDemoMode:  (v) => set({ isDemoMode: v }),
  setWsUrl:     (v) => set({ wsUrl: v }),

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

  // ── Event Log ────────────────────────────────────────────────────────────
  // Each entry: { id, ts, tag, text, raw? }
  log: [],

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

  // ── Topic Hz tracking ───────────────────────────────────────────────────
  topicHz: {},   // topic -> number (msgs/sec, rolling 2s)
  _topicTimes: {}, // topic -> timestamp[]

  recordTopicHit: (topic) => {
    const now = Date.now();
    const times = [...(get()._topicTimes[topic] || []), now]
      .filter(t => now - t < 2000);
    set(s => ({
      _topicTimes: { ...s._topicTimes, [topic]: times },
      topicHz:     { ...s.topicHz, [topic]: +(times.length / 2).toFixed(1) },
    }));
  },

  // ── Master message handler ───────────────────────────────────────────────
  handleROSMessage: (topic, rawVal) => {
    const { addLog, recordTopicHit } = get();
    recordTopicHit(topic);

    let parsed = rawVal;
    if (typeof rawVal === 'string') {
      try { parsed = JSON.parse(rawVal); } catch { parsed = rawVal; }
    }

    const meta = TOPIC_META[topic] || { tag: LOG_TAGS.SYS, label: topic };

    // ── Per-topic handling ──────────────────────────────────────────────
    try {
      switch (topic) {

        case '/dori/hri/manager_state': {
          const d = parsed;
          set({
            hriState: d.state || 'IDLE',
            hriStateElapsed: d.state_elapsed_sec ?? 0,
            hriTargetId: d.target_id ?? null,
            hriLocationContext: d.location_context || '',
          });
          addLog(LOG_TAGS.STATE, `→ ${d.state}  [${(d.state_elapsed_sec ?? 0).toFixed(1)}s]`, rawVal);
          break;
        }

        case '/dori/stt/wake_word_detected':
          if (rawVal === true || parsed === true) {
            addLog(LOG_TAGS.WAKE, 'Wake word detected!', rawVal);
          }
          break;

        case '/dori/stt/result': {
          const text = parsed?.text || parsed;
          set({ lastSttText: text });
          addLog(LOG_TAGS.STT, `"${text}"  [conf: ${parsed?.confidence?.toFixed(2) ?? '?'}]`, rawVal);
          break;
        }

        case '/dori/llm/query':
          addLog(LOG_TAGS.LLM, `query: "${parsed?.user_text || parsed}"`, rawVal);
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
          set({ ttsActive: !!parsed });
          if (parsed) addLog(LOG_TAGS.TTS, 'TTS speaking…', rawVal);
          break;

        case '/dori/tts/done':
          if (parsed) addLog(LOG_TAGS.TTS, 'TTS done', rawVal);
          break;

        case '/dori/hri/tracking_state':
          set({ trackingState: parsed });
          if (parsed?.state === 'lost') addLog(LOG_TAGS.TRACK, `Target lost (id:${parsed?.target_id})`, rawVal);
          break;

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

        case '/dori/landmark/context':
          set({ hriLocationContext: typeof parsed === 'string' ? parsed : JSON.stringify(parsed) });
          break;

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
