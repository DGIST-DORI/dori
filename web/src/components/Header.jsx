import { useState } from 'react';
import { LOG_TAGS, useStore } from '../core/store';
import { connectROS, disconnectROS } from '../core/ros';
import { startDemo, stopDemo } from '../core/demo';
import './Header.css';

export default function Header({ onLogoClick, themeMode, onThemeModeChange }) {
  const connected    = useStore(s => s.connected);
  const isDemoMode   = useStore(s => s.isDemoMode);
  const wsUrl        = useStore(s => s.wsUrl);
  const setConnected = useStore(s => s.setConnected);
  const setWsUrl     = useStore(s => s.setWsUrl);
  const addLog       = useStore(s => s.addLog);

  const [urlInput, setUrlInput] = useState(wsUrl);

  function handleConnect() {
    if (connected) {
      disconnectROS(); setConnected(false); addLog(LOG_TAGS.SYS, 'Disconnected from ROS');
    } else {
      stopDemo();
      connectROS(urlInput, {
        onConnect: () => { setConnected(true); addLog(LOG_TAGS.SYS, `Connected → ${urlInput}`); },
        onError:   (e) => addLog(LOG_TAGS.ERROR, `WebSocket error: ${e}`),
        onClose:   () => { setConnected(false); addLog(LOG_TAGS.SYS, 'Connection closed'); },
      });
      setWsUrl(urlInput);
    }
  }

  function handleDemo() {
    if (isDemoMode) stopDemo();
    else { disconnectROS(); setConnected(false); startDemo(); }
  }

  return (
    <header className="hdr">
      {/* Logo — click to go Home */}
      <button className="hdr-logo" onClick={onLogoClick}>
        <span className="hdr-logo-dori">DORI</span>
        <span className="hdr-logo-sep">/</span>
        <span className="hdr-logo-sub">dashboard</span>
      </button>

      <div className="hdr-spacer" />

      <div className="hdr-conn">
        <label className="hdr-theme-wrap">
          <span className="hdr-theme-label">theme</span>
          <select
            className="hdr-theme"
            value={themeMode}
            onChange={e => onThemeModeChange(e.target.value)}
          >
            <option value="light">Light</option>
            <option value="dark">Dark</option>
            <option value="auto">Automatic</option>
          </select>
        </label>

        <input
          className="hdr-url"
          value={urlInput}
          onChange={e => setUrlInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleConnect()}
          disabled={connected || isDemoMode}
          spellCheck={false}
        />
        <button className={`hdr-btn ${connected ? 'connected' : ''}`} onClick={handleConnect}>
          {connected ? '⏏ disconnect' : '⏎ connect'}
        </button>
        <button className={`hdr-btn demo ${isDemoMode ? 'active' : ''}`} onClick={handleDemo}>
          {isDemoMode ? '■ stop demo' : '▶ demo'}
        </button>
      </div>
    </header>
  );
}
