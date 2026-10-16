import React, { useState, useEffect, useCallback, useMemo } from 'react';
import FactoryHeader from './components/FactoryHeader';
import ChannelCard from './components/ChannelCard';
import FlowAccountsSection from './components/FlowAccountsSection';
import FactoryLiveGraph from './components/FactoryLiveGraph';
import ExecutionDrawer from './components/ExecutionDrawer';
import AgentOpsView from './components/AgentOps/AgentOpsView';
import { getLiveExecutions, getSystemStatus } from './api';
import './styles.css';

/**
 * App — Factory Live Command Console & Agent Ops Room (R6A.6 + Agent Ops V1.1).
 * Features:
 * - Single-focus detailed pipeline architecture for extreme scalability.
 * - Automatic deterministic selection of RUNNING channel, with fallback to first channel.
 * - Manual operator focus switching via top channel deck cards.
 * - Decoupled narrative execution drawer.
 * - Independent Agent Ops control room for real agent observability.
 */
export default function App() {
  // Navigation tab state (Factory Live | Agent Ops) with URL hash persistence
  const [activeTab, setActiveTab] = useState(() => {
    if (typeof window !== 'undefined' && window.location.hash === '#agent-ops') {
      return 'agent-ops';
    }
    return 'factory-live';
  });

  const [channels, setChannels] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [flowPool, setFlowPool] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isApiOnline, setIsApiOnline] = useState(true);

  // Focus selection for the detailed pipeline below
  const [userSelectedChannelId, setUserSelectedChannelId] = useState(null);

  // Drawer state
  const [drawerChannel, setDrawerChannel] = useState(null);
  const [drawerTaskId, setDrawerTaskId] = useState(null);
  const [drawerStage, setDrawerStage] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Polling loop for live execution and system status
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
      console.warn('Live API poll failed, keeping memory snapshot:', err.message);
      setIsApiOnline(false);
    }
  }, []);

  useEffect(() => {
    pollData();
    const interval = setInterval(pollData, 3000);
    return () => clearInterval(interval);
  }, [pollData]);

  // Latch initial channel ID once loaded so polling never auto-switches focus behind the operator's back
  useEffect(() => {
    if (!userSelectedChannelId && channels.length > 0) {
      const initialRunning = channels.find(
        (c) => c.execution?.status === 'RUNNING' || c.status === 'RUNNING'
      );
      const initial = initialRunning || channels[0];
      setUserSelectedChannelId(initial.channel_id || initial.profile_id);
    }
  }, [channels, userSelectedChannelId]);

  // Deterministic focused channel resolution (Requirement 1)
  const focusedChannel = useMemo(() => {
    if (!channels || channels.length === 0) return null;

    // 1. If operator manually picked a channel, look it up
    if (userSelectedChannelId) {
      const found = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (found) return found;
    }

    // 2. Fallback: Channel with active running task
    const running = channels.find(
      (c) => c.execution?.status === 'RUNNING' || c.status === 'RUNNING'
    );
    if (running) return running;

    // 3. Fallback: First channel
    return channels[0];
  }, [channels, userSelectedChannelId]);

  // Sync activeTab with URL hash changes
  useEffect(() => {
    const handleHashChange = () => {
      if (typeof window !== 'undefined') {
        const hash = window.location.hash;
        if (hash === '#agent-ops') {
          setActiveTab('agent-ops');
        } else {
          setActiveTab('factory-live');
        }
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectTab = (tab) => {
    setActiveTab(tab);
    if (typeof window !== 'undefined') {
      window.location.hash = tab === 'agent-ops' ? '#agent-ops' : '#factory-live';
    }
  };

  const handleSelectFocus = (channel) => {
    const id = channel.channel_id || channel.profile_id;
    setUserSelectedChannelId(id);
  };

  const handleOpenDrawer = (channel, taskId = null, stage = null) => {
    setDrawerChannel(channel);
    setDrawerTaskId(taskId || channel?.execution?.task_id);
    setDrawerStage(stage || channel?.execution?.pipeline_stage);
    setIsDrawerOpen(true);
  };

  return (
    <div className="app-container">
      {/* 1. Header with Navigation & System Health */}
      <FactoryHeader
        systemStatus={systemStatus}
        lastUpdated={lastUpdated}
        isApiOnline={isApiOnline}
        onRefresh={pollData}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
      />

      {/* 2. Main View: Factory Live vs Agent Ops */}
      {activeTab === 'agent-ops' ? (
        <AgentOpsView />
      ) : (
        <>
          {/* Top Channels Deck — Dynamic Multi-Channel Overview */}
          <div className="channels-deck-section">
            <div className="section-title-bar">
              <div className="deck-title-group">
                <span className="section-title-icon">📡</span>
                <span className="section-title">Canais Monitorados</span>
                <span className="channels-count-pill">
                  {channels.length} {channels.length === 1 ? 'canal' : 'canais'}
                </span>
                <span className="section-subtitle">
                  Clique em um canal para alternar o pipeline em tempo real
                </span>
              </div>
              {channels.length > 2 && (
                <div className="deck-scroll-hint">
                  <span>← Deslize para explorar ({channels.length}) →</span>
                </div>
              )}
            </div>

        <div className="channels-deck">
          {channels.length === 0 ? (
            <div style={{ padding: '16px', color: '#64748b', fontSize: '12px' }}>
              {isApiOnline ? 'Carregando canais operacionais...' : 'Nenhum canal disponível em memória.'}
            </div>
          ) : (
            channels.map((channel) => {
              const channelKey = channel.channel_id || channel.profile_id;
              const isFocused = (focusedChannel?.channel_id || focusedChannel?.profile_id) === channelKey;

              return (
                <ChannelCard
                  key={channelKey}
                  channel={channel}
                  isFocused={isFocused}
                  onSelectFocus={() => handleSelectFocus(channel)}
                  onOpenDrawer={() => handleOpenDrawer(channel)}
                />
              );
            })
          )}
        </div>
      </div>

      {/* 3. Google Flow Multi-Account Pool Deck */}
      <FlowAccountsSection flowPool={flowPool} />

      {/* 4. Factory Live Graph — Single-Focus 2x6 Snake Pipeline */}
      <div className="live-pipeline-section">
        <div className="section-title-bar pipeline-title-bar">
          <div className="title-left">
            <span className="section-title-icon">⚡</span>
            <span className="section-title">Pipeline em Tempo Real</span>
            {focusedChannel && (
              <span className="focused-channel-tag">
                Canal: <strong>{focusedChannel.channel_name || focusedChannel.profile_name}</strong>
              </span>
            )}
          </div>
          <div className="title-right">
            <span className="pipeline-legend">
              <span className="legend-dot running" /> Em Execução
              <span className="legend-dot success" /> Concluído
              <span className="legend-dot pending" /> Pendente
            </span>
          </div>
        </div>

        <FactoryLiveGraph
          channel={focusedChannel}
          onSelectChannelTask={handleOpenDrawer}
        />
      </div>

      {/* 5. Execution Lateral Drawer — Mission Control Narrative */}
      <ExecutionDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        channelData={drawerChannel}
        taskId={drawerTaskId}
        selectedStage={drawerStage}
        onRefresh={pollData}
        isPaused={Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED')}
      />
        </>
      )}
    </div>
  );
}
