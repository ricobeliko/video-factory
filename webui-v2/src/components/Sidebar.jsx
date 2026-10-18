import React from 'react';

export default function Sidebar({ activeNav, onSelectNav, systemStatus, unreviewedCount = 0 }) {
  const isPaused = Boolean(systemStatus?.is_paused);

  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '⚡' },
    { id: 'channels', label: 'Meus Canais', icon: '📺' },
    { id: 'pipeline', label: 'Produção & Grafo', icon: '🎬' },
    {
      id: 'review',
      label: 'Estoque & Revisão',
      icon: '📦',
      badge: unreviewedCount > 0 ? unreviewedCount : null,
    },
    { id: 'agent-ops', label: 'Agent Ops Room', icon: '🤖' },
    { id: 'settings', label: 'Configurações', icon: '⚙️' },
  ];

  return (
    <aside className="v2-sidebar">
      <div className="v2-sidebar-header">
        <div className="v2-logo-icon">VF</div>
        <div className="v2-brand-text">
          <span className="v2-brand-title">Video Factory</span>
          <span className="v2-brand-badge">V2 Isolada</span>
        </div>
      </div>

      <div className="v2-factory-status-pill">
        <span className={`v2-status-dot ${isPaused ? 'paused' : 'live'}`} />
        <span className="v2-status-text">
          {isPaused ? 'Fábrica Pausada' : 'Operação Ativa'}
        </span>
      </div>

      <nav className="v2-sidebar-nav">
        {navItems.map((item) => {
          const isActive = activeNav === item.id;
          return (
            <button
              key={item.id}
              className={`v2-nav-button ${isActive ? 'active' : ''}`}
              onClick={() => onSelectNav(item.id)}
            >
              <span className="v2-nav-icon">{item.icon}</span>
              <span className="v2-nav-label">{item.label}</span>
              {item.badge && (
                <span className="v2-nav-badge">{item.badge}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="v2-sidebar-footer">
        <div className="v2-env-badge">
          <span className="v2-env-tag">DEV_V2</span>
          <span className="v2-env-sub">Produção Protegida</span>
        </div>
      </div>
    </aside>
  );
}
