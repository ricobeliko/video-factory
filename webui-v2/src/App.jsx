import React, { useEffect, useState } from 'react';
import {
  getChannelsOverview,
  getLiveExecutions,
  getReviewTasks,
  getSystemStatus,
} from './api';
import Sidebar from './components/Sidebar';
import FactoryHeader from './components/FactoryHeader';
import DashboardView from './components/DashboardView';
import ProductionView from './components/ProductionView';
import SchedulesView from './components/SchedulesView';
import AnalyticsView from './components/AnalyticsView';
import SettingsView from './components/SettingsView';
import ChannelListView from './components/ChannelWorkspace/ChannelListView';
import ChannelDetailView from './components/ChannelWorkspace/ChannelDetailView';
import VideoReviewView from './components/VideoReview/VideoReviewView';
import ExecutionDrawer from './components/ExecutionDrawer';
import CreateChannelModal from './components/ChannelWorkspace/CreateChannelModal';

export default function App() {
  const [activeNav, setActiveNav] = useState('dashboard'); // 'dashboard' | 'channels' | 'production' | 'review' | 'schedules' | 'analytics' | 'settings'
  const [channels, setChannels] = useState([]);
  const [channelsDetailed, setChannelsDetailed] = useState([]);
  const [systemStatus, setSystemStatus] = useState(null);
  const [liveExecutions, setLiveExecutions] = useState(null);
  const [flowPool, setFlowPool] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isApiOnline, setIsApiOnline] = useState(true);
  const [unreviewedCount, setUnreviewedCount] = useState(0);

  // Foco do canal
  const [userSelectedChannelId, setUserSelectedChannelId] = useState(null);
  const [hasUserManuallySelected, setHasUserManuallySelected] = useState(false);
  const [selectedChannelDetail, setSelectedChannelDetail] = useState(null);

  // Modais e Drawers
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [drawerChannel, setDrawerChannel] = useState(null);
  const [drawerTaskId, setDrawerTaskId] = useState(null);
  const [drawerStage, setDrawerStage] = useState(null);

  // Sincronização dinâmica de hash
  useEffect(() => {
    const handleHash = () => {
      if (typeof window !== 'undefined') {
        const hash = window.location.hash.replace('#', '');
        const validNavs = ['dashboard', 'channels', 'production', 'review', 'schedules', 'analytics', 'settings'];
        if (validNavs.includes(hash)) {
          setActiveNav(hash);
        }
      }
    };
    handleHash();
    window.addEventListener('hashchange', handleHash);
    return () => window.removeEventListener('hashchange', handleHash);
  }, []);

  // Polling unificado dos dados da fábrica
  const pollData = async () => {
    try {
      const [liveRes, statusRes, channelsRes, reviewRes] = await Promise.all([
        getLiveExecutions().catch(() => null),
        getSystemStatus().catch(() => null),
        getChannelsOverview().catch(() => null),
        getReviewTasks('pending').catch(() => null),
      ]);

      if (liveRes) {
        setLiveExecutions(liveRes);
        if (Array.isArray(liveRes.channels)) {
          setChannels(liveRes.channels);
        }
        if (liveRes.flow_pool) {
          setFlowPool(liveRes.flow_pool);
        }
      }

      if (statusRes) {
        setSystemStatus(statusRes);
      }

      if (channelsRes && Array.isArray(channelsRes.channels)) {
        setChannelsDetailed(channelsRes.channels);
        if (!liveRes || !Array.isArray(liveRes.channels) || liveRes.channels.length === 0) {
          setChannels(channelsRes.channels);
        }
      }

      if (reviewRes && Array.isArray(reviewRes.tasks)) {
        setUnreviewedCount(reviewRes.tasks.length);
      }

      setIsApiOnline(true);
      setLastUpdated(new Date());
    } catch (err) {
      console.warn('Erro na sincronização de dados da API:', err);
      setIsApiOnline(false);
    }
  };

  useEffect(() => {
    pollData();
    const timer = setInterval(pollData, 4000);
    return () => clearInterval(timer);
  }, []);

  // Resolução do canal focado para o pipeline
  let focusedChannel = null;
  if (hasUserManuallySelected && userSelectedChannelId) {
    focusedChannel = channels.find(
      (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
    );
  }
  if (!focusedChannel) {
    focusedChannel = channels.find((c) => c.execution?.status === 'RUNNING') || channels[0] || null;
  }

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

  const handleResetFocus = () => {
    setHasUserManuallySelected(false);
    setUserSelectedChannelId(null);
  };

  const handleOpenDrawer = (channel, stage = null) => {
    setDrawerChannel(channel);
    setDrawerTaskId(channel?.execution?.task_id || channel?.task_id);
    setDrawerStage(stage);
    setIsDrawerOpen(true);
  };

  const handleOpenChannelWorkspace = (channel) => {
    setSelectedChannelDetail(channel);
    setActiveNav('channels');
    if (typeof window !== 'undefined') {
      window.location.hash = '#channels';
    }
  };

  return (
    <div className="v2-app-layout">
      {/* 1. Sidebar Lateral Moderna (7 Seções) */}
      <Sidebar
        activeNav={activeNav}
        onSelectNav={handleSelectNav}
        systemStatus={systemStatus}
        unreviewedCount={unreviewedCount}
      />

      {/* 2. Área de Conteúdo Principal */}
      <main className="v2-main-content">
        <FactoryHeader
          activeNav={activeNav}
          systemStatus={systemStatus}
          lastUpdated={lastUpdated}
          isApiOnline={isApiOnline}
          onRefresh={pollData}
          unreviewedCount={unreviewedCount}
          onNavigate={handleSelectNav}
        />

        {/* VIEW 1: DASHBOARD REDESENHADO */}
        {activeNav === 'dashboard' && (
          <div className="v2-view-section">
            <DashboardView
              channels={channelsDetailed.length > 0 ? channelsDetailed : channels}
              systemStatus={systemStatus}
              liveExecutions={liveExecutions}
              onOpenChannel={handleOpenChannelWorkspace}
              onOpenCreateModal={() => setIsCreateModalOpen(true)}
              onNavigate={handleSelectNav}
              onRefresh={pollData}
            />
          </div>
        )}

        {/* VIEW 2: MEUS CANAIS (CHANNEL WORKSPACE) */}
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

        {/* VIEW 3: ESTEIRA DE PRODUÇÃO & GRAFO CAUSAL */}
        {activeNav === 'production' && (
          <div className="v2-view-section">
            <ProductionView
              channels={channels}
              focusedChannel={focusedChannel}
              hasUserManuallySelected={hasUserManuallySelected}
              onSelectFocus={handleSelectFocus}
              onResetFocus={handleResetFocus}
              onOpenDrawer={handleOpenDrawer}
              flowPool={flowPool}
              isApiOnline={isApiOnline}
            />
          </div>
        )}

        {/* VIEW 4: ESTOQUE & REVISÃO HUMANA DE VÍDEOS */}
        {activeNav === 'review' && (
          <div className="v2-view-section">
            <VideoReviewView
              onReviewActionComplete={pollData}
              isPaused={Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED')}
            />
          </div>
        )}

        {/* VIEW 5: AGENDAMENTOS */}
        {activeNav === 'schedules' && (
          <div className="v2-view-section">
            <SchedulesView
              channels={channelsDetailed.length > 0 ? channelsDetailed : channels}
              onOpenChannel={handleOpenChannelWorkspace}
            />
          </div>
        )}

        {/* VIEW 6: ANALYTICS & HISTÓRICO */}
        {activeNav === 'analytics' && (
          <div className="v2-view-section">
            <AnalyticsView
              channels={channelsDetailed.length > 0 ? channelsDetailed : channels}
            />
          </div>
        )}

        {/* VIEW 7: CONFIGURAÇÕES, FLOW POOL & DIAGNÓSTICO */}
        {activeNav === 'settings' && (
          <div className="v2-view-section">
            <SettingsView
              systemStatus={systemStatus}
              onRefresh={pollData}
              flowPool={flowPool}
            />
          </div>
        )}

        {/* Drawer Lateral de Telemetria Causal */}
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
