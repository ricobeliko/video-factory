import React from 'react';
import { Handle, Position } from '@xyflow/react';

/**
 * ExecutionNode — Custom node for the 12 canonical pipeline stages
 * Strict Non-Inference: Only displays status and progress when returned by backend.
 */
export default function ExecutionNode({ data, selected }) {
  const {
    stage,
    stageLabel,
    status = 'PENDING',
    progress = null,
    isGap = false,
    provider = null,
  } = data;

  const statusClass = `node-status-${status}`;

  return (
    <div className={`execution-node ${statusClass} ${selected ? 'selected-node' : ''}`}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="node-header">
        <span className="node-stage-code">{stage}</span>
        <span className="node-status-badge">{status}</span>
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
        <div className="node-gap-hint">Sub-etapa ainda não instrumentada</div>
      )}
      {provider && (
        <div style={{ fontSize: '9px', color: '#94a3b8', marginTop: '2px', fontFamily: 'var(--font-mono)' }}>
          {provider}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}
