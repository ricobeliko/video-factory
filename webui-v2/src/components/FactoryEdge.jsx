import React from 'react';
import { BaseEdge, getSmoothStepPath } from '@xyflow/react';

/**
 * FactoryEdge — Custom React Flow edge for Factory Live (R6A.6).
 * Renders standard BaseEdge with semantic coloring, plus an energetic
 * data packet traveling along the path via native SVG <animateMotion>
 * strictly when the edge represents active RUNNING state.
 */
export default function FactoryEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
}) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
  });

  const isRunning = Boolean(data?.isRunning);

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      {isRunning && (
        <g className="edge-energy-packet" pointerEvents="none">
          {/* Subtle outer halo */}
          <circle r="4.5" fill="#38bdf8" opacity="0.45">
            <animateMotion dur="1.6s" repeatCount="indefinite" path={edgePath} />
          </circle>
          {/* Concentrated bright technical core */}
          <circle r="2" fill="#f0f9ff">
            <animateMotion dur="1.6s" repeatCount="indefinite" path={edgePath} />
          </circle>
        </g>
      )}
    </>
  );
}
