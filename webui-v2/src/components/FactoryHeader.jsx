import React, { useState } from 'react';
import { pauseFactory, resumeFactory, runFactoryCycle } from '../api';

/**
 * FactoryHeader — Cabecalho Global Simplificado (SaaS Minimalist)
 * Radicalmente limpo: exibe o titulo da pagina ativa, acoes operacionais rapidas e
 * notificacoes importantes, sem poluir a barra com dezenas de badges tecnicos.
 */
export default function FactoryHeader({
  activeNav = 'dashboard',
  systemStatus,
  lastUpdated,
  isApiOnline,
  onRefresh,
  unreviewedCount = 0,
  onNavigate,
}) {
  const [confirmAction, setConfirmAction] = useState(null); // 'pause' | 'resume' | 'run-cycle' | null
  const [isMutating, setIsMutating] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);
  const [successFeedback, setSuccessFeedback] = useState(null);

  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');

  // Mapeamento semântico dos títulos de página
  const titles = {
    dashboard: { title: 'Dashboard', subtitle: 'Visão executiva e status da fábrica' },
    channels: { title: 'Meus Canais', subtitle: 'Gerenciamento de canais e templates de conteúdo' },
    production: { title: 'Esteira de Produção', subtitle: 'Grafo de renderização e tarefas ativas' },
    review: { title: 'Estoque & Revisão', subtitle: 'Aprovação de vídeos homologados e controle de qualidade' },
    schedules: { title: 'Agendamentos', subtitle: 'Fila de publicação automatizada no YouTube' },
    analytics: { title: 'Analytics', subtitle: 'Métricas de publicação e histórico de postagens' },
    settings: { title: 'Configurações', subtitle: 'Preferências gerais, provedores e diagnóstico' },
  };

  const currentMeta = titles[activeNav] || { title: 'Video Factory', subtitle: 'Operação autônoma de vídeos' };

  const handleRequestAction = (action) => {
    setErrorMessage(null);
    setSuccessFeedback(null);
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
    setSuccessFeedback(null);

    try {
      if (action === 'pause') {
        await pauseFactory();
        setSuccessFeedback('Fábrica pausada');
      } else if (action === 'resume') {
        await resumeFactory();
        setSuccessFeedback('Fábrica retomada');
      } else if (action === 'run-cycle') {
        const res = await runFactoryCycle({ force: true, oneShot: true });
        setSuccessFeedback(res.message || 'Ciclo disparado com sucesso');
      }
      setConfirmAction(null);
      if (onRefresh) await onRefresh();
      setTimeout(() => setSuccessFeedback(null), 4000);
    } catch (err) {
      console.error(`Falha ao executar ${action}:`, err);
      let msg = err.message || 'Falha ao processar operação.';
      if (err.status === 409) {
        if (msg.toLowerCase().includes('already in progress')) {
          msg = 'Ciclo de produção já em andamento em segundo plano.';
        } else if (msg.toLowerCase().includes('paused') || msg.toLowerCase().includes('pausada')) {
          msg = 'Fábrica pausada — retome para disparar.';
        }
      } else if (err.status === 403) {
        msg = 'Bloqueado: somente nó primário pode executar.';
      }
      setErrorMessage(msg);
      setConfirmAction(null);
      setTimeout(() => setErrorMessage(null), 6000);
    } finally {
      setIsMutating(false);
    }
  };

  return (
    <>
      <header className="v2-header">
        {/* Esquerda: Titulo e Subtitulo Contextual */}
        <div className="v2-header-title-box">
          <h1 className="v2-header-title">{currentMeta.title}</h1>
          <span className="v2-header-subtitle">{currentMeta.subtitle}</span>
        </div>

        {/* Direita: Acoes Rapidas & Notificacoes */}
        <div className="v2-header-actions-box">
          {/* Acoes de Controle da Fabrica (Pause / Resume / Run-Cycle) */}
          <div className="v2-header-cycle-controls">
            {!confirmAction ? (
              <>
                <button
                  type="button"
                  className={`v2-btn-toggle-factory ${isPaused ? 'paused' : 'live'}`}
                  onClick={() => handleRequestAction(isPaused ? 'resume' : 'pause')}
                  disabled={isMutating}
                  title={isPaused ? 'Retomar operações da fábrica' : 'Pausar operações da fábrica'}
                >
                  <span className={`v2-btn-dot ${isPaused ? 'dot-paused' : 'dot-live'}`} />
                  {isPaused ? 'Retomar Fábrica' : 'Pausar'}
                </button>

                <button
                  type="button"
                  className="v2-btn-header-cycle"
                  onClick={() => handleRequestAction('run-cycle')}
                  disabled={isMutating || isPaused}
                  title={isPaused ? 'Fábrica pausada — retome antes de disparar' : 'Disparar ciclo autônomo supervisionado'}
                >
                  ⚡ Executar Ciclo
                </button>
              </>
            ) : (
              <div className="v2-header-confirm-inline">
                <span className="v2-confirm-text">
                  {confirmAction === 'pause'
                    ? 'Pausar fábrica?'
                    : confirmAction === 'resume'
                    ? 'Retomar fábrica?'
                    : 'Disparar ciclo agora?'}
                </span>
                <button
                  type="button"
                  className="v2-confirm-btn-yes"
                  onClick={handleConfirmAction}
                  disabled={isMutating}
                >
                  {isMutating ? '...' : 'Sim'}
                </button>
                <button
                  type="button"
                  className="v2-confirm-btn-no"
                  onClick={handleCancelAction}
                  disabled={isMutating}
                >
                  Não
                </button>
              </div>
            )}

            {successFeedback && (
              <span className="v2-header-toast success">
                ✓ {successFeedback}
              </span>
            )}

            {errorMessage && (
              <span className="v2-header-toast error" title={errorMessage}>
                ⚠️ {errorMessage}
              </span>
            )}
          </div>

          {/* Sino de Notificacoes / Estoque Pendente */}
          {unreviewedCount > 0 && (
            <button
              type="button"
              className="v2-header-notif-btn"
              onClick={() => onNavigate && onNavigate('review')}
              title={`${unreviewedCount} vídeo(s) aguardando revisão humana`}
            >
              🔔 <span className="v2-notif-badge">{unreviewedCount}</span>
            </button>
          )}

          {/* Botao Discreto de Atualizacao */}
          <button
            type="button"
            className="v2-header-refresh-btn"
            onClick={onRefresh}
            title={lastUpdated ? `Atualizado: ${lastUpdated.toLocaleTimeString()}` : 'Atualizar'}
          >
            ↻
          </button>
        </div>
      </header>

      {!isApiOnline && (
        <div className="v2-offline-banner">
          <div>
            <strong>🔴 Servidor Desconectado</strong> — Exibindo último snapshot em memória da sessão.
          </div>
          {lastUpdated && (
            <span>Última sincronização bem-sucedida: {lastUpdated.toLocaleTimeString()}</span>
          )}
        </div>
      )}
    </>
  );
}
