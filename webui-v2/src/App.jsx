import React, { useState, useEffect } from 'react';
import FleetView from './components/Fleet/FleetView';
import ProductionView from './components/Production/ProductionView';
import SystemView from './components/System/SystemView';
import DiagnosticsView from './components/Diagnostics/DiagnosticsView';
import VideoReviewView from './components/VideoReview/VideoReviewView';
import {
  parseSystemChannelFromHash,
} from './components/System/systemEditLogic';
import './styles.css';

/**
 * App — Video Factory Command Console V2.
 * Gerencia a navegação central unificada entre as 5 telas canônicas:
 * - Frota (#frota)
 * - Produção (#producao)
 * - Diagnóstico (#diagnostico)
 * - Revisão de Vídeos (#video-review)
 * - Sistema (#sistema)
 *
 * Hashes legados #factory-live e #agent-ops caem estritamente em #frota.
 */
export default function App() {
  const [activeTab, setActiveTab] = useState(() => {
    if (typeof window !== 'undefined') {
      const hash = window.location.hash;
      if (hash.startsWith('#sistema')) return 'sistema';
      if (hash === '#diagnostico') return 'diagnostico';
      if (hash === '#producao') return 'producao';
      if (hash === '#video-review') return 'video-review';
      if (hash === '#frota' || hash === '#factory-live' || hash === '#agent-ops') return 'frota';
    }
    return 'frota';
  });

  const [systemFocusChannelId, setSystemFocusChannelId] = useState(() => {
    if (typeof window !== 'undefined' && window.location.hash.startsWith('#sistema')) {
      return parseSystemChannelFromHash(window.location.hash);
    }
    return null;
  });

  // Sincroniza activeTab com mudanças no URL hash (#factory-live e #agent-ops caem em #frota)
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
          } else if (hash === '#video-review') {
            setActiveTab('video-review');
          } else {
            // #factory-live, #agent-ops e qualquer hash desconhecido caem em #frota
            setActiveTab('frota');
            if (hash === '#factory-live' || hash === '#agent-ops') {
              window.location.hash = '#frota';
            }
          }
        }
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleSelectTab = (tab) => {
    const targetTab = (tab === 'factory-live' || tab === 'agent-ops') ? 'frota' : tab;
    setActiveTab(targetTab);
    if (targetTab !== 'sistema') {
      setSystemFocusChannelId(null);
    }
    if (typeof window !== 'undefined') {
      window.location.hash =
        targetTab === 'sistema'
          ? '#sistema'
          : targetTab === 'diagnostico'
          ? '#diagnostico'
          : targetTab === 'producao'
          ? '#producao'
          : targetTab === 'video-review'
          ? '#video-review'
          : '#frota';
    }
  };

  if (activeTab === 'frota') {
    return <FleetView onNavigate={handleSelectTab} />;
  }

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

  if (activeTab === 'video-review') {
    return <VideoReviewView onNavigate={handleSelectTab} />;
  }

  return <FleetView onNavigate={handleSelectTab} />;
}
