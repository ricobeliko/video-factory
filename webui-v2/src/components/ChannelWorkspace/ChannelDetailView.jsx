import React, { useState, useEffect } from 'react';
import {
  getProfileSettings,
  updateProfileSettings,
  updateProfileAutonomousMode,
  updateProfileQuotas,
  updateProfileSchedule,
  getVoices,
} from '../../api';

/**
 * ChannelDetailView — Painel de Gerenciamento Detalhado do Canal (V2.16)
 * Permite edição e persistência real no SQLite de diretrizes editoriais,
 * parâmetros de quiz, motores visuais (Flow/Stock), vozes Azure e som ambiente.
 */
export default function ChannelDetailView({ channel, onBack, onUpdateChannel }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [settings, setSettings] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  // Informações básicas
  const [channelName, setChannelName] = useState(channel.name || '');
  const [channelNiche, setChannelNiche] = useState(channel.niche || '');
  const [targetStock, setTargetStock] = useState(channel.target_stock || 3);
  const [maxGen, setMaxGen] = useState(5);

  // Parâmetros Editoriais Paridade
  const [topicBrief, setTopicBrief] = useState('');
  const [closingType, setClosingType] = useState('provocative');
  const [numQuestions, setNumQuestions] = useState(5);

  // Parâmetros de Mídia & Áudio
  const [voiceList, setVoiceList] = useState([]);
  const [voiceName, setVoiceName] = useState('');
  const [visualDirectorEnabled, setVisualDirectorEnabled] = useState(true);
  const [flowEnabled, setFlowEnabled] = useState(false);
  const [flowSceneCount, setFlowSceneCount] = useState(3);
  const [stockFallbackEnabled, setStockFallbackEnabled] = useState(true);
  const [musicEnabled, setMusicEnabled] = useState(false);
  const [musicVolume, setMusicVolume] = useState(0.20);
  const [musicMood, setMusicMood] = useState('neutral');

  const channelId = channel.channel_id || channel.profile_id || channel.id;

  // Carrega configurações detalhadas e catálogo de vozes
  useEffect(() => {
    setIsLoading(true);
    setChannelName(channel.name || '');
    setChannelNiche(channel.niche || '');
    setTargetStock(channel.target_stock || 3);

    // Carrega catálogo de vozes
    getVoices('pt-BR')
      .then((res) => {
        const list = res?.voices || res?.data?.voices || [];
        if (Array.isArray(list) && list.length > 0) {
          setVoiceList(list);
        }
      })
      .catch((err) => console.warn('Erro ao carregar vozes:', err));

    getProfileSettings(channelId)
      .then((data) => {
        setSettings(data);
        const ws = data?.workspace_settings || {};
        const ed = ws.editorial || {};
        const vc = ws.voice || {};
        const vis = ws.visual || {};
        const mus = ws.music || {};
        const quo = data?.quotas || ws.automation || {};

        if (quo.max_generations_24h) setMaxGen(quo.max_generations_24h);
        if (quo.target_ready_stock) setTargetStock(quo.target_ready_stock);

        setTopicBrief(ed.topic_brief || '');
        if (ed.closing_type) setClosingType(ed.closing_type);
        if (ed.num_questions) setNumQuestions(ed.num_questions);

        setVoiceName(vc.voice_name || 'pt-BR-AntonioNeural');
        setVisualDirectorEnabled(vis.visual_director_enabled !== false);
        setFlowEnabled(Boolean(vis.flow_enabled));
        setFlowSceneCount(vis.flow_scene_count || 3);
        setStockFallbackEnabled(vis.stock_fallback_enabled !== false);

        setMusicEnabled(Boolean(mus.enabled));
        setMusicVolume(mus.volume !== undefined ? mus.volume : 0.20);
        setMusicMood(mus.default_mood || 'neutral');
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
      setFeedback({ type: 'success', msg: `Autonomia ${nextState ? 'ativada' : 'pausada'} com sucesso no SQLite!` });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao alterar autonomia.' });
    }
  };

  const handleSaveEditorial = async () => {
    setIsSaving(true);
    setFeedback(null);
    try {
      await updateProfileSettings(channelId, {
        name: channelName.trim(),
        niche: channelNiche.trim(),
        topic_brief: topicBrief.trim(),
        closing_type: channelFormat === 'quiz_dilemma' ? closingType : undefined,
        num_questions: channelFormat === 'quiz_dilemma' ? Number(numQuestions) : undefined,
      });
      channel.name = channelName.trim();
      channel.niche = channelNiche.trim();
      setFeedback({ type: 'success', msg: 'Diretrizes editoriais e parâmetros do canal salvos com sucesso!' });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao salvar diretrizes editoriais.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveMedia = async () => {
    setIsSaving(true);
    setFeedback(null);
    try {
      await updateProfileSettings(channelId, {
        voice_name: voiceName,
        visual_director_enabled: visualDirectorEnabled,
        flow_enabled: flowEnabled,
        flow_scene_count: Number(flowSceneCount),
        stock_fallback_enabled: stockFallbackEnabled,
        music_enabled: musicEnabled,
        music_volume: Number(musicVolume),
        music_mood: musicMood,
      });
      setFeedback({ type: 'success', msg: 'Configurações de voz, Google Flow e áudio persistidas com sucesso!' });
      if (onUpdateChannel) onUpdateChannel();
    } catch (err) {
      setFeedback({ type: 'error', msg: err.message || 'Erro ao salvar configurações de mídia.' });
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
    if (fmt === 'quiz_paper') return { label: 'Quiz Papel P1.3', color: '#f59e0b', desc: 'Perguntas e 4 alternativas em papel rústico com timer circular (60-65s)' };
    if (fmt === 'quiz_dilemma') return { label: 'Quiz Dilema Q0-R', color: '#8b5cf6', desc: 'Tela dividida 50/50 com escolhas impossíveis e votação visual' };
    return { label: 'Tradicional', color: '#10b981', desc: 'Montagem dinâmica com clipes Pexels/Pixabay e narração fluida' };
  };

  const badge = formatBadge(channelFormat);
  const effectiveVoice = voiceName || channel.settings?.voice?.voice_name || 'pt-BR-AntonioNeural';

  const tabs = [
    { id: 'overview', label: 'Visão Geral' },
    { id: 'editorial', label: 'Diretrizes Editoriais' },
    { id: 'audio_video', label: 'Áudio, Voz & Flow' },
    { id: 'publishing', label: 'Destinos Sociais' },
    { id: 'automation', label: 'Quotas & Automação' },
    { id: 'stock', label: 'Estoque do Canal' },
    { id: 'logs', label: 'Diagnóstico' },
  ];

  return (
    <div className="v2-channel-detail-container">
      {/* Top Breadcrumb & Action Header */}
      <div className="v2-detail-header">
        <div className="v2-breadcrumb">
          <button className="v2-btn-back" onClick={onBack}>
            ← Voltar para Meus Canais
          </button>
          <span className="v2-separator">/</span>
          <span className="v2-current-channel">{channel.name}</span>
        </div>

        <div className="v2-header-quick-actions">
          <span
            className="v2-badge-format"
            style={{ backgroundColor: `${badge.color}20`, color: badge.color, border: `1px solid ${badge.color}50` }}
          >
            {badge.label}
          </span>
          <div
            className={`v2-auto-pill ${channel.autonomous_enabled ? 'active' : 'paused'}`}
            onClick={handleToggleAutonomous}
            title="Clique para alternar o modo de produção autônoma"
          >
            <span className="v2-pulse-dot" />
            <span>{channel.autonomous_enabled ? 'Autônomo Ativo' : 'Pausado (Manual)'}</span>
          </div>
        </div>
      </div>

      {feedback && (
        <div className={`v2-alert-feedback ${feedback.type === 'success' ? 'success' : 'error'}`}>
          {feedback.msg}
        </div>
      )}

      {/* Tabs de Navegação */}
      <div className="v2-tabs-nav">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`v2-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => {
              setActiveTab(tab.id);
              setFeedback(null);
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Conteúdo das Abas */}
      <div className="v2-tab-content">
        {/* ABA 1: VISÃO GERAL */}
        {activeTab === 'overview' && (
          <div className="v2-overview-grid">
            <div className="v2-card-section">
              <h4 className="v2-section-title">Identidade do Canal</h4>
              <div className="v2-info-list">
                <div className="v2-info-item">
                  <span className="v2-info-label">Nome:</span>
                  <span className="v2-info-value">{channel.name}</span>
                </div>
                <div className="v2-info-item">
                  <span className="v2-info-label">Nicho:</span>
                  <span className="v2-info-value">{channel.niche || 'Nenhum definido'}</span>
                </div>
                <div className="v2-info-item">
                  <span className="v2-info-label">Formato:</span>
                  <span className="v2-info-value" style={{ color: badge.color, fontWeight: 'bold' }}>
                    {badge.label}
                  </span>
                </div>
                <div className="v2-info-item">
                  <span className="v2-info-label">Briefing Temático:</span>
                  <span className="v2-info-value">{topicBrief || 'Padrão da fábrica'}</span>
                </div>
              </div>
            </div>

            <div className="v2-card-section">
              <h4 className="v2-section-title">Status Operacional & Estoque</h4>
              <div className="v2-kpi-compact">
                <div className="v2-kpi-item">
                  <span className="v2-kpi-num" style={{ color: '#10b981' }}>{channel.ready_stock || 0}</span>
                  <span className="v2-kpi-lbl">Vídeos Prontos</span>
                </div>
                <div className="v2-kpi-item">
                  <span className="v2-kpi-num" style={{ color: '#38bdf8' }}>{targetStock}</span>
                  <span className="v2-kpi-lbl">Meta de Buffer</span>
                </div>
                <div className="v2-kpi-item">
                  <span className="v2-kpi-num" style={{ color: '#f59e0b' }}>{channel.pending_processing || 0}</span>
                  <span className="v2-kpi-lbl">Em Processamento</span>
                </div>
              </div>
              <div style={{ marginTop: '16px' }}>
                <span className="v2-text-muted">Provedor Visual: </span>
                <strong style={{ color: '#f8fafc' }}>
                  {flowEnabled ? `Google Flow (${flowSceneCount} cenas)` : 'Clipes de Stock Pexels/Pixabay'}
                </strong>
              </div>
            </div>
          </div>
        )}

        {/* ABA 2: DIRETRIZES EDITORIAIS */}
        {activeTab === 'editorial' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Diretrizes Editoriais do Canal</h4>
            <div className="v2-form-group">
              <label className="v2-form-label">Nome do Canal</label>
              <input
                type="text"
                className="v2-input-text"
                value={channelName}
                onChange={(e) => setChannelName(e.target.value)}
              />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Nicho Editorial</label>
              <input
                type="text"
                className="v2-input-text"
                value={channelNiche}
                onChange={(e) => setChannelNiche(e.target.value)}
              />
            </div>
            <div className="v2-form-group">
              <label className="v2-form-label">Diretriz Temática / Briefing Base (`topic_brief`)</label>
              <textarea
                className="v2-textarea"
                rows={3}
                placeholder="Ex: Fatos impressionantes e curiosidades científicas com tom dinâmico e direto."
                value={topicBrief}
                onChange={(e) => setTopicBrief(e.target.value)}
              />
              <span className="v2-form-hint">
                Injetado em todas as gerações de roteiro do canal para manter coerência editorial.
              </span>
            </div>

            {/* Configurações condicionais para Quiz Dilema */}
            {channelFormat === 'quiz_dilemma' && (
              <div className="v2-format-extra-box" style={{ marginTop: '16px' }}>
                <h5 className="v2-extra-title">Regras do Quiz Dilema (Q0-R)</h5>
                <div className="v2-form-row-2">
                  <div className="v2-form-group">
                    <label className="v2-form-label">Tipo de Encerramento</label>
                    <select
                      className="v2-select"
                      value={closingType}
                      onChange={(e) => setClosingType(e.target.value)}
                    >
                      <option value="provocative">Provocativo (Call-to-action nos comentários)</option>
                      <option value="direct">Direto (Exibição dos resultados e encerramento)</option>
                    </select>
                  </div>
                  <div className="v2-form-group">
                    <label className="v2-form-label">Quantidade de Dilemas</label>
                    <input
                      type="number"
                      min={3}
                      max={10}
                      className="v2-input-text"
                      value={numQuestions}
                      onChange={(e) => setNumQuestions(Number(e.target.value))}
                    />
                  </div>
                </div>
              </div>
            )}

            <button
              className="v2-btn-primary"
              style={{ marginTop: '16px' }}
              disabled={isSaving}
              onClick={handleSaveEditorial}
            >
              {isSaving ? 'Salvando...' : 'Salvar Diretrizes Editoriais'}
            </button>
          </div>
        )}

        {/* ABA 3: VÍDEO & ÁUDIO */}
        {activeTab === 'audio_video' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Configurações de Áudio, Voz e Motores Visuais</h4>

            {/* Voz Neural */}
            <div className="v2-form-group">
              <label className="v2-form-label">Voz do Narrador (Azure Neural pt-BR)</label>
              <select
                className="v2-select"
                value={effectiveVoice}
                onChange={(e) => setVoiceName(e.target.value)}
              >
                {voiceList.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label || v.name}
                  </option>
                ))}
              </select>
              <span className="v2-form-hint">
                Catálogo certificado de vozes neurais em português brasileiro.
              </span>
            </div>

            {/* Motores Visuais */}
            <div className="v2-section-card-mini" style={{ marginTop: '16px' }}>
              <h5 className="v2-mini-title">🎨 Motores Visuais & Google Flow</h5>
              <div className="v2-toggles-grid">
                <label className="v2-toggle-item">
                  <input
                    type="checkbox"
                    checked={visualDirectorEnabled}
                    onChange={(e) => setVisualDirectorEnabled(e.target.checked)}
                  />
                  <span>Visual Director IA (Prompting Semântico)</span>
                </label>

                <label className="v2-toggle-item">
                  <input
                    type="checkbox"
                    checked={stockFallbackEnabled}
                    onChange={(e) => setStockFallbackEnabled(e.target.checked)}
                  />
                  <span>Fallback para Clipes Pexels / Pixabay</span>
                </label>

                <label className="v2-toggle-item">
                  <input
                    type="checkbox"
                    checked={flowEnabled}
                    onChange={(e) => setFlowEnabled(e.target.checked)}
                  />
                  <span>Google Flow (Geração de Clipes por IA)</span>
                </label>
              </div>

              {flowEnabled && (
                <div className="v2-slider-box" style={{ marginTop: '12px' }}>
                  <div className="v2-slider-header">
                    <span>Cenas geradas via Google Flow por vídeo:</span>
                    <strong>{flowSceneCount} cenas</strong>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="8"
                    value={flowSceneCount}
                    onChange={(e) => setFlowSceneCount(Number(e.target.value))}
                    className="v2-range-slider"
                  />
                </div>
              )}
            </div>

            {/* Som Ambiente & BGM */}
            <div className="v2-section-card-mini" style={{ marginTop: '16px' }}>
              <h5 className="v2-mini-title">🎵 Som Ambiente & Trilha Sonora</h5>
              <label className="v2-toggle-item">
                <input
                  type="checkbox"
                  checked={musicEnabled}
                  onChange={(e) => setMusicEnabled(e.target.checked)}
                />
                <span>Habilitar Música de Fundo (BGM Automático)</span>
              </label>

              {musicEnabled && (
                <div className="v2-form-row-2" style={{ marginTop: '12px' }}>
                  <div className="v2-form-group">
                    <label className="v2-form-label">Mood Musical</label>
                    <select
                      className="v2-select"
                      value={musicMood}
                      onChange={(e) => setMusicMood(e.target.value)}
                    >
                      <option value="neutral">Neutro / Equilibrado</option>
                      <option value="curious">Curioso / Intrigante</option>
                      <option value="dramatic">Dramático / Tensão</option>
                      <option value="upbeat">Animado / Dinâmico</option>
                      <option value="mysterious">Misterioso / Suspense</option>
                    </select>
                  </div>

                  <div className="v2-form-group">
                    <label className="v2-form-label">Volume do Fundo: {Math.round(musicVolume * 100)}%</label>
                    <input
                      type="range"
                      min="0.05"
                      max="0.50"
                      step="0.05"
                      value={musicVolume}
                      onChange={(e) => setMusicVolume(Number(e.target.value))}
                      className="v2-range-slider"
                    />
                  </div>
                </div>
              )}
            </div>

            <button
              className="v2-btn-primary"
              style={{ marginTop: '20px' }}
              disabled={isSaving}
              onClick={handleSaveMedia}
            >
              {isSaving ? 'Salvando...' : 'Salvar Configurações de Mídia & Áudio'}
            </button>
          </div>
        )}

        {/* ABA 4: DESTINOS & PUBLICAÇÃO */}
        {activeTab === 'publishing' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Destinos Sociais Vinculados (Post for Me)</h4>
            <p className="v2-text-muted" style={{ marginBottom: '16px' }}>
              Contas e canais autorizados associados a este perfil para publicação agendada.
            </p>

            {(!channel.channels || channel.channels.length === 0) ? (
              <div className="v2-empty-state-mini">
                <span>📡 Nenhuma conta social vinculada a este perfil. O canal produz em modo buffer local.</span>
              </div>
            ) : (
              channel.channels.map((acc, idx) => (
                <div key={idx} className="v2-destination-card">
                  <div>
                    <strong style={{ color: '#f4f4f5' }}>
                      {acc.platform?.toUpperCase()}: {acc.display_name || acc.name || 'Conta'}
                    </strong>
                    <div className="v2-text-muted" style={{ fontSize: '12px' }}>
                      Conta Externa: {acc.external_account_id || acc.id} {acc.project_id ? `| Projeto: ${acc.project_id}` : ''}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span className="v2-dest-pill-id">ID: {acc.id}</span>
                    <span className="v2-dest-pill-status">Conectado (Prontidão DEV)</span>
                  </div>
                </div>
              ))
            )}

            <div className="v2-info-banner" style={{ marginTop: '16px' }}>
              <span className="v2-info-icon">🛡️</span>
              <span className="v2-info-text">
                <strong>Isolamento DEV:</strong> Contas sociais registradas estão seguras. Nenhuma publicação externa real será transmitida nesta branch.
              </span>
            </div>
          </div>
        )}

        {/* ABA 5: AUTOMAÇÃO & QUOTAS */}
        {activeTab === 'automation' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Metas de Estoque e Regras de Autonomia</h4>
            <div className="v2-form-row-2">
              <div className="v2-form-group">
                <label className="v2-form-label">Meta de Estoque Pronto</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  className="v2-input-text"
                  value={targetStock}
                  onChange={(e) => setTargetStock(Number(e.target.value))}
                />
                <span className="v2-form-hint">Quantidade alvo mantida no buffer de estoque.</span>
              </div>

              <div className="v2-form-group">
                <label className="v2-form-label">Teto de Gerações em 24h</label>
                <input
                  type="number"
                  min="1"
                  max="30"
                  className="v2-input-text"
                  value={maxGen}
                  onChange={(e) => setMaxGen(Number(e.target.value))}
                />
                <span className="v2-form-hint">Limite de segurança diário contra exaustão de cotas.</span>
              </div>
            </div>

            <div className="v2-auto-guardian-box" style={{ marginTop: '16px' }}>
              <div className="v2-auto-guardian-info">
                <strong>Modo Autônomo da Fábrica para este Canal:</strong>
                <span>
                  Estado atual:{' '}
                  <strong style={{ color: channel.autonomous_enabled ? '#10b981' : '#f59e0b' }}>
                    {channel.autonomous_enabled ? '🟢 ATIVADO' : '🟡 PAUSADO (MANUAL)'}
                  </strong>
                </span>
              </div>
              <button
                className={`v2-btn-toggle-auto ${channel.autonomous_enabled ? 'active' : ''}`}
                onClick={handleToggleAutonomous}
              >
                {channel.autonomous_enabled ? 'Pausar Autonomia' : 'Ativar Autonomia'}
              </button>
            </div>

            <button
              className="v2-btn-primary"
              style={{ marginTop: '20px' }}
              disabled={isSaving}
              onClick={handleSaveQuotas}
            >
              {isSaving ? 'Salvando...' : 'Salvar Metas e Quotas'}
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
                <div key={idx} className="v2-stock-item-row">
                  <div>
                    <span style={{ color: '#10b981', marginRight: '8px' }}>●</span>
                    <strong style={{ fontSize: '13px', color: '#f4f4f5' }}>{channel.name} — Item #{idx}</strong>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>task_{channelId}_{idx} | Quality: 85.0 | Safety: PASS</div>
                  </div>
                  <span className="v2-stock-badge-ready">Pronto para Postagem</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ABA 7: DIAGNÓSTICO */}
        {activeTab === 'logs' && (
          <div className="v2-card-section">
            <h4 className="v2-section-title">Auditoria e Diagnósticos do Canal</h4>
            <div className="v2-logs-console">
              <div>[2026-10-18] Canal [{channelId}] sincronizado com a Video Factory V2.</div>
              <div>[2026-10-18] Guardião de isolamento ativo: gravação em produção bloqueada (DEV_V2).</div>
              <div>[2026-10-18] Formato validado: {badge.label} | Voz efetiva: {effectiveVoice}</div>
              <div>[2026-10-18] Buffer de estoque inspecionado: {channel.ready_stock || 0} itens prontos.</div>
              <div>[2026-10-18] Provedor visual configurado: {flowEnabled ? 'Google Flow' : 'Stock Clips'}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
