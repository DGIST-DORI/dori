import { useState, useEffect } from 'react';
import Header    from './components/Header';
import Sidebar   from './components/Sidebar';
import HomeTab   from './tabs/HomeTab';
import FaceTab   from './tabs/FaceTab';
import HRITab    from './tabs/HRITab';
import CubeTab   from './tabs/CubeTab';
import SystemTab from './tabs/SystemTab';
import { useStore, TOPIC_META } from './core/store';
import { fetchTopicDiagnostics, subscribeROS } from './core/ros';

import HriIcon       from './assets/icons/icon-hri.svg?react';
import FaceIcon      from './assets/icons/icon-face.svg?react';
import FaceActiveIcon from './assets/icons/icon-face-active.svg?react';
import CubeIcon      from './assets/icons/icon-cube.svg?react';
import SystemIcon    from './assets/icons/icon-system.svg?react';

import './index.css';
import './App.css';

// icon: 기본 아이콘 / iconActive: 선택됐을 때 아이콘 (없으면 icon 그대로)
const TABS = [
  { id: 'face',   label: 'Face Display', icon: <FaceIcon />,  iconActive: <FaceActiveIcon />, component: FaceTab },
  { id: 'hri',    label: 'HRI Monitor',  icon: <HriIcon />,                                   component: HRITab },
  { id: 'cube',   label: 'Cube Sim',     icon: <CubeIcon />,                                  component: CubeTab },
  { id: 'system', label: 'System',       icon: <SystemIcon />,                                component: SystemTab },
];

export default function App() {
  const [activeTab,       setActiveTab]       = useState('home');
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [isOverlaySidebar, setIsOverlaySidebar] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
  );
  const [themeMode, setThemeMode] = useState(() => localStorage.getItem('theme-mode') || 'auto');

  const connected        = useStore(s => s.connected);
  const handleROSMessage = useStore(s => s.handleROSMessage);
  const setTopicMeta = useStore(s => s.setTopicMeta);

  useEffect(() => {
    if (!connected) return;

    let cancelled = false;
    fetchTopicDiagnostics(Object.keys(TOPIC_META))
      .then((metaMap) => {
        if (cancelled) return;
        Object.entries(metaMap).forEach(([topic, meta]) => setTopicMeta(topic, meta));
      })
      .catch(() => {
        // rosapi may be unavailable; diagnostics panel will show N/A for metadata.
      });

    const unsubs = Object.keys(TOPIC_META).map(topic =>
      subscribeROS(topic, undefined, (val, rawMsg) => handleROSMessage(topic, rawMsg ?? val))
    );
    return () => {
      cancelled = true;
      unsubs.forEach(fn => fn());
    };
  }, [connected, handleROSMessage, setTopicMeta]);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const applyTheme = () => {
      const resolvedTheme = themeMode === 'auto'
        ? (mediaQuery.matches ? 'dark' : 'light')
        : themeMode;
      document.documentElement.dataset.theme = resolvedTheme;
    };

    applyTheme();
    localStorage.setItem('theme-mode', themeMode);

    if (themeMode !== 'auto') return undefined;

    mediaQuery.addEventListener('change', applyTheme);
    return () => mediaQuery.removeEventListener('change', applyTheme);
  }, [themeMode]);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 768px)');

    const applySidebarMode = (event) => {
      const isMobile = typeof event?.matches === 'boolean' ? event.matches : mediaQuery.matches;
      setIsOverlaySidebar(isMobile);
    };

    applySidebarMode();
    mediaQuery.addEventListener('change', applySidebarMode);
    return () => mediaQuery.removeEventListener('change', applySidebarMode);
  }, []);

  const ActiveComponent =
    TABS.find(t => t.id === activeTab)?.component ?? HomeTab;

  function handleTabChange(nextTab) {
    setActiveTab(nextTab);
    if (isOverlaySidebar) {
      setSidebarExpanded(false);
    }
  }

  return (
    <div className={`app ${sidebarExpanded ? 'sb-expanded' : ''} ${isOverlaySidebar ? 'sb-overlay' : ''}`}>
      <div className="app-sidebar">
        <Sidebar
          expanded={sidebarExpanded}
          onExpand={() => setSidebarExpanded(true)}
          onCollapse={() => setSidebarExpanded(false)}
          activeTab={activeTab}
          onTabChange={handleTabChange}
          tabs={TABS}
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
          onLogoClick={() => setActiveTab('home')}
          themeMode={themeMode}
          onThemeModeChange={setThemeMode}
        />
      </div>

      <main className="app-main">
        <ActiveComponent />
      </main>
    </div>
  );
}
