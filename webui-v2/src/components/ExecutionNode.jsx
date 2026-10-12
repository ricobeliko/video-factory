import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { STAGE_BY_CODE, getStatusStyle } from '../utils/stageVisuals';
import AgentAvatar from './AgentAvatar';

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
    isGap = false,
    provider = null,
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

  return (
    <div
      className={`execution-node node-status-${status} ${selected ? 'selected-node' : ''} ${isRunning ? 'is-running' : ''}`}
      style={{
        '--node-accent': accentColor,
        borderColor: isRunning
          ? accentColor
          : (isComplete
              ? 'rgba(16, 185, 129, 0.55)'
              : (isBlocked
                  ? 'rgba(245, 158, 11, 0.5)'
                  : (isFailed
                      ? 'rgba(239, 68, 68, 0.6)'
                      : statusTheme.borderColor))),
      }}
    >
      {/* Category top accent line with subtle localized aura */}
      <div
        className="node-category-pip"
        style={{
          backgroundColor: accentColor,
          boxShadow: isRunning ? `0 0 8px ${accentColor}` : 'none',
        }}
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

      {/* Header: Step Number, Agent Persona Identity Chip, and Status Badge */}
      <div className="node-header">
        <div className="node-id-group">
          <span className="node-step-badge">#{stepNumber}</span>
          {persona.code && (
            <div className="node-persona-chip" title={`${persona.name} — ${persona.role}: ${persona.bio}`}>
              <span className="persona-code">{persona.code}</span>
            </div>
          )}
        </div>
        <span
          className="node-status-badge"
          style={{
            color: statusTheme.color,
            backgroundColor: 'rgba(15, 23, 42, 0.75)',
            borderColor: isRunning ? accentColor : statusTheme.borderColor,
          }}
        >
          {isRunning && <span className="running-dot" />}
          {status}
        </span>
      </div>

      {/* Stage Core Info with Integrated Tech-Factory AgentAvatar */}
      <div className="node-stage-body">
        <div className="node-stage-icon-row">
          <AgentAvatar
            persona={persona}
            accentColor={accentColor}
            isRunning={isRunning}
            size="sm"
          />
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
            style={{
              width: `${Math.min(100, Math.max(0, progress))}%`,
              backgroundColor: accentColor,
            }}
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
