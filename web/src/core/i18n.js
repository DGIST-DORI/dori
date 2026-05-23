/**
 * core/i18n.js
 * Internationalization — Korean / English
 *
 * Usage:
 *   import { t, useI18n } from './i18n';
 *   const { t } = useI18n();   // reactive (re-renders on lang change)
 *   t('sidebar.hri')           // → 'HRI' or 'HRI'
 */

import { useStore } from './store';

// ── Language detection ────────────────────────────────────────────────────────

export const SUPPORTED_LANGS = ['auto', 'ko', 'en'];
export const LANG_LABELS = { auto: 'Auto', ko: '한국어', en: 'English' };

/**
 * Detect browser/OS preferred language.
 * Returns 'ko' or 'en'. Falls back to 'en'.
 */
export function detectBrowserLang() {
  try {
    const langs = navigator.languages?.length
      ? navigator.languages
      : [navigator.language || navigator.userLanguage || ''];
    for (const lang of langs) {
      const base = lang.split('-')[0].toLowerCase();
      if (base === 'ko') return 'ko';
      if (base === 'en') return 'en';
    }
  } catch {
    // SSR / old browser
  }
  return 'en';
}

/**
 * Resolve effective language from the stored preference.
 * 'auto' → detectBrowserLang()
 */
export function resolveEffectiveLang(stored) {
  if (stored === 'ko') return 'ko';
  if (stored === 'en') return 'en';
  return detectBrowserLang(); // 'auto' or unknown
}

// ── Translation strings ───────────────────────────────────────────────────────

