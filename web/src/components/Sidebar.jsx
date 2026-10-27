import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../core/store';
import { translateKeyBoth, useI18n } from '../core/i18n';
import { filterTree } from '../panelTree';
import DoriLogoIconMono  from '../assets/logo/logo-icon-mono.svg?react';
import DoriLogoIconColor from '../assets/logo/logo-icon-color.svg?react';
import DoriLogoText      from '../assets/logo/logo-text.svg?react';
import DoriLogoTextDark  from '../assets/logo/logo-text-dark.svg?react';
import CloseIcon         from '../assets/icons/icon-close.svg?react';
import SearchIcon        from '../assets/icons/icon-search.svg?react';
import SettingsIcon      from '../assets/icons/icon-settings.svg?react';
import './Sidebar.css';

// ── Sub-components ────────────────────────────────────────────────────────────

function LeafItem({ node, onSelect, expanded }) {
  const [flashing, setFlashing] = useState(false);

  function handleClick() {
    if (node.placeholder) return;
    setFlashing(true);
    setTimeout(() => setFlashing(false), 220);
    onSelect(node.id);
  }

  return (
    <button
      className={`sb-leaf ${node.placeholder ? 'placeholder' : ''} ${flashing ? 'flash' : ''}`}
      onClick={handleClick}
      title={!expanded ? node.label : undefined}
      disabled={node.placeholder}
    >
      {expanded && (
        <span className="sb-leaf-label">
          {node.label}
          {node.placeholder && <span className="sb-placeholder-tag">{node._soonLabel || 'soon'}</span>}
        </span>
      )}
      {!expanded && <span className="sb-tooltip">{node.label}{node.placeholder ? ` (${node._soonLabel || 'soon'})` : ''}</span>}
    </button>
  );
}

function SubcategoryBlock({ node, onSelect, expanded, searchActive }) {
  const [open, setOpen] = useState(false);
  const isOpen = searchActive ? true : open;

  if (!node.label) {
    return (
      <div className="sb-flat-group">
        {node.children.map(leaf => (
          <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
        ))}
      </div>
    );
  }

  return (
    <div className={`sb-subcategory ${isOpen ? 'open' : ''}`}>
      {expanded && (
        <button className="sb-subcat-header" onClick={() => !searchActive && setOpen(o => !o)}>
          {node.icon && <span className="sb-subcat-icon">{node.icon}</span>}
          <span className="sb-subcat-label">{node.label}</span>
          <span className="sb-subcat-chevron">▾</span>
        </button>
      )}
      <div className="sb-subcat-leaves">
        <div className="sb-subcat-leaves-inner">
          {node.children.map(leaf => (
            <LeafItem key={leaf.id} node={leaf} onSelect={onSelect} expanded={expanded} />
          ))}
        </div>
      </div>
    </div>
  );
}

