/**
 * core/demo.js
 * Mock data script for offline development.
 * Injects messages into the store as if they came from ROS.
 *
 * To add new demo events: just push an object to MOCK_SCRIPT.
 */

import { LOG_TAGS, useStore } from './store';

let timers = [];

const MOCK_SCRIPT = [
  { delay: 300,  topic: '/dori/hri/manager_state',
    data: JSON.stringify({ state: 'IDLE', state_elapsed_sec: 0, target_id: null, location_context: '' }) },

  { delay: 1500, topic: '/dori/stt/wake_word_detected', data: true },

  { delay: 1700, topic: '/dori/hri/manager_state',
    data: JSON.stringify({ state: 'LISTENING', state_elapsed_sec: 0, target_id: null }) },

  { delay: 1800, topic: '/dori/tts/text',
    data: '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?' },

  { delay: 2000, topic: '/dori/tts/speaking', data: true },

  { delay: 4200, topic: '/dori/tts/speaking', data: false },
  { delay: 4300, topic: '/dori/tts/done', data: true },

  { delay: 5000, topic: '/dori/hri/persons',
    data: JSON.stringify({
      count: 1, target_id: 3, state: 'tracking',
      detections: [{ track_id: 3, bbox: [120, 80, 320, 400], center_norm: [0.47, 0.5],
                     bbox_area_norm: 0.14, distance_m: 1.8 }]
    }) },

  { delay: 5200, topic: '/dori/hri/tracking_state',
    data: JSON.stringify({ state: 'tracking', target_id: 3, lost_elapsed_sec: 0, last_distance_m: 1.8 }) },

  { delay: 6000, topic: '/dori/hri/gesture',
    data: JSON.stringify({ gesture: 'WAVE', direction: null }) },

  { delay: 6800, topic: '/dori/stt/result',
    data: JSON.stringify({ text: '도서관 어디야', language: 'ko', confidence: 0.92 }) },

  { delay: 6900, topic: '/dori/hri/manager_state',
    data: JSON.stringify({ state: 'RESPONDING', state_elapsed_sec: 0, target_id: 3 }) },

  { delay: 7000, topic: '/dori/llm/query',
    data: JSON.stringify({ user_text: '도서관 어디야', location_context: '공학관 앞' }) },

  { delay: 8400, topic: '/dori/llm/response',
    data: '도서관으로 안내하겠습니다. 직진 후 우회전하세요.' },

  { delay: 8600, topic: '/dori/tts/text',
    data: '도서관으로 안내하겠습니다. 직진 후 우회전하세요.' },

  { delay: 8800, topic: '/dori/tts/speaking', data: true },

  { delay: 10500, topic: '/dori/tts/speaking', data: false },
  { delay: 10600, topic: '/dori/tts/done', data: true },

  { delay: 10800, topic: '/dori/hri/manager_state',
    data: JSON.stringify({ state: 'NAVIGATING', state_elapsed_sec: 0, target_id: 3 }) },

  { delay: 11000, topic: '/dori/nav/command',
    data: JSON.stringify({ action: 'goto', destination: 'library' }) },

  { delay: 13000, topic: '/dori/hri/expression',
    data: JSON.stringify({ expression: 'SATISFIED', confidence: 0.78 }) },

  { delay: 15000, topic: '/dori/hri/tracking_state',
    data: JSON.stringify({ state: 'lost', target_id: 3, lost_elapsed_sec: 2.1 }) },

  { delay: 15200, topic: '/dori/hri/manager_state',
    data: JSON.stringify({ state: 'IDLE', state_elapsed_sec: 0, target_id: null }) },
];

export function startDemo() {
  stopDemo();
  const { handleROSMessage, addLog, setDemoMode } = useStore.getState();
  setDemoMode(true);
  addLog(LOG_TAGS.DEMO, '── DEMO MODE STARTED ──');

  timers = MOCK_SCRIPT.map(({ delay, topic, data }) =>
    setTimeout(() => handleROSMessage(topic, data), delay)
  );
}

export function stopDemo() {
  timers.forEach(clearTimeout);
  timers = [];
  useStore.getState().setDemoMode(false);
}
