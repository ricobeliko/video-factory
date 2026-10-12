import React, { useState, useEffect, useCallback } from 'react';
import FactoryHeader from './components/FactoryHeader';
import ChannelCard from './components/ChannelCard';
import FlowAccountsSection from './components/FlowAccountsSection';
import FactoryLiveGraph from './components/FactoryLiveGraph';
import ExecutionDrawer from './components/ExecutionDrawer';
import { getLiveExecutions, getSystemStatus } from './api';
import './styles.css';

export default function App() {
  const [channels, setChannels] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [flowPool, setFlowPool] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isApiOnline, setIsApiOnline] = useState(true);

  // Drawer state
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Polling loop for live execution and system status (reutilizado para Flow Pool)
  const pollData = useCallback(async () => {
    try {
      const [liveRes, statusRes] = await Promise.all([
        getLiveExecutions(),
        getSystemStatus(),
      ]);

      const channelsList = liveRes?.channels || liveRes?.data?.channels;
      if (Array.isArray(channelsList)) {
        setChannels(channelsList);
      }

      const poolData = liveRes?.flow_accounts || liveRes?.data?.flow_accounts || liveRes?.flow_pool || liveRes?.data?.flow_pool;
      if (poolData) {
        setFlowPool(poolData);
      }

      const sysData = statusRes?.data || statusRes;
      if (sysData) {
        setSystemStatus(sysData);
      }

      setLastUpdated(new Date());
      setIsApiOnline(true);
    } catch (err) {
      // Preserve existing memory snapshot; mark offline
      console.warn('Live API poll failed, keeping memory snapshot:', err.message);
      setIsApiOnline(false);
    }
  }, []);

  useEffect(() => {
    pollData();
    const interval = setInterval(pollData, 3000);
    return () => clearInterval(interval);
  }, [pollData]);

  const handleSelectChannel = (channel, taskId = null) => {
    setSelectedChannel(channel);
    setSelectedTaskId(taskId || channel?.execution?.task_id);
    setIsDrawerOpen(true);
  };

  return (
    <div className="app-container">
      {/* 1. Header with System Health & Sync State */}
      <FactoryHeader
        systemStatus={systemStatus}
        lastUpdated={lastUpdated}
        isApiOnline={isApiOnline}
        onRefresh={pollData}
      />

      {/* 2. Top Channels Deck */}
      <div className="channels-deck">
        {channels.length === 0 ? (
          <div style={{ padding: '12px', color: '#64748b', fontSize: '12px' }}>
            {isApiOnline ? 'Carregando canais operacionais...' : 'Nenhum canal disponível em memória.'}
          </div>
        ) : (
          channels.map((channel) => (
            <ChannelCard
              key={channel.channel_id || channel.profile_id}
              channel={channel}
              isSelected={selectedChannel?.profile_id === channel.profile_id && isDrawerOpen}
              onClick={() => handleSelectChannel(channel)}
            />
          ))
        )}
      </div>

      {/* 2.5 Google Flow Multi-Account Pool Deck (FLOW-UI-001) */}
      <FlowAccountsSection flowPool={flowPool} />

      {/* 3. Factory Live Graph (Single Canvas Multi-Lane React Flow) */}
      <FactoryLiveGraph
        channels={channels}
        onSelectChannelTask={handleSelectChannel}
      />

      {/* 4. Execution Lateral Drawer */}
      <ExecutionDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        channelData={selectedChannel}
        taskId={selectedTaskId}
      />
    </div>
  );
}
