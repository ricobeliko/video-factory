import React, { useMemo } from 'react';
import {
  ReactFlow,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import ExecutionNode from './ExecutionNode';
import LaneHeaderNode from './LaneHeaderNode';
import FactoryEdge from './FactoryEdge';
import { STAGE_DEFINITIONS, getEdgeSemantics } from '../utils/stageVisuals';

const nodeTypes = {
  executionNode: ExecutionNode,
  laneHeader: LaneHeaderNode,
};

const edgeTypes = {
  factoryEdge: FactoryEdge,
};

/**
 * FactoryLiveGraph — Single-Focus 2x6 Snake Pipeline for the Selected Channel (R6A.6).
 * Features:
 * - Single-focus detailed pipeline for the selected channel.
 * - 2x6 snake routing: Steps 1..6 (left->right) on Row 1, Steps 7..12 (right->left) on Row 2.
 * - Reactive state-driven FactoryEdge with native SVG energy packets on RUNNING edges.
 * - Dynamic context passed to LaneHeaderNode (active agent persona, progress, stock).
 */
export default function FactoryLiveGraph({ channel, onSelectChannelTask }) {
  const { nodes, edges } = useMemo(() => {
    if (!channel) {
      return { nodes: [], edges: [] };
    }

    const calculatedNodes = [];
    const calculatedEdges = [];

    // Layout coordinates
    const START_X = 40;
    const STEP_X = 200; // 180px node + 20px gap
    const headerY = 20;
    const row1Y = 88;
    const row2Y = 208;

    const channelId = channel.channel_id || channel.profile_id;
    const execution = channel.execution;
    const activeStage = execution?.pipeline_stage;
    const executionStatus = execution?.status || 'IDLE';

    // 1. Calculate status for all 12 stages
    const stageEvaluations = STAGE_DEFINITIONS.map((stageDef) => {
      let stageStatus = 'PENDING';
      let progress = null;
      let isGap = false;
      let provider = null;

      if (executionStatus === 'IDLE') {
        stageStatus = 'IDLE';
      } else if (activeStage === stageDef.code) {
        stageStatus = executionStatus;
        progress = execution?.progress;
        provider = execution?.provider;
      } else if (
        executionStatus === 'RUNNING' &&
        !activeStage &&
        ['SCRIPT', 'NARRATION', 'VISUALS'].includes(stageDef.code)
      ) {
        stageStatus = 'RUNNING';
        isGap = true;
        progress = execution?.progress;
      } else if (
        stageDef.code === 'YOUTUBE' &&
        execution?.publication_state?.status === 'success'
      ) {
        stageStatus = 'SUCCESS';
      } else if (
        stageDef.code === 'READY_STOCK' &&
        (channel.ready_stock > 0 || channel.stock > 0) &&
        executionStatus === 'IDLE'
      ) {
        stageStatus = 'SUCCESS';
      }

      return {
        stageDef,
        stageStatus,
        progress,
        isGap,
        provider,
      };
    });

    // Count strictly terminal positive REAL states
    const completedCount = stageEvaluations.filter(
      (e) => e.stageStatus === 'SUCCESS' || e.stageStatus === 'COMPLETE'
    ).length;

    // Detect currently running stage for pipeline hero readout
    const runningStageEval = stageEvaluations.find(
      (e) => e.stageStatus === 'RUNNING' || e.stageStatus === 'PROCESSING'
    );
    const activePersona = runningStageEval?.stageDef?.persona || null;
    const activeStageDef = runningStageEval?.stageDef || null;
    const activeProgress = runningStageEval?.progress || null;

    // 2. Channel Section Header Banner
    const headerNodeId = `header-${channelId}`;
    calculatedNodes.push({
      id: headerNodeId,
      type: 'laneHeader',
      position: { x: START_X, y: headerY },
      data: {
        profileName: channel.profile_name,
        channelName: channel.channel_name,
        channelId: channel.channel_id,
        profileId: channel.profile_id,
        platform: channel.platform,
        isAutonomous: channel.autonomous_enabled,
        growthMode: channel.growth_mode,
        readyStock: channel.ready_stock,
        targetStock: channel.target_stock,
        status: executionStatus,
        topic: execution?.topic,
        completedStagesCount: completedCount,
        activePersona,
        activeStageDef,
        activeProgress,
        onOpenDrawer: () => onSelectChannelTask(channel, execution?.task_id),
      },
      selectable: true,
    });

    // 3. 12 Pipeline Stage Nodes in 2x6 Snake Grid
    const stageNodeIds = {};

    stageEvaluations.forEach(({ stageDef, stageStatus, progress, isGap, provider }) => {
      const stepNum = stageDef.step;
      const nodeId = `node-${channelId}-${stageDef.code}`;
      stageNodeIds[stepNum] = nodeId;

      // Position: 1..6 on Row 1 (col 0..5), 7..12 on Row 2 (col 5..0)
      let x;
      let y;

      if (stepNum <= 6) {
        const colIndex = stepNum - 1; // 0..5
        x = START_X + colIndex * STEP_X;
        y = row1Y;
      } else {
        const colIndex = 12 - stepNum; // 5..0
        x = START_X + colIndex * STEP_X;
        y = row2Y;
      }

      calculatedNodes.push({
        id: nodeId,
        type: 'executionNode',
        position: { x, y },
        data: {
          stepNumber: stepNum,
          stage: stageDef.code,
          stageLabel: stageDef.label,
          status: stageStatus,
          progress,
          isGap,
          provider,
          channelData: channel,
          taskId: execution?.task_id,
        },
        selectable: true,
      });
    });

    // 4. Edges with state semantics (R6A.6 motion language)
    // Edge from Header to Stage #1 (TOPIC)
    const topicStatus = stageEvaluations[0]?.stageStatus || 'IDLE';
    const isTopicActive = topicStatus === 'RUNNING' || executionStatus === 'RUNNING';
    calculatedEdges.push({
      id: `edge-${headerNodeId}-topic`,
      source: headerNodeId,
      sourceHandle: 'header-source',
      target: stageNodeIds[1],
      targetHandle: 'target-top',
      type: 'factoryEdge',
      data: { isRunning: isTopicActive },
      className: isTopicActive ? 'active-edge edge-running' : 'edge-dimmed',
      animated: isTopicActive,
      style: {
        stroke: isTopicActive ? '#38bdf8' : '#334155',
        strokeWidth: isTopicActive ? 2 : 1.5,
        strokeDasharray: isTopicActive ? '6 4' : '3 3',
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 10,
        height: 10,
        color: isTopicActive ? '#38bdf8' : '#475569',
      },
    });

    // Internal snake edges for steps 1..11 -> 2..12
    for (let s = 1; s < 12; s++) {
      const fromStep = s;
      const toStep = s + 1;
      const fromId = stageNodeIds[fromStep];
      const toId = stageNodeIds[toStep];
      const fromEval = stageEvaluations[fromStep - 1];
      const toEval = stageEvaluations[toStep - 1];

      let sourceHandle;
      let targetHandle;

      if (fromStep < 6) {
        sourceHandle = 'source-right';
        targetHandle = 'target-left';
      } else if (fromStep === 6) {
        sourceHandle = 'source-bottom';
        targetHandle = 'target-top';
      } else {
        sourceHandle = 'source-left';
        targetHandle = 'target-right';
      }

      // Compute edge semantics based on real statuses
      const edgeSemantics = getEdgeSemantics(fromEval.stageStatus, toEval.stageStatus);
      const isEdgeRunning = edgeSemantics.type === 'running';

      calculatedEdges.push({
        id: `edge-${fromId}-${toId}`,
        source: fromId,
        sourceHandle,
        target: toId,
        targetHandle,
        type: 'factoryEdge',
        data: { isRunning: isEdgeRunning },
        className: edgeSemantics.className,
        animated: edgeSemantics.animated,
        style: {
          stroke: edgeSemantics.stroke,
          strokeWidth: edgeSemantics.strokeWidth,
          strokeDasharray: edgeSemantics.strokeDasharray,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 12,
          height: 12,
          color: edgeSemantics.markerColor,
        },
      });
    }

    return {
      nodes: calculatedNodes,
      edges: calculatedEdges,
    };
  }, [channel, onSelectChannelTask]);

  const handleNodeClick = (_, node) => {
    if (!channel) return;
    if (node.type === 'laneHeader') {
      onSelectChannelTask(channel, channel.execution?.task_id);
    } else if (node.type === 'executionNode') {
      onSelectChannelTask(channel, node.data.taskId, node.data.stage);
    }
  };

  if (!channel) {
    return (
      <div className="graph-container empty-graph" style={{ height: '340px' }}>
        <div className="graph-empty-message">
          <span>⚙️ Selecione um canal acima para inspecionar o pipeline em tempo real</span>
        </div>
      </div>
    );
  }

  return (
    <div className="graph-container" style={{ height: '335px' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={handleNodeClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
        minZoom={1}
        maxZoom={1}
        zoomOnScroll={false}
        zoomOnPinch={false}
        panOnScroll={false}
        zoomOnDoubleClick={false}
        panOnDrag={false}
        preventScrolling={false}
      />
    </div>
  );
}
