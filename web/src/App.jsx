import { useState, useEffect } from 'react';
import Header             from './components/Header';
import Sidebar            from './components/Sidebar';
import FloatingWorkspace  from './components/FloatingWorkspace';
import SettingsTab        from './tabs/SettingsTab';
import { useStore, TOPIC_META } from './core/store';
import { fetchTopicDiagnostics, subscribeROS } from './core/ros';
import { createAudioOutputRouter } from './core/audioOutput';
import { PANEL_TREE, findLeaf } from './panelTree';

import './index.css';
import './App.css';

const MOBILE_BP = 768;

export default function App() {
  const [sidebarExpanded,  setSidebarExpanded]  = useState(false);
  const [isOverlaySidebar, setIsOverlaySidebar] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(`(max-width: ${MOBILE_BP}px)`).matches
  );
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(`(max-width: ${MOBILE_BP}px)`).matches
  );
  const [themeMode, setThemeMode] = useState(
    () => localStorage.getItem('theme-mode') || 'auto'
  );

  const connected        = useStore(s => s.connected);
  const handleROSMessage = useStore(s => s.handleROSMessage);
  const setTopicMeta     = useStore(s => s.setTopicMeta);
  const openPanel        = useStore(s => s.openPanel);
  const activeMainView   = useStore(s => s.activeMainView);
  const setActiveMainView = useStore(s => s.setActiveMainView);
  const rosBindingEpoch = useStore(s => s.rosBindingEpoch);
  const audioOutputMode = useStore(s => s.audioOutputMode);
  const executionProfile = useStore(s => s.executionProfile);
  const addLog = useStore(s => s.addLog);
  const setActiveAudioRoute = useStore(s => s.setActiveAudioRoute);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    fetchTopicDiagnostics(Object.keys(TOPIC_META))
      .then(metaMap => {
        if (cancelled) return;
        Object.entries(metaMap).forEach(([topic, meta]) => setTopicMeta(topic, meta));
      })
      .catch(() => {});
    const unsubs = Object.keys(TOPIC_META).map(topic =>
      subscribeROS(topic, undefined, (_, rawMsg) => handleROSMessage(topic, rawMsg))
    );
    return () => { cancelled = true; unsubs.forEach(fn => fn()); };
  }, [connected, handleROSMessage, setTopicMeta, rosBindingEpoch]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => {
      document.documentElement.dataset.theme =
        themeMode === 'auto' ? (mq.matches ? 'dark' : 'light') : themeMode;
    };
    apply();
    localStorage.setItem('theme-mode', themeMode);
    if (themeMode !== 'auto') return;
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [themeMode]);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${MOBILE_BP}px)`);
    const apply = (e) => {
      const mobile = typeof e?.matches === 'boolean' ? e.matches : mq.matches;
      setIsOverlaySidebar(mobile);
      setIsMobile(mobile);
    };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  useEffect(() => {
    if (!connected) return undefined;
    const cleanup = createAudioOutputRouter({
      mode: audioOutputMode,
      executionProfile,
      addLog,
      setActiveAudioRoute,
    });
    return cleanup;
  }, [connected, audioOutputMode, executionProfile, addLog, setActiveAudioRoute]);

  function handlePanelSelect(id) {
    const leaf = findLeaf(PANEL_TREE, id);
    if (!leaf || leaf.placeholder) return;
    openPanel(leaf);
    setActiveMainView('workspace');
    if (isOverlaySidebar) setSidebarExpanded(false);
  }

  function handleSettingsOpen() {
    setActiveMainView(activeMainView === 'settings' ? 'workspace' : 'settings');
    if (isOverlaySidebar) setSidebarExpanded(false);
  }

  function handleSettingsClose() {
    setActiveMainView('workspace');
  }

  return (
    <div className={`app ${sidebarExpanded ? 'sb-expanded' : ''} ${isOverlaySidebar ? 'sb-overlay' : ''}`}>
      <div className="app-sidebar">
        <Sidebar
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
          expanded={sidebarExpanded}
          onExpand={() => setSidebarExpanded(true)}
          onCollapse={() => setSidebarExpanded(false)}
          onSelect={handlePanelSelect}
          onSettingsOpen={handleSettingsOpen}
          tree={PANEL_TREE}
        />
      </div>

      {isOverlaySidebar && sidebarExpanded && (
        <button
          className="app-sidebar-backdrop"
          type="button"
          aria-label="Close sidebar"
          onClick={() => setSidebarExpanded(false)}
        />
      )}

      <div className="app-header">
        <Header
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
          sidebarExpanded={sidebarExpanded}
        />
      </div>

      <main className="app-main">
        {activeMainView === 'settings' ? (
          <SettingsTab
            themeMode={themeMode}
            onThemeModeChange={setThemeMode}
            onClose={handleSettingsClose}
          />
        ) : (
          <FloatingWorkspace isMobile={isMobile} />
        )}
      </main>
    </div>
  );
}
