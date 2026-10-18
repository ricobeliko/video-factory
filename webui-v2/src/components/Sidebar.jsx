import React from 'react';

/**
 * Sidebar — Navegação Lateral Principal (SaaS Minimalist Dark)
 * Estrutura canônica de 7 seções operacionais.
 * Agent Ops Room foi removido da navegação principal do operador e realocado para Configurações > Diagnóstico.
 */
export default function Sidebar({ activeNav, onSelectNav, systemStatus, unreviewedCount = 0 }) {
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
    <aside className="v2-sidebar">
      {/* 1. Header com Logo e Branding Limpo */}
      <div className="v2-sidebar-header">
        <div className="v2-logo-icon">VF</div>
        <div className="v2-brand-text">
          <span className="v2-brand-title">Video Factory</span>
          <span className="v2-brand-badge">V2 Pro</span>
        </div>
      </div>

      {/* 2. Status Discreto da Fábrica */}
      <div className="v2-factory-status-pill">
        <span className={`v2-status-dot ${isPaused ? 'paused' : 'live'}`} />
        <span className="v2-status-text">
          {isPaused ? 'Fábrica Pausada' : 'Fábrica Online'}
        </span>
      </div>

      {/* 3. Navegação Primária */}
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

      {/* 4. Rodapé do Ambiente Isolado */}
      <div className="v2-sidebar-footer">
        <div className="v2-env-badge">
          <span className="v2-env-tag">DEV_V2</span>
          <span className="v2-env-sub">Produção Protegida</span>
        </div>
      </div>
    </aside>
  );
}
