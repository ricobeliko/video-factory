import React from 'react';

/**
 * ChannelCard — Dynamic header card for each profile/channel
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

  return (
    <div
      className={`channel-card ${isSelected ? 'active-selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className="channel-card-top">
        <div className="channel-name" title={channel_name || profile_name}>
          📺 {channel_name || profile_name}
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
          <strong>{stock !== undefined && stock !== null ? stock : '—'}</strong>
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
                {execution.status}
              </span>
              <span style={{ fontSize: '10px', color: '#94a3b8' }}>
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
