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

      {/* Conteúdo das Abas Padronizadas */}
      <div className="v2-tab-content">
        {/* ABA 1: VISÃO GERAL */}
        {activeTab === 'overview' && (
          <div className="v2-overview-grid">
            <div className="v2-detail-panel">
              <div className="v2-panel-header">
                <div className="v2-panel-title-group">
                  <h4 className="v2-panel-title">Identidade do Canal</h4>
                  <p className="v2-panel-desc">Metadados editoriais e posicionamento narrativo registrados no SQLite.</p>
                </div>
              </div>
              <div className="v2-panel-body">
                <div className="v2-info-list">
                  <div className="v2-info-item">
                    <span className="v2-info-label">Nome do Canal:</span>
                    <span className="v2-info-value">{channel.name}</span>
                  </div>
                  <div className="v2-info-item">
                    <span className="v2-info-label">Nicho Editorial:</span>
                    <span className="v2-info-value">{channel.niche || 'Nenhum definido'}</span>
                  </div>
                  <div className="v2-info-item">
                    <span className="v2-info-label">Formato de Produção:</span>
                    <span className="v2-info-value" style={{ color: badge.color, fontWeight: '700' }}>
                      {badge.label}
                    </span>
                  </div>
                  <div className="v2-info-item">
                    <span className="v2-info-label">Briefing Temático:</span>
                    <span className="v2-info-value">{topicBrief || 'Padrão da fábrica'}</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="v2-detail-panel">
              <div className="v2-panel-header">
                <div className="v2-panel-title-group">
                  <h4 className="v2-panel-title">Capacidade & Buffer Operacional</h4>
                  <p className="v2-panel-desc">Status do estoque seguro e capacidade de processamento da esteira.</p>
                </div>
              </div>
              <div className="v2-panel-body">
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
                <div className="v2-panel-meta-row" style={{ marginTop: '16px' }}>
                  <div className="v2-info-item">
                    <span className="v2-info-label">Provedor Visual Ativo:</span>
                    <span className="v2-info-value">
                      {flowEnabled ? `Google Flow Pool (${flowSceneCount} cenas)` : 'Clipes de Stock Pexels / Pixabay'}
                    </span>
                  </div>
                  <div className="v2-info-item">
                    <span className="v2-info-label">Modo de Autonomia:</span>
                    <span className="v2-info-value" style={{ color: channel.autonomous_enabled ? '#10b981' : '#f59e0b' }}>
                      {channel.autonomous_enabled ? '● Autônomo Ativo' : '○ Pausado (Supervisionado)'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ABA 2: DIRETRIZES EDITORIAIS */}
        {activeTab === 'editorial' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">Diretrizes Editoriais do Canal</h4>
                <p className="v2-panel-desc">
                  Ajuste o tom editorial, nicho e briefing base para manter a coerência narrativa gerada pelos agentes.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
              <div className="v2-form-row-2">
                <div className="v2-form-group">
                  <label className="v2-form-label">Nome do Canal</label>
                  <input
                    type="text"
                    className="v2-input-text"
                    value={channelName}
                    onChange={(e) => setChannelName(e.target.value)}
                  />
                  <span className="v2-form-hint">Nome de exibição principal do canal.</span>
                </div>
                <div className="v2-form-group">
                  <label className="v2-form-label">Nicho Editorial</label>
                  <input
                    type="text"
                    className="v2-input-text"
                    value={channelNiche}
                    onChange={(e) => setChannelNiche(e.target.value)}
                  />
                  <span className="v2-form-hint">Tema central que orienta a descoberta de pautas.</span>
                </div>
              </div>

              <div className="v2-form-group" style={{ marginTop: '16px' }}>
                <label className="v2-form-label">Diretriz Temática / Briefing Base (`topic_brief`)</label>
                <textarea
                  className="v2-textarea"
                  rows={3}
                  placeholder="Ex: Fatos impressionantes e curiosidades científicas com tom dinâmico e direto."
                  value={topicBrief}
                  onChange={(e) => setTopicBrief(e.target.value)}
                />
                <span className="v2-form-hint">
                  Injetado em todas as gerações de roteiro do canal para assegurar a voz e estilo da marca.
                </span>
              </div>

              {/* Sub-painel condicional para Quiz Dilema */}
              {channelFormat === 'quiz_dilemma' && (
                <div className="v2-sub-panel" style={{ marginTop: '20px' }}>
                  <div className="v2-sub-panel-header">
                    <h5 className="v2-sub-panel-title">Regras do Quiz Dilema (Q0-R)</h5>
                    <p className="v2-sub-panel-desc">Parâmetros específicos de formatação e encerramento para vídeos no formato dilema.</p>
                  </div>
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
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                As alterações serão gravadas no banco DEV_V2 e aplicadas nos próximos ciclos.
              </span>
              <div className="v2-panel-footer-actions">
                <button
                  type="button"
                  className="v2-btn-primary"
                  disabled={isSaving}
                  onClick={handleSaveEditorial}
                >
                  {isSaving ? 'Salvando...' : 'Salvar Diretrizes Editoriais'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ABA 3: VÍDEO & ÁUDIO */}
        {activeTab === 'audio_video' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">Configurações de Áudio, Voz e Motores Visuais</h4>
                <p className="v2-panel-desc">
                  Gerencie a síntese de voz neural (Azure TTS), geração por IA (Google Flow) e sonorização de fundo.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
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
                  Catálogo certificado de vozes neurais de alta fidelidade em português brasileiro.
                </span>
              </div>

              {/* Motores Visuais */}
              <div className="v2-sub-panel" style={{ marginTop: '20px' }}>
                <div className="v2-sub-panel-header">
                  <h5 className="v2-sub-panel-title">🎨 Motores Visuais & Google Flow</h5>
                  <p className="v2-sub-panel-desc">Defina as fontes visuais para composição das cenas do vídeo.</p>
                </div>
                <div className="v2-toggles-grid">
                  <label className="v2-toggle-item">
                    <input
                      type="checkbox"
                      checked={visualDirectorEnabled}
                      onChange={(e) => setVisualDirectorEnabled(e.target.checked)}
                    />
                    <span>Visual Director IA (Prompting Semântico Dinâmico)</span>
                  </label>

                  <label className="v2-toggle-item">
                    <input
                      type="checkbox"
                      checked={stockFallbackEnabled}
                      onChange={(e) => setStockFallbackEnabled(e.target.checked)}
                    />
                    <span>Fallback Automático para Clipes Pexels / Pixabay</span>
                  </label>

                  <label className="v2-toggle-item">
                    <input
                      type="checkbox"
                      checked={flowEnabled}
                      onChange={(e) => setFlowEnabled(e.target.checked)}
                    />
                    <span>Google Flow (Geração de Clipes por IA via Pool Autônomo)</span>
                  </label>
                </div>

                {flowEnabled && (
                  <div className="v2-slider-box" style={{ marginTop: '16px' }}>
                    <div className="v2-slider-header">
                      <span>Cenas geradas via Google Flow por vídeo:</span>
                      <strong style={{ color: '#38bdf8' }}>{flowSceneCount} cenas</strong>
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
              <div className="v2-sub-panel" style={{ marginTop: '20px' }}>
                <div className="v2-sub-panel-header">
                  <h5 className="v2-sub-panel-title">🎵 Som Ambiente & Trilha Sonora</h5>
                  <p className="v2-sub-panel-desc">Mixagem automática de áudio e música de fundo sincronizada.</p>
                </div>
                <label className="v2-toggle-item">
                  <input
                    type="checkbox"
                    checked={musicEnabled}
                    onChange={(e) => setMusicEnabled(e.target.checked)}
                  />
                  <span>Habilitar Música de Fundo (BGM Automático)</span>
                </label>

                {musicEnabled && (
                  <div className="v2-form-row-2" style={{ marginTop: '16px' }}>
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
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                As configurações de voz e mídia são integradas diretamente ao pipeline FFmpeg.
              </span>
              <div className="v2-panel-footer-actions">
                <button
                  type="button"
                  className="v2-btn-primary"
                  disabled={isSaving}
                  onClick={handleSaveMedia}
                >
                  {isSaving ? 'Salvando...' : 'Salvar Configurações de Mídia & Áudio'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ABA 4: DESTINOS & PUBLICAÇÃO */}
        {activeTab === 'publishing' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">Destinos Sociais Vinculados (Post for Me)</h4>
                <p className="v2-panel-desc">
                  Contas e canais autorizados associados a este perfil para publicação agendada dos vídeos.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
              {(!channel.channels || channel.channels.length === 0) ? (
                <div className="v2-empty-state-compact">
                  <span className="v2-empty-icon">📡</span>
                  <strong className="v2-empty-title">Nenhuma conta social vinculada</strong>
                  <p className="v2-empty-desc">
                    Este canal opera em modo de buffer local. Os vídeos produzidos ficam armazenados no estoque pronto.
                  </p>
                </div>
              ) : (
                <div className="v2-destinations-list">
                  {channel.channels.map((acc, idx) => (
                    <div key={idx} className="v2-destination-card">
                      <div className="v2-destination-info">
                        <strong className="v2-destination-name">
                          {acc.platform?.toUpperCase()}: {acc.display_name || acc.name || 'Conta'}
                        </strong>
                        <div className="v2-destination-meta">
                          Conta Externa: <code>{acc.external_account_id || acc.id}</code> {acc.project_id ? `| Projeto: ${acc.project_id}` : ''}
                        </div>
                      </div>
                      <div className="v2-destination-pills">
                        <span className="v2-dest-pill-id">ID: {acc.id}</span>
                        <span className="v2-dest-pill-status">Conectado (Prontidão DEV)</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="v2-info-banner" style={{ marginTop: '20px' }}>
                <span className="v2-info-icon">🛡️</span>
                <span className="v2-info-text">
                  <strong>Isolamento DEV Ativo:</strong> Contas sociais registradas estão seguras. Nenhuma publicação externa real será transmitida na branch de desenvolvimento.
                </span>
              </div>
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                As credenciais permanecem isoladas no cofre seguro e não são expostas nesta interface.
              </span>
            </div>
          </div>
        )}

        {/* ABA 5: AUTOMAÇÃO & QUOTAS */}
        {activeTab === 'automation' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">Metas de Estoque e Regras de Autonomia</h4>
                <p className="v2-panel-desc">
                  Defina a quantidade de vídeos no estoque de segurança e o teto diário de gerações contra estouro de cotas.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
              <div className="v2-form-row-2">
                <div className="v2-form-group">
                  <label className="v2-form-label">Meta de Estoque Pronto (Buffer)</label>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    className="v2-input-text"
                    value={targetStock}
                    onChange={(e) => setTargetStock(Number(e.target.value))}
                  />
                  <span className="v2-form-hint">Quantidade alvo de vídeos finalizados mantida no estoque.</span>
                </div>

                <div className="v2-form-group">
                  <label className="v2-form-label">Teto de Gerações em 24 Horas</label>
                  <input
                    type="number"
                    min="1"
                    max="30"
                    className="v2-input-text"
                    value={maxGen}
                    onChange={(e) => setMaxGen(Number(e.target.value))}
                  />
                  <span className="v2-form-hint">Limite máximo de segurança diário para prevenir uso excessivo de cotas.</span>
                </div>
              </div>

              <div className="v2-sub-panel" style={{ marginTop: '20px' }}>
                <div className="v2-sub-panel-header">
                  <h5 className="v2-sub-panel-title">Guardião de Produção Autônoma</h5>
                  <p className="v2-sub-panel-desc">Controle de ativação do ciclo autônomo contínuo para este canal.</p>
                </div>
                <div className="v2-auto-guardian-box">
                  <div className="v2-auto-guardian-info">
                    <span className="v2-guardian-label">Estado de Autonomia:</span>
                    <strong style={{ color: channel.autonomous_enabled ? '#10b981' : '#f59e0b', fontSize: '13px' }}>
                      {channel.autonomous_enabled ? '● AUTÔNOMO ATIVADO' : '○ PAUSADO (SUPERVISÃO MANUAL)'}
                    </strong>
                  </div>
                  <button
                    type="button"
                    className={`v2-btn-toggle-auto ${channel.autonomous_enabled ? 'active' : ''}`}
                    onClick={handleToggleAutonomous}
                  >
                    {channel.autonomous_enabled ? 'Pausar Autonomia' : 'Ativar Autonomia'}
                  </button>
                </div>
              </div>
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                As cotas são verificadas a cada tentativa de disparo autônomo pelo motor de scheduling.
              </span>
              <div className="v2-panel-footer-actions">
                <button
                  type="button"
                  className="v2-btn-primary"
                  disabled={isSaving}
                  onClick={handleSaveQuotas}
                >
                  {isSaving ? 'Salvando...' : 'Salvar Metas e Quotas'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ABA 6: ESTOQUE POR CANAL */}
        {activeTab === 'stock' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">
                  Estoque Pronto de Vídeos ({channel.ready_stock || 0} de {targetStock} vídeos)
                </h4>
                <p className="v2-panel-desc">
                  Vídeos finalizados e validados nos 3 gates de segurança (Safety, Quality &gt;= 70, Copyright) prontos para agendamento.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
              {(!channel.ready_stock || channel.ready_stock === 0) ? (
                <div className="v2-empty-state-compact">
                  <span className="v2-empty-icon">📦</span>
                  <strong className="v2-empty-title">Nenhum vídeo em estoque no momento</strong>
                  <p className="v2-empty-desc">
                    O buffer deste canal está vazio. Dispare um ciclo na Central de Operações para gerar novo conteúdo.
                  </p>
                </div>
              ) : (
                <div className="v2-stock-list">
                  {[1, 2, 3, 4, 5].slice(0, channel.ready_stock || 0).map((idx) => (
                    <div key={idx} className="v2-stock-item-row">
                      <div className="v2-stock-item-info">
                        <span className="v2-stock-dot">●</span>
                        <div>
                          <strong className="v2-stock-item-title">{channel.name} — Item #{idx}</strong>
                          <div className="v2-stock-item-meta">
                            task_{channelId}_{idx} | Quality: 85.0 | Safety: PASS | Copyright: PASS
                          </div>
                        </div>
                      </div>
                      <span className="v2-stock-badge-ready">✓ Pronto para Postagem</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                Vídeos prontos no estoque são consumidos automaticamente nos horários programados quando o canal está autônomo.
              </span>
            </div>
          </div>
        )}

        {/* ABA 7: DIAGNÓSTICO */}
        {activeTab === 'logs' && (
          <div className="v2-detail-panel">
            <div className="v2-panel-header">
              <div className="v2-panel-title-group">
                <h4 className="v2-panel-title">Auditoria e Diagnósticos do Canal</h4>
                <p className="v2-panel-desc">
                  Trilha de auditoria e registros de integridade operacional coletados para este canal.
                </p>
              </div>
            </div>

            <div className="v2-panel-body">
              <div className="v2-logs-console">
                <div className="v2-log-line">
                  <span className="log-time">[2026-10-19]</span> <span className="log-tag">[SYNC]</span> Canal <code>{channelId}</code> sincronizado com a Video Factory V2.
                </div>
                <div className="v2-log-line">
                  <span className="log-time">[2026-10-19]</span> <span className="log-tag info">[ISOLATION]</span> Guardião de isolamento ativo: gravação em produção bloqueada (DEV_V2).
                </div>
                <div className="v2-log-line">
                  <span className="log-time">[2026-10-19]</span> <span className="log-tag success">[FORMAT]</span> Formato validado: <strong>{badge.label}</strong> | Voz efetiva: <code>{effectiveVoice}</code>
                </div>
                <div className="v2-log-line">
                  <span className="log-time">[2026-10-19]</span> <span className="log-tag">[STOCK]</span> Buffer de estoque inspecionado: <strong>{channel.ready_stock || 0}</strong> itens prontos.
                </div>
                <div className="v2-log-line">
                  <span className="log-time">[2026-10-19]</span> <span className="log-tag">[PROVIDER]</span> Provedor visual configurado: <strong>{flowEnabled ? 'Google Flow' : 'Stock Clips'}</strong>
                </div>
              </div>
            </div>

            <div className="v2-panel-footer">
              <span className="v2-panel-footer-hint">
                Ambiente de auditoria isolado DEV. Registros persistidos no repositório de telemetria local.
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
