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
import SystemView from './components/System/SystemView';
import {
  buildSystemChannelHash,
  parseSystemChannelFromHash,
} from './components/System/systemEditLogic';
import DiagnosticsView from './components/Diagnostics/DiagnosticsView';
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
      if (window.location.hash.startsWith('#sistema')) return 'sistema';
      if (window.location.hash === '#diagnostico') return 'diagnostico';
      if (window.location.hash === '#producao') return 'producao';
      if (window.location.hash === '#factory-live') return 'factory-live';
      if (window.location.hash === '#agent-ops') return 'agent-ops';
      if (window.location.hash === '#video-review') return 'video-review';
      if (window.location.hash === '#frota') return 'frota';
    }
    return 'frota';
  });

  const [systemFocusChannelId, setSystemFocusChannelId] = useState(() => {
    if (typeof window !== 'undefined' && window.location.hash.startsWith('#sistema')) {
      return parseSystemChannelFromHash(window.location.hash);
    }
    return null;
  });

  const [liveData, setLiveData] = useState({
    channels: [],
    pipeline_stages: [],
    last_event: null,
  });
  const [systemStatus, setSystemStatus] = useState(null);
  const [userSelectedChannelId, setUserSelectedChannelId] = useState(null);
  const [hasUserManuallySelected, setHasUserManuallySelected] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Poll live execution data every 2 seconds
  const fetchLiveData = useCallback(async () => {
    try {
      const res = await getLiveExecutions();
      if (res && res.data) {
        setLiveData(res.data);
      }
    } catch (err) {
      console.error('Failed to fetch live executions:', err);
      setError('Falha ao sincronizar estado da fábrica');
    }
  }, []);

  // Poll general system status
  const fetchSystemData = useCallback(async () => {
    try {
      const res = await getSystemStatus();
      if (res && res.data) {
        setSystemStatus(res.data);
      }
    } catch (err) {
      console.error('Failed to fetch system status:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLiveData();
    fetchSystemData();

    const interval = setInterval(() => {
      fetchLiveData();
      fetchSystemData();
    }, 2000);

    return () => clearInterval(interval);
  }, [fetchLiveData, fetchSystemData]);

  const channels = liveData.channels || [];

  // 1. Single-Focus Deterministic Resolution
  const focusedChannel = useMemo(() => {
    if (!channels || channels.length === 0) return null;

    // 1. Manual user override has highest precedence if channel still exists
    if (hasUserManuallySelected && userSelectedChannelId) {
      const match = channels.find(
        (c) => (c.channel_id || c.profile_id) === userSelectedChannelId
      );
      if (match) return match;
    }

    // 2. Deterministic priority: Any RUNNING or RETRYING channel
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
        if (hash.startsWith('#sistema')) {
          setActiveTab('sistema');
          setSystemFocusChannelId(parseSystemChannelFromHash(hash));
        } else {
          setSystemFocusChannelId(null);
          if (hash === '#diagnostico') {
            setActiveTab('diagnostico');
          } else if (hash === '#producao') {
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
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectTab = (tab) => {
    setActiveTab(tab);
    if (tab !== 'sistema') {
      setSystemFocusChannelId(null);
    }
    if (typeof window !== 'undefined') {
      window.location.hash =
        tab === 'sistema'
          ? '#sistema'
          : tab === 'diagnostico'
          ? '#diagnostico'
          : tab === 'producao'
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

  const handleNavigateToSystemChannel = (channelId) => {
    const targetChannelId = channelId || null;
    setSystemFocusChannelId(targetChannelId);
    setActiveTab('sistema');
    if (typeof window !== 'undefined') {
      window.location.hash = buildSystemChannelHash(targetChannelId);
    }
  };

  const handleSelectChannel = (channelId) => {
    setUserSelectedChannelId(channelId);
    setHasUserManuallySelected(true);
  };

  const handleOpenDrawer = (channel) => {
    const cid = channel.channel_id || channel.profile_id;
    setUserSelectedChannelId(cid);
    setHasUserManuallySelected(true);
    setIsDrawerOpen(true);
  };

  const handleCloseDrawer = () => {
    setIsDrawerOpen(false);
  };

  // If user selected 'frota', render full Fleet screen view
  if (activeTab === 'frota') {
    return <FleetView onNavigate={handleSelectTab} />;
  }

  // If user selected 'producao', render unified Production screen view
  if (activeTab === 'producao') {
    return <ProductionView onNavigate={handleSelectTab} />;
  }
  if (activeTab === 'sistema') {
    return (
      <SystemView
        onNavigate={handleSelectTab}
        focusChannelId={systemFocusChannelId}
      />
    );
  }
  if (activeTab === 'diagnostico') {
    return <DiagnosticsView onNavigate={handleSelectTab} />;
  }

  return (
    <div className="app-container">
      {/* Global Factory Header */}
      <FactoryHeader
        systemStatus={systemStatus}
        liveData={liveData}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
      />

      {/* Main Content Workspace */}
      <main className="main-content">
        {error && (
          <div className="app-error-banner" role="alert">
            <span className="error-icon">⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {activeTab === 'video-review' ? (
          <VideoReviewView
            onNavigateToLive={() => handleSelectTab('factory-live')}
          />
        ) : activeTab === 'agent-ops' ? (
          <AgentOpsView
            channels={channels}
            onSelectChannel={handleSelectChannel}
            onOpenDrawer={handleOpenDrawer}
          />
        ) : (
          <>
            {/* Top Channel Deck Cards */}
            <section
              className="channel-deck-section"
              aria-label="Canais Ativos"
            >
              <div className="channel-deck">
                {channels.map((channel) => {
                  const channelKey =
                    channel.channel_id ||
                    channel.profile_id ||
                    `chan-${channel.name}`;
                  const isFocused =
                    focusedChannel &&
                    (focusedChannel.channel_id === channel.channel_id ||
                      focusedChannel.profile_id === channel.profile_id);

                  return (
                    <ChannelCard
                      key={channelKey}
                      channel={channel}
                      isFocused={isFocused}
                      onSelectChannel={handleSelectChannel}
                      onOpenDrawer={handleOpenDrawer}
                    />
                  );
                })}
              </div>
            </section>

            {/* Middle Pipeline Live Graph Area for Focused Channel */}
            <section
              className="pipeline-graph-section"
              aria-label="Grafo de Execução em Tempo Real"
            >
              <FactoryLiveGraph
                focusedChannel={focusedChannel}
                pipelineStages={liveData.pipeline_stages}
                onOpenDrawer={handleOpenDrawer}
              />
            </section>

            {/* Bottom Flow Accounts & Quotas Section */}
            <section
              className="flow-accounts-container"
              aria-label="Painel de Contas e Cotas"
            >
              <FlowAccountsSection />
            </section>
          </>
        )}
      </main>

      {/* Slide-over Detailed Narrative Execution Drawer */}
      <ExecutionDrawer
        isOpen={isDrawerOpen}
        channel={focusedChannel}
        onClose={handleCloseDrawer}
        onNavigateToSystem={handleNavigateToSystemChannel}
      />
    </div>
  );
}