const TRANSLATIONS = {
  en: {
    // Sidebar categories
    'sidebar.hri': 'HRI',
    'sidebar.navigation': 'Navigation',
    'sidebar.control': 'Control',
    'sidebar.perception': 'Perception & Intelligence',
    'sidebar.system': 'System',

    // Sidebar subcategories
    'sidebar.hri.voice': 'Voice',
    'sidebar.hri.state': 'State',
    'sidebar.hri.conversation': 'Conversation',
    'sidebar.hri.face': 'Face',
    'sidebar.nav.map': 'Map',
    'sidebar.ctrl.cube': 'Cube',
    'sidebar.perc.vision': 'Vision',
    'sidebar.perc.llm': 'LLM',
    'sidebar.perc.knowledge': 'Knowledge',

    // Sidebar leaves
    'panel.stt': 'STT Test',
    'panel.wakeword': 'Wake Word',
    'panel.tts': 'TTS Inject',
    'panel.state-monitor': 'State Monitor',
    'panel.conversation': 'Conversation',
    'panel.face-display': 'Face Display',
    'panel.face-palette': 'Emotion Palette',
    'panel.campus-map': 'Campus Map',
    'panel.cube-3d': '3D View',
    'panel.cube-rotation': 'Rotation Control',
    'panel.cube-pieces': 'Piece Table',
    'panel.vision-test': 'Vision Test',
    'panel.llm-inject': 'LLM Inject',
    'panel.menu-parser': 'Menu Parser',
    'panel.index-builder': 'Index Builder',
    'panel.campus-crawler': 'Campus Crawler',
    'panel.knowledge-docs': 'Document Browser',
    'panel.knowledge-building': 'Building Editor',
    'panel.sys-connection': 'Connection',
    'panel.sys-topics': 'Topic Diagnostics',
    'panel.sys-metrics': 'Metrics',
    'panel.event-log': 'Event Log',
    'panel.sys-topic-publisher': 'Topic Publisher',
    'panel.sys-deploy': 'Deploy Status',
    'panel.settings': 'Settings',

    // Sidebar UI
    'sidebar.search.placeholder': 'Search panels...',
    'sidebar.search.empty': 'No panels found',
    'sidebar.open': 'Open sidebar',
    'sidebar.close': 'Close sidebar',
    'sidebar.soon': 'soon',

    // Header
    'header.connect': '⏎ connect',
    'header.disconnect': '⏏ disconnect',
    'header.connecting': 'connecting...',
    'header.demo.start': '▶ demo',
    'header.demo.stop': '■ stop demo',

    // Status
    'status.connected': 'LIVE',
    'status.demo': 'DEMO',
    'status.offline': 'OFF',

    // Home tab
    'home.title': 'DORI',
    'home.sub': 'Dual-shell Omnidirectional Robot for Interaction',
    'home.org': 'DGIST UGRP 2026',
    'home.card.ros': 'ROS Connection',
    'home.card.hri': 'HRI State',
    'home.card.log': 'Log Entries',
    'home.status.connected': 'CONNECTED',
    'home.status.demo': 'DEMO MODE',
    'home.status.offline': 'OFFLINE',
    'home.hint.1': '← Select a tab from the sidebar, or connect to ROS in the top right.',
    'home.hint.2': 'To test without ROS, press the ▶ demo button.',

    // Settings panel
    'settings.title': 'Settings',
    'settings.section.appearance': 'Appearance',
    'settings.section.language': 'Language',
    'settings.theme.label': 'Theme',
    'settings.theme.light': 'Light',
    'settings.theme.dark': 'Dark',
    'settings.theme.auto': 'Automatic',
    'settings.lang.label': 'Interface Language',
    'settings.lang.ko': '한국어',
    'settings.lang.en': 'English',
    'settings.lang.auto': 'Automatic',
    'settings.lang.detected': 'Detected',
    'settings.section.connection': 'Connection',
    'settings.ws.label': 'ROS WebSocket URL',
    'settings.ws.hint': 'Default: ws://[Robot IP]:9090',

    // HRI / Perception panel texts
    'panel.tts.placeholder': 'Text for robot speech (e.g. Hello, I am DORI.)',
    'panel.stt.placeholder': 'Enter a test utterance (e.g. Where is the library?)',
    'panel.stt.hint': 'Mic audio is published as wav_pcm16 (16 kHz mono) to the configured STT input topic. Set voice.launch.py stt_audio_input_mode=topic to run the real STT pipeline test.',
    'panel.wakeword.hint': 'HRI Manager only reacts in IDLE. You can test the LISTENING → RESPONDING → IDLE cycle.',
    'panel.llm.query.placeholder': 'Question (e.g. Where is the student cafeteria?)',
    'panel.llm.location.placeholder': 'e.g. In front of Building E7',
    'panel.vision.hint': 'Frames are published as sensor_msgs/msg/CompressedImage. If person detection, gesture, or expression nodes subscribe, you can run real-time vision tests.',
  },

  ko: {
    // Sidebar categories
    'sidebar.hri': 'HRI',
    'sidebar.navigation': '주행',
    'sidebar.control': '제어',
    'sidebar.perception': '인지 & 지능',
    'sidebar.system': '시스템',

    // Sidebar subcategories
    'sidebar.hri.voice': '음성',
    'sidebar.hri.state': '상태',
    'sidebar.hri.conversation': '대화',
    'sidebar.hri.face': '얼굴',
    'sidebar.nav.map': '지도',
    'sidebar.ctrl.cube': '큐브',
    'sidebar.perc.vision': '비전',
    'sidebar.perc.llm': 'LLM',
    'sidebar.perc.knowledge': '지식 베이스',

    // Sidebar leaves
    'panel.stt': 'STT 테스트',
    'panel.wakeword': '웨이크 워드',
    'panel.tts': 'TTS 주입',
    'panel.state-monitor': '상태 모니터',
    'panel.conversation': '대화 기록',
    'panel.face-display': '얼굴 표시',
    'panel.face-palette': '감정 팔레트',
    'panel.campus-map': '캠퍼스 지도',
    'panel.cube-3d': '3D 뷰',
    'panel.cube-rotation': '회전 제어',
    'panel.cube-pieces': '조각 테이블',
    'panel.vision-test': '비전 테스트',
    'panel.llm-inject': 'LLM 주입',
    'panel.menu-parser': '메뉴 파서',
    'panel.index-builder': '인덱스 빌더',
    'panel.campus-crawler': '캠퍼스 크롤러',
    'panel.knowledge-docs': '문서 브라우저',
    'panel.knowledge-building': '건물 편집기',
    'panel.sys-connection': '연결 정보',
    'panel.sys-topics': '토픽 진단',
    'panel.sys-metrics': '시스템 지표',
    'panel.event-log': '이벤트 로그',
    'panel.sys-topic-publisher': '토픽 퍼블리셔',
    'panel.sys-deploy': '배포 상태',
    'panel.settings': '설정',

    // Sidebar UI
    'sidebar.search.placeholder': '패널 검색...',
    'sidebar.search.empty': '패널을 찾을 수 없습니다',
    'sidebar.open': '사이드바 열기',
    'sidebar.close': '사이드바 닫기',
    'sidebar.soon': '준비중',

    // Header
    'header.connect': '⏎ 연결',
    'header.disconnect': '⏏ 연결 해제',
    'header.connecting': '연결 중...',
    'header.demo.start': '▶ 데모',
    'header.demo.stop': '■ 데모 중지',

    // Status
    'status.connected': 'LIVE',
    'status.demo': 'DEMO',
    'status.offline': 'OFF',

    // Home tab
    'home.title': 'DORI',
    'home.sub': 'Dual-shell Omnidirectional Robot for Interaction',
    'home.org': 'DGIST UGRP 2026',
    'home.card.ros': 'ROS 연결',
    'home.card.hri': 'HRI 상태',
    'home.card.log': '로그 항목',
    'home.status.connected': '연결됨',
    'home.status.demo': '데모 모드',
    'home.status.offline': '오프라인',
    'home.hint.1': '← 사이드바에서 탭을 선택하거나, 우측 상단에서 ROS에 연결하세요.',
    'home.hint.2': 'ROS 없이 테스트하려면 ▶ 데모 버튼을 누르세요.',

    // Settings panel
    'settings.title': '설정',
    'settings.section.appearance': '화면',
    'settings.section.language': '언어',
    'settings.theme.label': '테마',
    'settings.theme.light': '라이트',
    'settings.theme.dark': '다크',
    'settings.theme.auto': '자동',
    'settings.lang.label': '인터페이스 언어',
    'settings.lang.ko': '한국어',
    'settings.lang.en': 'English',
    'settings.lang.auto': '자동',
    'settings.lang.detected': '감지됨',
    'settings.section.connection': '연결',
    'settings.ws.label': 'ROS WebSocket URL',
    'settings.ws.hint': '기본값: ws://[로봇 IP]:9090',

    // HRI / Perception panel texts
    'panel.tts.placeholder': '로봇이 말할 텍스트 (예: 안녕하세요, 도리입니다.)',
    'panel.stt.placeholder': '테스트할 발화를 입력하세요 (예: 도서관 어디야)',
    'panel.stt.hint': '마이크 오디오는 설정된 STT 입력 토픽으로 wav_pcm16(16kHz mono) 포맷으로 publish됩니다. voice.launch.py에서 stt_audio_input_mode=topic으로 설정하면 실제 STT 파이프라인 테스트가 가능합니다.',
    'panel.wakeword.hint': 'HRI Manager가 IDLE일 때만 반응합니다. LISTENING → RESPONDING → IDLE 사이클을 테스트할 수 있습니다.',
    'panel.llm.query.placeholder': '질문 (예: 학생식당 어디에 있어요?)',
    'panel.llm.location.placeholder': '예: E7 건물 앞',
    'panel.vision.hint': '프레임은 sensor_msgs/msg/CompressedImage로 publish됩니다. person_detection, gesture, expression 노드가 구독 중이라면 실시간 비전 테스트가 가능합니다.',
  },
};

