import { useStore } from '../../core/store';
import { useState } from 'react';
import { Zap, Radio, RefreshCw, Circle } from 'lucide-react';
import './EmotionPalettePanel.css';

// ── Emotion configuration ─────────────────────────────────────────────────────
const EMOTION_CONFIG = {
  CALM:      { label: 'Calm' },
  ATTENTIVE: { label: 'Attentive' },
  THINKING:  { label: 'Thinking' },
  HAPPY:     { label: 'Happy' },
  CURIOUS:   { label: 'Curious' },
  SHY:       { label: 'Shy' },
  SURPRISED: { label: 'Surprised' },
  BUMPED:    { label: 'Bumped' },
  RELIEVED:  { label: 'Relieved' },
  SLEEPY:    { label: 'Sleepy' },
};

function EmotionPalettePanel() {
  const emotion       = useStore(s => s.emotion);
  const emotionSource = useStore(s => s.emotionSource);
  const hriState      = useStore(s => s.hriState);

  const [statusOpen, setStatusOpen] = useState(emotionSource === 'override');
  const [search,     setSearch]     = useState('');

  const filteredEmotions = Object.entries(EMOTION_CONFIG).filter(([key, cfg]) =>
    !search.trim() ||
    cfg.label.toLowerCase().includes(search.trim().toLowerCase()) ||
    key.toLowerCase().includes(search.trim().toLowerCase())
  );

  const sourceIcon =
    emotionSource === 'override' ? <Zap    size={10} strokeWidth={2} /> :
    emotionSource === 'ros'      ? <Radio  size={10} strokeWidth={2} /> :
                                   <RefreshCw size={10} strokeWidth={2} />;

  return (
    <div className="face-palette-root">

      {/* Search */}
      <div className="face-palette-search-wrap">
        <input
          type="text"
          className="input-search"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search emotions…"
        />
      </div>

      {/* Palette — scrollable */}
      <div className="face-palette-scroll">
        <div className="face-palette">
          {filteredEmotions.length === 0 ? (
            <div className="empty-state">No results</div>
          ) : filteredEmotions.map(([key, cfg]) => (
            <button
              key={key}
              className={`face-palette-btn ${emotion === key ? 'active' : ''}`}
              onClick={() => { useStore.getState().setEmotionOverride(key); setStatusOpen(true); }}
            >
              <span className="face-palette-dot" />
              <span className="face-palette-name">{cfg.label}</span>
              {emotion === key && (
                <span className="face-palette-active-mark">
                  <Circle size={6} fill="currentColor" strokeWidth={0} />
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Status — collapsible */}
      <div className="face-status-section">
        <button
          className={`face-status-toggle ${emotionSource === 'override' ? 'override-active' : ''}`}
          onClick={() => setStatusOpen(o => !o)}
        >
          <span>Status</span>
          <span className="face-status-chevron">{statusOpen ? '▾' : '▸'}</span>
        </button>

        <div className={`face-status-body ${statusOpen ? 'open' : ''}`}>
          <div className="face-status-list">
            <div className="face-status-row">
              <span className="face-status-key">Emotion</span>
              <span className="face-status-val">{emotion}</span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">Source</span>
              <span className={`face-status-val face-source-${emotionSource} face-source-icon`}>
                {sourceIcon} {emotionSource}
              </span>
            </div>
            <div className="face-status-row">
              <span className="face-status-key">HRI State</span>
              <span className="face-status-val">{hriState}</span>
            </div>
            {emotionSource === 'override' && (
              <button
                className="face-clear-override"
                onClick={() => useStore.getState().clearEmotionOverride()}
              >
                Clear Override
              </button>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

export default EmotionPalettePanel;
export { EmotionPalettePanel };
