import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { STAGE_BY_CODE, getStatusStyle } from '../utils/stageVisuals';

/**
 * ExecutionNode — Custom node for the 2x6 snake pipeline (R6A.6).
 * Features:
 * - Rich layered tonal background fill with subtle radial depth.
 * - Autonomous agent persona integration via tech-factory AgentAvatar.
 * - High-contrast semantic status badge with state-driven glow when RUNNING.
 * - Category accent line and discrete handles.
 */
export default function ExecutionNode({ data, selected }) {
  const {
    stepNumber,
    stage,
    stageLabel,
    status = 'PENDING',
    progress = null,
  } = data;

  const stageDef = STAGE_BY_CODE[stage] || {};
  const categoryLabel = stageDef.categoryLabel || '';
  const accentColor = stageDef.accentColor || '#38bdf8';
  const persona = stageDef.persona || {};
  const statusTheme = getStatusStyle(status);

  const isRunning = status === 'RUNNING' || status === 'PROCESSING';
  const isComplete = status === 'SUCCESS' || status === 'COMPLETE';
  const isBlocked = status === 'BLOCKED';
  const isFailed = status === 'FAILED';

  const getSummarizedStatus = (st) => {
    switch (st) {
      case 'RUNNING':
      case 'PROCESSING':
        return 'Executando';
      case 'SUCCESS':
      case 'COMPLETE':
        return 'Concluído';
      case 'FAILED':
        return 'Falhou';
      case 'BLOCKED':
        return 'Bloqueado';
      case 'WAITING':
        return 'Aguardando';
      case 'SCHEDULED':
        return 'Agendado';
      case 'RETRY':
      case 'RETRYING':
        return 'Tentando';
      case 'IDLE':
      case 'PENDING':
      default:
        return 'Aguardando';
    }
  };

  const summarizedStatus = getSummarizedStatus(status);

  return (
    <div
      className={`execution-node node-compact node-status-${status} ${selected ? 'selected-node' : ''} ${isRunning ? 'is-running' : ''}`}
      style={{
        '--node-accent': accentColor,
        borderColor: isRunning
          ? accentColor
          : (isComplete
              ? 'rgba(16, 185, 129, 0.6)'
              : (isBlocked
                  ? 'rgba(245, 158, 11, 0.6)'
                  : (isFailed
                      ? 'rgba(239, 68, 68, 0.7)'
                      : statusTheme.borderColor))),
      }}
      title={`Etapa #${stepNumber}: ${stageLabel} • ${summarizedStatus} • Agente: ${persona.code || stage} (Clique para detalhes no Drawer)`}
    >
      {/* Category top accent line with glow when active */}
      <div
        className="node-category-pip"
        style={{
          backgroundColor: accentColor,
          boxShadow: isRunning ? `0 0 10px ${accentColor}` : 'none',
        }}
      />

      {/* Target Handles for Snake routing */}
      <Handle
        type="target"
        id="target-left"
        position={Position.Left}
        className="node-handle handle-left"
      />
      <Handle
        type="target"
        id="target-top"
        position={Position.Top}
        className="node-handle handle-top"
      />
      <Handle
        type="target"
        id="target-right"
        position={Position.Right}
        className="node-handle handle-right"
      />

      {/* Source Handles for Snake routing */}
      <Handle
        type="source"
        id="source-right"
        position={Position.Right}
        className="node-handle handle-right"
      />
      <Handle
        type="source"
        id="source-bottom"
        position={Position.Bottom}
        className="node-handle handle-bottom"
      />
      <Handle
        type="source"
        id="source-left"
        position={Position.Left}
        className="node-handle handle-left"
      />

      {/* Header: Step Number & Summarized State Badge */}
      <div className="node-compact-header">
        <span className="node-step-badge">#{stepNumber}</span>
        <span
          className={`node-status-pill status-${status.toLowerCase()}`}
          style={{
            color: statusTheme.color,
            borderColor: isRunning ? accentColor : statusTheme.borderColor,
          }}
        >
          {isRunning && <span className="running-dot" />}
          {isComplete && <span className="status-sym">✓</span>}
          {isBlocked && <span className="status-sym">⚠</span>}
          {isFailed && <span className="status-sym">✕</span>}
          <span className="status-text">{summarizedStatus}</span>
        </span>
      </div>

      {/* Body: Stage Icon + Stage Name */}
      <div className="node-compact-body">
        <span className="node-compact-icon" style={{ borderColor: `${accentColor}40` }}>
          {stageDef.icon || persona.avatar || '⚙️'}
        </span>
        <span className="node-compact-label" title={stageLabel}>
          {stageLabel}
        </span>
      </div>

      {/* Progress Bar (when active with telemetry progress) */}
      {progress !== null && progress !== undefined && isRunning && (
        <div className="node-progress-bar">
          <div
            className="node-progress-fill"
            style={{
              width: `${Math.min(100, Math.max(0, progress))}%`,
              backgroundColor: accentColor,
            }}
          />
        </div>
      )}
    </div>
  );
}
