import React, { useState } from 'react';
import FactoryLiveGraph from './FactoryLiveGraph';
import FlowAccountsSection from './FlowAccountsSection';
import ChannelCard from './ChannelCard';

/**
 * ProductionView — Visão Centralizada da Esteira de Produção & Grafo de Execução
 * Desacoplada do Dashboard principal para manter foco na renderização e tarefas ativas.
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

  return (
    <div className="v2-production-view-container">
      {/* 1. Header com controles de foco e canais na esteira */}
      <div className="v2-production-toolbar">
        <div className="v2-toolbar-left">
          <h2 className="v2-view-title">Esteira de Produção</h2>
          <span className="v2-view-subtitle">Grafo causal em tempo real e monitoramento de renderização</span>
        </div>

        <div className="v2-toolbar-right">
          {hasUserManuallySelected ? (
            <button
              type="button"
              className="v2-btn-secondary"
              onClick={onResetFocus}
              title="Voltar ao rastreamento automático do canal ativo"
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
            className="v2-btn-ghost"
            onClick={() => setShowFlowDetails(!showFlowDetails)}
          >
            {showFlowDetails ? 'Ocultar Contas Flow' : 'Visualizar Pool Flow'}
          </button>
        </div>
      </div>

      {/* 2. Seleção rápida de canais para focar no Grafo */}
      <div className="v2-channels-rail-container">
        <div className="v2-rail-header">
          <span>Selecione um canal para inspecionar o pipeline:</span>
        </div>
        <div className="v2-channels-rail">
          {channels.map((ch) => {
            const chId = ch.channel_id || ch.profile_id;
            const isFocused = (focusedChannel?.channel_id || focusedChannel?.profile_id) === chId;
            return (
              <ChannelCard
                key={chId}
                channel={ch}
                isFocused={isFocused}
                onSelectFocus={() => onSelectFocus(ch)}
                onOpenDrawer={() => onOpenDrawer(ch)}
              />
            );
          })}
        </div>
      </div>

      {/* 3. Seção colapsável de contas Flow */}
      {showFlowDetails && (
        <div className="v2-flow-section-wrapper" style={{ marginBottom: '16px' }}>
          <FlowAccountsSection flowPool={flowPool} />
        </div>
      )}

      {/* 4. Grafo Interativo Completo (12 Estágios) */}
      <div className="v2-graph-wrapper">
        <div className="v2-graph-header">
          <div className="v2-graph-title-left">
            <span className="v2-graph-icon">⚡</span>
            <span className="v2-graph-title">Pipeline em Tempo Real</span>
            {focusedChannel && (
              <span className="v2-focused-tag">
                Canal: <strong>{focusedChannel.channel_name || focusedChannel.profile_name}</strong>
              </span>
            )}
          </div>
          <span className="v2-graph-hint">Clique em qualquer nó ou tarefa para abrir o trace causal detalhado</span>
        </div>

        <FactoryLiveGraph
          channel={focusedChannel}
          onSelectChannelTask={onOpenDrawer}
        />
      </div>
    </div>
  );
}
