import React from 'react';
import { Handle, Position } from '@xyflow/react';
import AgentAvatar from './AgentAvatar';
import { sanitizeDisplayText } from '../utils/stageVisuals';

/**
 * LaneHeaderNode — Channel Mission Control & Hero Context Banner (R6A.6).
 * Features:
 * - Channel primary identity with platform & focus badge.
 * - Active Agent Hero pill (AgentAvatar, persona code, role, progress) when RUNNING.
 * - Factual Idle/Standby status when not running (no simulated work).
 * - Real Ready Stock and Pipeline progress metrics.
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
    activePersona = null,
    activeStageDef = null,
    activeProgress = null,
    onOpenDrawer,
  } = data;

  const primaryName = sanitizeDisplayText(channelName || profileName || channelId);
  const platformLabel = data.platform === 'tiktok' ? 'TikTok' : 'YouTube';
  const secondaryDetails = `${platformLabel} • ${channelId || profileId}`;

  // Ready Stock real percentage (null -> '—', never 0)
  const stockCount = typeof readyStock === 'number' ? readyStock : null;
  const stockDisplay = stockCount !== null ? stockCount : '—';
  const hasTargetStock = typeof targetStock === 'number' && targetStock > 0;
  const stockPct = (hasTargetStock && stockCount !== null)
    ? Math.min(100, Math.round((stockCount / targetStock) * 100))
    : null;

  // Pipeline real completed stages
  const hasPipelineProgress = typeof completedStagesCount === 'number' && completedStagesCount > 0;
  const pipelinePct = hasPipelineProgress
    ? Math.min(100, Math.round((completedStagesCount / 12) * 100))
    : null;

  const isRunning = status === 'RUNNING';

  return (
    <div className={`lane-header-card status-lane-${status.toLowerCase()}`}>
      {/* 1. Left: Channel Identity */}
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

      {/* 2. Center: Active Agent Hero / Standby Context */}
      <div className="lane-header-center">
        {isRunning && activePersona ? (
          <div
            className="lane-active-agent-pill"
            title={`${activePersona.name} (${activePersona.role}): ${activePersona.bio}`}
          >
            <span className="agent-live-tag">⚡ AGENTE ATIVO</span>
            <AgentAvatar
              persona={activePersona}
              accentColor={activeStageDef?.accentColor || '#38bdf8'}
              isRunning={true}
              size="xs"
            />
            <strong className="agent-pill-code">{activePersona.code}</strong>
            <span className="agent-pill-role">{activePersona.role}</span>
            {activeProgress !== null && activeProgress !== undefined && (
              <span className="agent-pill-progress">[{activeProgress}%]</span>
            )}
          </div>
        ) : (
          <div className="lane-standby-pill">
            <span className="standby-dot" />
            <span className="standby-text">
              {status === 'BLOCKED'
                ? 'Canal Bloqueado / Cooldown'
                : 'Fábrica em Standby • Sem agente ativo'}
            </span>
          </div>
        )}

        {topic && (
          <div className="lane-topic-pill" title={sanitizeDisplayText(topic)}>
            <span>Pauta:</span> {sanitizeDisplayText(topic)}
          </div>
        )}
      </div>

      {/* 3. Right: Metrics & Actions */}
      <div className="lane-header-right">
        <div className="lane-badges-row">
          <span className={`mini-badge ${isAutonomous ? 'autonomous' : 'manual'}`}>
            {isAutonomous ? '● AUTO' : '○ MANUAL'}
          </span>
          <span className="mini-badge growth">
            {String(growthMode || 'warmup').toUpperCase()}
          </span>

          <span
            className="mini-badge stock"
            title="Estoque pronto para agendamento/publicação"
          >
            Estoque: {hasTargetStock ? `${stockDisplay} / ${targetStock}` : stockDisplay}
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