function CategoryBlock({
  node,
  onSelect,
  expanded,
  searchActive,
  onExpandSidebar,
  open,
  onToggleOpen,
  onOpenFromCollapsed,
}) {
  const isOpen = searchActive ? true : open;

  function handleHeaderClick() {
    if (!expanded) {
      onOpenFromCollapsed(node.id);
      onExpandSidebar();
      return;
    }
    if (!searchActive) onToggleOpen(node.id);
  }

  return (
    <div className={`sb-category ${isOpen ? 'open' : ''}`}>
      <button
        className="sb-cat-header"
        onClick={handleHeaderClick}
        title={!expanded ? node.label : undefined}
      >
        {node.icon && <span className="sb-cat-icon">{node.icon}</span>}
        {expanded && (
          <>
            <span className="sb-cat-label">{node.label}</span>
            <span className="sb-cat-chevron">▾</span>
          </>
        )}
        {!expanded && <span className="sb-tooltip">{node.label}</span>}
      </button>

      {expanded && (
        <div className="sb-cat-body">
          <div className="sb-cat-body-inner">
            {node.children.map(sub => (
              <SubcategoryBlock
                key={sub.id}
                node={sub}
                onSelect={onSelect}
                expanded={expanded}
                searchActive={searchActive}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Sidebar ──────────────────────────────────────────────────────────────

export default function Sidebar({
  themeMode,
  expanded,
  onExpand,
  onCollapse,
  activeId,
  onSelect,
  tree,
  onSettingsOpen,
}) {
  const { t } = useI18n();
  const connected  = useStore(s => s.connected);
  const isDemoMode = useStore(s => s.isDemoMode);

  const statusLabel = connected
    ? t('status.connected')
    : isDemoMode
      ? t('status.demo')
      : t('status.offline');
  const statusClass = connected ? 'connected' : isDemoMode ? 'demo' : '';

  // Resolve dark/light for logo variant
  const [autoIsDark, setAutoIsDark] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  useEffect(() => {
    if (themeMode !== 'auto') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = e => setAutoIsDark(e.matches);
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [themeMode]);

  const [query,        setQuery]        = useState('');
  const pendingFocus = useRef(false);
  const [openCategoryMap, setOpenCategoryMap] = useState({});
  const searchInputRef = useRef(null);
  const searchActive   = query.trim().length > 0;

  // Build a translated version of the tree for display
  // The tree nodes themselves carry their own labels; we remap them with i18n keys.
  const translatedTree = useMemo(() => {
    function getNodeI18nKey(node) {
      return (node.component || node.placeholder)
        ? `panel.${node.id}`
        : `sidebar.${node.id.replace(/-/g, '.')}`;
    }

    function buildSearchTexts(currentLabel, originalLabel, i18nKey) {
      const { ko, en } = translateKeyBoth(i18nKey, originalLabel || currentLabel || '');
      return [
        currentLabel,
        originalLabel,
        ko,
        en,
      ].filter(Boolean);
    }

    function translateNode(node) {
      const i18nKey = getNodeI18nKey(node);
      const originalLabel = node.label;
      if (node.component || node.placeholder) {
        const translatedLabel = t(i18nKey) || originalLabel;
        return {
          ...node,
          label: translatedLabel,
          _soonLabel: t('sidebar.soon'),
          searchTexts: buildSearchTexts(translatedLabel, originalLabel, i18nKey),
        };
      }
      // Category or subcategory — try specific i18n key, fall back to original label
      const translatedByKey = t(i18nKey);
      const translatedLabel = translatedByKey !== i18nKey ? translatedByKey : originalLabel;
      return {
        ...node,
        label: translatedLabel,
        searchTexts: buildSearchTexts(translatedLabel, originalLabel, i18nKey),
        children: node.children ? node.children.map(translateNode) : undefined,
      };
    }
    return tree.map(translateNode);
  }, [tree, t]);

  const visibleTree = useMemo(() => filterTree(translatedTree, query), [translatedTree, query]);

  useEffect(() => {
    if (expanded && pendingFocus.current) {
      searchInputRef.current?.focus();
      pendingFocus.current = false;

    }
  }, [expanded]);

  const isDark = themeMode === 'dark' || (themeMode === 'auto' && autoIsDark);
  const LogoText = isDark ? DoriLogoTextDark : DoriLogoText;

  function handleToggleCategory(categoryId) {
    setOpenCategoryMap(prev => ({ ...prev, [categoryId]: !prev[categoryId] }));
  }

  function handleOpenFromCollapsed(categoryId) {
    setOpenCategoryMap({ [categoryId]: true });
  }

  return (
    <aside className={`sidebar ${expanded ? 'expanded' : 'collapsed'}`}>

      {/* ── Top cell ── */}
      <div className="sb-top">
        {expanded ? (
          <>
            <div className="sb-logo">
              <div className="sb-logo-anchor">
                <DoriLogoIconColor className="sb-icon-svg is-expanded-logo" aria-hidden="true" />
              </div>
              <LogoText className="sb-logo-text-svg" aria-label="DORI" />
            </div>
            <button
              className="sb-close"
              onClick={e => { e.stopPropagation(); onCollapse(); }}
              title={t('sidebar.close')}
            >
              <CloseIcon />
            </button>
          </>
        ) : (
          <button
            className="sb-open"
            onClick={e => { e.stopPropagation(); onExpand(); }}
            aria-label={t('sidebar.open')}
          >
            <div className="sb-logo-anchor">
              <DoriLogoIconMono className="sb-icon-svg is-collapsed-logo" />
            </div>
            <span className="sb-tooltip">{t('sidebar.open')}</span>
          </button>
        )}
      </div>

      {/* ── Search ── */}
      <div className="sb-search-cell" onClick={e => e.stopPropagation()}>
        {expanded ? (
          <div className="sb-search-wrap">
            <SearchIcon className="sb-search-icon" />
            <input
              ref={searchInputRef}
              className="sb-search-input"
              type="text"
              placeholder={t('sidebar.search.placeholder')}
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            {searchActive && (
              <button className="sb-search-clear" onClick={() => setQuery('')}>×</button>
            )}
          </div>
        ) : (
          <button
            className="sb-search-btn"
            onClick={() => { onExpand(); pendingFocus.current = true; }}
          >
            <SearchIcon className="sb-search-btn-icon" />
            <span className="sb-tooltip">{t('sidebar.search.placeholder')}</span>
          </button>
        )}
      </div>

      {/* ── Nav tree ── */}
      <nav className="sb-nav" onClick={e => e.stopPropagation()}>
        {visibleTree.length === 0 && expanded && (
          <div className="sb-empty">{t('sidebar.search.empty')}</div>
        )}
        {visibleTree.map(category => (
          <CategoryBlock
            key={category.id}
            node={category}
            activeId={activeId}
            onSelect={id => onSelect(id)}
            expanded={expanded}
            searchActive={searchActive}
            onExpandSidebar={onExpand}
            open={!!openCategoryMap[category.id]}
            onToggleOpen={handleToggleCategory}
            onOpenFromCollapsed={handleOpenFromCollapsed}
          />
        ))}
      </nav>

      {/* ── Settings button ── */}
      <div className="sb-settings-cell" onClick={e => e.stopPropagation()}>
        <button
          className="sb-settings-btn"
          onClick={() => {
            onSettingsOpen?.();
          }}
          title={!expanded ? t('panel.settings') : undefined}
        >
          <span className="sb-settings-icon"><SettingsIcon /></span>
          {expanded && <span className="sb-settings-label">{t('panel.settings')}</span>}
          {!expanded && <span className="sb-tooltip">{t('panel.settings')}</span>}
        </button>
      </div>

      {/* ── Bottom: connection status ── */}
      <div className="sb-bottom">
        <div className={`sb-status ${statusClass}`}>
          <div className="sb-status-dot" />
          {expanded  && <span className="sb-status-label">{statusLabel}</span>}
          {!expanded && <span className="sb-tooltip sb-tooltip-status">{statusLabel}</span>}
        </div>
      </div>

    </aside>
  );
}
