import { useState, useEffect } from 'react';
import Header    from './components/Header';
import Sidebar   from './components/Sidebar';
import HomeTab   from './tabs/HomeTab';
import HRITab    from './tabs/HRITab';
import CubeTab   from './tabs/CubeTab';
import SystemTab from './tabs/SystemTab';
import { useStore, TOPIC_META } from './core/store';
import { subscribeROS } from './core/ros';

import HriIcon       from './assets/icons/icon-hri.svg?react';
import HriActiveIcon from './assets/icons/icon-hri-active.svg?react';
import CubeIcon      from './assets/icons/icon-cube.svg?react';
import SystemIcon    from './assets/icons/icon-system.svg?react';

import './index.css';
import './App.css';

// icon: 기본 아이콘 / iconActive: 선택됐을 때 아이콘 (없으면 icon 그대로)
const TABS = [
  { id: 'hri',    label: 'HRI Monitor', icon: <HriIcon />,    iconActive: <HriActiveIcon />, component: HRITab },
  { id: 'cube',   label: 'Cube Sim',    icon: <CubeIcon />,                                  component: CubeTab },
  { id: 'system', label: 'System',      icon: <SystemIcon />,                                component: SystemTab },
];

export default function App() {
  const [activeTab,       setActiveTab]       = useState('home');
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [themeMode, setThemeMode] = useState(() => localStorage.getItem('theme-mode') || 'auto');

  const connected        = useStore(s => s.connected);
  const handleROSMessage = useStore(s => s.handleROSMessage);

  useEffect(() => {
    if (!connected) return;
    const unsubs = Object.keys(TOPIC_META).map(topic =>
      subscribeROS(topic, undefined, (val) => handleROSMessage(topic, val))
    );
    return () => unsubs.forEach(fn => fn());
  }, [connected, handleROSMessage]);

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

  const ActiveComponent =
    TABS.find(t => t.id === activeTab)?.component ?? HomeTab;

  return (
    <div className={`app ${sidebarExpanded ? 'sb-expanded' : ''}`}>
      <div className="app-sidebar">
        <Sidebar
          expanded={sidebarExpanded}
          onExpand={() => setSidebarExpanded(true)}
          onCollapse={() => setSidebarExpanded(false)}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          tabs={TABS}
        />
      </div>

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
