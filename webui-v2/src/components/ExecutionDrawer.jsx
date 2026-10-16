import React, { useEffect, useState } from 'react';
import { getExecutionDetail, runFactoryCycle } from '../api';
import { STAGE_BY_CODE } from '../utils/stageVisuals';
import AgentAvatar from './AgentAvatar';

/**
 * ExecutionDrawer — Narrative Mission Control & Causal Trace Panel (R6A.5).
 * Features:
 * - Active Agent Persona Card with avatar, bio, and operational role.
 * - Deep Causal Trace ("Quem chamou quem").
 * - Execution snapshot and chronological timeline.
 * - Terminal publication confirmation with direct YouTube link.
 * - Supervised channel run cycle trigger.
 */
export default function ExecutionDrawer({
  isOpen,
  onClose,
  channelData,
  taskId: propTaskId,
  selectedStage: propSelectedStage,
  onRefresh,
  isPaused,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Channel dispatch state
  const [isChannelMutating, setIsChannelMutating] = useState(false);
  const [confirmChannelCycle, setConfirmChannelCycle] = useState(false);
  const [channelActionMsg, setChannelActionMsg] = useState(null);
  const [channelActionError, setChannelActionError] = useState(null);

  const isChannelRunning = channelData?.execution?.status === 'RUNNING';
  const isFactoryPaused = Boolean(isPaused);

  const handleTriggerChannelCycle = async () => {
    if (isChannelMutating || isChannelRunning || isFactoryPaused) return;
    setIsChannelMutating(true);
    setChannelActionMsg(null);
    setChannelActionError(null);

    try {
      await runFactoryCycle({
        profileId: channelData?.profile_id,
        channelId: channelData?.channel_id,
        force: true,
        oneShot: true,
      });
      setConfirmChannelCycle(false);
      setChannelActionMsg('Ciclo disparado com sucesso para este canal!');
      if (onRefresh) {
        await onRefresh();
      }
      setTimeout(() => setChannelActionMsg(null), 5000);
    } catch (err) {
      console.error('Falha ao disparar ciclo do canal:', err);
      let msg = err.message || 'Falha ao processar disparo';
      if (err.status === 409) {
        if (msg.toLowerCase().includes('already in progress') || msg.toLowerCase().includes('em andamento')) {
          msg = 'Ciclo de produção já em andamento.';
        } else if (msg.toLowerCase().includes('paused') || msg.toLowerCase().includes('pausada')) {
          msg = 'Fábrica pausada — retome antes de disparar.';
        }
      } else if (err.status === 403) {
        msg = 'Bloqueado: somente nó primário pode executar.';
      }
      setConfirmChannelCycle(false);
      setChannelActionError(msg);
      setTimeout(() => setChannelActionError(null), 6000);
    } finally {
      setIsChannelMutating(false);
    }
  };

  // Active taskId resolution
  const activeTaskId = propTaskId || channelData?.execution?.task_id;

  // Poll detail while drawer is open
  useEffect(() => {
    if (!isOpen || !activeTaskId) {
      setDetail(null);
      return;
    }

    let isMounted = true;
    setLoading(true);

    const fetchDetail = async () => {
      try {
        const res = await getExecutionDetail(activeTaskId);
        if (isMounted) {
          setDetail(res);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message);
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchDetail();
    const interval = setInterval(fetchDetail, 3000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isOpen, activeTaskId]);

  if (!isOpen) return null;

  const execution = channelData?.execution;
  const trace = detail?.causal_trace || {};
  const publication = detail?.publication || execution?.publication_state;
  const timeline = detail?.timeline || [];

  const isPublishedSuccess = publication?.status === 'success' || (execution?.status === 'SUCCESS' && publication?.published_at);

  // Determine stage and active persona
  const activeStageCode = propSelectedStage || execution?.pipeline_stage || detail?.task?.pipeline_stage || 'TOPIC';
  const stageDef = STAGE_BY_CODE[activeStageCode] || STAGE_BY_CODE.TOPIC;
  const persona = stageDef.persona || {};

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="execution-drawer" onClick={(e) => e.stopPropagation()}>
        {/* Drawer Header */}
        <div className="drawer-header">
          <div>
            <div className="drawer-title">
              📺 {channelData?.channel_name || channelData?.profile_name || 'Painel de Execução'}
            </div>
            <div className="drawer-subtitle">
              {channelData?.channel_name ? `${channelData.channel_name} • ` : ''}Perfil: <code>{channelData?.profile_id}</code>
            </div>
          </div>
        </div>

        {/* Channel Dispatch Action Bar */}
        {channelData && (
          <div className="drawer-channel-actions">
            <div className="drawer-channel-actions-label">
              <span>Disparo Supervisionado:</span>
            </div>
            {!confirmChannelCycle ? (
              <button
                type="button"
                className="drawer-dispatch-btn"
                onClick={() => {
                  setChannelActionError(null);
                  setChannelActionMsg(null);
                  setConfirmChannelCycle(true);
                }}
                disabled={isChannelMutating || isChannelRunning || isFactoryPaused}
                title={
                  isFactoryPaused
                    ? 'Fábrica pausada — retome antes de disparar'
                    : isChannelRunning
                    ? 'Canal já possui tarefa em execução'
                    : 'Disparar ciclo autônomo específico para este canal'
                }
              >
                {isChannelRunning ? '⏳ Em Execução' : isFactoryPaused ? '⏸ Fábrica Pausada' : '⚡ Disparar Ciclo do Canal'}
              </button>
            ) : (
              <div className="drawer-confirm-inline">
                <span className="drawer-confirm-text">Disparar ciclo agora?</span>
                <button
                  type="button"
                  className="drawer-confirm-yes"
                  onClick={handleTriggerChannelCycle}
                  disabled={isChannelMutating}
                >
                  {isChannelMutating ? 'Disparando...' : 'Sim'}
                </button>
                <button
                  type="button"
                  className="drawer-confirm-no"
                  onClick={() => setConfirmChannelCycle(false)}
                  disabled={isChannelMutating}
                >
                  Cancelar
                </button>
              </div>
            )}
            {channelActionMsg && <span className="drawer-action-success">✓ {channelActionMsg}</span>}
            {channelActionError && <span className="drawer-action-error">⚠️ {channelActionError}</span>}
          </div>
        )}

        <div className="drawer-body">
          {/* Active Agent Persona Card */}
          <div className="agent-persona-card" style={{ borderColor: stageDef.accentColor }}>
            <div className="agent-persona-top">
              <AgentAvatar
                persona={persona}
                accentColor={stageDef.accentColor}
                isRunning={execution?.status === 'RUNNING'}
                size="lg"
              />
              <div className="agent-persona-meta">
                <div className="agent-persona-code-row">
                  <span className="agent-code-badge" style={{ backgroundColor: stageDef.accentColor }}>
                    {persona.code || activeStageCode}
                  </span>
                  <span className="agent-badge-tag">{persona.badge || 'OPERATOR'}</span>
                </div>
                <div className="agent-persona-name">
                  {persona.name || stageDef.label} — <span className="agent-persona-role">{persona.role}</span>
                </div>
              </div>
            </div>
            <div className="agent-persona-bio">
              {persona.bio || 'Módulo operacional integrado à esteira de produção autônoma.'}
            </div>
          </div>

          {/* Publication Terminal Success Banner */}
          {isPublishedSuccess && (
            <div className="publication-banner">
              <div className="publication-title">
                <span>✅ PUBLICADO NO YOUTUBE</span>
              </div>
              {publication?.video_url && (
                <a
                  className="publication-link"
                  href={publication.video_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  🔗 Assistir no YouTube: {publication.video_url}
                </a>
              )}
              {publication?.published_at && (
                <div style={{ fontSize: '10px', color: '#6ee7b7' }}>
                  Publicado em: {new Date(publication.published_at).toLocaleString()}
                </div>
              )}
            </div>
          )}

          {/* Core Execution Snapshot */}
          <div className="drawer-section">
            <span className="section-label">Snapshot de Execução</span>
            <div className="info-grid">
              <div className="info-box full-width">
                <div className="info-box-label">Task ID</div>
                <div className="info-box-value mono">{activeTaskId || 'Sem tarefa ativa (IDLE)'}</div>
              </div>

              <div className="info-box full-width">
                <div className="info-box-label">Tema / Tópico</div>
                <div className="info-box-value">{execution?.topic || detail?.task?.video_subject || '—'}</div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Status Atual</div>
                <div className="info-box-value">{execution?.status || detail?.task?.status || 'IDLE'}</div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Etapa Canônica</div>
                <div className="info-box-value">
                  {stageDef.label} ({stageDef.code})
                </div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Progresso Real</div>
                <div className="info-box-value">
                  {execution?.progress !== null && execution?.progress !== undefined
                    ? `${execution.progress}%`
                    : '—'}
                </div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Componente Ativo</div>
                <div className="info-box-value mono">{execution?.component || detail?.task?.component || '—'}</div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Provedor Ativo</div>
                <div className="info-box-value mono">{execution?.provider || '—'}</div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Próxima Etapa</div>
                <div className="info-box-value">{execution?.next_stage || '—'}</div>
              </div>

              {execution?.error && (
                <div className="info-box full-width" style={{ borderColor: 'var(--status-failed)' }}>
                  <div className="info-box-label" style={{ color: 'var(--status-failed)' }}>Erro Registrado</div>
                  <div className="info-box-value" style={{ color: '#fca5a5' }}>{execution.error}</div>
                </div>
              )}

              {execution?.message && (
                <div className="info-box full-width">
                  <div className="info-box-label">Mensagem Operacional</div>
                  <div className="info-box-value">{execution.message}</div>
                </div>
              )}
            </div>
          </div>

          {/* Causal Trace Flow */}
          <div className="drawer-section">
            <span className="section-label">Trace Causal ("Quem chamou quem")</span>
            <div className="causal-trace">
              <div className="trace-step">
                <div className="trace-step-icon">📺</div>
                <div>
                  <div className="trace-step-label">Canal / Perfil</div>
                  <div className="trace-step-val">{trace.channel || channelData?.channel_name || channelData?.profile_id}</div>
                </div>
              </div>
              <div className="trace-arrow">↓</div>

              <div className="trace-step">
                <div className="trace-step-icon">🤖</div>
                <div>
                  <div className="trace-step-label">Gatilho / Orquestrador</div>
                  <div className="trace-step-val">{trace.trigger || 'AUTONOMOUS_PRODUCTION'}</div>
                </div>
              </div>
              <div className="trace-arrow">↓</div>

              <div className="trace-step">
                <div className="trace-step-icon">⚙️</div>
                <div>
                  <div className="trace-step-label">Componente Backend</div>
                  <div className="trace-step-val">{trace.component || execution?.component || 'task_service'}</div>
                </div>
              </div>
              <div className="trace-arrow">↓</div>

              <div className="trace-step">
                <div className="trace-step-icon">🔌</div>
                <div>
                  <div className="trace-step-label">Provedor</div>
                  <div className="trace-step-val">{trace.provider || execution?.provider || 'Não aplicável'}</div>
                </div>
              </div>
              <div className="trace-arrow">↓</div>

              <div className="trace-step">
                <div className="trace-step-icon">🏁</div>
                <div>
                  <div className="trace-step-label">Resultado Consolidado</div>
                  <div className="trace-step-val">{trace.result || execution?.status || 'IDLE'}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Operational Events Timeline */}
          {timeline.length > 0 && (
            <div className="drawer-section">
              <span className="section-label">Linha do Tempo Operacional ({timeline.length} eventos)</span>
              <div className="timeline-list">
                {timeline.map((evt, idx) => (
                  <div key={idx} className="timeline-item">
                    <div className="timeline-time">
                      {evt.created_at ? new Date(evt.created_at).toLocaleTimeString() : '—'} • {evt.component || 'sistema'}
                    </div>
                    <div className="timeline-msg">
                      <strong>{evt.event_type}</strong>: {evt.message || '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
