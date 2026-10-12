import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import AgentAvatar from '../AgentAvatar';
import { getAgentOps } from '../../api';

const ACTOR_PERSONAS = {
  ARCHITECT: {
    avatar: '🧠',
    code: 'ARC',
    name: 'OpenAI Architect',
    role: 'Planejamento Arquitetural',
    accentColor: '#8b5cf6',
  },
  EXECUTOR: {
    avatar: '⚡',
    code: 'EXE',
    name: 'Antigravity',
    role: 'Executor de Código',
    accentColor: '#06b6d4',
  },
  VALIDATOR: {
    avatar: '🛡️',
    code: 'VAL',
    name: 'Bridge Validator',
    role: 'Validação & Build',
    accentColor: '#10b981',
  },
  HUMAN: {
    avatar: '👤',
    code: 'HUM',
    name: 'Operador Humano',
    role: 'Autoridade de Fábrica',
    accentColor: '#f59e0b',
  },
  SYSTEM: {
    avatar: '⚙️',
    code: 'SYS',
    name: 'Bridge System',
    role: 'Ciclo de Vida',
    accentColor: '#64748b',
  },
};

/**
 * AgentOpsView — AI Operations Room (Agent Ops V1.1).
 * Features:
 * - Current Mission Card with factual telemetry (task_id, cycle, elapsed, branch, conv_id).
 * - 4-Actor Operational Deck (Architect, Executor, Validator, Human).
 * - Honest Architect offline display ("OpenAI Architect será conectado na V2").
 * - Sanitized chronological conversation/activity timeline feed.
 * - Dynamic filtering by Actor and auto-scroll control.
 * - Lightweight 2-second polling loop active ONLY while view is mounted.
 * - Prefers-reduced-motion safe styling.
 */
