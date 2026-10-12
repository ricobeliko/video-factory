import React, { useEffect, useState } from 'react';
import { getExecutionDetail } from '../api';
import { STAGE_BY_CODE } from '../utils/stageVisuals';

/**
 * ExecutionDrawer — Narrative Mission Control & Causal Trace Panel (R6A.5).
 * Features:
 * - Active Agent Persona Card with avatar, bio, and operational role.
 * - Deep Causal Trace ("Quem chamou quem").
 * - Execution snapshot and chronological timeline.
 * - Terminal publication confirmation with direct YouTube link.
 */
export default function ExecutionDrawer({
  isOpen,
  onClose,
  channelData,
  taskId: propTaskId,
  selectedStage: propSelectedStage,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
          <button className="drawer-close-btn" onClick={onClose} title="Fechar painel">
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {/* Active Agent Persona Card */}
          <div className="agent-persona-card" style={{ borderColor: stageDef.accentColor }}>
            <div className="agent-persona-top">
              <div className="agent-persona-avatar-wrap" style={{ background: stageDef.tonalBg }}>
                <span className="agent-persona-avatar">{persona.avatar || '🤖'}</span>
              </div>
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
