import React, { useState } from 'react';
import { pauseFactory, resumeFactory } from '../api';

export default function SettingsView({ systemStatus, onRefresh }) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [msg, setMsg] = useState(null);

  const isPaused = Boolean(systemStatus?.is_paused);

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
            Status do ambiente isolado, proteção de produção e parâmetros globais.
          </p>
        </div>
      </div>

      {msg && (
        <div className={`v2-alert-${msg.type}`}>
          {msg.text}
          <button className="v2-alert-close" onClick={() => setMsg(null)}>×</button>
        </div>
      )}

      {/* Cartão de Segurança Crítica */}
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

      {/* Controle de Parada de Emergência */}
      <div className="v2-card-section" style={{ marginTop: '24px' }}>
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
            className={`v2-btn-${isPaused ? 'primary' : 'danger'}`}
            onClick={handleTogglePause}
            disabled={isProcessing}
          >
            {isProcessing ? 'Aguarde...' : isPaused ? '▶ Retomar Fábrica' : '⏸ Pausar Fábrica'}
          </button>
        </div>
      </div>
    </div>
  );
}
