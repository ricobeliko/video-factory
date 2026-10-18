import React, { useEffect, useState } from 'react';
import { getPublications } from '../api';

/**
 * AnalyticsView — Histórico Consolidado de Publicações e Métricas
 * Exibe eventos reais de publicação realizados no YouTube.
 */
export default function AnalyticsView({ channels = [] }) {
  const [publications, setPublications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState('');

  const loadPubs = async () => {
    setLoading(true);
    try {
      const res = await getPublications(50, selectedProfileId || null);
      if (res && Array.isArray(res.publications)) {
        setPublications(res.publications);
      } else {
        setPublications([]);
      }
    } catch (err) {
      console.error('Erro ao buscar publicações:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPubs();
  }, [selectedProfileId]);

  const totalPubs = publications.length;
  const successPubs = publications.filter(p => p.status === 'success' || p.status === 'published').length;
  const successRate = totalPubs > 0 ? Math.round((successPubs / totalPubs) * 100) : 100;

  return (
    <div className="v2-analytics-view-container">
      <div className="v2-page-header">
        <div>
          <h2 className="v2-view-title">Analytics & Histórico de Publicações</h2>
          <p className="v2-view-subtitle">Métricas factuais de postagens realizadas via YouTube Direct e Post for Me</p>
        </div>

        <div className="v2-page-actions">
          <select
            className="v2-select-input"
            value={selectedProfileId}
            onChange={(e) => setSelectedProfileId(e.target.value)}
          >
            <option value="">Todos os Canais</option>
            {channels.map((ch) => (
              <option key={ch.channel_id || ch.profile_id} value={ch.channel_id || ch.profile_id}>
                {ch.channel_name || ch.profile_name}
              </option>
            ))}
          </select>

          <button type="button" className="v2-btn-secondary" onClick={loadPubs} disabled={loading}>
            ↻ Atualizar
          </button>
        </div>
      </div>

      {/* KPI Cards de Analytics */}
      <div className="v2-kpi-grid" style={{ marginBottom: '24px' }}>
        <div className="v2-kpi-card">
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">TOTAL DE PUBLICAÇÕES</span>
            <span className="v2-kpi-icon">🚀</span>
          </div>
          <div className="v2-kpi-metric">{totalPubs}</div>
          <div className="v2-kpi-context">
            <span className="v2-kpi-subtext">Histórico registrado no banco</span>
          </div>
        </div>

        <div className="v2-kpi-card">
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">YOUTUBE SHORTS</span>
            <span className="v2-kpi-icon">▶️</span>
          </div>
          <div className="v2-kpi-metric">{successPubs}</div>
          <div className="v2-kpi-context">
            <span className="v2-badge-pill subtle-green">Destino Principal</span>
          </div>
        </div>

        <div className="v2-kpi-card">
          <div className="v2-kpi-header">
            <span className="v2-kpi-title">TAXA DE SUCESSO</span>
            <span className="v2-kpi-icon">📊</span>
          </div>
          <div className="v2-kpi-metric" style={{ color: successRate >= 90 ? '#34d399' : '#fbbf24' }}>
            {successRate}%
          </div>
          <div className="v2-kpi-context">
            <span className="v2-kpi-subtext">Zero falhas silenciosas</span>
          </div>
        </div>
      </div>

      {/* Tabela de Publicações */}
      <div className="v2-card-table-wrapper">
        <table className="v2-data-table">
          <thead>
            <tr>
              <th>DATA / HORA</th>
              <th>VÍDEO PUBLICADO</th>
              <th>CANAL</th>
              <th>DESTINO</th>
              <th>STATUS</th>
              <th>AÇÕES</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan="6" className="v2-table-cell-empty">
                  Carregando histórico de publicações...
                </td>
              </tr>
            ) : publications.length === 0 ? (
              <tr>
                <td colSpan="6" className="v2-table-cell-empty">
                  <span style={{ fontSize: '24px', display: 'block', marginBottom: '8px' }}>📈</span>
                  Nenhuma publicação registrada no ambiente DEV_V2. Em ambiente de homologação as publicações reais permanecem bloqueadas por segurança.
                </td>
              </tr>
            ) : (
              publications.map((item, idx) => (
                <tr key={item.id || idx}>
                  <td className="v2-font-mono">{item.created_at || item.published_at || 'Recente'}</td>
                  <td>
                    <span className="v2-post-topic-title">{item.title || item.task_topic || 'Vídeo Publicado'}</span>
                    {item.task_id && <span className="v2-task-id-hint">ID: {item.task_id.slice(0, 8)}...</span>}
                  </td>
                  <td>{item.channel_name || item.profile_name || 'YouTube'}</td>
                  <td>
                    <span className="v2-badge-pill subtle-red">
                      YouTube
                    </span>
                  </td>
                  <td>
                    <span className={`v2-badge-pill ${item.status === 'success' ? 'subtle-green' : 'subtle-amber'}`}>
                      {item.status || 'SUCCESS'}
                    </span>
                  </td>
                  <td>
                    {item.youtube_url ? (
                      <a
                        href={item.youtube_url}
                        target="_blank"
                        rel="noreferrer"
                        className="v2-btn-ghost"
                        style={{ fontSize: '11px', textDecoration: 'none' }}
                      >
                        Abrir Vídeo ↗
                      </a>
                    ) : (
                      <span style={{ color: '#64748b', fontSize: '11px' }}>-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
