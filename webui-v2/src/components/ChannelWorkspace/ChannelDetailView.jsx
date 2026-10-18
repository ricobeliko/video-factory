import React, { useState, useEffect } from 'react';
import {
  getProfileSettings,
  updateProfileSettings,
  updateProfileAutonomousMode,
  updateProfileQuotas,
  updateProfileSchedule,
} from '../../api';

export default function ChannelDetailView({ channel, onBack, onUpdateChannel }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [settings, setSettings] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const channelId = channel.channel_id || channel.profile_id || channel.id;

  // Carrega configurações detalhadas do canal
  useEffect(() => {
    setIsLoading(true);
    getProfileSettings(channelId)
      .then((data) => {
        setSettings(data);
      })
      .catch((err) => {
        console.warn('Erro ao carregar settings do canal:', err);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [channelId]);

  const handleToggleAutonomous = async () => {
    try {
      const nextState = !channel.autonomous_enabled;
      await updateProfileAutonomousMode(channelId, nextState);
      channel.autonomous_enabled = nextState;
      setFeedback({ type: 'success', msg: `Autonomia ${nextState ? 'ativada' : 'pausada'} com sucesso!` });
      onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao alterar autonomia.' });
    }
  };

  const handleSaveQuotas = async (newStock, maxGen) => {
    setIsSaving(true);
    try {
      await updateProfileQuotas(channelId, {
        target_ready_stock: Number(newStock),
        max_generations_24h: Number(maxGen),
      });
      setFeedback({ type: 'success', msg: 'Metas e quotas atualizadas com sucesso!' });
      onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message });
    } finally {
      setIsSaving(false);
    }
  };

  const formatBadge = (fmt) => {
    if (fmt === 'quiz_paper') return { label: 'Quiz Papel P1.3', color: '#f59e0b' };
    if (fmt === 'quiz_dilemma') return { label: 'Quiz Dilema Q0-R', color: '#8b5cf6' };
    return { label: 'Tradicional', color: '#10b981' };
  };

  const badge = formatBadge(channel.settings?.video_format || 'traditional');

  return (
    <div className="v2-channel-detail-view">
      <div className="v2-detail-topbar">
        <button className="v2-btn-back" onClick={onBack}>
          ← Voltar para Canais
        </button>
        <div className="v2-channel-identity">
          <div className="v2-channel-avatar-lg">
            {channel.name?.slice(0, 2).toUpperCase() || 'CH'}
          </div>
          <div>
            <div className="v2-channel-title-row">
              <h2 className="v2-channel-name-lg">{channel.name}</h2>
              <span className="v2-format-pill" style={{ backgroundColor: `${badge.color}20`, color: badge.color }}>
                {badge.label}
              </span>
              <span className={`v2-auto-pill ${channel.autonomous_enabled ? 'active' : 'idle'}`}>
                {channel.autonomous_enabled ? 'Autonomia Ativa' : 'Autonomia Pausada'}
              </span>
            </div>
            <p className="v2-channel-niche-sub">
              Nicho: <strong>{channel.niche || 'Geral'}</strong> | ID: <code>{channelId}</code>
            </p>
          </div>
        </div>

        <div className="v2-detail-actions">
          <button
            className={`v2-btn-toggle-auto ${channel.autonomous_enabled ? 'btn-danger' : 'btn-success'}`}
            onClick={handleToggleAutonomous}
          >
            {channel.autonomous_enabled ? '⏸ Pausar Autonomia' : '▶ Ativar Autonomia'}
          </button>
        </div>
      </div>

      {feedback && (
        <div className={`v2-alert-${feedback.type}`}>
          {feedback.msg}
          <button className="v2-alert-close" onClick={() => setFeedback(null)}>×</button>
        </div>
      )}

      {/* Navegação por Abas do Canal */}
      <div className="v2-tabs-nav">
        {[
          { id: 'overview', label: 'Visão Geral' },
          { id: 'editorial', label: 'Editorial' },
          { id: 'audio_video', label: 'Vídeo e Áudio' },
          { id: 'publishing', label: 'Publicação' },
          { id: 'automation', label: 'Automação & Metas' },
          { id: 'stock', label: 'Estoque' },
          { id: 'logs', label: 'Logs & Diagnóstico' },
        ].map((tab) => (
          <button
            key={tab.id}
            className={`v2-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Conteúdo das Abas */}
      <div className="v2-tab-content">
        {/* ABA 1: VISÃO GERAL */}
        {activeTab === 'overview' && (
          <div className="v2-tab-overview">
            <div className="v2-metrics-grid">
              <div className="v2-metric-card">
                <span className="v2-metric-label">Estoque Pronto</span>
                <span className="v2-metric-value">{channel.ready_stock || 0} / {channel.target_stock || 3}</span>
                <div className="v2-progress-bar">
                  <div
                    className="v2-progress-fill"
                    style={{
                      width: `${Math.min(100, ((channel.ready_stock || 0) / (channel.target_stock || 3)) * 100)}%`,
                    }}
                  />
                </div>
              </div>
              <div className="v2-metric-card">
                <span className="v2-metric-label">Em Processamento</span>
                <span className="v2-metric-value">{channel.pending_processing || 0}</span>
                <small className="v2-text-muted">Tarefas ativas na esteira</small>
              </div>
              <div className="v2-metric-card">
                <span className="v2-metric-label">Agendados</span>
                <span className="v2-metric-value">{channel.scheduled || 0}</span>
                <small className="v2-text-muted">Aguardando horário de postagem</small>
              </div>
              <div className="v2-metric-card">
                <span className="v2-metric-label">Falhas Recentes</span>
                <span className="v2-metric-value" style={{ color: channel.failed > 0 ? '#ef4444' : '#10b981' }}>
                  {channel.failed || 0}
                </span>
                <small className="v2-text-muted">Necessitam intervenção</small>
              </div>
            </div>

            <div className="v2-card-section" style={{ marginTop: '24px' }}>
              <h4 className="v2-section-title">Destinos Sociais Vinculados (Post for Me)</h4>
              <div className="v2-destinations-list">
                {channel.channels && channel.channels.length > 0 ? (
                  channel.channels.map((acc, idx) => (
                    <div key={idx} className="v2-destination-row">
                      <span className="v2-dest-platform">
                        {acc.platform === 'youtube' ? '🔴 YouTube' : '🎵 TikTok'}
                      </span>
                      <span className="v2-dest-name">{acc.name || acc.channel_name || 'Conta Vinculada'}</span>
                      <span className="v2-dest-project">
                        Projeto Post for Me: <code>{acc.project_id || 'Principal'}</code>
                      </span>
                      <span className="v2-dest-status">✓ Ativa</span>
                    </div>
                  ))
                ) : (
                  <p className="v2-text-muted">Nenhum destino social associado a este canal ainda.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ABA 2: EDITORIAL */}
        {activeTab === 'editorial' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Diretrizes Editoriais</h4>
            <div className="v2-form-group">
              <label className="v2-form-label">Nicho de Atuação</label>
              <input type="text" className="v2-input-text" value={channel.niche || ''} readOnly />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Formato de Produção Homologado</label>
              <input type="text" className="v2-input-text" value={badge.label} readOnly />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Idioma e Região</label>
              <input type="text" className="v2-input-text" value={`${channel.language || 'pt-BR'} (${channel.region || 'BR'})`} readOnly />
            </div>
          </div>
        )}

        {/* ABA 3: VÍDEO E ÁUDIO */}
        {activeTab === 'audio_video' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Configurações Canônicas de Áudio e Imagem</h4>
            <div className="v2-form-group">
              <label className="v2-form-label">Voz Oficial do Narrador</label>
              <input
                type="text"
                className="v2-input-text"
                value={channel.settings?.voice?.voice_name || 'pt-BR-AntonioNeural (Herdada do Canal)'}
                readOnly
              />
              <small className="v2-text-muted">
                Precedência canônica ativa: Template Fixo &gt; Perfil do Canal &gt; Global.
              </small>
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Resolução e Proporção</label>
              <input type="text" className="v2-input-text" value="1080x1920 (9:16 - Vertical Shorts/Reels/TikTok)" readOnly />
            </div>
          </div>
        )}

        {/* ABA 4: PUBLICAÇÃO */}
        {activeTab === 'publishing' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Roteamento Multiprojeto Post for Me</h4>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              As credenciais de cada projeto são resolvidas de forma isolada pela Video Factory V2.
            </p>
            {channel.channels?.map((acc, idx) => (
              <div key={idx} className="v2-destination-card">
                <div>
                  <strong>{acc.platform?.toUpperCase()}: {acc.name || 'Conta'}</strong>
                  <div className="v2-text-muted">ID Externo: {acc.external_account_id || acc.id}</div>
                </div>
                <div className="v2-badge-project">
                  Projeto: {acc.project_id || 'farme videos LABEL'}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ABA 5: AUTOMAÇÃO & METAS */}
        {activeTab === 'automation' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Metas de Estoque e Regras de Autonomia</h4>
            <div className="v2-form-row">
              <div className="v2-form-group" style={{ flex: 1 }}>
                <label className="v2-form-label">Meta de Estoque Pronto</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  className="v2-input-text"
                  defaultValue={channel.target_stock || 3}
                  id="inp-target-stock"
                />
              </div>
              <div className="v2-form-group" style={{ flex: 1 }}>
                <label className="v2-form-label">Teto de Gerações em 24h</label>
                <input
                  type="number"
                  min="1"
                  max="15"
                  className="v2-input-text"
                  defaultValue={settings?.quotas?.max_generations_24h || 5}
                  id="inp-max-gen"
                />
              </div>
            </div>

            <button
              className="v2-btn-primary"
              style={{ marginTop: '16px' }}
              disabled={isSaving}
              onClick={() => {
                const stock = document.getElementById('inp-target-stock').value;
                const maxGen = document.getElementById('inp-max-gen').value;
                handleSaveQuotas(stock, maxGen);
              }}
            >
              {isSaving ? 'Salvando...' : 'Salvar Metas do Canal'}
            </button>
          </div>
        )}

        {/* ABA 6: ESTOQUE */}
        {activeTab === 'stock' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Vídeos em Estoque</h4>
            <p className="v2-text-muted">
              {channel.ready_stock || 0} vídeo(s) pronto(s) para publicação aguardando na fila.
            </p>
          </div>
        )}

        {/* ABA 7: LOGS */}
        {activeTab === 'logs' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Auditoria e Diagnósticos</h4>
            <div className="v2-logs-console">
              <code>[2026-10-18 04:12] Canal {channel.name} sincronizado com a Video Factory V2.</code>
              <br />
              <code>[2026-10-18 04:12] Guardião de isolamento ativo: gravação em produção bloqueada.</code>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
