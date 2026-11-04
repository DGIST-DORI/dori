// Describe TTS output without retaining MP3 payloads in the dashboard log.
export function describeTtsEvent(event) {
  if (!event || !['tts_text', 'remote_audio'].includes(event.event_type)) return null;
  const text = typeof event.text === 'string' ? event.text : '';
  if (event.event_type === 'tts_text') {
    return { text, message: `speak: "${text}"`, raw: event };
  }
  return {
    text,
    message: text ? `speak: "${text}"` : 'remote_audio: 스마트폰으로 TTS 음성 전달',
    raw: {
      event_type: 'remote_audio', output: 'phone',
      id: event.id, timestamp: event.timestamp, text,
      audio_bytes: event.audio_bytes,
    },
  };
}
