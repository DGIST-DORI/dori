export const DEFAULT_EMOTION = 'CALM';

export const EMOTION_KEYS = Object.freeze([
  'CALM',
  'ATTENTIVE',
  'THINKING',
  'HAPPY',
  'CURIOUS',
  'SHY',
  'SURPRISED',
  'RELIEVED',
  'SLEEPY',
]);

// State->emotion rule table (extend this map when new HRI states are added).
export const STATE_TO_EMOTION = Object.freeze({
  IDLE: 'CALM',
  LISTENING: 'ATTENTIVE',
  RESPONDING: 'THINKING',
  NAVIGATING: 'HAPPY',
  INTERACTION: 'THINKING',
  GUIDING: 'HAPPY',
  ARRIVED: 'HAPPY',
  USER_LOST_CONFIRM: 'CURIOUS',
  ACCESS_HELP: 'CURIOUS',
  WAIT_MIC_RETURN: 'ATTENTIVE',
  CANCELED: 'CALM',
  ERROR: 'SURPRISED',
});

export const normalizeEmotionKey = (emotion) => {
  const key = typeof emotion === 'string' ? emotion.trim().toUpperCase() : '';
  return EMOTION_KEYS.includes(key) ? key : null;
};

export const resolveEmotionFromState = (hriState) => (
  STATE_TO_EMOTION[hriState] || DEFAULT_EMOTION
);

/**
 * Emotion priority policy for incoming runtime signals:
 * 1) Manual palette override (_emotionOverride) has the highest priority.
 * 2) /dori/hri/emotion can set emotion when payload key is valid.
 * 3) Invalid/missing ROS emotion falls back to state-derived emotion.
 */
export const resolveROSOrStateEmotion = (payload, hriState) => {
  const normalized = normalizeEmotionKey(payload?.emotion);
  if (normalized) {
    return { emotion: normalized, source: 'ros' };
  }

  return {
    emotion: resolveEmotionFromState(hriState),
    source: 'state',
  };
};
