import React, { useEffect, useState } from 'react';
import { getSchedulerPosts, runFactoryCycle } from '../api';

/**
 * DashboardView — Painel Operacional Principal (Redesign V2)
 * Inspirado nas diretrizes Tremor ("show the data, hide the chrome") e shadcn-admin.
 * Responde de imediato:
 * 1. A fábrica está funcionando?
 * 2. Quantos canais ativos?
 * 3. Quantos vídeos em produção?
 * 4. Quantos vídeos prontos em estoque?
 * 5. O que está agendado e se há algum problema?
 */
export default function DashboardView({
  channels = [],
  systemStatus,
  liveExecutions,
  onOpenChannel,
  onOpenCreateModal,
  onNavigate,
  onRefresh,
}) {
  const [upcomingPosts, setUpcomingPosts] = useState([]);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [cycleMsg, setCycleMsg] = useState(null);
  const [isCycling, setIsCycling] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function loadUpcoming() {
      setLoadingPosts(true);
      try {
        const res = await getSchedulerPosts(5);
        if (mounted && res && Array.isArray(res.upcoming_posts)) {
          setUpcomingPosts(res.upcoming_posts);
        }
      } catch (err) {
        // Silencioso em caso de mock ou erro de rede
      } finally {
        if (mounted) setLoadingPosts(false);
      }
    }
    loadUpcoming();
    return () => { mounted = false; };
  }, []);

  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');
  const activeChannels = channels.length;
  const autonomousChannels = channels.filter(c => c.autonomous_enabled).length;

  // Calcula estoque pronto e metas consolidadas
  const totalReadyStock = channels.reduce((sum, c) => sum + (c.ready_stock || c.stats?.ready_stock || 0), 0);
  const totalTargetStock = channels.reduce((sum, c) => sum + (c.target_ready_stock || 4), 0);
  const stockProgress = totalTargetStock > 0 ? Math.min(100, Math.round((totalReadyStock / totalTargetStock) * 100)) : 0;

  // Identifica se há tarefa ativa
  const runningChannel = channels.find(c => c.execution?.status === 'RUNNING' || c.status === 'RUNNING');
  const activeTask = runningChannel?.execution || null;

  // Próximo agendamento
  const nextPost = upcomingPosts.length > 0 ? upcomingPosts[0] : null;

  const handleQuickCycle = async () => {
    setIsCycling(true);
    setCycleMsg(null);
    try {
      const res = await runFactoryCycle({ force: true, oneShot: true });
      setCycleMsg({ type: 'success', text: res.message || 'Ciclo de produção disparado com sucesso!' });
      if (onRefresh) onRefresh();
    } catch (err) {
      setCycleMsg({ type: 'error', text: err.message || 'Falha ao disparar ciclo.' });
    } finally {
      setIsCycling(false);
      setTimeout(() => setCycleMsg(null), 5000);
    }
  };

  return (
    <div className="v2-dashboard-container">
      {/* 1. TOPO: 4 CARDS KPI (Estilo Tremor) */}
      <section className="v2-kpi-grid">
        {/* KPI 1: Canais */}
        <div className="v2-kpi-card" onClick={() => onNavigate('channels')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">CANAIS ATIVOS</span>
            <span className="v2-kpi-icon">📺</span>
          </div>
          <div className="v2-kpi-metric">{activeChannels}</div>
          <div className="v2-kpi-context">
            <span className="v2-badge-pill subtle-blue">
              {autonomousChannels} no modo autônomo
            </span>
          </div>
        </div>

        {/* KPI 2: Produção */}
        <div className="v2-kpi-card" onClick={() => onNavigate('production')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">EM PRODUÇÃO</span>
            <span className="v2-kpi-icon">🎬</span>
          </div>
          <div className="v2-kpi-metric">
            {activeTask ? (
              <span style={{ color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="v2-pulse-dot active" /> 1 Ativo
              </span>
            ) : (
              <span style={{ color: '#94a3b8', fontSize: '20px' }}>Ocioso (Pronto)</span>
            )}
          </div>
          <div className="v2-kpi-context">
            {activeTask ? (
              <span className="v2-kpi-subtext">
                {activeTask.stage || 'Processando pipeline...'}
              </span>
            ) : (
              <span className="v2-kpi-subtext">Aguardando próximo agendamento</span>
            )}
          </div>
        </div>

        {/* KPI 3: Estoque Pronto */}
        <div className="v2-kpi-card" onClick={() => onNavigate('review')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">ESTOQUE PRONTO</span>
            <span className="v2-kpi-icon">📦</span>
          </div>
          <div className="v2-kpi-metric">
            {totalReadyStock} <span style={{ fontSize: '14px', color: '#64748b', fontWeight: 500 }}>/ {totalTargetStock} meta</span>
          </div>
          <div className="v2-kpi-context">
            <div className="v2-progress-track">
              <div className="v2-progress-fill" style={{ width: `${stockProgress}%` }} />
            </div>
          </div>
        </div>

        {/* KPI 4: Próximo Agendamento */}
        <div className="v2-kpi-card" onClick={() => onNavigate('schedules')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">PRÓXIMO AGENDAMENTO</span>
            <span className="v2-kpi-icon">📅</span>
          </div>
          <div className="v2-kpi-metric" style={{ fontSize: nextPost ? '18px' : '16px' }}>
            {nextPost ? (
              nextPost.scheduled_time || 'Hoje'
            ) : (
              <span style={{ color: '#64748b' }}>Nenhum na fila</span>
            )}
          </div>
          <div className="v2-kpi-context">
            {nextPost ? (
              <span className="v2-kpi-subtext" style={{ color: '#34d399' }}>
                {nextPost.channel_name || nextPost.profile_name || 'YouTube'}
              </span>
            ) : (
              <span className="v2-kpi-subtext">Fila de posts sincronizada</span>
            )}
          </div>
        </div>
      </section>

      {/* 2. CENTRO: GRID 2 COLUNAS (60% Meus Canais / 40% Atividade Recente) */}
      <div className="v2-dashboard-split">
        {/* Coluna Esquerda: Canais em Destaque */}
        <div className="v2-dashboard-card v2-channels-summary-card">
          <div className="v2-card-header">
            <div>
              <h3 className="v2-card-title">Meus Canais</h3>
              <p className="v2-card-subtitle">Visão geral rápida de estoque e autonomia</p>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="v2-btn-secondary"
                onClick={() => onNavigate('channels')}
              >
                Ver Todos
              </button>
              <button
                type="button"
                className="v2-btn-primary"
                onClick={onOpenCreateModal}
              >
                + Novo Canal
              </button>
            </div>
          </div>

          <div className="v2-channels-summary-list">
            {channels.length === 0 ? (
              <div className="v2-empty-state">
                <span className="v2-empty-icon">📺</span>
                <p className="v2-empty-title">Nenhum canal cadastrado</p>
                <p className="v2-empty-desc">Crie seu primeiro canal para iniciar a produção automatizada.</p>
                <button type="button" className="v2-btn-primary" onClick={onOpenCreateModal}>
                  Criar Canal Agora
                </button>
              </div>
            ) : (
              channels.slice(0, 4).map((ch) => {
                const pId = ch.channel_id || ch.profile_id;
                const ready = ch.ready_stock || ch.stats?.ready_stock || 0;
                const target = ch.target_ready_stock || 4;
                const formatLabel = ch.video_format || ch.format || 'Tradicional';

                return (
                  <div key={pId} className="v2-channel-summary-row" onClick={() => onOpenChannel(ch)}>
                    <div className="v2-channel-avatar">
                      {(ch.channel_name || ch.profile_name || 'C')[0].toUpperCase()}
                    </div>
                    <div className="v2-channel-info">
                      <span className="v2-channel-name">{ch.channel_name || ch.profile_name}</span>
                      <div className="v2-channel-meta-tags">
                        <span className="v2-tag-badge">{formatLabel}</span>
                        <span className={`v2-tag-badge ${ch.autonomous_enabled ? 'tag-auto' : 'tag-manual'}`}>
                          {ch.autonomous_enabled ? 'AUTO' : 'MANUAL'}
                        </span>
                      </div>
                    </div>
                    <div className="v2-channel-stock-gauge">
                      <span className="v2-gauge-label">{ready}/{target} prontos</span>
                      <div className="v2-mini-track">
                        <div
                          className="v2-mini-fill"
                          style={{ width: `${Math.min(100, Math.round((ready / target) * 100))}%` }}
                        />
                      </div>
                    </div>
                    <button
                      type="button"
                      className="v2-btn-ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenChannel(ch);
                      }}
                      title="Abrir Channel Workspace"
                    >
                      Abrir →
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Coluna Direita: Atividade de Produção & Despacho */}
        <div className="v2-dashboard-card v2-activity-card">
          <div className="v2-card-header">
            <div>
              <h3 className="v2-card-title">Produção em Tempo Real</h3>
              <p className="v2-card-subtitle">Status do ciclo e pipeline ativo</p>
            </div>
            <button
              type="button"
              className="v2-btn-secondary"
              onClick={() => onNavigate('production')}
            >
              Abrir Esteira →
            </button>
          </div>

          <div className="v2-activity-content">
            {activeTask ? (
              <div className="v2-active-task-hero">
                <div className="v2-task-badge-row">
                  <span className="v2-badge-pulse">● Gerando Agora</span>
                  <span className="v2-task-id">ID: {activeTask.task_id?.slice(0, 8)}...</span>
                </div>
                <h4 className="v2-task-topic">{activeTask.topic || 'Renderizando vídeo selecionado...'}</h4>
                <div className="v2-task-stage-indicator">
                  <span>Etapa: <strong>{activeTask.stage || 'Montagem de Cenas'}</strong></span>
                  <span>{activeTask.progress || 45}%</span>
                </div>
                <div className="v2-progress-track" style={{ height: '8px' }}>
                  <div
                    className="v2-progress-fill"
                    style={{ width: `${activeTask.progress || 45}%`, backgroundColor: '#38bdf8' }}
                  />
                </div>
              </div>
            ) : (
              <div className="v2-idle-state-box">
                <div className="v2-idle-icon">⚡</div>
                <h4>Fábrica Ociosa & Pronta</h4>
                <p>Nenhuma tarefa de renderização em andamento. Os canais em modo autônomo monitoram seu estoque.</p>
                <button
                  type="button"
                  className="v2-btn-cycle-action"
                  onClick={handleQuickCycle}
                  disabled={isCycling || isPaused}
                >
                  {isCycling ? 'Disparando Ciclo...' : '⚡ Executar Ciclo de Produção'}
                </button>
                {cycleMsg && (
                  <div className={`v2-cycle-alert ${cycleMsg.type}`}>
                    {cycleMsg.text}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3. INFERIOR: GRID 2 COLUNAS (50% Próximos Posts / 50% Saúde do Sistema) */}
      <div className="v2-dashboard-bottom-grid">
        {/* Próximas Publicações */}
        <div className="v2-dashboard-card">
          <div className="v2-card-header">
            <div>
              <h3 className="v2-card-title">Próximos Posts Agendados</h3>
              <p className="v2-card-subtitle">Fila gerenciada pelo Scheduler Worker</p>
            </div>
            <button
              type="button"
              className="v2-btn-ghost"
              onClick={() => onNavigate('schedules')}
            >
              Ver Todos →
            </button>
          </div>

          <div className="v2-upcoming-list">
            {upcomingPosts.length === 0 ? (
              <p className="v2-empty-inline">
                Nenhum vídeo agendado na fila. Os vídeos aprovados em estoque são agendados automaticamente nas janelas configuradas.
              </p>
            ) : (
              upcomingPosts.slice(0, 3).map((post, idx) => (
                <div key={post.id || idx} className="v2-upcoming-row">
                  <div className="v2-upcoming-time">
                    <span className="v2-time-badge">{post.scheduled_time || 'Programado'}</span>
                  </div>
                  <div className="v2-upcoming-info">
                    <span className="v2-upcoming-title">{post.title || post.task_topic || 'Vídeo Homologado'}</span>
                    <span className="v2-upcoming-chan">{post.channel_name || 'YouTube'}</span>
                  </div>
                  <div className="v2-upcoming-status">
                    <span className="v2-status-pill-subtle">Agendado</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Saúde do Sistema & Diagnóstico */}
        <div className="v2-dashboard-card">
          <div className="v2-card-header">
            <div>
              <h3 className="v2-card-title">Saúde do Sistema</h3>
              <p className="v2-card-subtitle">Estado operacional dos serviços de segundo plano</p>
            </div>
            <button
              type="button"
              className="v2-btn-ghost"
              onClick={() => onNavigate('settings')}
            >
              Diagnóstico →
            </button>
          </div>

          <div className="v2-health-indicators-grid">
            <div className="v2-health-item">
              <span className={`v2-indicator-dot ${isPaused ? 'inactive' : 'active'}`} />
              <div>
                <div className="v2-health-name">Fábrica</div>
                <div className="v2-health-val">{isPaused ? 'Pausada' : 'Online'}</div>
              </div>
            </div>

            <div className="v2-health-item">
              <span className={`v2-indicator-dot ${systemStatus?.worker_running ? 'active' : 'inactive'}`} />
              <div>
                <div className="v2-health-name">Worker Pipeline</div>
                <div className="v2-health-val">{systemStatus?.worker_running ? 'Ativo' : 'Parado'}</div>
              </div>
            </div>

            <div className="v2-health-item">
              <span className={`v2-indicator-dot ${systemStatus?.scheduler_running ? 'active' : 'inactive'}`} />
              <div>
                <div className="v2-health-name">Scheduler</div>
                <div className="v2-health-val">{systemStatus?.scheduler_running ? 'Ativo' : 'Parado'}</div>
              </div>
            </div>

            <div className="v2-health-item">
              <span className={`v2-indicator-dot ${systemStatus?.auto_publish_enabled ? 'active' : 'neutral'}`} />
              <div>
                <div className="v2-health-name">Auto Publish</div>
                <div className="v2-health-val">{systemStatus?.auto_publish_enabled ? 'Ativo' : 'Off'}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
