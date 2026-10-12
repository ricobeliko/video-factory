import React from 'react';

/**
 * FactoryHeader — Top bar displaying system health, workers and sync state
 */
export default function FactoryHeader({
  systemStatus,
  lastUpdated,
  isApiOnline,
  onRefresh,
}) {
  const isPaused = Boolean(systemStatus?.is_paused);
  const workerRunning = Boolean(systemStatus?.worker_running);
  const schedulerRunning = Boolean(systemStatus?.scheduler_running);
  const autoPublish = Boolean(systemStatus?.auto_publish_enabled);
  const dryRun = Boolean(systemStatus?.dry_run);

  return (
    <>
      <header className="factory-header">
        <div className="header-brand">
          <div className="brand-title">
            <span>⚙️ VIDEO FACTORY</span>
            <span className="brand-badge">Factory Live</span>
          </div>
        </div>

        <div className="header-status-group">
          <div className="status-pill">
            <span className={`indicator-dot ${isPaused ? 'inactive' : 'active'}`} />
            <span>Fábrica: {isPaused ? 'Pausada' : 'Online'}</span>
          </div>

          <div className="status-pill">
            <span className={`indicator-dot ${workerRunning ? 'active' : 'inactive'}`} />
            <span>Worker: {workerRunning ? 'Ativo' : 'Parado'}</span>
          </div>

          <div className="status-pill">
            <span className={`indicator-dot ${schedulerRunning ? 'active' : 'inactive'}`} />
            <span>Scheduler: {schedulerRunning ? 'Ativo' : 'Parado'}</span>
          </div>

          <div className="status-pill">
            <span className={`indicator-dot ${autoPublish ? 'active' : 'neutral'}`} />
            <span>Auto Publish: {autoPublish ? 'Ativo' : 'Off'}</span>
          </div>

          <div className="status-pill">
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
