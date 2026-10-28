import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { getFleetSummary } from '../../api';
import {
  formatStatus,
  formatVideoFormat,
  formatRelativeTime,
  formatApprovalRate,
  formatReadyStock,
  formatTotalReadyStock,
  sortChannelsBySeverity,
  getAttentionList,
  filterChannels,
} from './fleetLogic';
import Workshop from './Workshop';
import './fleet.css';

const POLL_INTERVAL_MS = 15000;

export default function FleetView({ onNavigate }) {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);

  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [selectedChannelId, setSelectedChannelId] = useState(null);

  const isFetchingRef = useRef(false);
  const searchInputRef = useRef(null);

  // Fetch fleet summary data with overlap prevention
  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const res = await getFleetSummary();
      const payload = res?.data || res;
      if (payload) {
        setData(payload);
        setError(null);
        setLastFetchTime(new Date());
        setSecondsSinceSync(0);
      }
    } catch (err) {
      console.warn('Erro ao atualizar frota:', err.message);
      setError(err.message || 'Falha ao conectar com a API.');
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, []);

  // Polling loop: every 15s, paused when tab is hidden
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

  // Tick timer for "atualizado há Xs"
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastFetchTime) {
        const diff = Math.floor((Date.now() - lastFetchTime.getTime()) / 1000);
        setSecondsSinceSync(Math.max(0, diff));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastFetchTime]);

  // Keyboard shortcut Ctrl+K to focus search input, and Esc to close drawer
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchInputRef.current?.focus();
      } else if (e.key === 'Escape') {
        setSelectedChannelId(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Resolved channels list and totals
  const rawChannels = useMemo(() => data?.channels || [], [data]);
  const totals = useMemo(() => data?.totals || {}, [data]);

  // Sorted by severity for table display
  const sortedChannels = useMemo(() => {
    return sortChannelsBySeverity(rawChannels);
  }, [rawChannels]);

  // Filtered channels based on active filter chip and search
  const displayedChannels = useMemo(() => {
    return filterChannels(sortedChannels, {
      filter: activeFilter,
      query: searchQuery,
    });
  }, [sortedChannels, activeFilter, searchQuery]);

  // Attention list for "Precisa de você"
  const attentionList = useMemo(() => {
    return getAttentionList(rawChannels);
  }, [rawChannels]);

  // Selected channel for drawer
  const selectedChannel = useMemo(() => {
    if (!selectedChannelId) return null;
    return rawChannels.find((c) => (c.profile_id || c.slug) === selectedChannelId) || null;
  }, [rawChannels, selectedChannelId]);

  // Counts for filter chips
  const filterCounts = useMemo(() => {
    const total = rawChannels.length;
    const attention = rawChannels.filter(
      (c) => c.status === 'attention' || c.status === 'blocked'
    ).length;
    const quiz = rawChannels.filter((c) => String(c.format || '').includes('quiz')).length;
    const traditional = rawChannels.filter((c) => c.format === 'traditional').length;
    const paused = rawChannels.filter((c) => c.status === 'paused').length;

    return { all: total, attention, quiz, traditional, paused };
  }, [rawChannels]);

  const handleNavClick = (tab) => {
    if (onNavigate) {
      onNavigate(tab);
    } else {
      window.location.hash = `#${tab}`;
    }
  };

  return (
    <div className="fleet-root">
      {/* 1. Header Bar */}
      <header className="fleet-header" aria-label="Cabeçalho da Frota">
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
          <button type="button" className="fleet-nav-link active">
            Frota
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('producao')}
          >
            Produção
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('diagnostico')}
          >
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

        <div className="fleet-header-spacer" />

        {/* Search Input */}
        <label className="fleet-search-label" aria-label="Buscar canal ou nicho">
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#9099AA"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input
            ref={searchInputRef}
            type="text"
            className="fleet-search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Buscar canal ou nicho"
          />
          <span className="fleet-mono fleet-search-hint">Ctrl K</span>
        </label>

        {/* API / Engine status */}
        <div className="fleet-status-indicator">
          <span
            className={`fleet-status-dot ${error ? 'offline' : ''}`}
            aria-hidden="true"
          />
          <span className="fleet-mono">Motor V2</span>
          {lastFetchTime && (
            <span className="fleet-sync-label fleet-mono">
              (atualizado há {secondsSinceSync}s)
            </span>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main className="fleet-main">
        {/* Error notification if any */}
        {error && (
          <div className="fleet-error-banner" role="alert">
            <span className="fleet-error-text">
              Aviso de conexão com o motor: {error}
            </span>
            <button
              type="button"
              className="fleet-btn-secondary"
              onClick={fetchData}
            >
              Tentar de novo
            </button>
          </div>
        )}

        {/* 2. Title Section */}
        <div className="fleet-title-bar">
          <div>
            <h1 className="fleet-title">Frota</h1>
            <p className="fleet-subtitle">
              A fábrica faz um vídeo por vez, um canal depois do outro. O que
              precisa de você aparece primeiro.
            </p>
          </div>
        </div>

        {/* 3. 6 Key Indicators (KPIs) */}
        <section className="fleet-kpis-grid" aria-label="Indicadores da frota">
          {/* KPI 1: Canais ativos */}
          <div className="fleet-kpi-card">
            <span className="fleet-kpi-label">Canais ativos</span>
            <div className="fleet-kpi-value-row">
              <span className="fleet-mono fleet-kpi-value" style={{ color: '#E8EBF1' }}>
                {totals.active_channels ?? (isLoading ? '—' : 0)}
              </span>
              <span className="fleet-mono fleet-kpi-sub">
                de {totals.total_channels ?? (isLoading ? '—' : 0)}
              </span>
            </div>
            <div className="fleet-kpi-bar-track">
              <div
                className="fleet-kpi-bar-fill"
                style={{
                  width: totals.total_channels
                    ? `${Math.min(100, Math.round(((totals.active_channels || 0) / totals.total_channels) * 100))}%`
                    : '0%',
                  backgroundColor: 'var(--fleet-accent)',
                }}
              />
            </div>
          </div>

          {/* KPI 2: Publicados hoje */}
          <div className="fleet-kpi-card">
            <span className="fleet-kpi-label">Publicados hoje</span>
            <div className="fleet-kpi-value-row">
              <span className="fleet-mono fleet-kpi-value" style={{ color: '#E8EBF1' }}>
                {totals.published_today ?? (isLoading ? '—' : 0)}
              </span>
              <span className="fleet-mono fleet-kpi-sub">
                de meta {totals.goal_today ?? (isLoading ? '—' : 0)}
              </span>
            </div>
            <div className="fleet-kpi-bar-track">
              <div
                className="fleet-kpi-bar-fill"
                style={{
                  width: totals.goal_today
                    ? `${Math.min(100, Math.round(((totals.published_today || 0) / totals.goal_today) * 100))}%`
                    : '0%',
                  backgroundColor: 'var(--fleet-accent)',
                }}
              />
            </div>
          </div>

          {/* KPI 3: Estoque pronto total */}
          {(() => {
            const totalStockFmt = formatTotalReadyStock(totals.total_ready_stock, isLoading);
            return (
              <div className="fleet-kpi-card">
                <span className="fleet-kpi-label">Estoque pronto total</span>
                <div className="fleet-kpi-value-row">
                  <span className="fleet-mono fleet-kpi-value" style={{ color: '#E8EBF1' }}>
                    {totalStockFmt.display}
                  </span>
                  <span className="fleet-mono fleet-kpi-sub">vídeos</span>
                </div>
                <div className="fleet-kpi-bar-track">
                  <div
                    className="fleet-kpi-bar-fill"
                    style={{
                      width: totalStockFmt.barWidth,
                      backgroundColor: 'var(--fleet-accent)',
                    }}
                  />
                </div>
              </div>
            );
          })()}

          {/* KPI 4: Produzindo agora */}
          <div className="fleet-kpi-card">
            <span className="fleet-kpi-label">Produzindo agora</span>
            <div className="fleet-kpi-value-row">
              <span className="fleet-mono fleet-kpi-value" style={{ color: '#6AA8FF' }}>
                {totals.channels_running ?? (isLoading ? '—' : 0)}
              </span>
              <span className="fleet-mono fleet-kpi-sub">
                {totals.channels_running === 1 ? 'canal' : 'canais'}
              </span>
            </div>
            <div className="fleet-kpi-bar-track">
              <div
                className="fleet-kpi-bar-fill"
                style={{
                  width: totals.channels_running ? '100%' : '0%',
                  backgroundColor: '#6AA8FF',
                }}
              />
            </div>
          </div>

          {/* KPI 5: Precisam de atenção */}
          {(() => {
            const attnCount = (totals.channels_attention || 0) + (totals.channels_blocked || 0);
            return (
              <div className="fleet-kpi-card">
                <span className="fleet-kpi-label">Precisam de atenção</span>
                <div className="fleet-kpi-value-row">
                  <span
                    className="fleet-mono fleet-kpi-value"
                    style={{ color: attnCount > 0 ? '#F5B546' : '#34D399' }}
                  >
                    {isLoading ? '—' : attnCount}
                  </span>
                  <span className="fleet-mono fleet-kpi-sub">
                    {attnCount === 1 ? 'canal' : 'canais'}
                  </span>
                </div>
                <div className="fleet-kpi-bar-track">
                  <div
                    className="fleet-kpi-bar-fill"
                    style={{
                      width: attnCount > 0 ? '100%' : '0%',
                      backgroundColor: attnCount > 0 ? '#F5B546' : '#34D399',
                    }}
                  />
                </div>
              </div>
            );
          })()}

          {/* KPI 6: Pausados */}
          <div className="fleet-kpi-card">
            <span className="fleet-kpi-label">Pausados</span>
            <div className="fleet-kpi-value-row">
              <span className="fleet-mono fleet-kpi-value" style={{ color: '#9099AA' }}>
                {totals.channels_paused ?? (isLoading ? '—' : 0)}
              </span>
              <span className="fleet-mono fleet-kpi-sub">
                {totals.channels_paused === 1 ? 'canal' : 'canais'}
              </span>
            </div>
            <div className="fleet-kpi-bar-track">
              <div
                className="fleet-kpi-bar-fill"
                style={{
                  width: totals.channels_paused ? '50%' : '0%',
                  backgroundColor: '#9099AA',
                }}
              />
            </div>
          </div>
        </section>

        {/* 4. Fábrica ao vivo (Oficina dos Robôs) */}
        <section className="fleet-workshop-section" aria-label="Fábrica ao vivo">
          <div className="fleet-workshop-header">
            <h2 className="fleet-workshop-title">Fábrica ao vivo</h2>
          </div>
          <Workshop fleetSummary={data} />
        </section>

        {/* 5. Middle Row: "Precisa de você" + "Mapa da frota" */}
        <div className="fleet-middle-row">
          {/* Precisa de você */}
          <section className="fleet-attention-card" aria-label="Precisa de atenção">
            <div className="fleet-attention-title-row">
              <h2 className="fleet-workshop-title">Precisa de você</h2>
              <span className="fleet-mono fleet-attention-count-badge">
                {attentionList.length}
              </span>
            </div>

            {attentionList.length === 0 ? (
              <div className="fleet-attention-empty">
                Tudo certo na frota. Nenhum canal bloqueado ou com pendências críticas.
              </div>
            ) : (
              attentionList.map((ch) => {
                const id = ch.profile_id || ch.slug;
                const st = formatStatus(ch.status);
                return (
                  <div key={id} className="fleet-attention-item">
                    <span
                      className="fleet-attention-glyph"
                      style={{
                        backgroundColor: st.tint,
                        color: st.color,
                      }}
                      aria-hidden="true"
                    >
                      {st.glyph}
                    </span>
                    <div className="fleet-attention-text">
                      <div className="fleet-attention-name-row">
                        {ch.name}{' '}
                        <span
                          className="fleet-attention-status-tag"
                          style={{ color: st.color }}
                        >
                          · {st.label}
                        </span>
                      </div>
                      <div className="fleet-attention-issue">
                        {ch.reason || ch.issue || 'Verifique o status do canal.'}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="fleet-btn-secondary"
                      onClick={() => setSelectedChannelId(id)}
                    >
                      Ver detalhes
                    </button>
                  </div>
                );
              })
            )}
          </section>

          {/* Mapa da frota */}
          <section className="fleet-map-card" aria-label="Mapa da frota">
            <div className="fleet-map-header">
              <h2 className="fleet-workshop-title">Mapa da frota</h2>
              <span className="fleet-mono" style={{ fontSize: '12px', color: 'var(--fleet-text-muted)' }}>
                {rawChannels.length} {rawChannels.length === 1 ? 'canal' : 'canais'}
              </span>
            </div>

            <div className="fleet-map-squares">
              {rawChannels.map((ch) => {
                const id = ch.profile_id || ch.slug;
                const st = formatStatus(ch.status);
                const isSelected = selectedChannelId === id;
                return (
                  <button
                    key={id}
                    type="button"
                    className={`fleet-sq ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedChannelId(id)}
                    title={`${ch.name}: ${st.label}`}
                    aria-label={`${ch.name}: ${st.label}`}
                    style={{
                      backgroundColor: st.sq,
                      color: st.sqfg,
                    }}
                  >
                    {st.glyph}
                  </button>
                );
              })}
            </div>

            <div className="fleet-map-legend">
              <span className="fleet-legend-item">
                <span className="fleet-legend-dot" style={{ backgroundColor: '#1F6F52' }} />
                Saudável
              </span>
              <span className="fleet-legend-item">
                <span className="fleet-legend-dot" style={{ backgroundColor: '#2B5FB8' }} />
                Produzindo
              </span>
              <span className="fleet-legend-item">
                <span className="fleet-legend-dot" style={{ backgroundColor: '#B47A12' }} />
                Atenção
              </span>
              <span className="fleet-legend-item">
                <span className="fleet-legend-dot" style={{ backgroundColor: '#B3402F' }} />
                Bloqueado
              </span>
              <span className="fleet-legend-item">
                <span className="fleet-legend-dot" style={{ backgroundColor: '#2A3040' }} />
                Pausado
              </span>
            </div>
          </section>
        </div>

        {/* 6. Bottom Section: Table + Drawer */}
        <div className="fleet-bottom-section">
          {/* Table Container */}
          <section className="fleet-table-card fleet-table-container" aria-label="Tabela de canais">
            {/* Filters Bar */}
            <div className="fleet-table-filters-bar">
              <h2 className="fleet-table-title">Todos os canais</h2>
              <button
                type="button"
                className={`fleet-chip ${activeFilter === 'all' ? 'active' : ''}`}
                onClick={() => setActiveFilter('all')}
              >
                <span>Todos</span>
                <span className="fleet-mono fleet-chip-count">{filterCounts.all}</span>
              </button>
              <button
                type="button"
                className={`fleet-chip ${activeFilter === 'attention' ? 'active' : ''}`}
                onClick={() => setActiveFilter('attention')}
              >
                <span>Atenção</span>
                <span className="fleet-mono fleet-chip-count">{filterCounts.attention}</span>
              </button>
              <button
                type="button"
                className={`fleet-chip ${activeFilter === 'quiz' ? 'active' : ''}`}
                onClick={() => setActiveFilter('quiz')}
              >
                <span>Quiz</span>
                <span className="fleet-mono fleet-chip-count">{filterCounts.quiz}</span>
              </button>
              <button
                type="button"
                className={`fleet-chip ${activeFilter === 'traditional' ? 'active' : ''}`}
                onClick={() => setActiveFilter('traditional')}
              >
                <span>Tradicional</span>
                <span className="fleet-mono fleet-chip-count">{filterCounts.traditional}</span>
              </button>
              <button
                type="button"
                className={`fleet-chip ${activeFilter === 'paused' ? 'active' : ''}`}
                onClick={() => setActiveFilter('paused')}
              >
                <span>Pausados</span>
                <span className="fleet-mono fleet-chip-count">{filterCounts.paused}</span>
              </button>
            </div>

            {/* Table Content */}
            <div className="fleet-table-wrapper">
              <div className="fleet-table-inner">
                {/* Header Row */}
                <div className="fleet-grid-header">
                  <span>Canal</span>
                  <span>Formato</span>
                  <span>Status</span>
                  <span>Estoque</span>
                  <span>Na fila</span>
                  <span>Agendados</span>
                  <span>Hoje</span>
                  <span>Aprov. 24h</span>
                  <span>Última exec.</span>
                </div>

                {/* Rows */}
                {displayedChannels.length === 0 ? (
                  <div className="fleet-empty-row">
                    {searchQuery
                      ? 'Nenhum canal encontrado para a busca especificada.'
                      : 'Nenhum canal com esse filtro.'}
                  </div>
                ) : (
                  displayedChannels.map((ch) => {
                    const id = ch.profile_id || ch.slug;
                    const isSelected = selectedChannelId === id;
                    const st = formatStatus(ch.status);
                    const fmt = formatVideoFormat(ch.format);
                    const stockFmt = formatReadyStock(ch.ready_stock, ch.target_stock);
                    const appr = formatApprovalRate(ch.approval_rate_24h);
                    const lastRun = formatRelativeTime(ch.last_run_at);

                    return (
                      <div
                        key={id}
                        className={`fleet-grid-row ${isSelected ? 'selected' : ''}`}
                      >
                        {/* Canal */}
                        <button
                          type="button"
                          className="fleet-channel-btn"
                          onClick={() => setSelectedChannelId(id)}
                        >
                          <span className="fleet-channel-name">{ch.name}</span>
                          <span className="fleet-channel-sub">{ch.niche || 'Geral'}</span>
                        </button>

                        {/* Formato */}
                        <span className="fleet-badge-format" style={{ color: fmt.color }}>
                          {fmt.label}
                        </span>

                        {/* Status */}
                        <span
                          className="fleet-badge-status"
                          style={{ color: st.color }}
                          title={ch.reason || ch.issue || st.label}
                        >
                          <span
                            className={`fleet-dot-indicator ${ch.status === 'running' ? 'fleet-pulse' : ''}`}
                            style={{ backgroundColor: st.color }}
                          />
                          <span>{st.label}{ch.reason && ch.status === 'ok' ? ` · ${ch.reason}` : ''}</span>
                        </span>

                        {/* Estoque */}
                        <div className="fleet-stock-col">
                          <div className="fleet-stock-track">
                            <div
                              className="fleet-stock-fill"
                              style={{
                                width: `${stockFmt.pct}%`,
                                backgroundColor: stockFmt.barColor,
                              }}
                            />
                          </div>
                          <span className="fleet-mono fleet-stock-val">
                            {stockFmt.label}
                          </span>
                        </div>

                        {/* Na fila */}
                        <span className="fleet-mono" style={{ fontSize: '13px', color: ch.pending_processing ? '#E8EBF1' : '#6B7385' }}>
                          {ch.pending_processing ?? 0}
                        </span>

                        {/* Agendados */}
                        <span className="fleet-mono" style={{ fontSize: '13px', color: ch.scheduled ? '#E8EBF1' : '#6B7385' }}>
                          {ch.scheduled ?? 0}
                        </span>

                        {/* Hoje */}
                        <span className="fleet-mono" style={{ fontSize: '13px' }}>
                          <span style={{ color: '#E8EBF1' }}>{ch.published_today ?? 0}</span>
                          <span style={{ color: 'var(--fleet-text-muted)' }}> / {ch.goal_today ?? 1}</span>
                        </span>

                        {/* Aprovação 24h */}
                        <span
                          className="fleet-mono"
                          style={{ fontSize: '13px', color: appr.color }}
                        >
                          {appr.text}
                        </span>

                        {/* Última execução */}
                        <span
                          className="fleet-mono"
                          style={{ fontSize: '12px', color: 'var(--fleet-text-muted)' }}
                        >
                          {lastRun}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Table Footer */}
            <div className="fleet-table-footer">
              <span>
                Mostrando <strong className="fleet-mono">{displayedChannels.length}</strong> de{' '}
                <strong className="fleet-mono">{rawChannels.length}</strong> canais
              </span>
            </div>
          </section>

          {/* 7. Channel Drawer */}
          {selectedChannel && (
            <aside className="fleet-drawer" aria-label="Detalhe do canal">
              <div className="fleet-drawer-header">
                <div className="fleet-drawer-title-group">
                  <div className="fleet-drawer-title">{selectedChannel.name}</div>
                  <div className="fleet-drawer-sub">
                    {selectedChannel.niche || 'Geral'} ·{' '}
                    <span style={{ color: formatVideoFormat(selectedChannel.format).color }}>
                      {formatVideoFormat(selectedChannel.format).label}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  className="fleet-drawer-close"
                  onClick={() => setSelectedChannelId(null)}
                  aria-label="Fechar detalhe do canal"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    aria-hidden="true"
                  >
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>

              {/* Status Pill */}
              {(() => {
                const st = formatStatus(selectedChannel.status);
                return (
                  <span
                    className="fleet-drawer-status-pill"
                    style={{
                      color: st.color,
                      backgroundColor: st.tint,
                    }}
                  >
                    <span
                      className={`fleet-dot-indicator ${selectedChannel.status === 'running' ? 'fleet-pulse' : ''}`}
                      style={{ backgroundColor: st.color }}
                    />
                    <span>{st.label}</span>
                  </span>
                );
              })()}

              {/* Reason / Issue box if any */}
              {(selectedChannel.reason || selectedChannel.issue) && (
                <div
                  className="fleet-drawer-issue-box"
                  style={{
                    backgroundColor: formatStatus(selectedChannel.status).tint,
                    border: `1px solid ${formatStatus(selectedChannel.status).color}`,
                  }}
                >
                  <div
                    className="fleet-drawer-issue-title"
                    style={{ color: formatStatus(selectedChannel.status).color }}
                  >
                    {formatStatus(selectedChannel.status).label}
                  </div>
                  <div style={{ color: '#D4D9E3' }}>
                    {selectedChannel.reason || selectedChannel.issue}
                  </div>
                </div>
              )}

              {/* Stat Cards Grid */}
              <div className="fleet-drawer-stats-grid">
                <div className="fleet-stat-card">
                  <div className="fleet-stat-label">Estoque pronto</div>
                  <div className="fleet-mono fleet-stat-value">
                    {formatReadyStock(selectedChannel.ready_stock, selectedChannel.target_stock).readyDisplay}
                    <span className="fleet-stat-sub"> / {formatReadyStock(selectedChannel.ready_stock, selectedChannel.target_stock).targetDisplay}</span>
                  </div>
                </div>

                <div className="fleet-stat-card">
                  <div className="fleet-stat-label">Publicados hoje</div>
                  <div className="fleet-mono fleet-stat-value">
                    {selectedChannel.published_today ?? 0}
                    <span className="fleet-stat-sub"> / {selectedChannel.goal_today ?? 1}</span>
                  </div>
                </div>

                <div className="fleet-stat-card">
                  <div className="fleet-stat-label">Na fila / Agendados</div>
                  <div className="fleet-mono fleet-stat-value">
                    {selectedChannel.pending_processing ?? 0}
                    <span className="fleet-stat-sub"> / {selectedChannel.scheduled ?? 0}</span>
                  </div>
                </div>

                <div className="fleet-stat-card">
                  <div className="fleet-stat-label">Aprovação 24h</div>
                  <div
                    className="fleet-mono fleet-stat-value"
                    style={{ color: formatApprovalRate(selectedChannel.approval_rate_24h).color }}
                  >
                    {formatApprovalRate(selectedChannel.approval_rate_24h).text}
                  </div>
                </div>
              </div>

              {/* Meta details list */}
              <div className="fleet-drawer-meta-list">
                <div className="fleet-meta-row">
                  <span className="fleet-meta-key">Modo de crescimento:</span>
                  <span className="fleet-meta-val fleet-mono">{selectedChannel.growth_mode || '—'}</span>
                </div>
                <div className="fleet-meta-row">
                  <span className="fleet-meta-key">Modo autônomo:</span>
                  <span className="fleet-meta-val">
                    {selectedChannel.autonomous_enabled ? (
                      <span style={{ color: '#34D399' }}>Ligado</span>
                    ) : (
                      <span style={{ color: '#9099AA' }}>Desligado</span>
                    )}
                  </span>
                </div>
                <div className="fleet-meta-row">
                  <span className="fleet-meta-key">Falhas 24h:</span>
                  <span className="fleet-meta-val fleet-mono" style={{ color: selectedChannel.failed > 0 ? '#FF8A7A' : 'var(--fleet-text-main)' }}>
                    {selectedChannel.failed ?? 0}
                  </span>
                </div>
                <div className="fleet-meta-row">
                  <span className="fleet-meta-key">Última execução:</span>
                  <span className="fleet-meta-val fleet-mono">
                    {selectedChannel.last_run_at
                      ? `${formatRelativeTime(selectedChannel.last_run_at)} (${new Date(selectedChannel.last_run_at).toLocaleTimeString()})`
                      : '—'}
                  </span>
                </div>
              </div>
            </aside>
          )}
        </div>
      </main>
    </div>
  );
}
