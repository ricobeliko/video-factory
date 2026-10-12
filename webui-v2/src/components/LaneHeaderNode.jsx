import React from 'react';
import { Handle, Position } from '@xyflow/react';

/**
 * LaneHeaderNode — Channel Mission Control Banner above the 2x6 pipeline (R6A.5).
 * Features:
 * - Channel primary identity with platform badge.
 * - Real Ready Stock and Pipeline progress metrics.
 * - Active topic pill and status chip.
 * - Focus indicator and drawer inspection trigger.
 */
export default function LaneHeaderNode({ data }) {
  const {
    profileName,
    channelName,
    channelId,
    profileId,
    isAutonomous,
    growthMode,
    readyStock = 0,
    targetStock = null,
    status = 'IDLE',
    topic,
    completedStagesCount = 0,
    onOpenDrawer,
  } = data;

  const primaryName = channelName || profileName || channelId;
  const platformLabel = data.platform === 'tiktok' ? 'TikTok' : 'YouTube';
  const secondaryDetails = `${platformLabel} • ${channelId || profileId}`;

  // Ready Stock real percentage
  const stockCount = typeof readyStock === 'number' ? readyStock : 0;
  const hasTargetStock = typeof targetStock === 'number' && targetStock > 0;
  const stockPct = hasTargetStock
    ? Math.min(100, Math.round((stockCount / targetStock) * 100))
    : null;

  // Pipeline real completed stages (Requirement 4: completed_count > 0 only, fail-closed)
  const hasPipelineProgress = typeof completedStagesCount === 'number' && completedStagesCount > 0;
  const pipelinePct = hasPipelineProgress
    ? Math.min(100, Math.round((completedStagesCount / 12) * 100))
    : null;

  return (
    <div className={`lane-header-card status-lane-${status.toLowerCase()}`}>
      <div className="lane-header-left">
        <div className="lane-channel-avatar">📺</div>
        <div className="lane-channel-info">
          <div className="lane-channel-title" title={primaryName}>
            {primaryName}
            <span className="lane-live-indicator">LIVE PIPELINE</span>
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
            {isAutonomous ? '● AUTO' : '○ MANUAL'}
          </span>
          <span className="mini-badge growth">
            {String(growthMode || 'warmup').toUpperCase()}
          </span>

          <span className="mini-badge stock">
            Estoque: {hasTargetStock ? `${stockCount} / ${targetStock}` : stockCount}
            {stockPct !== null && ` (${stockPct}%)`}
          </span>

          {hasPipelineProgress && (
            <span className="mini-badge pipeline-progress">
              {completedStagesCount} / 12 concluídos ({pipelinePct}%)
            </span>
          )}

          <span className={`mini-badge status-${status}`}>
            {status}
          </span>

          {onOpenDrawer && (
            <button
              className="lane-drawer-trigger-btn"
              onClick={(e) => {
                e.stopPropagation();
                onOpenDrawer();
              }}
              title="Abrir painel narrativo detalhado"
            >
              Trace Causal 🔍
            </button>
          )}
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
