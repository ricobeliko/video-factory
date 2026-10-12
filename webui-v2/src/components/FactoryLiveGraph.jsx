import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import ExecutionNode from './ExecutionNode';
import LaneHeaderNode from './LaneHeaderNode';

// Canonical 12 stages in strict pipeline sequence
const CANONICAL_STAGES = [
  { step: 1, code: 'TOPIC', label: 'Tema / Pauta' },
  { step: 2, code: 'SCRIPT', label: 'Roteiro' },
  { step: 3, code: 'NARRATION', label: 'Narração' },
  { step: 4, code: 'VISUALS', label: 'Visuais / Clipes' },
  { step: 5, code: 'RENDER', label: 'Renderização' },
  { step: 6, code: 'SAFETY', label: 'Safety Gate' },
  { step: 7, code: 'QUALITY', label: 'Quality Gate' },
  { step: 8, code: 'COPYRIGHT', label: 'Copyright Gate' },
  { step: 9, code: 'READY_STOCK', label: 'Estoque Pronto' },
  { step: 10, code: 'SCHEDULER', label: 'Agendamento' },
  { step: 11, code: 'PUBLISHER', label: 'Publicação' },
  { step: 12, code: 'YOUTUBE', label: 'YouTube' },
];

const nodeTypes = {
  executionNode: ExecutionNode,
  laneHeader: LaneHeaderNode,
};

/**
 * FactoryLiveGraph — 2 Rows x 6 Stages Snake Layout per Channel
 * Row 1 (L->R): 1. TOPIC -> 2. SCRIPT -> 3. NARRATION -> 4. VISUALS -> 5. RENDER -> 6. SAFETY
 *                                                                                        |
 * Row 2 (R->L): 12. YOUTUBE <- 11. PUBLISHER <- 10. SCHEDULER <- 9. READY <- 8. CPR <- 7. QUAL
 */
export default function FactoryLiveGraph({ channels, onSelectChannelTask }) {
  const { nodes, edges, totalHeight } = useMemo(() => {
    const calculatedNodes = [];
    const calculatedEdges = [];

    // Layout constants
    const START_X = 40;
    const STEP_X = 200; // 180px node + 20px gap
    const CHANNEL_BLOCK_HEIGHT = 330;

    channels.forEach((channel, cIndex) => {
      const channelY = cIndex * CHANNEL_BLOCK_HEIGHT + 25;
      const channelId = channel.channel_id || channel.profile_id;
      const execution = channel.execution;
      const activeStage = execution?.pipeline_stage;
      const executionStatus = execution?.status || 'IDLE';

      // 1. Channel Section Header Banner (Spanning above the 2x6 grid)
      const headerNodeId = `header-${channelId}`;
      calculatedNodes.push({
        id: headerNodeId,
        type: 'laneHeader',
        position: { x: START_X, y: channelY },
        data: {
          profileName: channel.profile_name,
          channelName: channel.channel_name,
          channelId: channel.channel_id,
          profileId: channel.profile_id,
          isAutonomous: channel.autonomous_enabled,
          growthMode: channel.growth_mode,
          stock: channel.stock,
          status: executionStatus,
          topic: execution?.topic,
        },
        selectable: true,
      });

      // 2. 12 Pipeline Stage Nodes in 2x6 Snake Grid
      const stageNodeIds = {};
      const row1Y = channelY + 68;
      const row2Y = channelY + 188;

      CANONICAL_STAGES.forEach((stageDef) => {
        const stepNum = stageDef.step;
        const nodeId = `node-${channelId}-${stageDef.code}`;
        stageNodeIds[stepNum] = nodeId;

        // Position calculation: 1..6 on Row 1 (col 0..5), 7..12 on Row 2 (col 5..0)
        let x;
        let y;

        if (stepNum <= 6) {
          // Row 1: Left to Right
          const colIndex = stepNum - 1; // 0..5
          x = START_X + colIndex * STEP_X;
          y = row1Y;
        } else {
          // Row 2: Right to Left
          const colIndex = 12 - stepNum; // 5..0
          x = START_X + colIndex * STEP_X;
          y = row2Y;
        }

        // Strict Non-Inference status determination
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
          channel.stock > 0 &&
          executionStatus === 'IDLE'
        ) {
          stageStatus = 'SUCCESS';
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

      // 3. Edges connecting the Snake sequence (1 -> 2 -> ... -> 12)
      // Edge from Header down to Stage 1 (TOPIC)
      calculatedEdges.push({
        id: `edge-${headerNodeId}-topic`,
        source: headerNodeId,
        sourceHandle: 'header-source',
        target: stageNodeIds[1],
        targetHandle: 'target-top',
        type: 'smoothstep',
        style: { stroke: '#475569', strokeWidth: 1.5, strokeDasharray: '3 3' },
      });

      // Internal snake edges
      for (let s = 1; s < 12; s++) {
        const fromStep = s;
        const toStep = s + 1;
        const fromId = stageNodeIds[fromStep];
        const toId = stageNodeIds[toStep];
        const fromStageCode = CANONICAL_STAGES[fromStep - 1].code;

        let sourceHandle;
        let targetHandle;

        if (fromStep < 6) {
          // Horizontal right: 1->2, 2->3, 3->4, 4->5, 5->6
          sourceHandle = 'source-right';
          targetHandle = 'target-left';
        } else if (fromStep === 6) {
          // Vertical down: 6 (SAFETY) -> 7 (QUALITY)
          sourceHandle = 'source-bottom';
          targetHandle = 'target-top';
        } else {
          // Horizontal left: 7->8, 8->9, 9->10, 10->11, 11->12
          sourceHandle = 'source-left';
          targetHandle = 'target-right';
        }

        const isEdgeActive =
          activeStage === fromStageCode && executionStatus === 'RUNNING';

        calculatedEdges.push({
          id: `edge-${fromId}-${toId}`,
          source: fromId,
          sourceHandle,
          target: toId,
          targetHandle,
          type: 'smoothstep',
          className: isEdgeActive ? 'active-edge' : '',
          animated: isEdgeActive,
          style: {
            stroke: isEdgeActive ? '#f59e0b' : '#334155',
            strokeWidth: isEdgeActive ? 2.5 : 2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 12,
            height: 12,
            color: isEdgeActive ? '#f59e0b' : '#475569',
          },
        });
      }
    });

    const computedHeight = Math.max(500, channels.length * CHANNEL_BLOCK_HEIGHT + 80);
    return {
      nodes: calculatedNodes,
      edges: calculatedEdges,
      totalHeight: computedHeight,
    };
  }, [channels]);

  const handleNodeClick = (_, node) => {
    if (node.type === 'laneHeader') {
      const channel = channels.find((c) => `header-${c.channel_id || c.profile_id}` === node.id);
      if (channel) onSelectChannelTask(channel);
    } else if (node.type === 'executionNode' && node.data?.channelData) {
      onSelectChannelTask(node.data.channelData, node.data.taskId);
    }
  };

  return (
    <div className="graph-container" style={{ height: `${totalHeight}px` }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.3}
        maxZoom={1.5}
      >
        <Background color="#1e293b" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
