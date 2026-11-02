import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  getPublications,
  getProductionOverview,
  getChannelsOverview,
} from '../../api';
import FleetNav from '../FleetNav';
import ScheduledPostsSection from '../Production/ScheduledPostsSection';
import {
  formatDateTimeBR,
  getAggregatedSectionData,
  filterByChannel,
} from '../Production/productionLogic';
import '../Fleet/fleet.css';
import '../Production/production.css';
import './publication.css';

const POLL_INTERVAL_MS = 15000;
const INITIAL_LIMIT = 50;
const MAX_LIMIT = 100;

/**
 * Renderiza o selo semântico de status de publicação:
 * - success: "Publicado" (verde)
 * - Qualquer outro valor: exibido como veio (fallback "unknown").
 * A tabela publication_events registra exclusivamente publicações concluídas com sucesso.
 */
function renderStatusBadge(status) {
  const s = String(status || '').toLowerCase().trim();
  if (s === 'success') {
    return <span className="pub-status-badge pub-status-badge--success">Publicado</span>;
  }
  return (
    <span className="pub-status-badge pub-status-badge--unknown">
      {status || '—'}
    </span>
  );
}

/**
 * PublicationView — Tela de Publicação SOMENTE LEITURA (Missão v2/tela-publicacao).
 * Fontes Únicas:
 * 1. Histórico: GET /api/v2/publications (tabela publication_events — publicações concluídas).
 * 2. Fila: GET /api/v2/production/overview (seção scheduled) + ScheduledPostsSection compartilhado.
 * 3. Navegação: FleetNav compartilhado com as demais 5 telas.
 */
