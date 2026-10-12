import React from 'react';
import { Handle, Position } from '@xyflow/react';

/**
 * LaneHeaderNode — Channel Section Header positioned directly above each channel's 2x6 pipeline.
 * Prioritizes profile_name as primary identity, with channel/platform details secondary.
 */
export default function LaneHeaderNode({ data }) {
  const {
    profileName,
    channelName,
    channelId,
    profileId,
    isAutonomous,
    growthMode,
    stock,
    status = 'IDLE',
    topic,
  } = data;

  // Prioritize channelName as primary identity, profileName as fallback
  const primaryName = channelName || profileName || channelId;
  const platformLabel = data.platform === 'tiktok' ? 'TikTok' : 'YouTube';
  const secondaryDetails = `${platformLabel} • ${channelId || profileId}`;

  return (
    <div className="lane-header-card">
      <div className="lane-header-left">
        <div className="lane-channel-avatar">📺</div>
        <div className="lane-channel-info">
          <div className="lane-channel-title" title={primaryName}>
            {primaryName}
          </div>
          <div className="lane-channel-subtitle">
            {secondaryDetails} • Perfil: <code>{profileId}</code>
          </div>
        </div>
      </div>

      <div className="lane-header-right">
        {topic && (
          <div className="lane-topic-pill" title={topic}>
            <span>Tarefa:</span> {topic}
          </div>
        )}
        <div className="lane-badges-row">
          <span className={`mini-badge ${isAutonomous ? 'autonomous' : 'manual'}`}>
            {isAutonomous ? '● Autônomo' : '○ Manual'}
          </span>
          <span className="mini-badge growth">
            {growthMode || 'warmup'}
          </span>
          <span className="mini-badge stock">
            Estoque: {stock !== undefined && stock !== null ? stock : 0}
          </span>
          <span className={`mini-badge status-${status}`}>
            {status}
          </span>
        </div>
      </div>

      {/* Discrete source handle to connect to Node #1 (TOPIC) */}
      <Handle
        type="source"
        id="header-source"
        position={Position.Bottom}
        className="node-handle handle-bottom"
        style={{ left: '90px' }}
      />
    </div>
  );
}
