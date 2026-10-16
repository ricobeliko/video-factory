import React from 'react';
import { STAGE_BY_CODE } from '../utils/stageVisuals';

/**
 * ChannelCard — Dynamic header card for each profile/channel in the top deck (R6A.6).
 * Features:
 * - Prioritizes channel_name as primary identity.
 * - Distinctive focus state when selected for detailed pipeline view.
 * - Real mathematical stock percentage and mini progress bar.
 * - Agent persona indicator when task is RUNNING.
 * - Scalable horizontal rail sizing (320-430px).
 * - Quick action to open causal execution drawer.
 */
export default function ChannelCard({
  channel,
  isFocused,
  onSelectFocus,
  onOpenDrawer,
}) {
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

  // Ready Stock real mathematical percentage calculation
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
      stockBarColor = '#38bdf8';
    }
  }

  const isRunning = execution?.status === 'RUNNING';
  const runningStage = execution?.pipeline_stage;
  const runningPersona = runningStage ? STAGE_BY_CODE[runningStage]?.persona : null;

  return (
    <div
      className={`channel-card ${isFocused ? 'active-focused' : ''} ${isRunning ? 'has-running-task' : ''}`}
      onClick={onSelectFocus}
      role="button"
      tabIndex={0}
      aria-label={`Canal ${primaryTitle}`}
      aria-selected={isFocused}
    >
      {/* Top Banner: 2-Row Responsive Header Layout */}
      <div className="channel-card-header">
        {/* Row 1: Primary Identity & Focus Badge */}
        <div className="channel-header-row channel-header-primary">
          <div className="channel-name-group">
            <span className="channel-icon">📺</span>
            <span className="channel-name" title={primaryTitle}>
              {primaryTitle}
            </span>
          </div>

          {isFocused && (
            <span className="mini-badge focused-badge" title="Canal com pipeline em exibição abaixo">
              ● EM FOCO
            </span>
          )}
        </div>

        {/* Row 2: Secondary Metadata & Mode Badges */}
        <div className="channel-header-row channel-header-secondary">
          <div className="channel-sub-id" title={`${secondarySubtitle} • ${profileMeta}`}>
            {secondarySubtitle} • <span className="profile-id-sub">{profileMeta}</span>
          </div>

          <div className="channel-mode-badges">
            <span
              className={`mini-badge ${isAutonomous ? 'autonomous' : 'manual'} clickable-badge`}
              title="Clique para gerenciar autonomia do canal"
              onClick={(e) => {
                e.stopPropagation();
                if (onOpenDrawer) onOpenDrawer();
              }}
            >
              {isAutonomous ? 'AUTO' : 'MANUAL'}
            </span>
            {growth_mode && (
              <span
                className="mini-badge growth clickable-badge"
                title={`Growth Mode: ${growth_mode} (clique para alterar)`}
                onClick={(e) => {
                  e.stopPropagation();
                  if (onOpenDrawer) onOpenDrawer();
                }}
              >
                {String(growth_mode).toUpperCase()}
              </span>
            )}
          </div>
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

        {/* Task Execution Status or IDLE */}
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

              {runningPersona && (
                <span
                  className="mini-badge agent-tag"
                  title={`${runningPersona.name} (${runningPersona.role})`}
                >
                  {runningPersona.avatar} {runningPersona.code}
                </span>
              )}

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

        {/* Quick Action Bar */}
        <div className="channel-card-actions">
          <button
            className="card-action-btn view-pipeline-btn"
            onClick={(e) => {
              e.stopPropagation();
              onSelectFocus();
            }}
            title="Exibir pipeline detalhado deste canal"
          >
            {isFocused ? '✓ Pipeline Ativo' : 'Ver Pipeline →'}
          </button>

          <button
            className="card-action-btn inspect-drawer-btn"
            onClick={(e) => {
              e.stopPropagation();
              if (onOpenDrawer) onOpenDrawer();
            }}
            title="Abrir painel lateral de execução"
          >
            Trace Causal 🔍
          </button>
        </div>
      </div>
    </div>
  );
}