export default function AgentOpsView() {
  const [telemetry, setTelemetry] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isApiOnline, setIsApiOnline] = useState(true);
  const [lastPollTime, setLastPollTime] = useState(null);
  const [actorFilter, setActorFilter] = useState('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedEvents, setExpandedEvents] = useState({});

  const timelineEndRef = useRef(null);
  const timelineContainerRef = useRef(null);

  // Polling loop — runs every 2s strictly while Agent Ops is open
  const fetchTelemetry = useCallback(async () => {
    try {
      const data = await getAgentOps();
      setTelemetry(data);
      setIsApiOnline(true);
      setLastPollTime(new Date());
    } catch (err) {
      console.warn('Agent Ops poll failed:', err.message);
      setIsApiOnline(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 2000);
    return () => clearInterval(interval);
  }, [fetchTelemetry]);

  // Handle auto-scroll
  useEffect(() => {
    if (autoScroll && timelineEndRef.current) {
      timelineEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [telemetry?.events, autoScroll]);

  // Detect user manual scroll up to temporarily pause auto-scroll
  const handleScroll = () => {
    if (!timelineContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = timelineContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 40;
    if (!isAtBottom && autoScroll) {
      setAutoScroll(false);
    }
  };

  const toggleEventExpand = (id) => {
    setExpandedEvents((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const mission = telemetry?.mission;
  const isConnected = Boolean(telemetry?.connected);
  const actors = telemetry?.actors || {};
  const events = telemetry?.events || [];

  // Filter events by actor
  const filteredEvents = useMemo(() => {
    if (actorFilter === 'ALL') return events;
    return events.filter((e) => e.actor === actorFilter);
  }, [events, actorFilter]);

  // Status badge styling helper
  const getStatusBadgeClass = (status) => {
    const s = String(status || '').toUpperCase();
    if (s.includes('WORKING') || s.includes('RUNNING') || s.includes('VALIDATING')) return 'status-pulse-cyan';
    if (s.includes('SUCCESS') || s.includes('PASSED') || s.includes('COMPLETE')) return 'status-badge-green';
    if (s.includes('BLOCKED')) return 'status-badge-gold';
    if (s.includes('FAILED') || s.includes('ERROR')) return 'status-badge-red';
    return 'status-badge-neutral';
  };

  return (
    <div className="agent-ops-room">
      {/* 1. Header Bar for Ops Room */}
      <div className="ops-header-bar">
        <div className="ops-title-cluster">
          <div className="ops-icon-orb">
            <span className="ops-icon">🤖</span>
            <span className={`ops-live-dot ${isConnected ? 'online' : 'offline'}`} />
          </div>
          <div>
            <div className="ops-title-row">
              <h1 className="ops-title">AGENT OPS CONTROL CENTER</h1>
              <span className="ops-version-tag">V1.1 LIVE TELEMETRY</span>
              <span className={`ops-bridge-pill ${isConnected ? 'connected' : 'disconnected'}`}>
                {isConnected ? 'BRIDGE CONNECTED' : 'BRIDGE DISCONNECTED'}
              </span>
            </div>
            <p className="ops-subtitle">
              Observabilidade em tempo real de agentes autônomos, execução de ferramentas e validação de ciclo.
            </p>
          </div>
        </div>

        <div className="ops-meta-controls">
          <div className="ops-poll-info">
            <span className="ops-poll-label">Frequência:</span>
            <span className="ops-poll-val">2.0s</span>
            <span className="ops-poll-sep">·</span>
            <span className="ops-poll-label">Último sync:</span>
            <span className="ops-poll-val">
              {lastPollTime ? lastPollTime.toLocaleTimeString() : '...'}
            </span>
          </div>
          <button
            type="button"
            className="ops-refresh-btn"
            onClick={fetchTelemetry}
            title="Atualizar telemetria do Bridge"
          >
            ↻ Sincronizar
          </button>
        </div>
      </div>

      {!isApiOnline && (
        <div className="ops-warning-banner">
          <span>⚠️ <strong>Aviso:</strong> Falha na comunicação com o backend (/api/v2/agent-ops). Exibindo último estado em cache.</span>
        </div>
      )}

      {/* 2. Current Mission Card */}
      <section className="ops-mission-card">
        <div className="mission-card-header">
          <div className="mission-header-left">
            <span className="mission-section-badge">MISSÃO ATIVA</span>
            <h2 className="mission-task-id">{mission?.task_id || 'Nenhuma missão em execução'}</h2>
          </div>
          <div className="mission-header-right">
            <span className={`mission-status-pill ${getStatusBadgeClass(mission?.status)}`}>
              {mission?.status || 'IDLE'}
            </span>
            {mission?.is_blocked_human && (
              <span className="mission-blocked-badge">
                ⚠️ BLOCKED_HUMAN — Ação Humana Necessária
              </span>
            )}
          </div>
        </div>

        <div className="mission-metrics-grid">
          <div className="mission-metric-item">
            <span className="metric-label">CICLO ATUAL</span>
            <span className="metric-value">#{mission?.cycle ?? '—'}</span>
            <span className="metric-sub">Ciclo autônomo</span>
          </div>

          <div className="mission-metric-item">
            <span className="metric-label">TEMPO DECORRIDO</span>
            <span className="metric-value font-mono">
              {mission?.elapsed_formatted || '—'}
            </span>
            <span className="metric-sub">
              {mission?.started_at ? `Início: ${String(mission.started_at).slice(11, 19)}` : 'Início desconhecido'}
            </span>
          </div>

          <div className="mission-metric-item">
            <span className="metric-label">GIT BRANCH</span>
            <span className="metric-value font-mono branch-name" title={mission?.branch || ''}>
              {mission?.branch || '—'}
            </span>
            <span className="metric-sub">Ambiente DEV isolado</span>
          </div>

          <div className="mission-metric-item">
            <span className="metric-label">CONVERSATION ID</span>
            <span className="metric-value font-mono conv-id" title={mission?.conversation_id || ''}>
              {mission?.conversation_id_short || '—'}
            </span>
            <span className="metric-sub">Sessão Antigravity</span>
          </div>
        </div>
      </section>

      {/* 3. 4-Actor Operational Roles Deck */}
      <section className="ops-actors-section">
        <div className="section-title-bar">
          <span className="section-title-icon">👥</span>
          <span className="section-title">Central de Papéis Operacionais</span>
          <span className="channels-count-pill">4 Entidades</span>
        </div>

        <div className="actors-quad-grid">
          {/* ARCHITECT (Violet) */}
          <div className="actor-card actor-architect">
            <div className="actor-card-header">
              <AgentAvatar
                persona={ACTOR_PERSONAS.ARCHITECT}
                accentColor="#8b5cf6"
                isRunning={false}
                size="md"
              />
              <div className="actor-identity">
                <span className="actor-role-tag role-violet">ARCHITECT</span>
                <h3 className="actor-name">OpenAI Architect</h3>
              </div>
              <span className="actor-status-pill pill-violet-offline">OFFLINE</span>
            </div>
            <div className="actor-card-body">
              <div className="actor-notice-box notice-violet">
                <span className="notice-icon">🔒</span>
                <span className="notice-text">V2 — OpenAI Architect pending</span>
              </div>
              <p className="actor-description">
                Conexão ao OpenAI Architect desativada nesta fase. Nenhuma mensagem ou inferência simulada.
              </p>
            </div>
            <div className="actor-card-footer">
              <span className="actor-telemetry-badge">Status: Não Conectado</span>
            </div>
          </div>

          {/* EXECUTOR (Cyan) */}
          <div className={`actor-card actor-executor ${mission?.status === 'AGENT_WORKING' ? 'is-active' : ''}`}>
            <div className="actor-card-header">
              <AgentAvatar
                persona={ACTOR_PERSONAS.EXECUTOR}
                accentColor="#06b6d4"
                isRunning={mission?.status === 'AGENT_WORKING'}
                size="md"
              />
              <div className="actor-identity">
                <span className="actor-role-tag role-cyan">EXECUTOR</span>
                <h3 className="actor-name">Antigravity</h3>
              </div>
              <span className={`actor-status-pill ${actors.executor?.status === 'AGENT_WORKING' ? 'pill-cyan-active' : 'pill-cyan-idle'}`}>
                {actors.executor?.status || 'IDLE'}
              </span>
            </div>
            <div className="actor-card-body">
              <div className="actor-live-activity">
                <span className="activity-label">Ação Atual / Última Ferramenta:</span>
                <div className="activity-action-box">
                  <span className="action-pulse-dot" />
                  <span className="action-text">{actors.executor?.status_text || 'Aguardando instruções'}</span>
                </div>
              </div>
              <p className="actor-description">
                Execução real de ferramentas, leitura de código e modificações do workspace via AgentBridge.
              </p>
            </div>
            <div className="actor-card-footer">
              <span className="actor-telemetry-badge">Fonte: AgentBridge live.ndjson</span>
            </div>
          </div>

          {/* VALIDATOR (Green) */}
          <div className={`actor-card actor-validator ${mission?.status === 'VALIDATING' ? 'is-active' : ''}`}>
            <div className="actor-card-header">
              <AgentAvatar
                persona={ACTOR_PERSONAS.VALIDATOR}
                accentColor="#10b981"
                isRunning={mission?.status === 'VALIDATING'}
                size="md"
              />
              <div className="actor-identity">
                <span className="actor-role-tag role-green">VALIDATOR</span>
                <h3 className="actor-name">Bridge Validator</h3>
              </div>
              <span className={`actor-status-pill ${actors.validator?.status === 'VALIDATING' ? 'pill-green-active' : 'pill-green-idle'}`}>
                {actors.validator?.status || 'IDLE'}
              </span>
            </div>
            <div className="actor-card-body">
              <div className="actor-scope-badges">
                <span className="scope-tag">Validation Harness</span>
                <span className="scope-tag">Build Verification</span>
                <span className="scope-tag">Git Operations</span>
              </div>
              <p className="actor-description">
                Garante que nenhuma mutação de branch ou merge ocorra sem validação externa estrita e testes direcionados.
              </p>
            </div>
            <div className="actor-card-footer">
              <span className="actor-telemetry-badge">Harness Externo Ativo</span>
            </div>
          </div>

          {/* HUMAN (Gold) */}
          <div className={`actor-card actor-human ${actors.human?.is_highlighted ? 'is-highlighted-blocked' : ''}`}>
            <div className="actor-card-header">
              <AgentAvatar
                persona={ACTOR_PERSONAS.HUMAN}
                accentColor="#f59e0b"
                isRunning={Boolean(actors.human?.is_highlighted)}
                size="md"
              />
              <div className="actor-identity">
                <span className="actor-role-tag role-gold">HUMAN</span>
                <h3 className="actor-name">Operador Humano</h3>
              </div>
              <span className={`actor-status-pill ${actors.human?.is_highlighted ? 'pill-gold-blocked' : 'pill-gold-idle'}`}>
                {actors.human?.status || 'STANDBY'}
              </span>
            </div>
            <div className="actor-card-body">
              {actors.human?.is_highlighted ? (
                <div className="actor-blocked-alert">
                  <strong>⚠️ Ação Requerida:</strong> O agente pausou a missão e aguarda decisão ou aprovação humana.
                </div>
              ) : (
                <p className="actor-description">
                  Autoridade soberana da Video Factory. Somente acionado em condições BLOCKED_HUMAN ou validações manuais.
                </p>
              )}
            </div>
            <div className="actor-card-footer">
              <span className="actor-telemetry-badge">
                {actors.human?.is_highlighted ? '🔴 Aguardando Resposta' : '🟢 Modo Observação (Standby)'}
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Live Activity Timeline Feed */}
      <section className="ops-timeline-section">
        <div className="timeline-header-bar">
          <div className="timeline-header-left">
            <span className="section-title-icon">📜</span>
            <span className="section-title">Live Activity Feed</span>
            <span className="events-count-pill">{filteredEvents.length} eventos</span>
          </div>

          <div className="timeline-filters">
            <span className="filter-label">Filtrar por:</span>
            {['ALL', 'EXECUTOR', 'VALIDATOR', 'SYSTEM', 'HUMAN', 'ARCHITECT'].map((actorKey) => (
              <button
                key={actorKey}
                type="button"
                className={`filter-chip ${actorFilter === actorKey ? 'active' : ''} chip-${actorKey.toLowerCase()}`}
                onClick={() => setActorFilter(actorKey)}
              >
                {actorKey === 'ALL' ? 'Todos' : actorKey}
              </button>
            ))}

            <button
              type="button"
              className={`autoscroll-toggle-btn ${autoScroll ? 'active' : ''}`}
              onClick={() => setAutoScroll(!autoScroll)}
              title="Fixar rolagem automática no fim do feed"
            >
              {autoScroll ? '⬇ Auto-scroll: ON' : '⏸ Auto-scroll: PAUSA'}
            </button>
          </div>
        </div>

        {/* Timeline Scroll Area */}
        <div
          className="timeline-container"
          ref={timelineContainerRef}
          onScroll={handleScroll}
        >
          {filteredEvents.length === 0 ? (
            <div className="timeline-empty-state">
              {isLoading ? (
                <span>Carregando telemetria do AgentBridge...</span>
              ) : !isConnected ? (
                <span>AgentBridge não conectado. Inicie a missão para visualizar o feed em tempo real.</span>
              ) : (
                <span>Nenhum evento registrado para o filtro selecionado.</span>
              )}
            </div>
          ) : (
            <div className="timeline-events-list">
              {filteredEvents.map((evt, idx) => {
                const actor = evt.actor || 'SYSTEM';
                const isExpanded = Boolean(expandedEvents[evt.id]);

                return (
                  <div
                    key={evt.id || idx}
                    className={`timeline-entry entry-${actor.toLowerCase()}`}
                  >
                    {/* Timestamp column */}
                    <div className="entry-time-col">
                      <span className="entry-timestamp font-mono">{evt.timestamp}</span>
                    </div>

                    {/* Spine dot & connector */}
                    <div className="entry-spine-col">
                      <span className={`entry-dot dot-${actor.toLowerCase()}`} />
                      <div className="entry-spine-line" />
                    </div>

                    {/* Content Card */}
                    <div className="entry-content-card">
                      <div className="entry-card-header">
                        <AgentAvatar
                          persona={ACTOR_PERSONAS[actor] || ACTOR_PERSONAS.SYSTEM}
                          accentColor={ACTOR_PERSONAS[actor]?.accentColor || '#64748b'}
                          size="xs"
                        />
                        <span className={`entry-actor-tag tag-${actor.toLowerCase()}`}>
                          {actor}
                        </span>

                        {evt.tool_name && (
                          <span className="entry-tool-pill">
                            <span className="tool-pill-icon">🔧</span>
                            <span className="tool-pill-name">{evt.tool_name}</span>
                          </span>
                        )}

                        {evt.relative_path && (
                          <span className="entry-path-pill font-mono" title={evt.relative_path}>
                            📄 {evt.relative_path}
                          </span>
                        )}

                        {evt.duration && (
                          <span className="entry-duration-pill font-mono" title={`Duração: ${evt.duration}`}>
                            ⏱ {evt.duration}
                          </span>
                        )}

                        {evt.status && evt.status !== 'info' && (
                          <span className={`entry-status-badge status-${String(evt.status).toLowerCase()}`}>
                            {evt.status}
                          </span>
                        )}
                      </div>

                      <div className="entry-action-headline">
                        {evt.tool_action || evt.message || 'Atividade registrada'}
                      </div>

                      {evt.message && evt.message !== evt.tool_action && (
                        <div className="entry-detail-text">
                          {evt.message}
                        </div>
                      )}

                      {/* Expandable technical details */}
                      {(evt.task_id || evt.conversation_id_short || evt.event_type) && (
                        <div className="entry-meta-tray">
                          <button
                            type="button"
                            className="entry-expand-toggle"
                            onClick={() => toggleEventExpand(evt.id)}
                          >
                            {isExpanded ? '▲ Ocultar metadados' : '▼ Metadados'}
                          </button>

                          {isExpanded && (
                            <div className="entry-expanded-details">
                              {evt.event_type && (
                                <span className="meta-pair">
                                  <strong>Tipo:</strong> {evt.event_type}
                                </span>
                              )}
                              {evt.task_id && (
                                <span className="meta-pair">
                                  <strong>Task:</strong> {evt.task_id}
                                </span>
                              )}
                              {evt.conversation_id_short && (
                                <span className="meta-pair font-mono">
                                  <strong>Conv:</strong> {evt.conversation_id_short}
                                </span>
                              )}
                              {evt.source && (
                                <span className="meta-pair">
                                  <strong>Fonte:</strong> {evt.source}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              <div ref={timelineEndRef} style={{ height: '1px' }} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
