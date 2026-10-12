import React from 'react';
import { Handle, Position } from '@xyflow/react';

/**
 * LaneHeaderNode — Left anchor node displaying Channel & Profile identity
 */
export default function LaneHeaderNode({ data }) {
  const { channelName, profileId, isAutonomous, growthMode } = data;

  return (
    <div className="lane-header-node">
      <div className="lane-channel-title">
        <span>📺</span>
        <span title={channelName}>{channelName}</span>
      </div>
      <div className="lane-channel-subtitle">
        {profileId} • {isAutonomous ? 'AUTÔNOMO' : 'MANUAL'} ({growthMode || 'warmup'})
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}
