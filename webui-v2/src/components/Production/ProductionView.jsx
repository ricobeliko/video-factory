import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { getProductionOverview } from '../../api';
import { formatVideoFormat } from '../Fleet/fleetLogic';
import {
  formatAgeHours,
  formatDuration,
  formatCopyrightStatus,
  formatRunStatus,
  formatStage,
  formatScheduledStatus,
  formatDateTimeBR,
  sortReadyStock,
  sortRecentRuns,
  filterByChannel,
  formatShowingCount,
  getAggregatedSectionData,
} from './productionLogic';
import '../Fleet/fleet.css';
import './production.css';

const POLL_INTERVAL_MS = 15000;

export default function ProductionView({ onNavigate }) {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);

  // Filtro por canal ('all' por padrão)
  const [selectedProfileId, setSelectedProfileId] = useState('all');

  const isFetchingRef = useRef(false);

  // Busca dados de produção sem sobreposição
  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const res = await getProductionOverview();
      const payload = res?.data || res;
      if (payload) {
        setData(payload);
        setError(null);
        setLastFetchTime(new Date());
        setSecondsSinceSync(0);
      }
    } catch (err) {
      console.warn('Erro ao atualizar produção:', err.message);
      setError(err.message || 'Falha ao conectar com a API de produção.');
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

  // Dados resolvidos
  const rawChannels = useMemo(() => data?.channels || [], [data]);
  const totals = useMemo(() => data?.totals || {}, [data]);

  // Canais filtrados pelo seletor de canal
  const filteredChannels = useMemo(() => {
    return filterByChannel(rawChannels, selectedProfileId);
  }, [rawChannels, selectedProfileId]);

  // 1. Seção Estoque Pronto
  const stockSection = useMemo(() => {
    const agg = getAggregatedSectionData(filteredChannels, 'ready_stock');
    return {
      items: sortReadyStock(agg.items),
      total: agg.total,
    };
  }, [filteredChannels]);

  // 2. Seção Agendados
  const scheduledSection = useMemo(() => {
    const agg = getAggregatedSectionData(filteredChannels, 'scheduled');
    const sorted = [...agg.items].sort((a, b) => {
      const tA = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
      const tB = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
      return tA - tB;
    });
    return {
      items: sorted,
      total: agg.total,
    };
  }, [filteredChannels]);

  // 3. Seção Últimas 24h
  const runsSection = useMemo(() => {
    const agg = getAggregatedSectionData(filteredChannels, 'recent_runs');
    return {
      items: sortRecentRuns(agg.items),
      total: agg.total,
    };
  }, [filteredChannels]);

  return (
    <div className="fleet-root">
      {/* 1. Header Bar com identidade visual idêntica à Frota */}
      <header className="fleet-header" aria-label="Cabeçalho da Produção">
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
          <button type="button" className="fleet-nav-link active">
            Produção
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
            title="Atualizar dados agora"
            aria-label="Atualizar dados agora"
          >
            ↻
          </button>
        </div>
      </header>

      {/* 2. Conteúdo Principal da Produção */}
      <main className="prod-main">
        {/* Banner de Erro (com manter último dado bom) */}
        {error && (
          <div className="prod-error-banner" role="alert">
            <span>⚠️ {error}</span>
            <button type="button" className="prod-retry-btn" onClick={fetchData}>
              Tentar de novo
            </button>
          </div>
        )}

        {/* Título da Tela */}
        <div className="fleet-title-bar">
          <div>
            <h1 className="fleet-title">Produção</h1>
            <p className="fleet-subtitle">
              Monitoramento em tempo real do estoque pronto, fila de agendamento e execuções das últimas 24h.
            </p>
          </div>
          {isLoading && !data && (
            <div className="prod-loading-banner">
              <span>Carregando dados de produção...</span>
            </div>
          )}
        </div>

        {/* 1) Cartões de Totais (KPIs) */}
        <section className="prod-kpis-grid" aria-label="Totais de Produção">
          <div className="prod-kpi-card kpi-stock">
            <span className="prod-kpi-label">Estoque pronto</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono">{totals.total_ready ?? 0}</span>
              <span className="prod-kpi-sub">vídeos</span>
            </div>
          </div>

          <div className="prod-kpi-card">
            <span className="prod-kpi-label">Agendados</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono">{totals.total_scheduled ?? 0}</span>
              <span className="prod-kpi-sub">posts</span>
            </div>
          </div>

          <div className="prod-kpi-card">
            <span className="prod-kpi-label">Sucesso 24 h</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono" style={{ color: '#34D399' }}>
                {totals.success_24h ?? 0}
              </span>
              <span className="prod-kpi-sub">concluídos</span>
            </div>
          </div>

          <div className="prod-kpi-card kpi-failed">
            <span className="prod-kpi-label">Falhas 24 h</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono" style={{ color: '#FF8A7A' }}>
                {totals.failed_24h ?? 0}
              </span>
              <span className="prod-kpi-sub">erros</span>
            </div>
          </div>

          <div className="prod-kpi-card kpi-rejected">
            <span className="prod-kpi-label">Reprovados 24 h</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono" style={{ color: '#F5B546' }}>
                {totals.rejected_24h ?? 0}
              </span>
              <span className="prod-kpi-sub">barrados</span>
            </div>
          </div>

          <div className="prod-kpi-card kpi-running">
            <span className="prod-kpi-label">Em execução</span>
            <div className="prod-kpi-value-row">
              <span className="prod-kpi-value fleet-mono" style={{ color: '#6AA8FF' }}>
                {totals.running_24h ?? 0}
              </span>
              <span className="prod-kpi-sub">ativas</span>
            </div>
          </div>

          {/* "Desconhecido" só se unknown_24h > 0 */}
          {Number(totals.unknown_24h || 0) > 0 && (
            <div className="prod-kpi-card">
              <span className="prod-kpi-label">Desconhecido</span>
              <div className="prod-kpi-value-row">
                <span className="prod-kpi-value fleet-mono" style={{ color: '#9099AA' }}>
                  {totals.unknown_24h}
                </span>
                <span className="prod-kpi-sub">sem estado</span>
              </div>
            </div>
          )}
        </section>

        {/* 2) Filtro por Canal (Chips) */}
        {rawChannels.length > 0 && (
          <section className="prod-filter-section" aria-label="Filtro por Canal">
            <span className="prod-filter-label">Filtrar por canal:</span>
            <div className="prod-filter-chips">
              <button
                type="button"
                className={`prod-chip ${selectedProfileId === 'all' ? 'active' : ''}`}
                onClick={() => setSelectedProfileId('all')}
              >
                <span>Todos</span>
                <span className="prod-chip-format-tag">{rawChannels.length}</span>
              </button>

              {rawChannels.map((ch) => {
                const fmt = formatVideoFormat(ch.video_format);
                const isSelected = selectedProfileId === ch.profile_id;
                return (
                  <button
                    key={ch.profile_id}
                    type="button"
                    className={`prod-chip ${isSelected ? 'active' : ''}`}
                    onClick={() => setSelectedProfileId(ch.profile_id)}
                  >
                    <span>{ch.channel_name || ch.profile_name}</span>
                    <span
                      className="prod-chip-format-tag"
                      style={{ color: fmt.color }}
                    >
                      {fmt.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {/* 3) Seção "Estoque pronto" */}
        <section className="prod-section-card" aria-labelledby="heading-estoque">
          <div className="prod-section-header">
            <div className="prod-section-title-group">
              <h2 id="heading-estoque" className="prod-section-title">
                📦 Estoque pronto
              </h2>
              <span className="prod-badge-count fleet-mono">{stockSection.total}</span>
            </div>
            {formatShowingCount(stockSection.items.length, stockSection.total) && (
              <span className="prod-section-showing-hint">
                {formatShowingCount(stockSection.items.length, stockSection.total)}
              </span>
            )}
          </div>

          <div className="prod-table-wrapper">
            {stockSection.items.length === 0 ? (
              <div className="prod-empty-box">
                <span className="prod-empty-icon" aria-hidden="true">📭</span>
                <span>Nada no estoque pronto.</span>
              </div>
            ) : (
              <table className="prod-table">
                <thead>
                  <tr>
                    <th scope="col">Canal</th>
                    <th scope="col">Assunto</th>
                    <th scope="col">Qualidade</th>
                    <th scope="col">Safety</th>
                    <th scope="col">Direitos</th>
                    <th scope="col">Idade</th>
                    <th scope="col">Duração</th>
                  </tr>
                </thead>
                <tbody>
                  {stockSection.items.map((item, idx) => {
                    const cp = formatCopyrightStatus(item.copyright_status);
                    return (
                      <tr key={item.task_id || idx}>
                        <td className="prod-col-channel">{item.channel_name || '—'}</td>
                        <td className="prod-col-topic" title={item.topic || ''}>
                          {item.topic || '—'}
                        </td>
                        <td className="prod-col-mono">
                          {item.quality_score != null ? Number(item.quality_score).toFixed(1) : '—'}
                        </td>
                        <td>
                          {item.safety_status ? (
                            <span
                              className="prod-status-chip"
                              style={{
                                color: item.safety_status === 'PASS' ? '#34D399' : '#FF8A7A',
                                backgroundColor:
                                  item.safety_status === 'PASS'
                                    ? 'rgba(52, 211, 153, 0.15)'
                                    : 'rgba(255, 138, 122, 0.15)',
                              }}
                            >
                              {item.safety_status}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td>
                          <span
                            className="prod-status-chip"
                            style={{
                              color: cp.color,
                              backgroundColor: cp.bg,
                              borderColor: cp.border,
                            }}
                          >
                            {cp.label}
                          </span>
                        </td>
                        <td className="prod-col-mono">{formatAgeHours(item.age_hours)}</td>
                        <td className="prod-col-mono">{formatDuration(item.duration)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* 4) Seção "Agendados" */}
        <section className="prod-section-card" aria-labelledby="heading-agendados">
          <div className="prod-section-header">
            <div className="prod-section-title-group">
              <h2 id="heading-agendados" className="prod-section-title">
                🗓️ Agendados
              </h2>
              <span className="prod-badge-count fleet-mono">{scheduledSection.total}</span>
            </div>
            {formatShowingCount(scheduledSection.items.length, scheduledSection.total) && (
              <span className="prod-section-showing-hint">
                {formatShowingCount(scheduledSection.items.length, scheduledSection.total)}
              </span>
            )}
          </div>

          <div className="prod-table-wrapper">
            {scheduledSection.items.length === 0 ? (
              <div className="prod-empty-box">
                <span className="prod-empty-icon" aria-hidden="true">⏳</span>
                <span>Nenhum post agendado na fila.</span>
              </div>
            ) : (
              <table className="prod-table">
                <thead>
                  <tr>
                    <th scope="col">Data / Hora (BR)</th>
                    <th scope="col">Canal</th>
                    <th scope="col">Assunto</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {scheduledSection.items.map((item, idx) => (
                    <tr key={item.post_id || idx}>
                      <td className="prod-col-mono">{formatDateTimeBR(item.scheduled_at)}</td>
                      <td className="prod-col-channel">{item.channel_name || '—'}</td>
                      <td className="prod-col-topic" title={item.topic || ''}>
                        {item.topic || '—'}
                      </td>
                      <td>
                        <span
                          className="prod-status-chip"
                          style={{
                            color: item.status === 'ready' ? '#34D399' : '#8B9DFF',
                            backgroundColor:
                              item.status === 'ready'
                                ? 'rgba(52, 211, 153, 0.15)'
                                : 'rgba(139, 157, 255, 0.15)',
                          }}
                        >
                          {formatScheduledStatus(item.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* 5) Seção "Últimas 24 h" */}
        <section className="prod-section-card" aria-labelledby="heading-recent-runs">
          <div className="prod-section-header">
            <div className="prod-section-title-group">
              <h2 id="heading-recent-runs" className="prod-section-title">
                ⚡ Últimas 24 h
              </h2>
              <span className="prod-badge-count fleet-mono">{runsSection.total}</span>
            </div>
            {formatShowingCount(runsSection.items.length, runsSection.total) && (
              <span className="prod-section-showing-hint">
                {formatShowingCount(runsSection.items.length, runsSection.total)}
              </span>
            )}
          </div>

          <div className="prod-table-wrapper">
            {runsSection.items.length === 0 ? (
              <div className="prod-empty-box">
                <span className="prod-empty-icon" aria-hidden="true">💤</span>
                <span>Nenhuma produção registrada nas últimas 24h.</span>
              </div>
            ) : (
              <table className="prod-table">
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    <th scope="col">Etapa</th>
                    <th scope="col">Motivo</th>
                    <th scope="col">Horário (BR)</th>
                    <th scope="col">Canal</th>
                    <th scope="col">Assunto</th>
                  </tr>
                </thead>
                <tbody>
                  {runsSection.items.map((item, idx) => {
                    const st = formatRunStatus(item.status);
                    const reason = item.gate_reason || item.error;
                    const isFailureOrRejection =
                      item.status === 'FAILED' || item.status === 'REJECTED';

                    return (
                      <tr key={item.task_id || idx}>
                        <td>
                          <span
                            className="prod-status-chip"
                            style={{
                              color: st.color,
                              backgroundColor: st.bg,
                              borderColor: st.border,
                            }}
                          >
                            <span
                              className="prod-dot-indicator"
                              style={{ backgroundColor: st.color }}
                              aria-hidden="true"
                            />
                            {st.label}
                          </span>
                        </td>
                        <td>{formatStage(item.failure_stage)}</td>
                        <td
                          className={`prod-reason-text ${
                            isFailureOrRejection && reason ? 'prod-reason-highlight' : ''
                          }`}
                          title={reason || ''}
                        >
                          {reason || '—'}
                        </td>
                        <td className="prod-col-mono">
                          {formatDateTimeBR(item.created_at || item.finished_at)}
                        </td>
                        <td className="prod-col-channel">{item.channel_name || '—'}</td>
                        <td className="prod-col-topic" title={item.topic || ''}>
                          {item.topic || '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
