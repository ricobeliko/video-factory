import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import ExecutionNode from './ExecutionNode';
import LaneHeaderNode from './LaneHeaderNode';

// Canonical 12 stages in strict pipeline sequence
const CANONICAL_STAGES = [
  { code: 'TOPIC', label: 'Tema / Pauta' },
  { code: 'SCRIPT', label: 'Roteiro' },
  { code: 'NARRATION', label: 'Narração' },
  { code: 'VISUALS', label: 'Visuais / Clipes' },
  { code: 'RENDER', label: 'Renderização' },
  { code: 'SAFETY', label: 'Safety Gate' },
  { code: 'QUALITY', label: 'Quality Gate' },
  { code: 'COPYRIGHT', label: 'Copyright Gate' },
  { code: 'READY_STOCK', label: 'Estoque Pronto' },
  { code: 'SCHEDULER', label: 'Agendamento' },
  { code: 'PUBLISHER', label: 'Publicação' },
  { code: 'YOUTUBE', label: 'YouTube' },
];

const nodeTypes = {
  executionNode: ExecutionNode,
  laneHeader: LaneHeaderNode,
};

/**
 * FactoryLiveGraph — Single Canvas Multi-Channel Pipeline Graph
 * Strict Non-Inference: Nodes only show status if backed by actual backend telemetry.
 */
export default function FactoryLiveGraph({ channels, onSelectChannelTask }) {
  // Build nodes and edges dynamically based on live channels
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes = [];
    const edges = [];

    const LANE_HEIGHT = 160;
    const START_X = 260;
    const STEP_X = 170;

    channels.forEach((channel, cIndex) => {
      const y = cIndex * LANE_HEIGHT + 40;
      const channelId = channel.channel_id || channel.profile_id;
      const execution = channel.execution;
      const activeStage = execution?.pipeline_stage;
      const executionStatus = execution?.status || 'IDLE';

      // 1. Lane Header Node on Left
      const headerNodeId = `header-${channelId}`;
      nodes.push({
        id: headerNodeId,
        type: 'laneHeader',
        position: { x: 40, y },
        data: {
          channelName: channel.channel_name || channel.profile_name,
          profileId: channel.profile_id,
          isAutonomous: channel.autonomous_enabled,
          growthMode: channel.growth_mode,
        },
        selectable: true,
      });

      let prevNodeId = headerNodeId;

      // 2. 12 Pipeline Stage Nodes
      CANONICAL_STAGES.forEach((stageDef, sIndex) => {
        const nodeId = `node-${channelId}-${stageDef.code}`;
        const x = START_X + sIndex * STEP_X;

        // Strict Non-Inference status determination
        let stageStatus = 'PENDING';
        let progress = null;
        let isGap = false;
        let provider = null;

        if (executionStatus === 'IDLE') {
          stageStatus = 'IDLE';
        } else if (activeStage === stageDef.code) {
          // Exact stage match from backend
          stageStatus = executionStatus;
          progress = execution?.progress;
          provider = execution?.provider;
        } else if (
          executionStatus === 'RUNNING' &&
          !activeStage &&
          ['SCRIPT', 'NARRATION', 'VISUALS'].includes(stageDef.code)
        ) {
          // Documented gap in R5B: in-flight processing without sub-stage telemetry
          stageStatus = 'RUNNING';
          isGap = true;
          progress = execution?.progress;
        } else if (
          stageDef.code === 'YOUTUBE' &&
          execution?.publication_state?.status === 'success'
        ) {
          // Terminal success on YouTube
          stageStatus = 'SUCCESS';
        } else if (
          stageDef.code === 'READY_STOCK' &&
          channel.stock > 0 &&
          executionStatus === 'IDLE'
        ) {
          stageStatus = 'SUCCESS';
        }

        nodes.push({
          id: nodeId,
          type: 'executionNode',
          position: { x, y },
          data: {
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

        // Edge from previous node
        const isEdgeActive =
          stageStatus === 'RUNNING' ||
          (activeStage === stageDef.code && executionStatus === 'RUNNING');

        edges.push({
          id: `edge-${prevNodeId}-${nodeId}`,
          source: prevNodeId,
          target: nodeId,
          className: isEdgeActive ? 'active-edge' : '',
          animated: isEdgeActive,
        });

        prevNodeId = nodeId;
      });
    });

    return { initialNodes: nodes, initialEdges: edges };
  }, [channels]);

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  // Sync state when channels change
  React.useEffect(() => {
    // When channels update, keep nodes refreshed
  }, [initialNodes, initialEdges]);

  const handleNodeClick = (_, node) => {
    if (node.type === 'laneHeader') {
      const channel = channels.find((c) => `header-${c.channel_id || c.profile_id}` === node.id);
      if (channel) onSelectChannelTask(channel);
    } else if (node.type === 'executionNode' && node.data?.channelData) {
      onSelectChannelTask(node.data.channelData, node.data.taskId);
    }
  };

  return (
    <div className="graph-container">
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background color="#1e293b" gap={20} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            if (n.type === 'laneHeader') return '#3b82f6';
            if (n.data?.status === 'RUNNING') return '#f59e0b';
            if (n.data?.status === 'SUCCESS') return '#10b981';
            if (n.data?.status === 'FAILED') return '#ef4444';
            return '#334155';
          }}
          style={{ backgroundColor: '#0f172a', border: '1px solid #1e293b' }}
        />
      </ReactFlow>
    </div>
  );
}
