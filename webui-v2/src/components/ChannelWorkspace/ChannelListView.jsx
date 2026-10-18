import React, { useState } from 'react';
import { updateProfileAutonomousMode } from '../../api';

export default function ChannelListView({
  channels = [],
  onSelectChannel,
  onOpenCreateModal,
  onRefresh,
}) {
  const [searchTerm, setSearchTerm] = useState('');
  const [formatFilter, setFormatFilter] = useState('all');

  const filteredChannels = channels.filter((ch) => {
    const term = (searchTerm || '').trim().toLowerCase();
    const nameStr = (ch.name || ch.profile_name || ch.channel_name || '').toLowerCase();
    const nicheStr = (ch.niche || '').toLowerCase();
    const matchesSearch = !term || nameStr.includes(term) || nicheStr.includes(term);

    const chFormat = ch.settings?.editorial?.video_format || ch.settings?.video_format || 'traditional';
    const matchesFormat = formatFilter === 'all' || chFormat === formatFilter;

    return Boolean(matchesSearch && matchesFormat);
  });

  const handleToggleAuto = async (e, ch) => {
    e.stopPropagation();
    const chId = ch.channel_id || ch.profile_id;
    const nextState = !ch.autonomous_enabled;
    try {
      await updateProfileAutonomousMode(chId, nextState);
      ch.autonomous_enabled = nextState;
      if (onRefresh) onRefresh();
    } catch (err) {
      alert(`Erro ao alterar autonomia: ${err.message}`);
    }
  };

  const formatBadge = (fmt) => {
    if (fmt === 'quiz_paper') return { label: 'Quiz Papel P1.3', color: '#f59e0b' };
    if (fmt === 'quiz_dilemma') return { label: 'Quiz Dilema Q0-R', color: '#8b5cf6' };
    return { label: 'Tradicional', color: '#10b981' };
  };

  return (
    <div className="v2-channel-list-container">
      {/* Top Header */}
      <div className="v2-workspace-header">
        <div>
          <h2 className="v2-workspace-title">Meus Canais de Vídeo</h2>
          <p className="v2-workspace-subtitle">
            Gerenciamento centralizado de identidade, formatos congelados, metas e publicação.
          </p>
        </div>
        <button className="v2-btn-primary" onClick={onOpenCreateModal}>
          + Novo Canal
        </button>
      </div>

      {/* Barra de Filtros e Busca */}
      <div className="v2-filter-bar">
        <div className="v2-search-box">
          <span className="v2-search-icon">🔍</span>
          <input
            type="text"
            className="v2-input-search"
            placeholder="Buscar por nome ou nicho..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="v2-format-filters">
          <button
            className={`v2-filter-chip ${formatFilter === 'all' ? 'active' : ''}`}
            onClick={() => setFormatFilter('all')}
          >
            Todos os Formatos
          </button>
          <button
            className={`v2-filter-chip ${formatFilter === 'traditional' ? 'active' : ''}`}
            onClick={() => setFormatFilter('traditional')}
          >
            Tradicional
          </button>
          <button
            className={`v2-filter-chip ${formatFilter === 'quiz_dilemma' ? 'active' : ''}`}
            onClick={() => setFormatFilter('quiz_dilemma')}
          >
            Quiz Q0-R
          </button>
          <button
            className={`v2-filter-chip ${formatFilter === 'quiz_paper' ? 'active' : ''}`}
            onClick={() => setFormatFilter('quiz_paper')}
          >
            Quiz Papel P1.3
          </button>
        </div>
      </div>

      {/* Grid de Canais */}
      <div className="v2-channels-grid">
        {filteredChannels.length === 0 ? (
          <div className="v2-empty-state">
            <span className="v2-empty-icon">📺</span>
            <h3>Nenhum canal encontrado</h3>
            <p>Tente ajustar a busca ou crie um novo canal para iniciar a produção.</p>
          </div>
        ) : (
          filteredChannels.map((ch) => {
            const chId = ch.channel_id || ch.profile_id;
            const badge = formatBadge(ch.settings?.editorial?.video_format || ch.settings?.video_format || 'traditional');
            const readyStock = ch.ready_stock || 0;
            const targetStock = ch.target_stock || 3;
            const stockPct = Math.min(100, (readyStock / targetStock) * 100);

            return (
              <div
                key={chId}
                className="v2-channel-card"
                onClick={() => onSelectChannel(ch)}
              >
                <div className="v2-card-top">
                  <div className="v2-channel-avatar">
                    {ch.name?.slice(0, 2).toUpperCase() || 'CH'}
                  </div>
                  <div className="v2-card-title-group">
                    <h3 className="v2-card-title">{ch.name}</h3>
                    <span className="v2-card-niche">{ch.niche || 'Nicho Geral'}</span>
                  </div>
                  <span
                    className="v2-card-format-tag"
                    style={{ backgroundColor: `${badge.color}20`, color: badge.color }}
                  >
                    {badge.label}
                  </span>
                </div>

                <div className="v2-card-stock-section">
                  <div className="v2-stock-header">
                    <span className="v2-stock-title">Estoque Pronto</span>
                    <span className="v2-stock-numbers">{readyStock} / {targetStock}</span>
                  </div>
                  <div className="v2-progress-track">
                    <div
                      className="v2-progress-bar-inner"
                      style={{
                        width: `${stockPct}%`,
                        backgroundColor: stockPct >= 100 ? '#10b981' : '#3b82f6',
                      }}
                    />
                  </div>
                </div>

                <div className="v2-card-destinations">
                  <span className="v2-dest-count">
                    {ch.channels?.length || 0} conta(s) social(is) vinculada(s)
                  </span>
                </div>

                <div className="v2-card-footer">
                  <div
                    className="v2-auto-toggle-wrapper"
                    onClick={(e) => handleToggleAuto(e, ch)}
                  >
                    <span
                      className={`v2-auto-switch ${ch.autonomous_enabled ? 'checked' : ''}`}
                    />
                    <span className="v2-auto-label">
                      {ch.autonomous_enabled ? 'Autônomo' : 'Manual'}
                    </span>
                  </div>

                  <button className="v2-btn-manage">
                    Gerenciar →
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
