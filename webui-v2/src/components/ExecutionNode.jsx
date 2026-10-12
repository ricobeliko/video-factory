import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { STAGE_BY_CODE, getStatusStyle } from '../utils/stageVisuals';

/**
 * ExecutionNode — Custom node for the 2x6 snake pipeline (R6A.5).
 * Features:
 * - Rich tonal background fill per stage.
 * - Autonomous agent persona chip (micro-avatar, agent code, role).
 * - Semantic status badge with active glow when RUNNING.
 * - Category accent line and discrete handles.
 */
export default function ExecutionNode({ data, selected }) {
  const {
    stepNumber,
    stage,
    stageLabel,
    status = 'PENDING',
    progress = null,
    isGap = false,
    provider = null,
  } = data;

  const stageDef = STAGE_BY_CODE[stage] || {};
  const stageIcon = stageDef.icon || '▪️';
  const categoryLabel = stageDef.categoryLabel || '';
  const accentColor = stageDef.accentColor || '#38bdf8';
  const persona = stageDef.persona || {};
  const statusTheme = getStatusStyle(status);

  const isRunning = status === 'RUNNING' || status === 'PROCESSING';
  const isComplete = status === 'SUCCESS' || status === 'COMPLETE';

  return (
    <div
      className={`execution-node node-status-${status} ${selected ? 'selected-node' : ''}`}
      style={{
        backgroundColor: stageDef.tonalBg || statusTheme.bgColor,
        borderColor: isRunning ? '#0284c7' : (isComplete ? 'rgba(16, 185, 129, 0.6)' : statusTheme.borderColor),
      }}
    >
      {/* Category top accent line */}
      <div
        className="node-category-pip"
        style={{ backgroundColor: accentColor }}
        title={`Categoria: ${categoryLabel} • Agente: ${persona.code || stage}`}
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

      {/* Header: Step Number, Agent Persona Chip, and Status Badge */}
      <div className="node-header">
        <div className="node-id-group">
          <span className="node-step-badge">#{stepNumber}</span>
          {persona.code && (
            <div className="node-persona-chip" title={`${persona.name} — ${persona.role}: ${persona.bio}`}>
              <span className="persona-glyph">{persona.avatar}</span>
              <span className="persona-code">{persona.code}</span>
            </div>
          )}
        </div>
        <span
          className="node-status-badge"
          style={{
            color: statusTheme.color,
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            borderColor: statusTheme.borderColor,
          }}
        >
          {isRunning && <span className="running-dot" />}
          {status}
        </span>
      </div>

      {/* Stage Core Info */}
      <div className="node-stage-body">
        <div className="node-stage-icon-row">
          <span className="node-stage-icon">{stageIcon}</span>
          <div className="node-stage-titles">
            <div className="node-stage-label" title={stageLabel}>
              {stageLabel}
            </div>
            {persona.role && (
              <div className="node-persona-role" title={persona.role}>
                {persona.role}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Progress Bar (When available) */}
      {progress !== null && progress !== undefined && isRunning && (
        <div className="node-progress-bar">
          <div
            className="node-progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      )}

      {/* Operational hints */}
      {isGap && isRunning && (
        <div className="node-gap-hint">Sub-etapa em execução</div>
      )}

      {provider && (
        <div className="node-provider-tag" title={`Provedor: ${provider}`}>
          Provedor: <span>{provider}</span>
        </div>
      )}
    </div>
  );
}
