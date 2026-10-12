import React from 'react';

/**
 * ChannelCard — Dynamic header card for each profile/channel in the top deck (R6A.3).
 * Prioritizes channel_name as primary identity, with real mathematical stock percentage.
 */
export default function ChannelCard({ channel, isSelected, onClick }) {
  const {
    profile_id,
    profile_name,
    channel_id,
    channel_name,
    platform = 'youtube',
    autonomous_enabled,
    growth_mode,
    ready_stock = 0,
    target_stock = null,
    status = 'IDLE',
    execution,
  } = channel;

  const isAutonomous = Boolean(autonomous_enabled);
  const isIdle = !execution || execution.status === 'IDLE';

  // Prioritize channel_name as primary identity, fallback to profile_name
  const primaryTitle = channel_name || profile_name || channel_id;
  const platformLabel = platform === 'tiktok' ? 'TikTok' : 'YouTube';
  const secondarySubtitle = `${platformLabel} • ${channel_id || profile_id}`;
  const profileMeta = `Perfil: ${profile_id || 'default'}`;

  // Ready Stock real mathematical percentage calculation (Section 3)
  const stockCount = typeof ready_stock === 'number' ? ready_stock : (channel.stock || 0);
  const hasTargetStock = typeof target_stock === 'number' && target_stock > 0;
  const stockPct = hasTargetStock
    ? Math.min(100, Math.round((stockCount / target_stock) * 100))
    : null;

  // Mini progress bar color semantics (100% green, >0 blue, 0 gray/neutral)
  let stockBarColor = '#64748b';
  if (stockPct !== null) {
    if (stockPct >= 100) {
      stockBarColor = '#10b981';
    } else if (stockPct > 0) {
      stockBarColor = '#3b82f6';
    }
  }

  return (
    <div
      className={`channel-card ${isSelected ? 'active-selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      aria-label={`Canal ${primaryTitle}`}
    >
      <div className="channel-card-top">
        <div className="channel-identity-group">
          <div className="channel-name" title={primaryTitle}>
            📺 {primaryTitle}
          </div>
          <div className="channel-sub-id" title={`${secondarySubtitle} • ${profileMeta}`}>
            {secondarySubtitle} • <span className="profile-id-sub">{profileMeta}</span>
          </div>
        </div>
        <div className="channel-badges">
          <span className={`mini-badge ${isAutonomous ? 'autonomous' : 'manual'}`}>
            {isAutonomous ? 'AUTO' : 'MANUAL'}
          </span>
          {growth_mode && (
            <span className="mini-badge growth">
              {String(growth_mode).toUpperCase()}
            </span>
          )}
        </div>
      </div>

      <div className="channel-card-body">
        {/* Ready Stock Section with real percentage and mini progress bar */}
        <div className="channel-stock-block">
          <div className="channel-stock-header">
            <span className="stock-title">Estoque Pronto</span>
            <div className="stock-values">
              <strong>{hasTargetStock ? `${stockCount} / ${target_stock}` : stockCount}</strong>
              {stockPct !== null && (
                <span className="stock-pct-badge" style={{ color: stockBarColor }}>
                  {stockPct}%
                </span>
              )}
            </div>
          </div>
          {hasTargetStock && (
            <div className="stock-progress-track">
              <div
                className="stock-progress-fill"
                style={{
                  width: `${stockPct}%`,
                  backgroundColor: stockBarColor,
                }}
              />
            </div>
          )}
        </div>

        {isIdle ? (
          <div className="task-idle-note">
            <span className="idle-indicator">⚪ {status === 'BLOCKED' ? 'BLOQUEADO' : 'IDLE'}</span>
            <span>• Sem tarefa ativa</span>
          </div>
        ) : (
          <div className="channel-current-task">
            <div className="task-topic-preview" title={execution.topic || 'Sem título'}>
              {execution.topic || 'Tarefa em andamento'}
            </div>
            <div className="task-meta-row">
              <span className={`mini-badge ${execution.status === 'RUNNING' ? 'running' : 'status-tag'}`}>
                {execution.status === 'RUNNING' && <span className="running-dot" />}
                {execution.status}
              </span>
              <span className="task-stage-label">
                {execution.pipeline_stage_label || execution.pipeline_stage || 'Processando'}
              </span>
              {execution.progress !== null && execution.progress !== undefined && (
                <span className="task-progress-pct">
                  {execution.progress}%
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
