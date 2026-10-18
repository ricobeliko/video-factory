import React, { useState, useEffect } from 'react';
import { runFactoryCycle, getSchedulerPosts } from '../api';

/**
 * DashboardView — Visão Executiva e Painel de Controle (Shadcn Admin Zinc Style)
 * Organização em 3 níveis:
 * 1. Topo: 4 KPI Cards compactos com elevação no hover.
 * 2. Centro: Grid 2 colunas (Meus Canais + Produção em Tempo Real).
 * 3. Abaixo: Grid 2 colunas (Próximos Posts + Saúde do Sistema).
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
  const [isCycling, setIsCycling] = useState(false);
  const [cycleMsg, setCycleMsg] = useState(null);
  const [upcomingPosts, setUpcomingPosts] = useState([]);

  // Carrega agendamentos para o card de próximos posts
  useEffect(() => {
    let mounted = true;
    getSchedulerPosts()
      .then((data) => {
        if (mounted && Array.isArray(data)) {
          setUpcomingPosts(data.slice(0, 4));
        }
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, [systemStatus]);

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
      {/* 1. TOPO: 4 CARDS KPI (Estilo Shadcn Admin / Tremor) */}
      <section className="v2-kpi-grid">
        {/* KPI 1: Canais */}
        <div className="v2-kpi-card" onClick={() => onNavigate('channels')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">CANAIS ATIVOS</span>
            <span className="v2-kpi-icon">📺</span>
          </div>
          <div className="v2-kpi-val">{activeChannels}</div>
          <div className="v2-kpi-sub">
            <span className="v2-kpi-trend-pill">
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
          <div className="v2-kpi-val">
            {activeTask ? (
              <span className="v2-val-active">
                <span className="v2-indicator-dot active" /> 1 Ativo
              </span>
            ) : (
              <span className="v2-val-idle">Ocioso (Pronto)</span>
            )}
          </div>
          <div className="v2-kpi-sub">
            {activeTask ? (
              <span className="v2-text-muted">
                {activeTask.stage || 'Processando pipeline...'}
              </span>
            ) : (
              <span className="v2-text-muted">Aguardando próximo agendamento</span>
            )}
          </div>
        </div>

        {/* KPI 3: Estoque Pronto */}
        <div className="v2-kpi-card" onClick={() => onNavigate('review')} style={{ cursor: 'pointer' }}>
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">ESTOQUE PRONTO</span>
            <span className="v2-kpi-icon">📦</span>
          </div>
          <div className="v2-kpi-val">
            {totalReadyStock} <span className="v2-val-target">/ {totalTargetStock} meta</span>
          </div>
          <div className="v2-kpi-sub">
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
          <div className="v2-kpi-val v2-kpi-val-time">
            {nextPost ? (
              nextPost.scheduled_time || 'Hoje'
            ) : (
              <span className="v2-text-muted">Nenhum na fila</span>
            )}
          </div>
          <div className="v2-kpi-sub">
            {nextPost ? (
              <span className="v2-text-success">
                {nextPost.channel_name || nextPost.profile_name || 'YouTube'}
              </span>
            ) : (
              <span className="v2-text-muted">Fila de posts sincronizada</span>
            )}
          </div>
        </div>
      </section>

      {/* 2. CENTRO: GRID 2 COLUNAS (Meus Canais / Produção em Tempo Real) */}
      <div className="v2-dashboard-split">
        {/* Coluna Esquerda: Canais em Destaque */}
        <div className="v2-card-section">
          <div className="v2-section-header-row">
            <div className="v2-section-title-box">
              <h3 className="v2-section-title">Meus Canais</h3>
              <p className="v2-section-desc">Visão geral rápida de estoque e autonomia</p>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className="v2-btn-link-action"
                onClick={() => onNavigate('channels')}
              >
                Ver Todos
              </button>
              <button
                type="button"
                className="v2-btn-primary-action"
                onClick={onOpenCreateModal}
              >
                + Novo Canal
              </button>
            </div>
          </div>

          <div className="v2-channels-summary-list">
            {channels.length === 0 ? (
              <div className="v2-empty-state-compact">
                <span className="v2-empty-icon">📺</span>
                <span className="v2-empty-title">Nenhum canal cadastrado</span>
                <span className="v2-empty-desc">Crie seu primeiro canal para iniciar a produção automatizada.</span>
                <button type="button" className="v2-btn-primary-action" onClick={onOpenCreateModal} style={{ marginTop: '8px' }}>
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
                    <div className="v2-channel-stock-badge">
                      <span className="v2-stock-numbers">{ready}/{target}</span>
                      <span className="v2-stock-label">prontos</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Coluna Direita: Produção em Tempo Real */}
        <div className="v2-card-section">
          <div className="v2-section-header-row">
            <div className="v2-section-title-box">
              <h3 className="v2-section-title">Produção em Tempo Real</h3>
              <p className="v2-section-desc">Status do ciclo e pipeline ativo</p>
            </div>
            <button
              type="button"
              className="v2-btn-link-action"
              onClick={() => onNavigate('production')}
            >
              Abrir Esteira →
            </button>
          </div>

          <div className="v2-live-production-content">
            {activeTask ? (
              <div className="v2-active-task-hero">
                <div className="v2-task-badge-row">
                  <span className="v2-badge-pulse">● EM EXECUÇÃO</span>
                  <span className="v2-task-id">{activeTask.task_id}</span>
                </div>
                <h4 className="v2-task-topic">{activeTask.topic || 'Renderização em Andamento'}</h4>
                <div className="v2-task-stage-indicator">
                  <span>Etapa: <strong>{activeTask.stage || 'Iniciando'}</strong></span>
                  <span>{activeTask.progress || 0}%</span>
                </div>
                <div className="v2-progress-track">
                  <div className="v2-progress-fill" style={{ width: `${activeTask.progress || 10}%` }} />
                </div>
              </div>
            ) : (
              <div className="v2-idle-state-box">
                <span className="v2-idle-icon">⚡</span>
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

      {/* 3. ABAIXO: GRID 2 COLUNAS (Próximos Posts + Saúde do Sistema) */}
      <div className="v2-dashboard-bottom-grid">
        {/* Próximas Publicações */}
        <div className="v2-card-section">
          <div className="v2-section-header-row">
            <div className="v2-section-title-box">
              <h3 className="v2-section-title">Próximos Posts Agendados</h3>
              <p className="v2-section-desc">Fila gerenciada pelo Scheduler Worker</p>
            </div>
            <button
              type="button"
              className="v2-btn-link-action"
              onClick={() => onNavigate('schedules')}
            >
              Ver Todos →
            </button>
          </div>

          <div className="v2-upcoming-list">
            {upcomingPosts.length === 0 ? (
              <div className="v2-text-muted" style={{ padding: '16px 0', fontSize: '13px' }}>
                Nenhum vídeo agendado na fila. Os vídeos aprovados em estoque são agendados automaticamente nas janelas configuradas.
              </div>
            ) : (
              upcomingPosts.map((post, idx) => (
                <div key={post.post_id || idx} className="v2-upcoming-row">
                  <span className="v2-time-badge">{post.scheduled_time || 'Programado'}</span>
                  <div className="v2-upcoming-info">
                    <span className="v2-upcoming-title">{post.title || post.topic || 'Vídeo sem título'}</span>
                    <span className="v2-upcoming-chan">{post.channel_name || post.profile_name || 'Canal'} • {post.platform || 'YouTube'}</span>
                  </div>
                  <span className="v2-status-pill-subtle">Agendado</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Saúde do Sistema (Compacta) */}
        <div className="v2-card-section">
          <div className="v2-section-header-row">
            <div className="v2-section-title-box">
              <h3 className="v2-section-title">Saúde do Sistema</h3>
              <p className="v2-section-desc">Estado operacional dos serviços de segundo plano</p>
            </div>
            <button
              type="button"
              className="v2-btn-link-action"
              onClick={() => onNavigate('settings')}
            >
              Diagnóstico →
            </button>
          </div>

          <div className="v2-health-indicators-grid">
            <div className="v2-health-item">
              <span className={`v2-indicator-dot ${!isPaused ? 'active' : 'warning'}`} />
              <div>
                <div className="v2-health-name">Fábrica</div>
                <div className="v2-health-val">{!isPaused ? 'Online' : 'Pausada'}</div>
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
              <span className={`v2-indicator-dot ${systemStatus?.auto_publish ? 'active' : 'neutral'}`} />
              <div>
                <div className="v2-health-name">Auto Publish</div>
                <div className="v2-health-val">{systemStatus?.auto_publish ? 'Ativo' : 'Off'}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
