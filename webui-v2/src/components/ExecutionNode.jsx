import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { STAGE_BY_CODE, getStatusStyle } from '../utils/stageVisuals';

/**
 * ExecutionNode — Custom node for the 2x6 snake pipeline (R6A.3).
 * Displays step number (#1..#12), category icon, stage code, friendly label, and status.
 * Visuals driven by centralized stageVisuals: status is primary, category is accent.
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
  const statusTheme = getStatusStyle(status);

  return (
    <div
      className={`execution-node node-status-${status} ${selected ? 'selected-node' : ''}`}
      style={{
        borderColor: statusTheme.borderColor,
        backgroundColor: statusTheme.bgColor,
      }}
    >
      {/* Category top accent pip */}
      <div
        className="node-category-pip"
        style={{ backgroundColor: accentColor }}
        title={`Categoria: ${categoryLabel}`}
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

      <div className="node-header">
        <div className="node-id-group">
          <span className="node-step-badge">#{stepNumber}</span>
          <span className="node-stage-icon" title={categoryLabel}>{stageIcon}</span>
          <span className="node-stage-code">{stage}</span>
        </div>
        <span
          className="node-status-badge"
          style={{
            color: statusTheme.color,
            backgroundColor: 'rgba(255, 255, 255, 0.06)',
            borderColor: statusTheme.borderColor,
          }}
        >
          {status === 'RUNNING' && <span className="running-dot" />}
          {status}
        </span>
      </div>

      <div className="node-stage-label" title={stageLabel}>
        {stageLabel}
      </div>

      {progress !== null && progress !== undefined && status === 'RUNNING' && (
        <div className="node-progress-bar">
          <div
            className="node-progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      )}

      {isGap && status === 'RUNNING' && (
        <div className="node-gap-hint">Sub-etapa em execução</div>
      )}

      {provider && (
        <div className="node-provider-tag" title={`Provedor: ${provider}`}>
          {provider}
        </div>
      )}

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
    </div>
  );
}
