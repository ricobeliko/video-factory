import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Sidebar from './components/Sidebar';
import FactoryHeader from './components/FactoryHeader';
import ChannelCard from './components/ChannelCard';
import FlowAccountsSection from './components/FlowAccountsSection';
import FactoryLiveGraph from './components/FactoryLiveGraph';
import ExecutionDrawer from './components/ExecutionDrawer';
import AgentOpsView from './components/AgentOps/AgentOpsView';
import VideoReviewView from './components/VideoReview/VideoReviewView';
import ChannelListView from './components/ChannelWorkspace/ChannelListView';
import ChannelDetailView from './components/ChannelWorkspace/ChannelDetailView';
import CreateChannelModal from './components/ChannelWorkspace/CreateChannelModal';
import SettingsView from './components/SettingsView';
import { getLiveExecutions, getSystemStatus, getReviewTasks, getChannelsOverview } from './api';
import './styles.css';

/**
 * App — Video Factory V2 Main Console
 * Features:
 * - Modern Sidebar navigation (Dashboard, Meus Canais, Pipeline, Estoque, Agent Ops, Configurações).
 * - Channel-Centric Workspace (Channel Workspace & 7 Management Tabs).
 * - Smart Format-Aware Forms (Traditional, Quiz Q0-R, Quiz Paper P1.3).
 * - Real-time Execution Pipeline and Decoupled Lateral Drawer.
 * - Human Video Review Center for Quality Gate recovery.
 */
