import React, { useEffect, useState } from 'react';
import { getSchedulerPosts } from '../api';

/**
 * SchedulesView — Fila e Agenda de Publicações do Scheduler
 * Exibe as tarefas aprovadas que estão aguardando janela de publicação no YouTube.
 */
export default function SchedulesView({ channels = [], onOpenChannel }) {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState('');

  const loadPosts = async () => {
    setLoading(true);
    try {
      const res = await getSchedulerPosts(50, selectedProfileId || null);
      if (res && Array.isArray(res.upcoming_posts)) {
        setPosts(res.upcoming_posts);
      } else {
        setPosts([]);
      }
    } catch (err) {
      console.error('Erro ao buscar agendamentos:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPosts();
  }, [selectedProfileId]);

  return (
    <div className="v2-schedules-view-container">
      <div className="v2-page-header">
        <div>
          <h2 className="v2-view-title">Agendamentos</h2>
          <p className="v2-view-subtitle">Fila de vídeos aprovados aguardando publicação pelo Scheduler Worker</p>
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

          <button type="button" className="v2-btn-secondary" onClick={loadPosts} disabled={loading}>
            ↻ Atualizar
          </button>
        </div>
      </div>

      <div className="v2-card-table-wrapper">
        <table className="v2-data-table">
          <thead>
            <tr>
              <th>HORÁRIO PROGRAMADO</th>
              <th>VÍDEO / TEMA</th>
              <th>CANAL</th>
              <th>PLATAFORMA</th>
              <th>STATUS</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan="5" className="v2-table-cell-empty">
                  Carregando agendamentos...
                </td>
              </tr>
            ) : posts.length === 0 ? (
              <tr>
                <td colSpan="5" className="v2-table-cell-empty">
                  <span style={{ fontSize: '24px', display: 'block', marginBottom: '8px' }}>📅</span>
                  Nenhum post agendado no momento. Os vídeos aprovados no estoque serão alocados automaticamente pelo Scheduler Worker nas janelas configuradas.
                </td>
              </tr>
            ) : (
              posts.map((p, idx) => (
                <tr key={p.id || idx}>
                  <td className="v2-font-mono">{p.scheduled_time || 'Imediato'}</td>
                  <td>
                    <span className="v2-post-topic-title">{p.title || p.task_topic || 'Vídeo Homologado'}</span>
                    {p.task_id && <span className="v2-task-id-hint">ID: {p.task_id.slice(0, 8)}...</span>}
                  </td>
                  <td>
                    <span className="v2-channel-link" onClick={() => onOpenChannel && onOpenChannel({ profile_id: p.profile_id })}>
                      {p.channel_name || p.profile_name || 'Canal Padrão'}
                    </span>
                  </td>
                  <td>
                    <span className="v2-badge-pill subtle-red">
                      YouTube Shorts
                    </span>
                  </td>
                  <td>
                    <span className="v2-badge-pill subtle-green">
                      {p.status || 'SCHEDULED'}
                    </span>
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
