import React from 'react';

/**
 * ChannelCard — Dynamic header card for each profile/channel in the top deck.
 * Prioritizes profile_name as the primary operational identity.
 */
export default function ChannelCard({ channel, isSelected, onClick }) {
  const {
    profile_id,
    profile_name,
    channel_id,
    channel_name,
    autonomous_enabled,
    growth_mode,
    stock,
    execution,
  } = channel;

  const isAutonomous = Boolean(autonomous_enabled);
  const isIdle = !execution || execution.status === 'IDLE';

  // Prioritize channel_name as primary identity, profile_name as fallback
  const primaryTitle = channel_name || profile_name || channel_id;
  const platformLabel = channel.platform === 'tiktok' ? 'TikTok' : 'YouTube';
  const secondarySubtitle = `${platformLabel} • ${channel_id || profile_id}`;
  const profileMeta = `Perfil: ${profile_id || 'default'}`;

  return (
    <div
      className={`channel-card ${isSelected ? 'active-selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className="channel-card-top">
        <div className="channel-identity-group">
          <div className="channel-name" title={primaryTitle}>
            📺 {primaryTitle}
          </div>
          <div className="channel-sub-id" title={`${secondarySubtitle} • ${profileMeta}`}>
            {secondarySubtitle} • <span style={{ opacity: 0.8 }}>{profileMeta}</span>
          </div>
        </div>
        <div className="channel-badges">
          <span className={`mini-badge ${isAutonomous ? 'autonomous' : 'manual'}`}>
            {isAutonomous ? 'Autônomo' : 'Manual'}
          </span>
          {growth_mode && (
            <span className="mini-badge growth">
              {growth_mode}
            </span>
          )}
        </div>
      </div>

      <div className="channel-card-body">
        <div className="channel-stock-row">
          <span>Estoque Pronto:</span>
          <strong>{stock !== undefined && stock !== null ? stock : 0}</strong>
        </div>

        {isIdle ? (
          <div className="task-idle-note">
            <span>⚪ IDLE</span>
            <span>• Sem tarefa ativa</span>
          </div>
        ) : (
          <div className="channel-current-task">
            <div className="task-topic-preview" title={execution.topic || 'Sem título'}>
              {execution.topic || 'Tarefa em andamento'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className={`mini-badge ${execution.status === 'RUNNING' ? 'autonomous' : 'manual'}`}>
                {execution.status === 'RUNNING' && <span className="running-dot" />}
                {execution.status}
              </span>
              <span style={{ fontSize: '11px', color: '#cbd5e1', fontWeight: 500 }}>
                {execution.pipeline_stage_label || execution.stage || 'Processando'}
              </span>
              {execution.progress !== null && execution.progress !== undefined && (
                <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: '#fbbf24' }}>
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
