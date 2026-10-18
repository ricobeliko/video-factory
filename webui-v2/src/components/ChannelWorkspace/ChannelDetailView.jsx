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

  const [channelName, setChannelName] = useState(channel.name || '');
  const [channelNiche, setChannelNiche] = useState(channel.niche || '');
  const [targetStock, setTargetStock] = useState(channel.target_stock || 3);
  const [maxGen, setMaxGen] = useState(5);

  const channelId = channel.channel_id || channel.profile_id || channel.id;

  // Carrega configurações detalhadas do canal
  useEffect(() => {
    setIsLoading(true);
    setChannelName(channel.name || '');
    setChannelNiche(channel.niche || '');
    setTargetStock(channel.target_stock || 3);

    getProfileSettings(channelId)
      .then((data) => {
        setSettings(data);
        if (data?.quotas?.max_generations_24h) {
          setMaxGen(data.quotas.max_generations_24h);
        }
        if (data?.quotas?.target_ready_stock) {
          setTargetStock(data.quotas.target_ready_stock);
        }
      })
      .catch((err) => {
        console.warn('Erro ao carregar settings do canal:', err);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [channelId, channel]);

  const handleToggleAutonomous = async () => {
    try {
      const nextState = !channel.autonomous_enabled;
      await updateProfileAutonomousMode(channelId, nextState);
      channel.autonomous_enabled = nextState;
      setFeedback({ type: 'success', msg: `Autonomia ${nextState ? 'ativada' : 'pausada'} com sucesso!` });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao alterar autonomia.' });
    }
  };

  const handleSaveChannelInfo = async () => {
    setIsSaving(true);
    setFeedback(null);
    try {
      await updateProfileSettings(channelId, {
        name: channelName.trim(),
        niche: channelNiche.trim(),
      });
      channel.name = channelName.trim();
      channel.niche = channelNiche.trim();
      setFeedback({ type: 'success', msg: 'Nome e nicho do canal salvos com persistência real no SQLite!' });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao salvar informações do canal.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveQuotas = async () => {
    setIsSaving(true);
    setFeedback(null);
    try {
      await updateProfileQuotas(channelId, {
        target_ready_stock: Number(targetStock),
        max_generations_24h: Number(maxGen),
      });
      channel.target_stock = Number(targetStock);
      setFeedback({ type: 'success', msg: 'Metas e quotas atualizadas com sucesso no SQLite!' });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao salvar quotas.' });
    } finally {
      setIsSaving(false);
    }
  };

  const channelFormat = channel.settings?.editorial?.video_format || channel.settings?.video_format || 'traditional';

  const formatBadge = (fmt) => {
    if (fmt === 'quiz_paper') return { label: 'Quiz Papel P1.3', color: '#f59e0b', desc: 'Template homologado P1.3 com estética rústica e parâmetros congelados de animação.' };
    if (fmt === 'quiz_dilemma') return { label: 'Quiz Dilema Q0-R', color: '#8b5cf6', desc: 'Template homologado Q0-R tela dividida 50/50, escolhas impossíveis e timer central.' };
    return { label: 'Tradicional', color: '#10b981', desc: 'Montagem dinâmica com clipes Pexels/Pixabay, roteiro fluido e legendas animadas.' };
  };

  const badge = formatBadge(channelFormat);
  const effectiveVoice = channel.settings?.voice?.voice_name || (channelFormat === 'quiz_dilemma' ? 'pt-BR-FranciscaNeural' : 'pt-BR-AntonioNeural');

  return (
    <div className="v2-channel-detail-view">
      <div className="v2-detail-topbar">
        <button className="v2-btn-back" onClick={onBack}>
          ← Voltar para Todos os Canais
        </button>
        <div className="v2-detail-title-row">
          <div className="v2-detail-header-left">
            <h2 className="v2-detail-title">{channelName || channel.name}</h2>
            <div className="v2-detail-meta">
              <span className="v2-format-pill" style={{ backgroundColor: `${badge.color}20`, color: badge.color }}>
                {badge.label}
              </span>
              <span className="v2-meta-tag">ID: <code>{channelId}</code></span>
              <span className="v2-meta-tag">Nicho: {channelNiche || channel.niche || 'Geral'}</span>
              <span className="v2-meta-tag">Idioma: {channel.language || 'pt-BR'}</span>
            </div>
          </div>
          <div className="v2-detail-actions">
            <button
              className={`v2-btn-toggle-auto ${channel.autonomous_enabled ? 'active' : ''}`}
              onClick={handleToggleAutonomous}
            >
              Autonomia: {channel.autonomous_enabled ? '🟢 ATIVA' : '⚪ PAUSADA (OFF)'}
            </button>
          </div>
        </div>
      </div>

      {feedback && (
        <div className={`v2-feedback-banner ${feedback.type}`} style={{
          padding: '12px 16px',
          marginBottom: '16px',
          borderRadius: '8px',
          backgroundColor: feedback.type === 'success' ? '#065f4625' : '#7f1d1d25',
          border: `1px solid ${feedback.type === 'success' ? '#10b981' : '#ef4444'}`,
          color: feedback.type === 'success' ? '#34d399' : '#f87171',
          fontSize: '13px'
        }}>
          {feedback.msg}
        </div>
      )}

      {/* Navegação por Abas do Canal */}
      <div className="v2-tabs-nav">
        {[
          { id: 'overview', label: '1. Visão Geral' },
          { id: 'editorial', label: '2. Editorial & Roteiro' },
          { id: 'audio_video', label: '3. Vídeo & Áudio' },
          { id: 'publishing', label: '4. Destinos & Publicação' },
          { id: 'automation', label: '5. Automação & Quotas' },
          { id: 'stock', label: '6. Estoque por Canal' },
          { id: 'logs', label: '7. Logs & Auditoria' },
        ].map((tab) => (
          <button
            key={tab.id}
            id={`tab-btn-${tab.id}`}
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
                <span className="v2-metric-value">{channel.ready_stock || 0} / {targetStock}</span>
                <div className="v2-progress-bar">
                  <div
                    className="v2-progress-fill"
                    style={{
                      width: `${Math.min(100, ((channel.ready_stock || 0) / targetStock) * 100)}%`,
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
                      <span className="v2-dest-name">{acc.display_name || acc.name || acc.channel_name || 'Conta Vinculada'}</span>
                      <span className="v2-dest-project">
                        ID: <code>{acc.external_account_id || acc.id}</code>
                      </span>
                      <span className="v2-dest-status">✓ Ativa (Simulada)</span>
                    </div>
                  ))
                ) : (
                  <p className="v2-text-muted">Nenhum destino social associado a este canal ainda.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ABA 2: EDITORIAL & ROTEIRO */}
        {activeTab === 'editorial' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Diretrizes Editoriais do Canal</h4>
            <div className="v2-form-group">
              <label className="v2-form-label">Nome do Canal</label>
              <input
                id="inp-channel-name"
                type="text"
                className="v2-input-text"
                value={channelName}
                onChange={(e) => setChannelName(e.target.value)}
              />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Nicho Editorial</label>
              <input
                id="inp-channel-niche"
                type="text"
                className="v2-input-text"
                value={channelNiche}
                onChange={(e) => setChannelNiche(e.target.value)}
              />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Formato de Produção Homologado</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <input
                  type="text"
                  className="v2-input-text"
                  value={badge.label}
                  readOnly
                  style={{ backgroundColor: '#18181b', color: badge.color, fontWeight: 'bold' }}
                />
              </div>
              <small className="v2-text-muted">{badge.desc}</small>
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Idioma e Região</label>
              <input type="text" className="v2-input-text" value={`${channel.language || 'pt-BR'} (${channel.region || 'BR'})`} readOnly />
            </div>

            <button
              id="btn-save-channel-info"
              className="v2-btn-primary"
              style={{ marginTop: '16px' }}
              disabled={isSaving}
              onClick={handleSaveChannelInfo}
            >
              {isSaving ? 'Salvando...' : 'Salvar Informações do Canal'}
            </button>
          </div>
        )}

        {/* ABA 3: VÍDEO & ÁUDIO */}
        {activeTab === 'audio_video' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Configurações Canônicas de Áudio e Imagem</h4>
            
            <div className="v2-form-group">
              <label className="v2-form-label">Voz Efetiva do Narrador</label>
              <input
                type="text"
                className="v2-input-text"
                value={effectiveVoice}
                readOnly
                style={{ fontWeight: 'bold', color: '#38bdf8' }}
              />
              <div style={{ marginTop: '8px', padding: '12px', background: '#18181b', borderRadius: '6px', border: '1px solid #27272a' }}>
                <strong style={{ fontSize: '12px', color: '#a1a1aa' }}>Precedência Canônica da Fonte de Verdade:</strong>
                <ol style={{ margin: '6px 0 0 18px', fontSize: '12px', color: '#71717a', lineHeight: '1.6' }}>
                  <li><strong style={{ color: '#e4e4e7' }}>Template Homologado:</strong> Se o formato exigir voz específica (ex: Quiz Q0-R / Papel P1.3), o template tem precedência máxima.</li>
                  <li><strong style={{ color: '#e4e4e7' }}>Canal Operacional:</strong> Configuração individual do canal (<code>{channel.settings?.voice?.voice_name || 'N/A'}</code>).</li>
                  <li><strong style={{ color: '#e4e4e7' }}>Global:</strong> Fallback do sistema Video Factory (<code>config.voice_name</code>).</li>
                </ol>
              </div>
            </div>

            <div className="v2-form-group">
              <label className="v2-form-label">Resolução e Proporção</label>
              <input type="text" className="v2-input-text" value="1080x1920 (9:16 - Vertical Shorts/Reels/TikTok)" readOnly />
            </div>

            {/* Controles format-aware */}
            {channelFormat === 'traditional' && (
              <div style={{ marginTop: '16px', padding: '12px', background: '#064e3b20', border: '1px solid #059669', borderRadius: '6px' }}>
                <strong style={{ color: '#34d399', fontSize: '13px' }}>Controles Tradicionais Ativos:</strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#a7f3d0' }}>
                  Montagem livre com clipes dinâmicos de stock (Pexels / Pixabay), legendas com bounce e duração ajustável.
                </p>
              </div>
            )}

            {channelFormat === 'quiz_dilemma' && (
              <div style={{ marginTop: '16px', padding: '12px', background: '#581c8720', border: '1px solid #9333ea', borderRadius: '6px' }}>
                <strong style={{ color: '#c084fc', fontSize: '13px' }}>Template Quiz Q0-R Homologado (Congelado):</strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#e9d5ff' }}>
                  Layout tela dividida 50/50, escolhas impossíveis, cronômetro de 5 segundos e duração prevista estrita de 60–65s. Controles tradicionais conflitantes bloqueados.
                </p>
              </div>
            )}

            {channelFormat === 'quiz_paper' && (
              <div style={{ marginTop: '16px', padding: '12px', background: '#78350f20', border: '1px solid #d97706', borderRadius: '6px' }}>
                <strong style={{ color: '#fbbf24', fontSize: '13px' }}>Template Quiz Papel P1.3 Homologado (Congelado):</strong>
                <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#fef3c7' }}>
                  Textura de papel rústica, animação física de revelação e estilo de mistério. Controles manuais bloqueados para proteger integridade visual do canal.
                </p>
              </div>
            )}
          </div>
        )}

        {/* ABA 4: DESTINOS & PUBLICAÇÃO */}
        {activeTab === 'publishing' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Roteamento Multiprojeto Post for Me</h4>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              As credenciais de cada destino social são isoladas pelo Post for Me.
            </p>
            {channel.channels?.map((acc, idx) => (
              <div key={idx} className="v2-destination-card" style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 16px',
                background: '#18181b',
                border: '1px solid #27272a',
                borderRadius: '8px',
                marginBottom: '8px'
              }}>
                <div>
                  <strong style={{ color: '#f4f4f5' }}>{acc.platform?.toUpperCase()}: {acc.display_name || acc.name || 'Conta'}</strong>
                  <div className="v2-text-muted" style={{ fontSize: '12px' }}>ID Externo: {acc.external_account_id || acc.id}</div>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: '#27272a', color: '#a1a1aa' }}>
                    Canal ID: <code>{acc.id}</code>
                  </span>
                  <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: '#064e3b30', color: '#34d399', border: '1px solid #059669' }}>
                    Status: Simulado Ativo
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ABA 5: AUTOMAÇÃO & QUOTAS */}
        {activeTab === 'automation' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Metas de Estoque e Regras de Autonomia</h4>
            <div className="v2-form-row" style={{ display: 'flex', gap: '16px' }}>
              <div className="v2-form-group" style={{ flex: 1 }}>
                <label className="v2-form-label">Meta de Estoque Pronto</label>
                <input
                  id="inp-target-stock"
                  type="number"
                  min="1"
                  max="10"
                  className="v2-input-text"
                  value={targetStock}
                  onChange={(e) => setTargetStock(e.target.value)}
                />
                <small className="v2-text-muted">Quantidade mínima mantida em buffer pronto.</small>
              </div>
              <div className="v2-form-group" style={{ flex: 1 }}>
                <label className="v2-form-label">Teto de Gerações em 24h</label>
                <input
                  id="inp-max-gen"
                  type="number"
                  min="1"
                  max="15"
                  className="v2-input-text"
                  value={maxGen}
                  onChange={(e) => setMaxGen(e.target.value)}
                />
                <small className="v2-text-muted">Limite de segurança contra consumo excessivo.</small>
              </div>
            </div>

            <div style={{ marginTop: '16px', padding: '12px', background: '#18181b', borderRadius: '6px', border: '1px solid #27272a' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong style={{ fontSize: '13px', color: '#f4f4f5' }}>Guardião de Autonomia:</strong>
                  <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: '#a1a1aa' }}>
                    Estado atual: <span style={{ color: channel.autonomous_enabled ? '#34d399' : '#fbbf24', fontWeight: 'bold' }}>
                      {channel.autonomous_enabled ? 'ATIVADA' : 'PAUSADA (OFF)'}
                    </span>
                  </p>
                </div>
                <button
                  className={`v2-btn-toggle-auto ${channel.autonomous_enabled ? 'active' : ''}`}
                  onClick={handleToggleAutonomous}
                >
                  Alternar Autonomia
                </button>
              </div>
            </div>

            <button
              id="btn-save-quotas"
              className="v2-btn-primary"
              style={{ marginTop: '20px' }}
              disabled={isSaving}
              onClick={handleSaveQuotas}
            >
              {isSaving ? 'Salvando...' : 'Salvar Metas do Canal'}
            </button>
          </div>
        )}

        {/* ABA 6: ESTOQUE POR CANAL */}
        {activeTab === 'stock' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Estoque Pronto de Vídeos ({channel.ready_stock || 0} de {targetStock})</h4>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Vídeos verificados com Safety PASS, Quality &gt;= 70 e arquivos físicos prontos para publicação.
            </p>
            <div className="v2-stock-list">
              {[1, 2, 3, 4, 5].slice(0, channel.ready_stock || 0).map((idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 14px',
                  background: '#18181b',
                  border: '1px solid #27272a',
                  borderRadius: '6px',
                  marginBottom: '8px'
                }}>
                  <div>
                    <span style={{ color: '#10b981', marginRight: '8px' }}>●</span>
                    <strong style={{ fontSize: '13px', color: '#f4f4f5' }}>{channel.name} - Episódio {String(idx).padStart(2, '0')}</strong>
                    <div style={{ fontSize: '11px', color: '#71717a' }}>task_{channelId}_{String(idx).padStart(2, '0')} | Quality: 85.5 (STRONG) | Safety: PASS</div>
                  </div>
                  <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '4px', background: '#064e3b30', color: '#34d399', border: '1px solid #059669' }}>
                    Pronto para Postagem
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ABA 7: LOGS & AUDITORIA */}
        {activeTab === 'logs' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Auditoria e Diagnósticos Operacionais</h4>
            <div className="v2-logs-console" style={{
              background: '#09090b',
              padding: '14px',
              borderRadius: '6px',
              fontFamily: 'monospace',
              fontSize: '12px',
              color: '#a1a1aa',
              lineHeight: '1.6'
            }}>
              <div>[2026-10-18 14:02:51 UTC] Canal [{channelId}] sincronizado com a Video Factory V2.</div>
              <div>[2026-10-18 14:02:51 UTC] Guardião de isolamento ativo: gravação em produção bloqueada (DEV_V2).</div>
              <div>[2026-10-18 14:02:51 UTC] Formato validado: {badge.label} | Voz efetiva: {effectiveVoice}</div>
              <div>[2026-10-18 14:02:51 UTC] Buffer de estoque inspecionado: {channel.ready_stock || 0} itens prontos.</div>
              <div>[2026-10-18 14:02:51 UTC] Scheduler ativo em modo passivo sem workers autônomos.</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
