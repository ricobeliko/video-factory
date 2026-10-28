import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { getDiagnosticsOverview } from '../../api';
import {
  sortDiagnosesBySeverity,
  formatTimeAgo,
  getStatusBadgeInfo,
  getSeverityBadgeInfo,
  formatOutcome,
  formatSafeValue,
  calculateFactorySummary,
} from './diagnosticsLogic';
import '../Fleet/fleet.css';
import './diagnostics.css';

const POLL_INTERVAL_MS = 15000;

export default function DiagnosticsView({ onNavigate }) {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);

  // Filtro por canal ('all' por padrão)
  const [selectedProfileId, setSelectedProfileId] = useState('all');

  const isFetchingRef = useRef(false);

  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const res = await getDiagnosticsOverview();
      const payload = res?.data || res;
      if (payload) {
        setData(payload);
        setError(null);
        setLastFetchTime(new Date());
        setSecondsSinceSync(0);
      }
    } catch (err) {
      console.warn('Erro ao atualizar diagnósticos:', err.message);
      setError(err.message || 'Falha ao conectar com a API de diagnósticos.');
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, []);

  // Polling a cada 15s, pausado com aba oculta
  useEffect(() => {
    fetchData();

    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchData();
      }
    }, POLL_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchData();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchData]);

  // Contador de segundos desde última atualização
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastFetchTime) {
        const diff = Math.floor((Date.now() - lastFetchTime.getTime()) / 1000);
        setSecondsSinceSync(Math.max(0, diff));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastFetchTime]);

  const handleNavClick = (tab) => {
    if (onNavigate) {
      onNavigate(tab);
    } else {
      window.location.hash = `#${tab}`;
    }
  };

  const rawChannels = useMemo(() => data?.channels || [], [data]);
  const factory = useMemo(() => data?.factory || {}, [data]);

  const summary = useMemo(() => {
    return calculateFactorySummary(rawChannels);
  }, [rawChannels]);

  const filteredChannels = useMemo(() => {
    if (selectedProfileId === 'all') return rawChannels;
    return rawChannels.filter((c) => c.profile_id === selectedProfileId);
  }, [rawChannels, selectedProfileId]);

  return (
    <div className="fleet-root">
      {/* 1. Header Bar com identidade visual e navegação */}
      <header className="fleet-header" aria-label="Cabeçalho do Diagnóstico">
        <div className="fleet-brand">
          <div className="fleet-brand-logo" aria-hidden="true">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#0A0C11"
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 4l14 8-14 8z" />
            </svg>
          </div>
          <span className="fleet-brand-title">Video Factory</span>
          <span className="fleet-mono fleet-brand-badge">V2</span>
        </div>

        <nav className="fleet-nav" aria-label="Navegação da Aplicação">
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('frota')}
          >
            Frota
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('producao')}
          >
            Produção
          </button>
          <button type="button" className="fleet-nav-link active">
            Diagnóstico
          </button>
          <button type="button" className="fleet-nav-link" disabled title="Em breve">
            <span>Publicação</span>
            <span className="fleet-nav-soon">em breve</span>
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('video-review')}
          >
            Revisão
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('factory-live')}
          >
            Factory Live
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('agent-ops')}
          >
            Agent Ops
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('sistema')}
          >
            Sistema
          </button>
        </nav>

        <div className="fleet-header-right">
          <div className="fleet-sync-pill" title="Intervalo automático de 15 segundos">
            <span className="fleet-live-dot" aria-hidden="true" />
            <span className="fleet-sync-text">
              {lastFetchTime ? `atualizado há ${secondsSinceSync}s` : 'conectando...'}
            </span>
          </div>

          <button
            type="button"
            className="fleet-icon-btn"
            onClick={fetchData}
            title="Atualizar diagnóstico agora"
            aria-label="Atualizar dados"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" />
            </svg>
          </button>
        </div>
      </header>

      {/* 2. Conteúdo Principal */}
      <main className="fleet-main">
        {/* Banner de Erro se API falhar */}
        {error && (
          <div className="fleet-error-banner" role="alert">
            <span className="fleet-error-icon" aria-hidden="true">⚠️</span>
            <div className="fleet-error-text">
              <strong>Falha de conexão com os diagnósticos:</strong> {error}
            </div>
            <button type="button" className="fleet-retry-btn" onClick={fetchData}>
              Tentar Novamente
            </button>
          </div>
        )}

        {/* Topo: Resumo da Fábrica e Totais de Saúde */}
        <section className="diag-summary-banner" aria-label="Resumo Geral da Fábrica">
          <div className="diag-summary-top">
            <div className="diag-factory-info">
              <span className="diag-factory-name">🏭 Estado da Fábrica:</span>
              <span
                className="diag-channel-badge"
                style={{
                  backgroundColor: factory.is_paused ? 'rgba(148, 163, 184, 0.15)' : (factory.state === 'ERROR' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)'),
                  color: factory.is_paused ? '#94a3b8' : (factory.state === 'ERROR' ? '#f87171' : '#34d399'),
                  border: `1px solid ${factory.is_paused ? 'rgba(148, 163, 184, 0.3)' : (factory.state === 'ERROR' ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)')}`,
                }}
              >
                {factory.is_paused ? '⏸ Pausada' : (factory.state === 'ERROR' ? '🚨 Erro' : '● Ativa')}
              </span>
              {factory.primary_instance?.node_name && (
                <span className="diag-node-badge" title={`PID: ${factory.primary_instance.pid || '—'}`}>
                  Nó: {factory.primary_instance.node_name} ({factory.primary_instance.status || 'ACTIVE'})
                </span>
              )}
              {factory.message && (
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                  {factory.message}
                </span>
              )}
            </div>

            <div className="diag-summary-counters">
              <span className="diag-counter-pill ok">
                ✓ {summary.ok} OK
              </span>
              {(summary.running || 0) > 0 && (
                <span className="diag-counter-pill running" style={{ color: '#38bdf8', borderColor: 'rgba(56, 189, 248, 0.25)', background: 'rgba(56, 189, 248, 0.1)' }}>
                  ▶ {summary.running} gerando
                </span>
              )}
              {(summary.attention || summary.atencao || 0) > 0 && (
                <span className="diag-counter-pill atencao">
                  ⚠ {summary.attention || summary.atencao} em atenção
                </span>
              )}
              {(summary.blocked || summary.parado || 0) > 0 && (
                <span className="diag-counter-pill parado">
                  ⏹ {summary.blocked || summary.parado} {((summary.blocked || summary.parado) === 1) ? 'canal bloqueado' : 'canais bloqueados'}
                </span>
              )}
              {(summary.paused || summary.pausado || 0) > 0 && (
                <span className="diag-counter-pill pausado">
                  ⏸ {summary.paused || summary.pausado} pausados
                </span>
              )}
            </div>
          </div>

          {/* Tetos Globais da Fábrica (Global Cost Guard) */}
          {(data?.limits || factory?.limits) && (
            <div className="diag-global-limits">
              <span className="diag-global-limit-item">
                <span className="diag-global-limit-label">Teto Global Tentativas:</span>
                <span className="diag-global-limit-val">
                  {formatSafeValue((data?.limits || factory?.limits)?.attempts_24h?.used)} / {formatSafeValue((data?.limits || factory?.limits)?.attempts_24h?.cap)}
                </span>
              </span>
              <span className="diag-global-limit-item">
                <span className="diag-global-limit-label">Teto Global Aprovados:</span>
                <span className="diag-global-limit-val">
                  {formatSafeValue((data?.limits || factory?.limits)?.approved_24h?.used)} / {formatSafeValue((data?.limits || factory?.limits)?.approved_24h?.cap)}
                </span>
              </span>
            </div>
          )}

          {/* Aviso discreto de Eventos sem canal (somente quando houver) */}
          {data?.unassigned_events && data.unassigned_events.count > 0 && (
            <div className="diag-unassigned-notice" role="status">
              <div className="diag-unassigned-header">
                <span className="diag-unassigned-icon" aria-hidden="true">ℹ️</span>
                <strong className="diag-unassigned-title">Eventos sem canal:</strong>
                <span className="diag-unassigned-count">
                  {data.unassigned_events.count} {data.unassigned_events.count === 1 ? 'evento operacional não associado' : 'eventos operacionais não associados'} a nenhum canal
                </span>
              </div>
              {Array.isArray(data.unassigned_events.diagnoses) && data.unassigned_events.diagnoses.length > 0 && (
                <div className="diag-unassigned-diagnoses">
                  {data.unassigned_events.diagnoses.map((diag, idx) => (
                    <div key={idx} className={`diag-unassigned-item ${diag.severity || 'info'}`}>
                      <span className={`diag-badge-severity ${diag.severity || 'info'}`}>
                        {(diag.severity || 'info').toUpperCase()}
                      </span>
                      <span className="diag-unassigned-diag-title">{diag.title}</span>
                      {diag.detail && (
                        <span className="diag-unassigned-diag-detail">— {diag.detail}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Seletor de Filtro de Canais */}
          {rawChannels.length > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingTop: '4px' }}>
              <span style={{ fontSize: '12px', color: '#64748b' }}>Filtrar canal:</span>
              <button
                type="button"
                className={`fleet-filter-pill ${selectedProfileId === 'all' ? 'active' : ''}`}
                onClick={() => setSelectedProfileId('all')}
                style={{
                  fontSize: '11px',
                  padding: '3px 10px',
                  borderRadius: '12px',
                  border: selectedProfileId === 'all' ? '1px solid #38bdf8' : '1px solid rgba(51,65,85,0.4)',
                  backgroundColor: selectedProfileId === 'all' ? 'rgba(56,189,248,0.15)' : 'transparent',
                  color: selectedProfileId === 'all' ? '#38bdf8' : '#94a3b8',
                  cursor: 'pointer',
                }}
              >
                Todos ({rawChannels.length})
              </button>
              {rawChannels.map((c) => (
                <button
                  key={c.profile_id}
                  type="button"
                  onClick={() => setSelectedProfileId(c.profile_id)}
                  style={{
                    fontSize: '11px',
                    padding: '3px 10px',
                    borderRadius: '12px',
                    border: selectedProfileId === c.profile_id ? '1px solid #38bdf8' : '1px solid rgba(51,65,85,0.4)',
                    backgroundColor: selectedProfileId === c.profile_id ? 'rgba(56,189,248,0.15)' : 'transparent',
                    color: selectedProfileId === c.profile_id ? '#38bdf8' : '#94a3b8',
                    cursor: 'pointer',
                  }}
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* 3. Grid de Cartões de Diagnóstico por Canal */}
        {isLoading && !data ? (
          <div className="fleet-empty-state">
            <span className="fleet-empty-icon" aria-hidden="true">⏳</span>
            <p className="fleet-empty-text">Carregando diagnósticos da frota...</p>
          </div>
        ) : filteredChannels.length === 0 ? (
          <div className="fleet-empty-state">
            <span className="fleet-empty-icon" aria-hidden="true">📡</span>
            <p className="fleet-empty-text">Nenhum canal localizado para diagnóstico.</p>
          </div>
        ) : (
          <div className="diag-grid">
            {filteredChannels.map((chan) => {
              const statusBadge = getStatusBadgeInfo(chan.status);
              const sortedDiagnoses = sortDiagnosesBySeverity(chan.diagnoses || []);
              const recentGens = chan.recent_generations || [];
              const isOff = chan.limits?.autonomous_enabled === false;

              return (
                <div key={chan.profile_id} className={`diag-card ${isOff ? 'is-disabled' : ''}`}>
                  {/* Cabeçalho do Cartão */}
                  <div className="diag-card-header">
                    <div className="diag-card-title-group">
                      <div className="diag-channel-name">{chan.name}</div>
                      <div className="diag-channel-meta">
                        <span style={{ fontFamily: 'monospace' }}>{chan.profile_id}</span>
                        <span>•</span>
                        <span>
                          Última geração: {chan.last_generation_at ? formatTimeAgo(chan.last_generation_at) : 'nenhuma recente'}
                        </span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {isOff && (
                        <span className="diag-badge-off" title="Produção autônoma desativada pelo operador">
                          ⏻ Desligado
                        </span>
                      )}
                      <span
                        className="diag-channel-badge"
                        style={{
                          backgroundColor: statusBadge.bg,
                          color: statusBadge.color,
                          border: `1px solid ${statusBadge.border}`,
                        }}
                      >
                        <span aria-hidden="true">{statusBadge.icon}</span>
                        <span>{statusBadge.label}</span>
                      </span>
                    </div>
                  </div>

                  {/* Barra de Métricas 24h e Estoque */}
                  <div className="diag-metrics-bar">
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Estoque / Meta</span>
                      <span className="diag-metric-val">
                        {formatSafeValue(chan.ready_stock?.count)} / {formatSafeValue(chan.ready_stock?.target)}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Iniciadas 24h</span>
                      <span className="diag-metric-val">{chan.counts_24h?.started ?? 0}</span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Aprovadas 24h</span>
                      <span className="diag-metric-val" style={{ color: '#34d399' }}>
                        {chan.counts_24h?.approved ?? 0}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Reprovadas 24h</span>
                      <span className="diag-metric-val" style={{ color: chan.counts_24h?.rejected ? '#f87171' : '#94a3b8' }}>
                        {chan.counts_24h?.rejected ?? 0}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Interrompidas 24h</span>
                      <span className="diag-metric-val" style={{ color: chan.counts_24h?.interrupted ? '#fbbf24' : '#94a3b8' }}>
                        {chan.counts_24h?.interrupted ?? 0}
                      </span>
                    </div>
                  </div>

                  {/* Linha de Limites do Canal (Guardas 5.1–5.4) */}
                  <div className="diag-limits-bar">
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Modo</span>
                      <span className="diag-metric-val">
                        {chan.limits?.growth_mode ? String(chan.limits.growth_mode).toUpperCase() : '—'}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Aprovados 24h</span>
                      <span className="diag-metric-val">
                        {formatSafeValue(chan.limits?.approved_24h?.used)} / {formatSafeValue(chan.limits?.approved_24h?.cap)}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Tentativas 24h</span>
                      <span className="diag-metric-val">
                        {formatSafeValue(chan.limits?.attempts_24h?.used)} / {formatSafeValue(chan.limits?.attempts_24h?.cap)}
                      </span>
                    </div>
                    <div className="diag-metric-item">
                      <span className="diag-metric-label">Rejeições Seguidas</span>
                      <span className="diag-metric-val">
                        {formatSafeValue(chan.limits?.consecutive_rejections?.used)} / {formatSafeValue(chan.limits?.consecutive_rejections?.limit)}
                      </span>
                    </div>
                  </div>

                  {/* Avisos do Canal (ex.: falha de estoque canônico) */}
                  {Array.isArray(chan.warnings) && chan.warnings.length > 0 && (
                    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {chan.warnings.map((w, wIdx) => (
                        <div
                          key={wIdx}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '6px 10px',
                            borderRadius: '6px',
                            background: 'rgba(245, 158, 11, 0.1)',
                            border: '1px solid rgba(245, 158, 11, 0.25)',
                            color: '#f59e0b',
                            fontSize: '12px',
                          }}
                        >
                          <span aria-hidden="true">⚠️</span>
                          <span>{w}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Seção de Diagnósticos e Problemas */}
                  <div className="diag-problems-section">
                    <div className="diag-section-label">
                      <span>Diagnósticos e Alertas ({sortedDiagnoses.length})</span>
                    </div>

                    {sortedDiagnoses.length === 0 ? (
                      <div className="diag-empty-problems">
                        <span aria-hidden="true">✓</span>
                        <span>Nenhum problema detectado nas últimas 24h. Canal operando conforme o esperado.</span>
                      </div>
                    ) : (
                      sortedDiagnoses.map((diag, dIdx) => {
                        const sev = getSeverityBadgeInfo(diag.severity);
                        return (
                          <div
                            key={`${diag.code}-${dIdx}`}
                            className="diag-problem-item"
                            style={{
                              backgroundColor: sev.bg,
                              borderColor: sev.border,
                            }}
                          >
                            <div className="diag-problem-header">
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontSize: '13px' }} aria-hidden="true">{sev.icon}</span>
                                <span className="diag-problem-title">{diag.title}</span>
                                <span
                                  style={{
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    padding: '1px 6px',
                                    borderRadius: '8px',
                                    backgroundColor: sev.border,
                                    color: sev.color,
                                  }}
                                >
                                  {sev.label}
                                </span>
                              </div>
                              {diag.since && (
                                <span className="diag-problem-since" title={diag.since}>
                                  ocorrência {formatTimeAgo(diag.since)}
                                </span>
                              )}
                            </div>

                            <div className="diag-problem-detail">
                              {diag.detail}
                            </div>

                            {diag.suggested_action && (
                              <div className="diag-suggested-action">
                                <span className="diag-action-label">Ação Sugerida:</span>
                                <span>{diag.suggested_action}</span>
                              </div>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>

                  {/* Linha do Tempo das Últimas 10 Gerações */}
                  <div className="diag-timeline-section">
                    <div className="diag-section-label">
                      <span>Últimas Gerações ({recentGens.length})</span>
                    </div>

                    {recentGens.length === 0 ? (
                      <div style={{ fontSize: '12px', color: '#64748b', fontStyle: 'italic', padding: '4px 0' }}>
                        Nenhuma geração registrada nas últimas 24 horas.
                      </div>
                    ) : (
                      <div className="diag-timeline-list">
                        {recentGens.map((gen, gIdx) => {
                          const outcomeInfo = formatOutcome(gen.outcome);
                          return (
                            <div key={`${gen.task_id}-${gIdx}`} className="diag-timeline-row">
                              <div className="diag-timeline-left">
                                <span className="diag-task-mono" title={gen.task_id}>
                                  {gen.task_id.slice(0, 10)}
                                </span>
                                <span
                                  className="diag-outcome-pill"
                                  style={{
                                    backgroundColor: outcomeInfo.bg,
                                    color: outcomeInfo.color,
                                  }}
                                >
                                  <span>{outcomeInfo.icon}</span>
                                  <span>{outcomeInfo.label}</span>
                                </span>
                                <span className="diag-topic-text" title={gen.topic || 'Sem tema'}>
                                  {formatSafeValue(gen.topic, 'Sem tema')}
                                </span>
                              </div>

                              <div className="diag-timeline-right">
                                {gen.reason && (
                                  <span className="diag-reason-text" title={gen.reason}>
                                    {gen.reason}
                                  </span>
                                )}
                                <span style={{ color: '#64748b', fontSize: '11px', whiteSpace: 'nowrap' }}>
                                  {formatTimeAgo(gen.started_at)}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
