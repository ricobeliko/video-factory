import React, { useState, useEffect, useCallback, useMemo } from 'react';
import FactoryHeader from './components/FactoryHeader';
import ChannelCard from './components/ChannelCard';
import FlowAccountsSection from './components/FlowAccountsSection';
import FactoryLiveGraph from './components/FactoryLiveGraph';
import ExecutionDrawer from './components/ExecutionDrawer';
import AgentOpsView from './components/AgentOps/AgentOpsView';
import VideoReviewView from './components/VideoReview/VideoReviewView';
import { getLiveExecutions, getSystemStatus } from './api';
import FleetView from './components/Fleet/FleetView';
import ProductionView from './components/Production/ProductionView';
import './styles.css';

/**
 * App — Factory Live Command Console, Agent Ops Room & Video Review Center.
 * Features:
 * - Single-focus detailed pipeline architecture for extreme scalability.
 * - Automatic deterministic selection of RUNNING channel, with fallback to first channel.
 * - Manual operator focus switching via top channel deck cards.
 * - Decoupled narrative execution drawer.
 * - Independent Agent Ops control room for real agent observability.
 * - Human Video Review Center for safe Quality Gate inspection and recovery.
 */
export default function App() {
  // Navigation tab state (Frota | Factory Live | Agent Ops | Video Review) with URL hash persistence
  const [activeTab, setActiveTab] = useState(() => {
    if (typeof window !== 'undefined') {
      if (window.location.hash === '#producao') return 'producao';
      if (window.location.hash === '#factory-live') return 'factory-live';
      if (window.location.hash === '#agent-ops') return 'agent-ops';
      if (window.location.hash === '#video-review') return 'video-review';
      if (window.location.hash === '#frota') return 'frota';
    }
    return 'frota';
  });

  const [channels, setChannels] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [flowPool, setFlowPool] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isApiOnline, setIsApiOnline] = useState(true);

  // Focus selection for the detailed pipeline below
  const [userSelectedChannelId, setUserSelectedChannelId] = useState(null);
  const [hasUserManuallySelected, setHasUserManuallySelected] = useState(false);

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
    if (activeTab === 'frota' || activeTab === 'producao') {
      return;
    }
    pollData();
    const interval = setInterval(pollData, 3000);
    return () => clearInterval(interval);
  }, [pollData, activeTab]);

  // Set default initial channel ID once loaded
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

    // 1. If operator explicitly clicked a channel, honor that manual selection
    if (hasUserManuallySelected && userSelectedChannelId) {
      const found = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (found) return found;
    }

    // 2. Dynamic tracking: prefer channel with active running or retrying task
    const active = channels.find(
      (c) =>
        c.execution?.status === 'RUNNING' ||
        c.status === 'RUNNING' ||
        c.execution?.status === 'RETRYING' ||
        c.status === 'RETRYING'
    );
    if (active) return active;

    // 3. Fallback: Previously defaulted channel
    if (userSelectedChannelId) {
      const found = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (found) return found;
    }

    // 4. Fallback: First channel
    return channels[0];
  }, [channels, userSelectedChannelId, hasUserManuallySelected]);

  // Sync activeTab with URL hash changes
  useEffect(() => {
    const handleHashChange = () => {
      if (typeof window !== 'undefined') {
        const hash = window.location.hash;
        if (hash === '#producao') {
          setActiveTab('producao');
        } else if (hash === '#agent-ops') {
          setActiveTab('agent-ops');
        } else if (hash === '#video-review') {
          setActiveTab('video-review');
        } else if (hash === '#factory-live') {
          setActiveTab('factory-live');
        } else {
          setActiveTab('frota');
        }
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectTab = (tab) => {
    setActiveTab(tab);
    if (typeof window !== 'undefined') {
      window.location.hash =
        tab === 'producao'
          ? '#producao'
          : tab === 'agent-ops'
          ? '#agent-ops'
          : tab === 'video-review'
          ? '#video-review'
          : tab === 'factory-live'
          ? '#factory-live'
          : '#frota';
    }
  };

  const handleSelectFocus = (channel) => {
    const id = channel.channel_id || channel.profile_id;
    setUserSelectedChannelId(id);
    setHasUserManuallySelected(true);
  };

  const handleOpenDrawer = (channel, taskId = null, stage = null) => {
    setDrawerChannel(channel);
    setDrawerTaskId(taskId || channel?.execution?.task_id);
    setDrawerStage(stage || channel?.execution?.pipeline_stage);
    setIsDrawerOpen(true);
  };

  if (activeTab === 'frota') {
    return <FleetView onNavigate={handleSelectTab} />;
  }
  if (activeTab === 'producao') {
    return <ProductionView onNavigate={handleSelectTab} />;
  }

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

      {/* 2. Main View: Factory Live vs Agent Ops vs Video Review */}
      {activeTab === 'agent-ops' ? (
        <AgentOpsView />
      ) : activeTab === 'video-review' ? (
        <VideoReviewView />
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
                {hasUserManuallySelected ? (
                  <button
                    type="button"
                    className="auto-track-toggle-btn manual"
                    onClick={() => setHasUserManuallySelected(false)}
                    title="Clique para voltar a focar automaticamente no canal com tarefa em execução"
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      border: '1px solid rgba(56, 189, 248, 0.4)',
                      backgroundColor: 'rgba(56, 189, 248, 0.1)',
                      color: '#38bdf8',
                      cursor: 'pointer',
                      marginLeft: '8px',
                    }}
                  >
                    🎯 Foco Manual [Voltar para Auto]
                  </button>
                ) : (
                  <span
                    style={{
                      fontSize: '11px',
                      color: '#34d399',
                      backgroundColor: 'rgba(16, 185, 129, 0.1)',
                      border: '1px solid rgba(16, 185, 129, 0.3)',
                      padding: '2px 8px',
                      borderRadius: '12px',
                      marginLeft: '8px',
                    }}
                    title="O pipeline acompanha automaticamente o canal com tarefa em andamento"
                  >
                    ● Rastreamento Dinâmico Ativo
                  </span>
                )}
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
