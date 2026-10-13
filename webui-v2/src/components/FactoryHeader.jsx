import React, { useState } from 'react';
import { pauseFactory, resumeFactory } from '../api';

/**
 * FactoryHeader — Top bar displaying system health, workers and sync state (R6A.3).
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
  const [confirmAction, setConfirmAction] = useState(null); // 'pause' | 'resume' | null
  const [isMutating, setIsMutating] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');
  const factoryState = systemStatus?.factory_state || (isPaused ? 'PAUSED' : 'RUNNING');
  const workerRunning = Boolean(systemStatus?.worker_running);
  const schedulerRunning = Boolean(systemStatus?.scheduler_running);
  const autoPublish = Boolean(systemStatus?.auto_publish_enabled);
  const dryRun = Boolean(systemStatus?.dry_run);

  const handleRequestAction = (action) => {
    setErrorMessage(null);
    setConfirmAction(action);
  };

  const handleCancelAction = () => {
    setConfirmAction(null);
    setErrorMessage(null);
  };

  const handleConfirmAction = async () => {
    if (!confirmAction || isMutating) return;
    const action = confirmAction;
    setIsMutating(true);
    setErrorMessage(null);

    try {
      if (action === 'pause') {
        await pauseFactory();
      } else {
        await resumeFactory();
      }
      setConfirmAction(null);
      if (onRefresh) {
        await onRefresh();
      }
    } catch (err) {
      console.error(`Falha ao executar ${action} da fábrica:`, err);
      setErrorMessage(`Falha ao ${action === 'pause' ? 'pausar' : 'retomar'} a fábrica. Tente novamente.`);
      setConfirmAction(null);
    } finally {
      setIsMutating(false);
    }
  };

  return (
    <>
      <header className="factory-header">
        <div className="header-brand">
          <div className="brand-title">
            <span>⚙️ VIDEO FACTORY</span>
            <span className="brand-badge">{activeTab === 'agent-ops' ? 'Agent Ops' : 'Factory Live'}</span>
          </div>

          {/* Navigation Tab Switcher: Factory Live | Agent Ops */}
          <nav className="header-nav-switcher" aria-label="Navegação Principal">
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
          </nav>
        </div>

        <div className="header-status-group">
          {/* 1. Fábrica (RUNNING / PAUSED) */}
          <div className={`status-pill ${isPaused ? 'pill-paused' : 'pill-online'}`}>
            <span className={`indicator-dot ${isPaused ? 'inactive' : 'active'}`} />
            <span>Fábrica: {factoryState === 'PAUSED' ? 'Pausada' : 'Online'}</span>
          </div>

          {/* Controle Operacional de Fábrica (Missão 4) */}
          <div className="factory-action-container" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            {!confirmAction ? (
              <button
                type="button"
                className="factory-toggle-btn"
                onClick={() => handleRequestAction(isPaused ? 'resume' : 'pause')}
                disabled={isMutating}
                title={isPaused ? 'Retomar operações da fábrica' : 'Pausar operações da fábrica'}
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '3px 10px',
                  borderRadius: '16px',
                  border: isPaused ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(245, 158, 11, 0.4)',
                  backgroundColor: isPaused ? 'rgba(16, 185, 129, 0.12)' : 'rgba(245, 158, 11, 0.12)',
                  color: isPaused ? '#34d399' : '#fbbf24',
                  cursor: isMutating ? 'not-allowed' : 'pointer',
                  opacity: isMutating ? 0.6 : 1,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  transition: 'all 0.15s ease',
                }}
              >
                {isPaused ? '▶ Retomar' : '⏸ Pausar'}
              </button>
            ) : (
              <div
                className="factory-confirm-inline"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '2px 8px',
                  borderRadius: '14px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(148, 163, 184, 0.25)',
                }}
              >
                <span style={{ fontSize: '11px', color: '#e2e8f0' }}>
                  {confirmAction === 'pause' ? 'Confirmar pausa?' : 'Confirmar retomada?'}
                </span>
                <button
                  type="button"
                  className="confirm-btn-yes"
                  onClick={handleConfirmAction}
                  disabled={isMutating}
                  style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: confirmAction === 'pause' ? '#d97706' : '#059669',
                    color: '#ffffff',
                    cursor: isMutating ? 'not-allowed' : 'pointer',
                  }}
                >
                  {isMutating ? 'Processando...' : 'Sim'}
                </button>
                <button
                  type="button"
                  className="confirm-btn-no"
                  onClick={handleCancelAction}
                  disabled={isMutating}
                  style={{
                    fontSize: '10px',
                    fontWeight: 500,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    border: '1px solid #475569',
                    backgroundColor: 'transparent',
                    color: '#94a3b8',
                    cursor: isMutating ? 'not-allowed' : 'pointer',
                  }}
                >
                  Cancelar
                </button>
              </div>
            )}

            {errorMessage && (
              <span
                className="factory-action-error"
                style={{
                  fontSize: '11px',
                  color: '#f87171',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '3px',
                }}
                title={errorMessage}
              >
                ⚠️ {errorMessage}
              </span>
            )}
          </div>

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
