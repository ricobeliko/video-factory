import React, { useState } from 'react';
import FactoryLiveGraph from './FactoryLiveGraph';
import FlowAccountsSection from './FlowAccountsSection';
import { runFactoryCycle } from '../api';

/**
 * ProductionView — Central de Comando da Esteira de Produção (V2.16)
 * Arquitetura Master-Detail: Trilha operacional de canais à esquerda
 * e Deck de telemetria, pipeline stepper e grafo causal à direita.
 */
export default function ProductionView({
  channels = [],
  focusedChannel,
  hasUserManuallySelected,
  onSelectFocus,
  onResetFocus,
  onOpenDrawer,
  flowPool,
  isApiOnline,
}) {
  const [showFlowDetails, setShowFlowDetails] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [isTriggering, setIsTriggering] = useState(false);
  const [actionFeedback, setActionFeedback] = useState(null);

  // Filtra canais na trilha esquerda
  const filteredChannels = channels.filter((ch) => {
    const term = (searchTerm || '').toLowerCase();
    const nameStr = (ch.name || ch.profile_name || ch.channel_name || '').toLowerCase();
    const nicheStr = (ch.niche || '').toLowerCase();
    return !term || nameStr.includes(term) || nicheStr.includes(term);
  });

  // Canal em foco atual (se nenhum focado manualmente, usa o primeiro da lista)
  const currentChannel = focusedChannel || channels[0] || null;
  const currentChId = currentChannel?.channel_id || currentChannel?.profile_id || currentChannel?.id;

  // Disparo manual de ciclo para o canal selecionado
  const handleTriggerCycle = async () => {
    if (!currentChId || isTriggering) return;
    setIsTriggering(true);
    setActionFeedback(null);
    try {
      const res = await runFactoryCycle({
        profile_id: currentChId,
        force: true,
        one_shot: true,
      });
      setActionFeedback({
        type: 'success',
        msg: res?.message || `Ciclo de produção iniciado para "${currentChannel?.name || currentChannel?.profile_name}".`,
      });
      setTimeout(() => setActionFeedback(null), 5000);
    } catch (err) {
      setActionFeedback({
        type: 'error',
        msg: err.message || 'Falha ao disparar ciclo de produção.',
      });
      setTimeout(() => setActionFeedback(null), 6000);
    } finally {
      setIsTriggering(false);
    }
  };

  const getFormatBadge = (fmt) => {
    if (fmt === 'quiz_paper') return { label: 'Quiz Papel P1.3', color: '#f59e0b' };
    if (fmt === 'quiz_dilemma') return { label: 'Quiz Dilema Q0-R', color: '#8b5cf6' };
    return { label: 'Tradicional', color: '#10b981' };
  };

  const currentFmt = currentChannel?.settings?.editorial?.video_format || currentChannel?.settings?.video_format || 'traditional';
  const badge = getFormatBadge(currentFmt);

  // Status da tarefa ativa do canal selecionado
  const activeTask = currentChannel?.active_task || null;
  const isRunning = Boolean(activeTask || currentChannel?.pending_processing > 0);

  // Mapeamento dos 5 estágios principais do pipeline
  const pipelineStages = [
    { id: 'script', label: '1. Roteiro & Tema', desc: 'LLM & Diretrizes' },
    { id: 'voice', label: '2. Narração', desc: 'Azure TTS pt-BR' },
    { id: 'visual', label: '3. Clipes & Flow', desc: 'Google Flow / Stock' },
    { id: 'montage', label: '4. Montagem & BGM', desc: 'Render FFmpeg' },
    { id: 'ready', label: '5. Estoque Pronto', desc: 'Buffer Seguro' },
  ];

  return (
    <div className="v2-command-center-container">
      {/* 1. Toolbar Superior */}
      <div className="v2-command-toolbar">
        <div className="v2-toolbar-left">
          <div className="v2-command-badge">CENTRAL DE OPERAÇÕES</div>
          <h2 className="v2-view-title">Esteira de Produção & Telemetria</h2>
          <span className="v2-view-subtitle">
            Pipeline causal em tempo real, monitoramento de renderização e estado dos canais
          </span>
        </div>

        <div className="v2-toolbar-right">
          {hasUserManuallySelected ? (
            <button
              type="button"
              className="v2-btn-secondary"
              onClick={onResetFocus}
              title="Voltar ao rastreamento automático do canal em atividade"
            >
              🎯 Foco Manual [Voltar para Auto]
            </button>
          ) : (
            <span className="v2-badge-pill subtle-green">
              ● Rastreamento Dinâmico Ativo
            </span>
          )}

          <button
            type="button"
            className={`v2-btn-ghost ${showFlowDetails ? 'active' : ''}`}
            onClick={() => setShowFlowDetails(!showFlowDetails)}
          >
            {showFlowDetails ? '✕ Ocultar Pool Flow' : '✨ Visualizar Pool Flow'}
          </button>
        </div>
      </div>

      {actionFeedback && (
        <div className={`v2-alert-feedback ${actionFeedback.type === 'success' ? 'success' : 'error'}`}>
          {actionFeedback.msg}
        </div>
      )}

      {/* Seção colapsável de contas Flow */}
      {showFlowDetails && (
        <div className="v2-flow-section-wrapper" style={{ marginBottom: '16px' }}>
          <FlowAccountsSection flowPool={flowPool} />
        </div>
      )}

      {/* 2. Layout Master-Detail */}
      <div className="v2-master-detail-layout">
        {/* Painel Master (Trilha Esquerda de Canais) */}
        <aside className="v2-master-channels-rail">
          <div className="v2-rail-top-bar">
            <span className="v2-rail-title">Canais Operacionais ({channels.length})</span>
          </div>

          <div className="v2-rail-search">
            <input
              type="text"
              className="v2-rail-input"
              placeholder="Filtrar canais..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          <div className="v2-rail-list">
            {filteredChannels.length === 0 ? (
              <div className="v2-rail-empty">Nenhum canal encontrado.</div>
            ) : (
              filteredChannels.map((ch) => {
                const chId = ch.channel_id || ch.profile_id || ch.id;
                const isSelected = chId === currentChId;
                const chFmt = ch.settings?.editorial?.video_format || ch.settings?.video_format || 'traditional';
                const chBadge = getFormatBadge(chFmt);
                const hasTask = Boolean(ch.active_task || ch.pending_processing > 0);

                return (
                  <div
                    key={chId}
                    className={`v2-rail-card ${isSelected ? 'active' : ''}`}
                    onClick={() => onSelectFocus(ch)}
                  >
                    <div className="v2-rail-card-header">
                      <div className="v2-rail-card-title-group">
                        <span className={`v2-live-indicator-dot ${hasTask ? 'running' : 'idle'}`} />
                        <strong className="v2-rail-card-name">{ch.name || ch.profile_name}</strong>
                      </div>
                      <span
                        className="v2-rail-fmt-tag"
                        style={{ color: chBadge.color, borderColor: `${chBadge.color}40` }}
                      >
                        {chBadge.label}
                      </span>
                    </div>

                    <div className="v2-rail-card-body">
                      <span className="v2-rail-niche">{ch.niche || 'Nicho Geral'}</span>
                      <span className="v2-rail-stock">
                        Estoque: <strong>{ch.ready_stock || 0}/{ch.target_stock || 3}</strong>
                      </span>
                    </div>

                    <div className="v2-rail-card-footer">
                      <span className={`v2-rail-status-pill ${hasTask ? 'running' : 'idle'}`}>
                        {hasTask ? '⚡ Em Produção' : '○ Em Espera'}
                      </span>
                      <span className="v2-rail-auto-tag">
                        {ch.autonomous_enabled ? 'Autônomo' : 'Manual'}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Painel Detail (Command Deck Direito) */}
        <main className="v2-detail-command-deck">
          {currentChannel ? (
            <>
              {/* Barra de Comando do Canal Selecionado */}
              <div className="v2-deck-channel-bar">
                <div className="v2-deck-channel-identity">
                  <div className="v2-deck-avatar">
                    {(currentChannel.name || currentChannel.profile_name)?.slice(0, 2).toUpperCase() || 'VF'}
                  </div>
                  <div>
                    <div className="v2-deck-title-row">
                      <h3 className="v2-deck-title">{currentChannel.name || currentChannel.profile_name}</h3>
                      <span
                        className="v2-deck-badge-fmt"
                        style={{ color: badge.color, backgroundColor: `${badge.color}15`, borderColor: `${badge.color}40` }}
                      >
                        {badge.label}
                      </span>
                      {currentChannel.settings?.visual?.flow_enabled && (
                        <span className="v2-card-flow-tag">✨ Google Flow</span>
                      )}
                    </div>
                    <span className="v2-deck-subtitle">
                      ID: <code>{currentChId}</code> | Nicho: {currentChannel.niche || 'Geral'} | Idioma: {currentChannel.language || 'pt-BR'}
                    </span>
                  </div>
                </div>

                <div className="v2-deck-actions">
                  <button
                    type="button"
                    className="v2-btn-run-deck"
                    disabled={isTriggering}
                    onClick={handleTriggerCycle}
                    title="Disparar novo ciclo de produção para este canal"
                  >
                    {isTriggering ? 'Disparando...' : '▶ Executar Ciclo Agora'}
                  </button>

                  <button
                    type="button"
                    className="v2-btn-trace-deck"
                    onClick={() => onOpenDrawer(currentChannel)}
                    title="Abrir trace causal com histórico de eventos e diagnósticos"
                  >
                    🔍 Inspecionar Trace Causal
                  </button>
                </div>
              </div>

              {/* Pipeline Stepper Horizontal */}
              <div className="v2-pipeline-stepper-card">
                <div className="v2-stepper-header">
                  <span className="v2-stepper-title">Fluxo Operacional do Pipeline</span>
                  <span className="v2-stepper-status-text">
                    {isRunning ? 'Pipeline em execução ativa' : 'Pronto para próximo ciclo'}
                  </span>
                </div>

                <div className="v2-pipeline-stepper">
                  {pipelineStages.map((st, sIdx) => {
                    const isStepActive = isRunning && sIdx === 1; // Visualização indicativa
                    return (
                      <div
                        key={st.id}
                        className={`v2-stepper-node ${isStepActive ? 'active' : ''}`}
                      >
                        <div className="v2-stepper-node-circle">
                          {isStepActive ? '⚡' : sIdx + 1}
                        </div>
                        <div className="v2-stepper-node-text">
                          <strong className="v2-stepper-node-name">{st.label}</strong>
                          <span className="v2-stepper-node-desc">{st.desc}</span>
                        </div>
                        {sIdx < pipelineStages.length - 1 && (
                          <div className="v2-stepper-connector" />
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Telemetria da Tarefa Ativa */}
              <div className="v2-task-telemetry-card">
                <div className="v2-telemetry-header">
                  <span className="v2-telemetry-badge">
                    {isRunning ? '● MONITORANDO ATIVIDADE' : '○ STANDBY OPERACIONAL'}
                  </span>
                  <span className="v2-telemetry-sub">Canal {currentChannel.name || currentChannel.profile_name}</span>
                </div>

                {isRunning ? (
                  <div className="v2-telemetry-active-grid">
                    <div className="v2-telemetry-item">
                      <span className="v2-telemetry-lbl">ID da Tarefa:</span>
                      <strong className="v2-telemetry-val">task_{currentChId}_active</strong>
                    </div>
                    <div className="v2-telemetry-item">
                      <span className="v2-telemetry-lbl">Provedor Visual:</span>
                      <strong className="v2-telemetry-val">
                        {currentChannel.settings?.visual?.flow_enabled ? 'Google Flow Pool' : 'Pexels / Pixabay'}
                      </strong>
                    </div>
                    <div className="v2-telemetry-item">
                      <span className="v2-telemetry-lbl">Voz do Narrador:</span>
                      <strong className="v2-telemetry-val">
                        {currentChannel.settings?.voice?.voice_name || 'pt-BR-AntonioNeural'}
                      </strong>
                    </div>
                    <div className="v2-telemetry-item">
                      <span className="v2-telemetry-lbl">Status:</span>
                      <strong className="v2-telemetry-val" style={{ color: '#10b981' }}>
                        Processando em segundo plano
                      </strong>
                    </div>
                  </div>
                ) : (
                  <div className="v2-telemetry-idle-box">
                    <span className="v2-telemetry-idle-icon">⏱️</span>
                    <div>
                      <strong style={{ color: '#f8fafc', fontSize: '13px' }}>Canal em Espera Operacional</strong>
                      <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: '#94a3b8' }}>
                        Estoque atual: {currentChannel.ready_stock || 0} de {currentChannel.target_stock || 3} vídeos prontos. O canal está pronto para disparar um novo ciclo a qualquer momento.
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* Grafo Interativo 12-Nós em Largura Completa */}
              <div className="v2-graph-deck-card">
                <div className="v2-graph-deck-header">
                  <div className="v2-graph-deck-title-group">
                    <span className="v2-graph-icon">⚡</span>
                    <strong className="v2-graph-deck-title">Grafo de Dependência Causal (12 Estágios)</strong>
                  </div>
                  <span className="v2-graph-deck-hint">
                    Clique em qualquer nó para inspecionar os detalhes e logs no Drawer lateral
                  </span>
                </div>

                <div className="v2-graph-deck-canvas">
                  <FactoryLiveGraph
                    channel={currentChannel}
                    onSelectChannelTask={onOpenDrawer}
                  />
                </div>
              </div>
            </>
          ) : (
            <div className="v2-deck-empty-state">
              <span>Selecione um canal na trilha esquerda para monitorar a esteira.</span>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