export default function App() {
  const [activeNav, setActiveNav] = useState(() => {
    if (typeof window !== 'undefined') {
      if (window.location.hash === '#channels') return 'channels';
      if (window.location.hash === '#pipeline') return 'pipeline';
      if (window.location.hash === '#review') return 'review';
      if (window.location.hash === '#agent-ops') return 'agent-ops';
      if (window.location.hash === '#settings') return 'settings';
    }
    return 'dashboard';
  });

  const [channels, setChannels] = useState([]);
  const [channelsDetailed, setChannelsDetailed] = useState([]);
  const [selectedChannelDetail, setSelectedChannelDetail] = useState(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState(null);
  const [flowPool, setFlowPool] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isApiOnline, setIsApiOnline] = useState(true);
  const [unreviewedCount, setUnreviewedCount] = useState(0);

  // Focus selection for the detailed pipeline
  const [userSelectedChannelId, setUserSelectedChannelId] = useState(null);
  const [hasUserManuallySelected, setHasUserManuallySelected] = useState(false);

  // Drawer state
  const [drawerChannel, setDrawerChannel] = useState(null);
  const [drawerTaskId, setDrawerTaskId] = useState(null);
  const [drawerStage, setDrawerStage] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Polling loop for live execution, system status and review count
  const pollData = useCallback(async () => {
    try {
      const [liveRes, statusRes, reviewRes, chRes] = await Promise.all([
        getLiveExecutions(),
        getSystemStatus(),
        getReviewTasks('pending').catch(() => null),
        getChannelsOverview().catch(() => null),
      ]);

      const channelsList = liveRes?.channels || liveRes?.data?.channels;
      if (Array.isArray(channelsList)) {
        setChannels(channelsList);
      }

      if (chRes?.channels) {
        setChannelsDetailed(chRes.channels);
      } else if (Array.isArray(channelsList)) {
        setChannelsDetailed(channelsList);
      }

      const poolData =
        liveRes?.flow_accounts ||
        liveRes?.data?.flow_accounts ||
        liveRes?.flow_pool ||
        liveRes?.data?.flow_pool;
      if (poolData) {
        setFlowPool(poolData);
      }

      const sysData = statusRes?.data || statusRes;
      if (sysData) {
        setSystemStatus(sysData);
      }

      const pendingTasks = reviewRes?.tasks || reviewRes?.data?.tasks;
      if (Array.isArray(pendingTasks)) {
        setUnreviewedCount(pendingTasks.length);
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

  // Deterministic focused channel resolution
  const focusedChannel = useMemo(() => {
    if (!channels || channels.length === 0) return null;

    if (hasUserManuallySelected && userSelectedChannelId) {
      const found = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (found) return found;
    }

    const active = channels.find(
      (c) =>
        c.execution?.status === 'RUNNING' ||
        c.status === 'RUNNING' ||
        c.execution?.status === 'RETRYING' ||
        c.status === 'RETRYING'
    );
    if (active) return active;

    if (userSelectedChannelId) {
      const found = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (found) return found;
    }

    return channels[0];
  }, [channels, userSelectedChannelId, hasUserManuallySelected]);

  const handleSelectNav = (navId) => {
    setActiveNav(navId);
    if (typeof window !== 'undefined') {
      window.location.hash = navId === 'dashboard' ? '' : `#${navId}`;
    }
  };

  const handleSelectFocus = (channel) => {
    const chId = channel.channel_id || channel.profile_id;
    setUserSelectedChannelId(chId);
    setHasUserManuallySelected(true);
  };

  const handleOpenDrawer = (channel, stage = null) => {
    setDrawerChannel(channel);
    setDrawerTaskId(channel?.execution?.task_id || channel?.task_id);
    setDrawerStage(stage);
    setIsDrawerOpen(true);
  };

  return (
    <div className="v2-app-layout">
      {/* 1. Sidebar Lateral Moderna */}
      <Sidebar
        activeNav={activeNav}
        onSelectNav={handleSelectNav}
        systemStatus={systemStatus}
        unreviewedCount={unreviewedCount}
      />

      {/* 2. Área de Conteúdo Principal */}
      <main className="v2-main-content">
        <FactoryHeader
          systemStatus={systemStatus}
          flowPool={flowPool}
          lastUpdated={lastUpdated}
          isApiOnline={isApiOnline}
          onRefresh={pollData}
          unreviewedCount={unreviewedCount}
        />

        {/* NAVEGAÇÃO 1: DASHBOARD */}
        {activeNav === 'dashboard' && (
          <div className="v2-view-section">
            <div className="channels-deck-container">
              <div className="section-title-bar deck-title-bar">
                <div className="title-left">
                  <span className="section-title-icon">📺</span>
                  <span className="section-title">Canais em Operação</span>
                  {hasUserManuallySelected ? (
                    <button
                      type="button"
                      className="auto-track-toggle-btn manual"
                      onClick={() => setHasUserManuallySelected(false)}
                      title="Voltar ao foco automático"
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
                    >
                      ● Rastreamento Dinâmico Ativo
                    </span>
                  )}
                </div>
              </div>

              <div className="channels-deck">
                {channels.length === 0 ? (
                  <div style={{ padding: '16px', color: '#64748b', fontSize: '12px' }}>
                    {isApiOnline ? 'Carregando canais operacionais...' : 'Nenhum canal disponível.'}
                  </div>
                ) : (
                  channels.map((channel) => {
                    const channelKey = channel.channel_id || channel.profile_id;
                    const isFocused =
                      (focusedChannel?.channel_id || focusedChannel?.profile_id) === channelKey;

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

            <FlowAccountsSection flowPool={flowPool} />

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
              </div>

              <FactoryLiveGraph
                channel={focusedChannel}
                onSelectChannelTask={handleOpenDrawer}
              />
            </div>
          </div>
        )}

        {/* NAVEGAÇÃO 2: MEUS CANAIS (CHANNEL WORKSPACE - FASE V2.4) */}
        {activeNav === 'channels' && (
          <div className="v2-view-section">
            {selectedChannelDetail ? (
              <ChannelDetailView
                channel={selectedChannelDetail}
                onBack={() => setSelectedChannelDetail(null)}
                onUpdateChannel={pollData}
              />
            ) : (
              <ChannelListView
                channels={channelsDetailed.length > 0 ? channelsDetailed : channels}
                onSelectChannel={(ch) => setSelectedChannelDetail(ch)}
                onOpenCreateModal={() => setIsCreateModalOpen(true)}
                onRefresh={pollData}
              />
            )}
          </div>
        )}

        {/* NAVEGAÇÃO 3: PIPELINE EM TELA CHEIA */}
        {activeNav === 'pipeline' && (
          <div className="v2-view-section">
            <div className="live-pipeline-section">
              <div className="section-title-bar pipeline-title-bar">
                <div className="title-left">
                  <span className="section-title-icon">⚡</span>
                  <span className="section-title">Pipeline Completo de Execução</span>
                  {focusedChannel && (
                    <span className="focused-channel-tag">
                      Canal: <strong>{focusedChannel.channel_name || focusedChannel.profile_name}</strong>
                    </span>
                  )}
                </div>
              </div>
              <FactoryLiveGraph
                channel={focusedChannel}
                onSelectChannelTask={handleOpenDrawer}
              />
            </div>
          </div>
        )}

        {/* NAVEGAÇÃO 4: ESTOQUE & REVISÃO HUMANA DE VÍDEOS */}
        {activeNav === 'review' && (
          <div className="v2-view-section">
            <VideoReviewView
              onReviewActionComplete={pollData}
              isPaused={Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED')}
            />
          </div>
        )}

        {/* NAVEGAÇÃO 5: AGENT OPS ROOM */}
        {activeNav === 'agent-ops' && (
          <div className="v2-view-section">
            <AgentOpsView />
          </div>
        )}

        {/* NAVEGAÇÃO 6: CONFIGURAÇÕES E DIAGNÓSTICO */}
        {activeNav === 'settings' && (
          <div className="v2-view-section">
            <SettingsView systemStatus={systemStatus} onRefresh={pollData} />
          </div>
        )}

        {/* Drawer Lateral de Telemetria */}
        <ExecutionDrawer
          isOpen={isDrawerOpen}
          onClose={() => setIsDrawerOpen(false)}
          channelData={drawerChannel}
          taskId={drawerTaskId}
          selectedStage={drawerStage}
          onRefresh={pollData}
          isPaused={Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED')}
        />

        {/* Modal de Criação Inteligente de Canais */}
        <CreateChannelModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
          onCreated={pollData}
        />
      </main>
    </div>
  );
}
