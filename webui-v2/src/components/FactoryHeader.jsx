import React from 'react';

/**
 * FactoryHeader — Top bar displaying system health, workers and sync state (R6A.3 + Controle Único).
 * Somente leitura para o estado da fábrica, com atalho "Ir para Sistema" (único lugar de controle global).
 * Semantic chip colors:
 * - ONLINE / ON: green
 * - OFF intentional: gray
 * - PARADO unexpected: red
 * - DRY RUN ON: amber
 */
export default function FactoryHeader({
  systemStatus,
  lastUpdated,
  isApiOnline,
  onRefresh,
  activeTab = 'factory-live',
  onSelectTab,
}) {
  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');
  const factoryState = systemStatus?.factory_state || (isPaused ? 'PAUSED' : 'RUNNING');
  const workerRunning = Boolean(systemStatus?.worker_running);
  const schedulerRunning = Boolean(systemStatus?.scheduler_running);
  const autoPublish = Boolean(systemStatus?.auto_publish_enabled);
  const dryRun = Boolean(systemStatus?.dry_run);

  const handleGoToSystem = () => {
    if (onSelectTab) {
      onSelectTab('sistema');
    } else if (typeof window !== 'undefined') {
      window.location.hash = '#sistema';
    }
  };

  return (
    <>
      <header className="factory-header">
        <div className="header-brand">
          <div className="brand-title">
            <span>⚙️ VIDEO FACTORY</span>
            <span className="brand-badge">
              {activeTab === 'agent-ops' ? 'Agent Ops' : activeTab === 'video-review' ? 'Revisão' : 'Factory Live'}
            </span>
          </div>

          {/* Navigation Tab Switcher: Factory Live | Agent Ops | Revisão de Vídeos */}
          <nav className="header-nav-switcher" aria-label="Navegação Principal">
            <button
              type="button"
              className={`nav-switch-tab ${activeTab === 'frota' ? 'active' : ''}`}
              onClick={() => onSelectTab && onSelectTab('frota')}
            >
              <span className="tab-icon">🚀</span>
              <span>Frota</span>
            </button>
            <button
              type="button"
              className={`nav-switch-tab ${activeTab === 'factory-live' ? 'active' : ''}`}
              onClick={() => onSelectTab && onSelectTab('factory-live')}
            >
              <span className="tab-icon">🏭</span>
              <span>Factory Live</span>
            </button>
            <button
              type="button"
              className={`nav-switch-tab ${activeTab === 'agent-ops' ? 'active' : ''}`}
              onClick={() => onSelectTab && onSelectTab('agent-ops')}
            >
              <span className="tab-icon">🤖</span>
              <span>Agent Ops</span>
            </button>
            <button
              type="button"
              className={`nav-switch-tab ${activeTab === 'video-review' ? 'active' : ''}`}
              onClick={() => onSelectTab && onSelectTab('video-review')}
            >
              <span className="tab-icon">🎬</span>
              <span>Revisão de Vídeos</span>
            </button>
          </nav>
        </div>

        <div className="header-status-group">
          {/* 1. Fábrica (RUNNING / PAUSED) — somente leitura */}
          <div className={`status-pill ${isPaused ? 'pill-paused' : 'pill-online'}`}>
            <span className={`indicator-dot ${isPaused ? 'inactive' : 'active'}`} />
            <span>Fábrica: {factoryState === 'PAUSED' ? 'Pausada' : 'Online'}</span>
          </div>

          {/* Atalho para o único lugar de controle global da fábrica (Tela Sistema) */}
          <button
            type="button"
            className="factory-system-shortcut-btn"
            onClick={handleGoToSystem}
            title="Gerenciar estado da fábrica (Pausar/Retomar e Rodar 1 ciclo) na tela Sistema"
            style={{
              fontSize: '11px',
              fontWeight: 600,
              padding: '3px 10px',
              borderRadius: '16px',
              border: '1px solid rgba(56, 189, 248, 0.35)',
              backgroundColor: 'rgba(56, 189, 248, 0.1)',
              color: '#38bdf8',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              transition: 'all 0.15s ease',
            }}
          >
            ⚙️ Ir para Sistema
          </button>

          {/* 2. Worker (Ativo / Parado inesperado) */}
          <div className={`status-pill ${workerRunning ? 'pill-running' : 'pill-stopped'}`}>
            <span className={`indicator-dot ${workerRunning ? 'active' : 'inactive'}`} />
            <span>Worker: {workerRunning ? 'Ativo' : 'Parado'}</span>
          </div>

          {/* 3. Scheduler (Ativo / Parado inesperado) */}
          <div className={`status-pill ${schedulerRunning ? 'pill-running' : 'pill-stopped'}`}>
            <span className={`indicator-dot ${schedulerRunning ? 'active' : 'inactive'}`} />
            <span>Scheduler: {schedulerRunning ? 'Ativo' : 'Parado'}</span>
          </div>

          {/* 4. Auto Publish (Ativo / Off intencional) */}
          <div className={`status-pill ${autoPublish ? 'pill-running' : 'pill-off'}`}>
            <span className={`indicator-dot ${autoPublish ? 'active' : 'neutral'}`} />
            <span>Auto Publish: {autoPublish ? 'Ativo' : 'Off'}</span>
          </div>

          {/* 5. Dry Run (ON âmbar / OFF neutro) */}
          <div className={`status-pill ${dryRun ? 'pill-warning' : 'pill-off'}`}>
            <span className={`indicator-dot ${dryRun ? 'warning' : 'neutral'}`} />
            <span>Dry Run: {dryRun ? 'ON' : 'OFF'}</span>
          </div>
        </div>

        <div className="header-meta">
          <span className="last-update-time">
            {lastUpdated ? `Atualizado: ${lastUpdated.toLocaleTimeString()}` : 'Conectando...'}
          </span>
          <button className="refresh-btn" onClick={onRefresh} title="Atualizar agora">
            ↻ Atualizar
          </button>
        </div>
      </header>

      {!isApiOnline && (
        <div className="api-offline-banner">
          <div>
            <strong>🔴 API Indisponível</strong> — Exibindo último snapshot em memória da sessão.
          </div>
          {lastUpdated && (
            <span>Última sincronização bem-sucedida: {lastUpdated.toLocaleTimeString()}</span>
          )}
        </div>
      )}
    </>
  );
}
