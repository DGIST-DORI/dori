export const EXECUTION_PROFILES = Object.freeze({
  ROBOT: 'robot',
  SIM: 'sim',
});

export const AUDIO_OUTPUT_MODES = Object.freeze({
  BROWSER_TTS: 'browser_tts',
  ROS_AUDIO: 'ros_audio',
});

export const TOPIC_PROFILES = Object.freeze({
  robot: {
    sttInputTopic: 'stt/audio_input',
    visionInputTopic: 'perception/vision/image/compressed',
    ttsTextTopic: 'tts/text',
    rosAudioStreamTopic: 'audio/output',
  },
  sim: {
    sttInputTopic: 'stt/audio_input',
    visionInputTopic: 'perception/vision/image/compressed',
    ttsTextTopic: 'tts/text',
    rosAudioStreamTopic: 'audio/output',
  },
});

export function resolveProfileTopics(profile) {
  return TOPIC_PROFILES[profile] || TOPIC_PROFILES.robot;
}