export default function PublicationView({ onNavigate }) {
  const [publications, setPublications] = useState([]);
  const [pubTotal, setPubTotal] = useState(0);
  const [pubLimit, setPubLimit] = useState(INITIAL_LIMIT);

  const [productionData, setProductionData] = useState(null);
  const [channelsList, setChannelsList] = useState([]);

  const [selectedProfileId, setSelectedProfileId] = useState('');

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);

  const isFetchingRef = useRef(false);

  // Busca dados de Publicação e Fila sem concorrência
  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const [pubRes, prodRes, chanRes] = await Promise.allSettled([
        getPublications(pubLimit, selectedProfileId || null),
        getProductionOverview(selectedProfileId || null),
        getChannelsOverview(),
      ]);

      if (pubRes.status === 'fulfilled' && pubRes.value) {
        const payload = pubRes.value.data || pubRes.value;
        setPublications(payload.publications || []);
        setPubTotal(payload.total ?? (payload.publications || []).length);
      }

      if (prodRes.status === 'fulfilled' && prodRes.value) {
        const payload = prodRes.value.data || prodRes.value;
        setProductionData(payload);
      }

      if (chanRes.status === 'fulfilled' && chanRes.value) {
        const payload = chanRes.value.data || chanRes.value;
        setChannelsList(payload.channels || []);
      }

      setError(null);
      setLastFetchTime(new Date());
      setSecondsSinceSync(0);
    } catch (err) {
      console.warn('Erro ao atualizar tela de publicação:', err.message);
      setError(err.message || 'Falha ao sincronizar dados de publicação.');
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, [pubLimit, selectedProfileId]);

  // Polling a cada 15 segundos, pausado quando a aba estiver oculta
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

  // Contador de segundos desde a última atualização
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastFetchTime) {
        const diff = Math.floor((Date.now() - lastFetchTime.getTime()) / 1000);
        setSecondsSinceSync(Math.max(0, diff));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastFetchTime]);

  // Mapa de canais para resolução de nomes amigáveis
  const channelNameMap = useMemo(() => {
    const map = {};
    for (const ch of channelsList) {
      const pid = ch.profile_id || ch.channel_id;
      if (pid) {
        map[pid] = ch.name || ch.channel_name || pid;
      }
    }
    // Também mescla do retorno de productionData caso presente
    const prodChannels = productionData?.channels || [];
    for (const ch of prodChannels) {
      const pid = ch.profile_id || ch.channel_id;
      if (pid && !map[pid]) {
        map[pid] = ch.channel_name || pid;
      }
    }
    return map;
  }, [channelsList, productionData]);

  // Fila: mesmos dados e ordenação da tela de Produção (Fonte Única 2)
  const scheduledSection = useMemo(() => {
    const rawChannels = productionData?.channels || [];
    const filtered = filterByChannel(rawChannels, selectedProfileId);
    const agg = getAggregatedSectionData(filtered, 'scheduled');
    const sorted = [...agg.items].sort((a, b) => {
      const tA = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
      const tB = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
      return tA - tB;
    });
    return {
      items: sorted,
      total: agg.total,
    };
  }, [productionData, selectedProfileId]);

  const handleLoadMore = () => {
    if (pubLimit < MAX_LIMIT) {
      setPubLimit(MAX_LIMIT);
    }
  };

  return (
    <div className="fleet-root publication-view">
      {/* 1. Header Bar com Fonte Única de Navegação */}
      <header className="fleet-header" aria-label="Cabeçalho de Publicação">
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

        <FleetNav activeTab="publicacao" onNavigate={onNavigate} />

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

      {/* 2. Conteúdo Principal */}
      <main className="publication-main">
        {error && (
          <div className="prod-action-banner prod-action-banner--error" role="alert">
            <span className="prod-action-banner-text">{error}</span>
          </div>
        )}

        {/* Seção 1: Fila de Publicação (Agendados) — Somente Leitura via Componente Compartilhado */}
        <ScheduledPostsSection
          items={scheduledSection.items}
          total={scheduledSection.total}
          title="🗓️ Fila de Publicação (Agendados)"
          emptyMessage="Nenhum post agendado na fila de publicação."
        />

        {/* Seção 2: Histórico de Publicações Concluídas */}
        <section className="prod-section-card" aria-labelledby="heading-historico">
          <div className="prod-section-header">
            <div className="prod-section-title-group">
              <h2 id="heading-historico" className="prod-section-title">
                📢 Publicações Concluídas
              </h2>
              <span className="prod-badge-count fleet-mono">
                {publications.length}
              </span>
              <span className="pub-section-hint">
                Vídeos publicados com sucesso (falhas não aparecem aqui)
              </span>
            </div>

            {/* Filtro por canal */}
            <div className="pub-filters-bar">
              <div className="pub-filter-group">
                <label htmlFor="pub-filter-channel" className="pub-filter-label">
                  Canal:
                </label>
                <select
                  id="pub-filter-channel"
                  className="pub-select"
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                >
                  <option value="">Todos os canais</option>
                  {channelsList.map((ch) => {
                    const pid = ch.profile_id || ch.channel_id;
                    return (
                      <option key={pid} value={pid}>
                        {ch.name || ch.channel_name || pid}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          </div>

          <div className="prod-table-wrapper">
            {publications.length === 0 ? (
              <div className="prod-empty-box">
                <span className="prod-empty-icon" aria-hidden="true">
                  📭
                </span>
                <span>
                  {isLoading
                    ? 'Carregando histórico...'
                    : 'Nenhuma publicação concluída encontrada.'}
                </span>
              </div>
            ) : (
              <table className="prod-table">
                <thead>
                  <tr>
                    <th scope="col">Data / Hora (BR)</th>
                    <th scope="col">Canal</th>
                    <th scope="col">Plataforma</th>
                    <th scope="col">Status</th>
                    <th scope="col">Link Externo</th>
                  </tr>
                </thead>
                <tbody>
                  {publications.map((item) => {
                    const channelName =
                      channelNameMap[item.profile_id] ||
                      channelNameMap[item.channel_id] ||
                      item.profile_id ||
                      item.channel_id ||
                      '—';
                    return (
                      <tr key={item.id}>
                        <td className="prod-col-mono">
                          {formatDateTimeBR(item.published_at)}
                        </td>
                        <td className="prod-col-channel">{channelName}</td>
                        <td className="pub-col-platform">{item.platform || '—'}</td>
                        <td>{renderStatusBadge(item.status)}</td>
                        <td>
                          {item.external_url ? (
                            <a
                              href={item.external_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="pub-external-link"
                              title={item.external_url}
                            >
                              Ver vídeo ↗
                            </a>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Barra de Paginação / Carregar Mais */}
          <div className="pub-pagination-bar">
            <span className="pub-pagination-hint">
              Exibindo {publications.length} de até {pubLimit} publicações concluídas
            </span>
            {pubLimit < MAX_LIMIT ? (
              <button
                type="button"
                className="pub-load-more-btn"
                onClick={handleLoadMore}
                disabled={isLoading}
              >
                Carregar mais (até {MAX_LIMIT})
              </button>
            ) : (
              <span className="pub-pagination-hint">
                Limite máximo do endpoint atingido ({MAX_LIMIT})
              </span>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
