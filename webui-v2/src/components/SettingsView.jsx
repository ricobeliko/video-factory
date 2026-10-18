import React, { useState } from 'react';
import { pauseFactory, resumeFactory } from '../api';
import FlowAccountsSection from './FlowAccountsSection';
import AgentOpsView from './AgentOps/AgentOpsView';

/**
 * SettingsView — Configuracoes Globais, Provedores e Diagnostico Avancado
 * Agrupado em 3 abas limpas:
 * 1. Geral & Seguranca
 * 2. Provedores & Pool Flow
 * 3. Diagnostico & Telemetria Tecnica (com Agent Ops preservado)
 */
export default function SettingsView({ systemStatus, onRefresh, flowPool }) {
  const [activeTab, setActiveTab] = useState('general'); // 'general' | 'providers' | 'diagnostics'
  const [isProcessing, setIsProcessing] = useState(false);
  const [msg, setMsg] = useState(null);

  const isPaused = Boolean(systemStatus?.is_paused || systemStatus?.factory_state === 'PAUSED');

  const handleTogglePause = async () => {
    setIsProcessing(true);
    setMsg(null);
    try {
      if (isPaused) {
        await resumeFactory();
        setMsg({ type: 'success', text: 'Fábrica retomada com sucesso!' });
      } else {
        await pauseFactory();
        setMsg({ type: 'success', text: 'Fábrica pausada de forma segura.' });
      }
      if (onRefresh) onRefresh();
    } catch (err) {
      setMsg({ type: 'error', text: err.message || 'Erro ao alterar estado da fábrica.' });
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="v2-settings-container">
      <div className="v2-workspace-header">
        <div>
          <h2 className="v2-workspace-title">Configurações & Diagnóstico</h2>
          <p className="v2-workspace-subtitle">
            Preferências globais, pool de computação, saúde do sistema e diagnóstico técnico.
          </p>
        </div>
      </div>

      {msg && (
        <div className={`v2-alert-${msg.type}`}>
          {msg.text}
          <button className="v2-alert-close" onClick={() => setMsg(null)}>×</button>
        </div>
      )}

      {/* Sub-abas de Configurações */}
      <div className="v2-tab-nav-bar" style={{ marginBottom: '20px' }}>
        <button
          type="button"
          className={`v2-tab-btn ${activeTab === 'general' ? 'active' : ''}`}
          onClick={() => setActiveTab('general')}
        >
          🛡️ Geral & Segurança
        </button>
        <button
          type="button"
          className={`v2-tab-btn ${activeTab === 'providers' ? 'active' : ''}`}
          onClick={() => setActiveTab('providers')}
        >
          ☁️ Provedores & Pool Flow
        </button>
        <button
          type="button"
          className={`v2-tab-btn ${activeTab === 'diagnostics' ? 'active' : ''}`}
          onClick={() => setActiveTab('diagnostics')}
        >
          🩺 Diagnóstico & Telemetria
        </button>
      </div>

      {/* ABA 1: GERAL & SEGURANÇA */}
      {activeTab === 'general' && (
        <div className="v2-settings-tab-content">
          <div className="v2-card-section" style={{ borderLeft: '4px solid #10b981' }}>
            <h3 className="v2-section-title">🛡️ Status de Isolamento e Segurança</h3>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Garantia de que a fábrica em produção no PC Forte permanece 100% protegida contra modificações.
            </p>

            <div className="v2-settings-grid">
              <div className="v2-setting-item">
                <span className="v2-setting-label">Identidade do Ambiente</span>
                <span className="v2-setting-val"><span className="v2-tag-green">DEV_V2 (Isolado)</span></span>
              </div>

              <div className="v2-setting-item">
                <span className="v2-setting-label">Ambiente de Produção (PC Forte)</span>
                <span className="v2-setting-val"><code>C:\Projetos\MoneyPrinterTurbo</code> (PROTEGIDO)</span>
              </div>

              <div className="v2-setting-item">
                <span className="v2-setting-label">Publicação Externa em DEV</span>
                <span className="v2-setting-val"><span className="v2-tag-red">BLOQUEADA (Mock / Simulação)</span></span>
              </div>

              <div className="v2-setting-item">
                <span className="v2-setting-label">Papel da Instância</span>
                <span className="v2-setting-val"><code>PRIMARY</code> (Worktree Local)</span>
              </div>
            </div>
          </div>

          <div className="v2-card-section" style={{ marginTop: '20px' }}>
            <h3 className="v2-section-title">Controle Operacional da Fábrica</h3>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Interrompa de forma segura o scheduler e a esteira de renderizações sem perdas de estado.
            </p>

            <div className="v2-pause-control-row">
              <div>
                <strong>Estado Atual: {isPaused ? 'PAUSADA' : 'EM OPERAÇÃO'}</strong>
                <p className="v2-text-muted" style={{ fontSize: '13px', margin: '4px 0 0 0' }}>
                  {isPaused
                    ? 'Novas renderizações e publicações autônomas estão suspensas.'
                    : 'O scheduler monitora estoques e produz vídeos normalmente.'}
                </p>
              </div>

              <button
                type="button"
                className={`v2-btn-${isPaused ? 'primary' : 'danger'}`}
                onClick={handleTogglePause}
                disabled={isProcessing}
              >
                {isProcessing ? 'Aguarde...' : isPaused ? '▶ Retomar Fábrica' : '⏸ Pausar Fábrica'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ABA 2: PROVEDORES & POOL FLOW */}
      {activeTab === 'providers' && (
        <div className="v2-settings-tab-content">
          <div className="v2-card-section">
            <h3 className="v2-section-title">Google Flow & IA de Vídeo</h3>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Gerenciamento das contas conectadas ao pool de geração de vídeo do Google Flow.
            </p>
            <FlowAccountsSection flowPool={flowPool} />
          </div>
        </div>
      )}

      {/* ABA 3: DIAGNÓSTICO & TELEMETRIA AVANÇADA (AGENT OPS EMBUTIDO) */}
      {activeTab === 'diagnostics' && (
        <div className="v2-settings-tab-content">
          <div className="v2-card-section" style={{ marginBottom: '20px' }}>
            <h3 className="v2-section-title">🩺 Saúde dos Serviços do Sistema</h3>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Detalhamento de estado dos workers e serviços internos da Video Factory.
            </p>

            <div className="v2-health-indicators-grid">
              <div className="v2-health-item">
                <span className={`v2-indicator-dot ${isPaused ? 'inactive' : 'active'}`} />
                <div>
                  <div className="v2-health-name">Fábrica</div>
                  <div className="v2-health-val">{isPaused ? 'Pausada' : 'Online'}</div>
                </div>
              </div>

              <div className="v2-health-item">
                <span className={`v2-indicator-dot ${systemStatus?.worker_running ? 'active' : 'inactive'}`} />
                <div>
                  <div className="v2-health-name">Worker Pipeline</div>
                  <div className="v2-health-val">{systemStatus?.worker_running ? 'Ativo' : 'Parado'}</div>
                </div>
              </div>

              <div className="v2-health-item">
                <span className={`v2-indicator-dot ${systemStatus?.scheduler_running ? 'active' : 'inactive'}`} />
                <div>
                  <div className="v2-health-name">Scheduler</div>
                  <div className="v2-health-val">{systemStatus?.scheduler_running ? 'Ativo' : 'Parado'}</div>
                </div>
              </div>

              <div className="v2-health-item">
                <span className={`v2-indicator-dot ${systemStatus?.auto_publish_enabled ? 'active' : 'neutral'}`} />
                <div>
                  <div className="v2-health-name">Auto Publish</div>
                  <div className="v2-health-val">{systemStatus?.auto_publish_enabled ? 'Ativo' : 'Off'}</div>
                </div>
              </div>

              <div className="v2-health-item">
                <span className={`v2-indicator-dot ${systemStatus?.dry_run ? 'warning' : 'neutral'}`} />
                <div>
                  <div className="v2-health-name">Dry Run</div>
                  <div className="v2-health-val">{systemStatus?.dry_run ? 'Ativo (Simulado)' : 'Desativado'}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="v2-card-section">
            <h3 className="v2-section-title">Telemetria de Agentes (Agent Ops)</h3>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Observabilidade detalhada das ações executadas pelos agentes autônomos na fábrica.
            </p>
            <AgentOpsView />
          </div>
        </div>
      )}
    </div>
  );
}