// ── Translate function ────────────────────────────────────────────────────────

/**
 * Translate a key for the given effective language.
 * Falls back to English if key is missing.
 * Falls back to the key itself if missing from both.
 */
export function translateKey(key, effectiveLang) {
  const lang = effectiveLang === 'ko' ? 'ko' : 'en';
  return TRANSLATIONS[lang]?.[key] ?? TRANSLATIONS['en']?.[key] ?? key;
}

/**
 * Get both Korean and English translations for a key.
 * If key is missing in both languages, both fields return fallback text.
 */
export function translateKeyBoth(key, fallback = '') {
  const en = translateKey(key, 'en');
  const ko = translateKey(key, 'ko');
  const hasAnyTranslation = en !== key || ko !== key;
  if (!hasAnyTranslation) return { en: fallback, ko: fallback };
  return {
    en: en === key ? fallback : en,
    ko: ko === key ? fallback : ko,
  };
}

/**
 * React hook — returns a `t(key)` function that re-renders when language changes.
 */
export function useI18n() {
  const langPref = useStore(s => s.langPref);
  const effectiveLang = resolveEffectiveLang(langPref);

  const t = (key) => translateKey(key, effectiveLang);
  return { t, effectiveLang, langPref };
}

/**
 * Non-reactive translate — for use outside React components.
 * Reads current store state directly.
 */
export function t(key) {
  const langPref = useStore.getState().langPref;
  const effectiveLang = resolveEffectiveLang(langPref);
  return translateKey(key, effectiveLang);
}
