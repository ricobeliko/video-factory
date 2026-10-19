import React, { useState } from 'react';

/**
 * Sidebar — Navegação Lateral Principal (SaaS Minimalist Command Deck)
 * Suporte a modo recolhido por padrão com rail de ícones e tooltips.
 * Preserva as 7 seções canônicas de navegação.
 */
export default function Sidebar({
  activeNav,
  onSelectNav,
  systemStatus,
  unreviewedCount = 0,
  isCollapsed = true,
  onToggleCollapse,
}) {
  const [collapsedLocal, setCollapsedLocal] = useState(true);
  const collapsed = typeof isCollapsed === 'boolean' ? isCollapsed : collapsedLocal;
  const handleToggle = onToggleCollapse || (() => setCollapsedLocal((prev) => !prev));

  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'channels', label: 'Meus Canais', icon: '📺' },
    { id: 'production', label: 'Produção', icon: '🎬' },
    {
      id: 'review',
      label: 'Estoque & Revisão',
      icon: '📦',
      badge: unreviewedCount > 0 ? unreviewedCount : null,
    },
    { id: 'schedules', label: 'Agendamentos', icon: '📅' },
    { id: 'analytics', label: 'Analytics', icon: '📈' },
    { id: 'settings', label: 'Configurações', icon: '⚙️' },
  ];

  return (
    <aside
      className={`v2-sidebar ${collapsed ? 'collapsed' : ''}`}
      aria-label="Menu principal de navegação"
    >
      {/* 1. Header com Logo, Branding e Controle de Expansão/Recolhimento */}
      <div className={`v2-sidebar-header ${collapsed ? 'collapsed' : ''}`}>
        <div
          className="v2-brand-wrapper"
          onClick={collapsed ? handleToggle : undefined}
          title={collapsed ? 'Expandir barra lateral' : undefined}
          style={{ cursor: collapsed ? 'pointer' : 'default' }}
        >
          <div className="v2-logo-icon" title="Video Factory V2">
            VF
          </div>
          {!collapsed && (
            <div className="v2-brand-text">
              <span className="v2-brand-title">Video Factory</span>
              <span className="v2-brand-badge">V2 Pro</span>
            </div>
          )}
        </div>

        <button
          type="button"
          className="v2-sidebar-toggle-btn"
          onClick={handleToggle}
          title={collapsed ? 'Expandir barra lateral' : 'Recolher barra lateral'}
          aria-label={collapsed ? 'Expandir barra lateral' : 'Recolher barra lateral'}
        >
          {collapsed ? '▶' : '◀'}
        </button>
      </div>

      {/* 2. Status Discreto da Fábrica */}
      <div
        className={`v2-factory-status-pill ${collapsed ? 'collapsed' : ''}`}
        title={isPaused ? 'Status: Fábrica Pausada' : 'Status: Fábrica Online'}
      >
        <span className={`v2-status-dot ${isPaused ? 'paused' : 'live'}`} />
        {!collapsed && (
          <span className="v2-status-text">
            {isPaused ? 'Fábrica Pausada' : 'Fábrica Online'}
          </span>
        )}
      </div>

      {/* 3. Navegação Primária */}
      <nav className="v2-sidebar-nav" aria-label="Navegação do sistema">
        {navItems.map((item) => {
          const isActive = activeNav === item.id;
          return (
            <button
              key={item.id}
              className={`v2-nav-button ${isActive ? 'active' : ''} ${collapsed ? 'collapsed' : ''}`}
              onClick={() => onSelectNav(item.id)}
              title={collapsed ? item.label : undefined}
              aria-label={item.label}
              aria-current={isActive ? 'page' : undefined}
            >
              <span className="v2-nav-icon">{item.icon}</span>
              {!collapsed && <span className="v2-nav-label">{item.label}</span>}
              {item.badge && (
                <span className={`v2-nav-badge ${collapsed ? 'badge-dot' : ''}`}>
                  {collapsed ? '●' : item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* 4. Rodapé do Ambiente Isolado */}
      <div className={`v2-sidebar-footer ${collapsed ? 'collapsed' : ''}`}>
        <div
          className="v2-env-badge"
          title="DEV_V2 — Produção Protegida (Instância Primária Segura)"
        >
          <span className="v2-env-tag">{collapsed ? 'DEV' : 'DEV_V2'}</span>
          {!collapsed && <span className="v2-env-sub">Produção Protegida</span>}
        </div>
      </div>
    </aside>
  );
}
