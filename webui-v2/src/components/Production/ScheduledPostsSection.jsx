import React from 'react';
import {
  formatDateTimeBR,
  formatScheduledStatus,
  formatShowingCount,
} from './productionLogic';

/**
 * ScheduledPostsSection — Componente compartilhado de renderização da fila de posts agendados (Fonte Única 2).
 * Utilizado por:
 * - Produção (com botões de ação 'Replanejar Agenda' e 'Publicar Agora')
 * - Publicação (somente leitura, sem botões de ação)
 */
export default function ScheduledPostsSection({
  items = [],
  total = 0,
  actions = null,
  actionResult = null,
  onCloseActionResult = null,
  title = '🗓️ Agendados',
  emptyMessage = 'Nenhum post agendado na fila.',
}) {
  const showingCount = formatShowingCount(items.length, total);

  return (
    <section className="prod-section-card" aria-labelledby="heading-agendados">
      <div className="prod-section-header">
        <div className="prod-section-title-group">
          <h2 id="heading-agendados" className="prod-section-title">
            {title}
          </h2>
          <span className="prod-badge-count fleet-mono">{total}</span>
          {showingCount && (
            <span className="prod-section-showing-hint">{showingCount}</span>
          )}
        </div>

        {actions && <div className="prod-actions-group">{actions}</div>}
      </div>

      {actionResult && (
        <div
          className={`prod-action-banner prod-action-banner--${actionResult.type}`}
          role="status"
        >
          <span className="prod-action-banner-text">{actionResult.text}</span>
          {onCloseActionResult && (
            <button
              type="button"
              className="prod-action-banner-close"
              onClick={onCloseActionResult}
              aria-label="Fechar notificação"
            >
              ×
            </button>
          )}
        </div>
      )}

      <div className="prod-table-wrapper">
        {items.length === 0 ? (
          <div className="prod-empty-box">
            <span className="prod-empty-icon" aria-hidden="true">
              ⏳
            </span>
            <span>{emptyMessage}</span>
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
              {items.map((item, idx) => (
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
  );
}
