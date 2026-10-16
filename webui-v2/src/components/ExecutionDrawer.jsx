import React, { useEffect, useState } from 'react';
import {
  getExecutionDetail,
  runFactoryCycle,
  updateProfileGrowthMode,
  updateProfileAutonomousMode,
  getProfileSettings,
  updateProfileSettings,
} from '../api';
import { STAGE_BY_CODE, sanitizeDisplayText } from '../utils/stageVisuals';
import AgentAvatar from './AgentAvatar';

/**
 * ExecutionDrawer — Narrative Mission Control & Causal Trace Panel (R6A.5 + R7).
 * Features:
 * - Active Agent Persona Card with avatar, bio, and operational role.
 * - Deep Causal Trace ("Quem chamou quem").
 * - Execution snapshot and chronological timeline.
 * - Terminal publication confirmation with direct YouTube link.
 * - Supervised channel run cycle trigger.
 * - Per-profile Growth Mode (WARMUP / SCALE) and Autonomous Mode controls (R7).
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

  // Channel settings state (R7)
  const [isUpdatingSettings, setIsUpdatingSettings] = useState(false);
  const [settingsSuccessMsg, setSettingsSuccessMsg] = useState(null);
  const [settingsErrorMsg, setSettingsErrorMsg] = useState(null);

  // R7 Phase 2: Per-profile quotas and schedule states
  const [targetStockVal, setTargetStockVal] = useState(3);
  const [maxGenerationsVal, setMaxGenerationsVal] = useState(2);
  const [postsPerDayVal, setPostsPerDayVal] = useState(1);
  const [publishStartHour, setPublishStartHour] = useState(10);
  const [publishEndHour, setPublishEndHour] = useState(22);
  const [minIntervalHours, setMinIntervalHours] = useState(2);
  const [isSavingCustomSettings, setIsSavingCustomSettings] = useState(false);

  const currentGrowthMode = (channelData?.growth_mode || 'warmup').toLowerCase();
  const currentAutonomous = Boolean(channelData?.autonomous_enabled);

  // Load factual profile settings on drawer open
  useEffect(() => {
    if (!isOpen || !channelData?.profile_id) return;
    let isMounted = true;
    getProfileSettings(channelData.profile_id)
      .then((res) => {
        if (!isMounted) return;
        const d = res?.data || {};
        if (d.quotas) {
          if (typeof d.quotas.target_ready_stock === 'number') setTargetStockVal(d.quotas.target_ready_stock);
          if (typeof d.quotas.max_generations_24h === 'number') setMaxGenerationsVal(d.quotas.max_generations_24h);
          if (typeof d.quotas.posts_per_day === 'number') setPostsPerDayVal(d.quotas.posts_per_day);
        }
        if (d.schedule) {
          if (typeof d.schedule.publish_start_hour === 'number') setPublishStartHour(d.schedule.publish_start_hour);
          if (typeof d.schedule.publish_end_hour === 'number') setPublishEndHour(d.schedule.publish_end_hour);
          if (typeof d.schedule.min_interval_hours === 'number') setMinIntervalHours(d.schedule.min_interval_hours);
          if (typeof d.schedule.posts_per_day === 'number' && !d.quotas?.posts_per_day) {
            setPostsPerDayVal(d.schedule.posts_per_day);
          }
        }
      })
      .catch((err) => {
        console.warn('Configurações detalhadas não puderam ser carregadas:', err.message);
      });
    return () => {
      isMounted = false;
    };
  }, [isOpen, channelData?.profile_id]);

  const handleSaveScheduleAndQuotas = async () => {
    if (isSavingCustomSettings || !channelData?.profile_id) return;
    setIsSavingCustomSettings(true);
    setSettingsSuccessMsg(null);
    setSettingsErrorMsg(null);

    try {
      await updateProfileSettings(channelData.profile_id, {
        quotas: {
          target_ready_stock: Number(targetStockVal),
          max_generations_24h: Number(maxGenerationsVal),
          posts_per_day: Number(postsPerDayVal),
        },
        schedule: {
          publish_start_hour: Number(publishStartHour),
          publish_end_hour: Number(publishEndHour),
          min_interval_hours: Number(minIntervalHours),
          posts_per_day: Number(postsPerDayVal),
        },
      });
      setSettingsSuccessMsg('Quotas e janela de publicação salvas com sucesso!');
      if (onRefresh) await onRefresh();
      setTimeout(() => setSettingsSuccessMsg(null), 4000);
    } catch (err) {
      console.error('Falha ao salvar quotas e janela:', err);
      let msg = err.message || 'Falha ao salvar configurações';
      if (err.status === 403) msg = 'Bloqueado: somente nó primário pode salvar configurações.';
      setSettingsErrorMsg(msg);
      setTimeout(() => setSettingsErrorMsg(null), 5000);
    } finally {
      setIsSavingCustomSettings(false);
    }
  };

  const handleToggleGrowthMode = async (targetMode) => {
    if (isUpdatingSettings || targetMode === currentGrowthMode) return;
    setIsUpdatingSettings(true);
    setSettingsSuccessMsg(null);
    setSettingsErrorMsg(null);

    try {
      await updateProfileGrowthMode(channelData?.profile_id, targetMode);
      setSettingsSuccessMsg(`Growth Mode alterado para ${targetMode.toUpperCase()}`);
      if (onRefresh) await onRefresh();
      setTimeout(() => setSettingsSuccessMsg(null), 4000);
    } catch (err) {
      console.error('Falha ao atualizar Growth Mode:', err);
      let msg = err.message || 'Falha ao atualizar Growth Mode';
      if (err.status === 403) msg = 'Bloqueado: somente nó primário pode alterar Growth Mode.';
      setSettingsErrorMsg(msg);
      setTimeout(() => setSettingsErrorMsg(null), 5000);
    } finally {
      setIsUpdatingSettings(false);
    }
  };

  const handleToggleAutonomous = async () => {
    if (isUpdatingSettings) return;
    const targetState = !currentAutonomous;
    setIsUpdatingSettings(true);
    setSettingsSuccessMsg(null);
    setSettingsErrorMsg(null);

    try {
      await updateProfileAutonomousMode(channelData?.profile_id, targetState);
      setSettingsSuccessMsg(`Autonomia ${targetState ? 'ativada (AUTO)' : 'pausada (MANUAL)'}`);
      if (onRefresh) await onRefresh();
      setTimeout(() => setSettingsSuccessMsg(null), 4000);
    } catch (err) {
      console.error('Falha ao atualizar modo autônomo:', err);
      let msg = err.message || 'Falha ao atualizar autonomia';
      if (err.status === 403) msg = 'Bloqueado: somente nó primário pode alterar autonomia.';
      setSettingsErrorMsg(msg);
      setTimeout(() => setSettingsErrorMsg(null), 5000);
    } finally {
      setIsUpdatingSettings(false);
    }
  };

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

          {/* Operational Settings Section (R7) */}
          {channelData && (
            <div className="drawer-section drawer-settings-section">
              <span className="section-label">Configurações Operacionais (R7)</span>
              
              <div className="drawer-settings-grid">
                {/* 1. Growth Mode Selector */}
                <div className="drawer-setting-item">
                  <div className="drawer-setting-header">
                    <span className="drawer-setting-title">Growth Mode:</span>
                    <span className="drawer-setting-desc">Teto de produção e slots do canal</span>
                  </div>
                  <div className="drawer-growth-selector">
                    <button
                      type="button"
                      className={`growth-toggle-btn ${currentGrowthMode === 'warmup' ? 'active-warmup' : ''}`}
                      onClick={() => handleToggleGrowthMode('warmup')}
                      disabled={isUpdatingSettings}
                      title="WARMUP: Modo aquecimento / 2 aprovações por 24h"
                    >
                      🌱 WARMUP
                    </button>
                    <button
                      type="button"
                      className={`growth-toggle-btn ${currentGrowthMode === 'scale' ? 'active-scale' : ''}`}
                      onClick={() => handleToggleGrowthMode('scale')}
                      disabled={isUpdatingSettings}
                      title="SCALE: Modo escala / 5 aprovações por 24h"
                    >
                      🚀 SCALE
                    </button>
                  </div>
                </div>

                {/* 2. Autonomous Mode Toggle */}
                <div className="drawer-setting-item">
                  <div className="drawer-setting-header">
                    <span className="drawer-setting-title">Produção Autônoma:</span>
                    <span className="drawer-setting-desc">Geração em background via Scheduler</span>
                  </div>
                  <div className="drawer-autonomous-selector">
                    <button
                      type="button"
                      className={`autonomous-toggle-btn ${currentAutonomous ? 'active-auto' : 'active-manual'}`}
                      onClick={handleToggleAutonomous}
                      disabled={isUpdatingSettings}
                      title={currentAutonomous ? 'Clique para pausar produção autônoma (MANUAL)' : 'Clique para ativar produção autônoma (AUTO)'}
                    >
                      {currentAutonomous ? '● AUTO (Ativo)' : '○ MANUAL (Pausado)'}
                    </button>
                  </div>
                </div>

                {/* 3. Quotas & Limites Operacionais (R7 Phase 2) */}
                <div className="drawer-subcard-settings">
                  <div className="drawer-subcard-header">
                    <span className="drawer-subcard-title">📊 Quotas & Limites Operacionais</span>
                  </div>

                  <div className="drawer-controls-row">
                    <div className="drawer-control-col">
                      <label className="drawer-field-label" title="Meta de vídeos finalizados mantidos em estoque (3 a 6)">
                        Meta Estoque Pronto:
                      </label>
                      <div className="drawer-btn-group">
                        {[3, 4, 5, 6].map((num) => (
                          <button
                            key={num}
                            type="button"
                            className={`drawer-num-btn ${Number(targetStockVal) === num ? 'active' : ''}`}
                            onClick={() => setTargetStockVal(num)}
                            disabled={isSavingCustomSettings}
                          >
                            {num}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="drawer-control-col">
                      <label className="drawer-field-label" title="Teto de vídeos aprovados criados por dia">
                        Gerações 24h:
                      </label>
                      <div className="drawer-btn-group">
                        {[1, 2, 3, 4, 5].map((num) => (
                          <button
                            key={num}
                            type="button"
                            className={`drawer-num-btn ${Number(maxGenerationsVal) === num ? 'active' : ''}`}
                            onClick={() => setMaxGenerationsVal(num)}
                            disabled={isSavingCustomSettings}
                          >
                            {num}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="drawer-control-col">
                      <label className="drawer-field-label" title="Frequência diária de publicações">
                        Posts / Dia:
                      </label>
                      <div className="drawer-btn-group">
                        {[1, 2, 3].map((num) => (
                          <button
                            key={num}
                            type="button"
                            className={`drawer-num-btn ${Number(postsPerDayVal) === num ? 'active' : ''}`}
                            onClick={() => setPostsPerDayVal(num)}
                            disabled={isSavingCustomSettings}
                          >
                            {num}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 4. Janela de Publicação & Agendamento (R7 Phase 2) */}
                <div className="drawer-subcard-settings">
                  <div className="drawer-subcard-header">
                    <span className="drawer-subcard-title">⏰ Janela de Publicação & Agendamento</span>
                    <span className="drawer-tz-tag">America/Sao_Paulo (UTC-3)</span>
                  </div>

                  <div className="drawer-controls-row">
                    <div className="drawer-control-col">
                      <label className="drawer-field-label">Início da Janela:</label>
                      <select
                        className="drawer-select"
                        value={publishStartHour}
                        onChange={(e) => setPublishStartHour(Number(e.target.value))}
                        disabled={isSavingCustomSettings}
                      >
                        {[6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20].map((h) => (
                          <option key={h} value={h}>
                            {String(h).padStart(2, '0')}:00
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="drawer-control-col">
                      <label className="drawer-field-label">Fim da Janela:</label>
                      <select
                        className="drawer-select"
                        value={publishEndHour}
                        onChange={(e) => setPublishEndHour(Number(e.target.value))}
                        disabled={isSavingCustomSettings}
                      >
                        {[12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23].map((h) => (
                          <option key={h} value={h}>
                            {String(h).padStart(2, '0')}:00
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="drawer-control-col">
                      <label className="drawer-field-label">Intervalo Mínimo:</label>
                      <select
                        className="drawer-select"
                        value={minIntervalHours}
                        onChange={(e) => setMinIntervalHours(Number(e.target.value))}
                        disabled={isSavingCustomSettings}
                      >
                        <option value={1}>1 hora</option>
                        <option value={2}>2 horas</option>
                        <option value={3}>3 horas</option>
                        <option value={4}>4 horas</option>
                        <option value={6}>6 horas</option>
                      </select>
                    </div>
                  </div>

                  <div className="drawer-save-row">
                    <button
                      type="button"
                      className="drawer-save-settings-btn"
                      onClick={handleSaveScheduleAndQuotas}
                      disabled={isSavingCustomSettings}
                    >
                      {isSavingCustomSettings ? 'Salvando...' : '💾 Salvar Quotas e Janela'}
                    </button>
                  </div>
                </div>
              </div>

              {settingsSuccessMsg && (
                <div className="drawer-settings-feedback success">
                  ✓ {settingsSuccessMsg}
                </div>
              )}
              {settingsErrorMsg && (
                <div className="drawer-settings-feedback error">
                  ⚠️ {settingsErrorMsg}
                </div>
              )}
            </div>
          )}

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

              {/* Factual Gate Verifications */}
              <div className="info-box">
                <div className="info-box-label">Safety Gate</div>
                <div className="info-box-value mono">
                  {detail?.task_snapshot?.safety_status || execution?.gates?.safety_status || 'PENDING'}
                </div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Quality Score</div>
                <div className="info-box-value mono">
                  {detail?.task_snapshot?.quality_score !== null && detail?.task_snapshot?.quality_score !== undefined
                    ? `${detail.task_snapshot.quality_score} pts`
                    : (execution?.gates?.quality_score !== null && execution?.gates?.quality_score !== undefined
                        ? `${execution.gates.quality_score} pts`
                        : 'PENDING')}
                </div>
              </div>

              <div className="info-box">
                <div className="info-box-label">Copyright Gate</div>
                <div className="info-box-value mono">
                  {detail?.task_snapshot?.copyright_status || execution?.gates?.copyright_status || 'PENDING'}
                </div>
              </div>

              {execution?.error && (
                <div className="info-box full-width" style={{ borderColor: 'var(--status-failed)' }}>
                  <div className="info-box-label" style={{ color: 'var(--status-failed)' }}>Erro Registrado</div>
                  <div className="info-box-value" style={{ color: '#fca5a5' }}>{sanitizeDisplayText(execution.error)}</div>
                </div>
              )}

              {execution?.message && (
                <div className="info-box full-width">
                  <div className="info-box-label">Mensagem Operacional</div>
                  <div className="info-box-value">{sanitizeDisplayText(execution.message)}</div>
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
                      <strong>{sanitizeDisplayText(evt.event_type)}</strong>: {sanitizeDisplayText(evt.message) || '—'}
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
