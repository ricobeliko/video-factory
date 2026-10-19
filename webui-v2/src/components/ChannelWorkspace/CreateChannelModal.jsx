import React, { useState, useEffect } from 'react';
import { createChannel, getVideoTemplates, getPublishingAccounts, getVoices } from '../../api';

/**
 * CreateChannelModal — Wizard Contextual em 5 Etapas para Novo Canal (V2.16)
 * Paridade total com a fábrica legada: Destinos Post for Me, Vozes Azure pt-BR,
 * Formatos Homologados (Q0-R, P1.3, Tradicional), Google Flow e Som Ambiente.
 */
export default function CreateChannelModal({ isOpen, onClose, onCreated }) {
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Passo 1: Identidade
  const [name, setName] = useState('');
  const [niche, setNiche] = useState('');
  const [topicBrief, setTopicBrief] = useState('');
  const [language, setLanguage] = useState('pt-BR');

  // Passo 2: Formato Homologado
  const [formatType, setFormatType] = useState('traditional');
  const [templates, setTemplates] = useState([]);
  const [closingType, setClosingType] = useState('provocative');
  const [numQuestions, setNumQuestions] = useState(5);

  // Passo 3: Destinos Sociais Post for Me
  const [ytAccounts, setYtAccounts] = useState([]);
  const [ttAccounts, setTtAccounts] = useState([]);
  const [selectedYtAccountId, setSelectedYtAccountId] = useState('');
  const [selectedTtAccountId, setSelectedTtAccountId] = useState('');

  // Passo 4: Motores de IA, Voz & Áudio
  const [voiceList, setVoiceList] = useState([]);
  const [voiceName, setVoiceName] = useState('pt-BR-AntonioNeural');
  const [visualDirectorEnabled, setVisualDirectorEnabled] = useState(true);
  const [stockFallbackEnabled, setStockFallbackEnabled] = useState(true);
  const [flowEnabled, setFlowEnabled] = useState(false);
  const [flowSceneCount, setFlowSceneCount] = useState(3);
  const [musicEnabled, setMusicEnabled] = useState(false);
  const [musicVolume, setMusicVolume] = useState(0.20);
  const [musicMood, setMusicMood] = useState('neutral');

  // Passo 5: Quotas & Automação
  const [targetStock, setTargetStock] = useState(3);
  const [dailyLimit, setDailyLimit] = useState(5);
  const [autonomousEnabled, setAutonomousEnabled] = useState(false);

  const resetForm = () => {
    setStep(1);
    setError(null);
    setIsSubmitting(false);
    setName('');
    setNiche('');
    setTopicBrief('');
    setLanguage('pt-BR');
    setFormatType('traditional');
    setClosingType('provocative');
    setNumQuestions(5);
    setSelectedYtAccountId('');
    setSelectedTtAccountId('');
    setVisualDirectorEnabled(true);
    setStockFallbackEnabled(true);
    setFlowEnabled(false);
    setFlowSceneCount(3);
    setMusicEnabled(false);
    setMusicVolume(0.20);
    setMusicMood('neutral');
    setTargetStock(3);
    setDailyLimit(5);
    setAutonomousEnabled(false);
  };

  // Carrega templates, contas conectadas e vozes ao abrir o modal
  useEffect(() => {
    if (!isOpen) return;

    // Reseta integralmente os dados do formulário ao abrir o wizard
    resetForm();

    // 1. Templates de Formato
    getVideoTemplates()
      .then((res) => {
        const list = res?.templates || res?.data?.templates || [];
        if (Array.isArray(list) && list.length > 0) {
          setTemplates(list);
        }
      })
      .catch(() => {
        setTemplates([
          {
            id: 'traditional',
            title: 'Vídeo Tradicional (Pexels / LLM)',
            description: 'Montagem fluida com clipes Pexels/Pixabay, narração dinâmica e legendas animadas.',
            locked_fields: [],
          },
          {
            id: 'quiz_dilemma',
            title: 'Quiz Q0-R — Escolhas Impossíveis',
            description: 'Template homologado com tela dividida 50/50, votação visual e barra de porcentagem.',
            locked_fields: ['orientation', 'aspect_ratio', 'resolution', 'split_screen'],
          },
          {
            id: 'quiz_paper',
            title: 'Quiz de Papel P1.3 — Perguntas & Respostas',
            description: 'Template rústico com perguntas e 4 alternativas em quadro único e timer circular (60-65s).',
            locked_fields: ['duration', 'orientation', 'aspect_ratio', 'resolution', 'timer_style'],
          },
        ]);
      });

    // 2. Contas Conectadas Post for Me
    getPublishingAccounts()
      .then((res) => {
        const accs = res?.accounts || res?.data?.accounts || [];
        setYtAccounts(accs.filter((a) => a.platform === 'youtube'));
        setTtAccounts(accs.filter((a) => a.platform === 'tiktok'));
      })
      .catch((err) => {
        console.warn('Erro ao carregar contas conectadas Post for Me:', err);
      });

    // 3. Catálogo de Vozes Azure Certificadas pt-BR
    getVoices('pt-BR')
      .then((res) => {
        const list = res?.voices || res?.data?.voices || [];
        if (Array.isArray(list) && list.length > 0) {
          setVoiceList(list);
          setVoiceName(list[0].id || list[0].name);
        }
      })
      .catch((err) => {
        console.warn('Erro ao carregar vozes:', err);
        setVoiceList([
          { id: 'pt-BR-AntonioNeural', label: 'pt-BR-AntonioNeural (Voz Masculina)' },
          { id: 'pt-BR-FranciscaNeural', label: 'pt-BR-FranciscaNeural (Voz Feminina)' },
          { id: 'pt-BR-ThalitaMultilingualNeural', label: 'pt-BR-ThalitaMultilingualNeural (Multilíngue)' },
        ]);
      });
  }, [isOpen]);

  if (!isOpen) return null;

  const currentTemplate = templates.find((t) => t.id === formatType) || templates[0];

  const handleNextStep = (e) => {
    if (e && e.preventDefault) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (step === 1) {
      if (!name.trim()) {
        setError('O nome do canal é obrigatório para avançar.');
        return;
      }
    }
    setError(null);
    setStep((prev) => Math.min(prev + 1, 5));
  };

  const handlePrevStep = (e) => {
    if (e && e.preventDefault) {
      e.preventDefault();
      e.stopPropagation();
    }
    setError(null);
    setStep((prev) => Math.max(prev - 1, 1));
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault();
      if (step < 5) {
        handleNextStep(e);
      }
    }
  };

  const handleSubmit = async (e) => {
    if (e && e.preventDefault) {
      e.preventDefault();
      e.stopPropagation();
    }
    // Salvaguarda 1: NUNCA criar o canal se não estiver explicitamente na etapa 5
    if (step !== 5) {
      return;
    }
    // Salvaguarda 2: Bloqueio estrito contra submissões repetidas / duplo clique
    if (isSubmitting) {
      return;
    }
    if (!name.trim()) {
      setError('Por favor, informe o nome do canal.');
      setStep(1);
      return;
    }

    setIsSubmitting(true);
    setError(null);

    // Resolve project IDs das contas selecionadas
    const ytObj = ytAccounts.find((a) => a.external_account_id === selectedYtAccountId);
    const ttObj = ttAccounts.find((a) => a.external_account_id === selectedTtAccountId);

    try {
      await createChannel({
        name: name.trim(),
        niche: niche.trim() || undefined,
        format_type: formatType,
        language,
        target_stock: Number(targetStock),
        autonomous_enabled: autonomousEnabled,
        voice_name: voiceName,
        topic_brief: topicBrief.trim() || undefined,
        closing_type: formatType === 'quiz_dilemma' ? closingType : undefined,
        num_questions: formatType === 'quiz_dilemma' ? Number(numQuestions) : undefined,
        visual_director_enabled: visualDirectorEnabled,
        stock_fallback_enabled: stockFallbackEnabled,
        flow_enabled: flowEnabled,
        flow_scene_count: Number(flowSceneCount),
        music_enabled: musicEnabled,
        music_volume: Number(musicVolume),
        music_mood: musicMood,
        daily_limit: Number(dailyLimit),
        youtube_account_id: selectedYtAccountId || undefined,
        youtube_project_id: ytObj?.project_id || undefined,
        tiktok_account_id: selectedTtAccountId || undefined,
        tiktok_project_id: ttObj?.project_id || undefined,
      });

      onCreated();
      onClose();
    } catch (err) {
      setError(err.message || 'Erro ao criar canal operacional.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const stepTitles = [
    { number: 1, label: 'Identidade & Nicho' },
    { number: 2, label: 'Formato Homologado' },
    { number: 3, label: 'Destinos Sociais' },
    { number: 4, label: 'IA, Voz & Som' },
    { number: 5, label: 'Quotas & Lançamento' },
  ];

  return (
    <div className="v2-modal-overlay">
      <div className="v2-modal-container v2-wizard-modal">
        {/* Header do Wizard */}
        <div className="v2-modal-header">
          <div className="v2-wizard-header-title">
            <span className="v2-modal-badge">Criação de Canal V2</span>
            <h3 className="v2-modal-title">Novo Canal de Produção</h3>
            <p className="v2-modal-subtitle">
              Onboarding completo com vinculação de contas, regras editoriais e salvaguardas de isolamento.
            </p>
          </div>
          <button className="v2-btn-close" onClick={onClose} title="Fechar modal">
            ×
          </button>
        </div>

        {/* Stepper Superior */}
        <div className="v2-wizard-stepper">
          {stepTitles.map((st) => (
            <div
              key={st.number}
              className={`v2-wizard-step-node ${step === st.number ? 'active' : ''} ${step > st.number ? 'completed' : ''}`}
              onClick={() => {
                if (st.number < step) {
                  setStep(st.number);
                }
              }}
            >
              <div className="v2-wizard-step-circle">
                {step > st.number ? '✓' : st.number}
              </div>
              <span className="v2-wizard-step-label">{st.label}</span>
            </div>
          ))}
        </div>

        {error && <div className="v2-alert-error">{error}</div>}

        {/* Corpo do Wizard */}
        <form
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
          className="v2-modal-form v2-wizard-body"
        >
          {/* PASSO 1: IDENTIDADE & NICHO */}
          {step === 1 && (
            <div className="v2-wizard-step-content">
              <h4 className="v2-step-heading">1. Identidade e Diretriz Temática</h4>
              <p className="v2-step-desc">
                Defina o nome, idioma e o tema orientador que guiará a geração de roteiros deste canal.
              </p>

              <div className="v2-form-group">
                <label className="v2-form-label">Nome do Canal *</label>
                <input
                  type="text"
                  className="v2-input-text"
                  placeholder="Ex: Dose Diária de Curiosidades"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <div className="v2-form-row-2">
                <div className="v2-form-group">
                  <label className="v2-form-label">Nicho Editorial</label>
                  <input
                    type="text"
                    className="v2-input-text"
                    placeholder="Ex: Filosofia, Finanças, Fatos Históricos"
                    value={niche}
                    onChange={(e) => setNiche(e.target.value)}
                  />
                </div>

                <div className="v2-form-group">
                  <label className="v2-form-label">Idioma de Narração & Legenda</label>
                  <select
                    className="v2-select"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                  >
                    <option value="pt-BR">Português (Brasil) — pt-BR</option>
                  </select>
                </div>
              </div>

              <div className="v2-form-group">
                <label className="v2-form-label">
                  Diretriz Temática / Briefing Editorial (Opcional)
                </label>
                <textarea
                  className="v2-textarea"
                  rows={3}
                  placeholder="Ex: Roteiros curtos e intrigantes sobre escolhas morais cotidianas, com tom reflexivo e gancho inicial forte."
                  value={topicBrief}
                  onChange={(e) => setTopicBrief(e.target.value)}
                />
                <span className="v2-form-hint">
                  Usado pelos agentes LLM como contexto permanente para seleção de temas e geração de roteiros.
                </span>
              </div>
            </div>
          )}

          {/* PASSO 2: FORMATO HOMOLOGADO */}
          {step === 2 && (
            <div className="v2-wizard-step-content">
              <h4 className="v2-step-heading">2. Formato Homologado de Vídeo</h4>
              <p className="v2-step-desc">
                Selecione o formato estrutural. Parâmetros técnicos congelados protegem a consistência visual.
              </p>

              <div className="v2-format-grid">
                {templates.map((tpl) => (
                  <div
                    key={tpl.id}
                    className={`v2-format-card ${formatType === tpl.id ? 'selected' : ''}`}
                    onClick={() => setFormatType(tpl.id)}
                  >
                    <div className="v2-format-header-row">
                      <span className="v2-format-title">{tpl.title}</span>
                      {formatType === tpl.id && <span className="v2-format-check">● Selecionado</span>}
                    </div>
                    <p className="v2-format-desc">{tpl.description}</p>
                    {tpl.locked_fields?.length > 0 && (
                      <div className="v2-format-badge">
                        🔒 {tpl.locked_fields.length} parâmetros técnicos congelados
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Opções específicas de Quiz Dilema Q0-R */}
              {formatType === 'quiz_dilemma' && (
                <div className="v2-format-extra-box">
                  <h5 className="v2-extra-title">⚡ Regras Específicas do Quiz Dilema (Q0-R)</h5>
                  <div className="v2-form-row-2">
                    <div className="v2-form-group">
                      <label className="v2-form-label">Estilo de Encerramento</label>
                      <select
                        className="v2-select"
                        value={closingType}
                        onChange={(e) => setClosingType(e.target.value)}
                      >
                        <option value="provocative">Provocativo (Pergunta final e call-to-action nos comentários)</option>
                        <option value="direct">Direto (Exibição dos resultados e despedida)</option>
                      </select>
                    </div>

                    <div className="v2-form-group">
                      <label className="v2-form-label">Quantidade de Dilemas por Vídeo</label>
                      <input
                        type="number"
                        className="v2-input-text"
                        min={3}
                        max={10}
                        value={numQuestions}
                        onChange={(e) => setNumQuestions(Math.max(3, Math.min(10, Number(e.target.value))))}
                      />
                      <span className="v2-form-hint">Recomendado: 5 dilemas (vídeo de ~60 segundos).</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* PASSO 3: DESTINOS SOCIAIS */}
          {step === 3 && (
            <div className="v2-wizard-step-content">
              <h4 className="v2-step-heading">3. Destinos Sociais de Publicação (Post for Me)</h4>
              <p className="v2-step-desc">
                Vincule o canal a contas autorizadas no Post for Me. O ambiente DEV opera em modo seguro sem publicação externa real.
              </p>

              <div className="v2-form-group">
                <label className="v2-form-label">Canal do YouTube Conectado</label>
                <select
                  className="v2-select"
                  value={selectedYtAccountId}
                  onChange={(e) => setSelectedYtAccountId(e.target.value)}
                >
                  <option value="">-- Não vincular ao YouTube agora --</option>
                  {ytAccounts.map((acc) => (
                    <option key={acc.external_account_id} value={acc.external_account_id}>
                      {acc.display_name} ({acc.project_name || 'Post for Me'}) — {acc.external_account_id}
                    </option>
                  ))}
                </select>
                <span className="v2-form-hint">
                  {ytAccounts.length === 0
                    ? 'Nenhuma conta YouTube conectada no Post for Me. O canal operará em estoque local.'
                    : `${ytAccounts.length} conta(s) YouTube conectada(s) detectada(s).`}
                </span>
              </div>

              <div className="v2-form-group">
                <label className="v2-form-label">Conta do TikTok Conectada</label>
                <select
                  className="v2-select"
                  value={selectedTtAccountId}
                  onChange={(e) => setSelectedTtAccountId(e.target.value)}
                >
                  <option value="">-- Não vincular ao TikTok agora --</option>
                  {ttAccounts.map((acc) => (
                    <option key={acc.external_account_id} value={acc.external_account_id}>
                      {acc.display_name} ({acc.project_name || 'Post for Me'}) — {acc.external_account_id}
                    </option>
                  ))}
                </select>
                <span className="v2-form-hint">
                  {ttAccounts.length === 0
                    ? 'Nenhuma conta TikTok conectada no Post for Me.'
                    : `${ttAccounts.length} conta(s) TikTok conectada(s) detectada(s).`}
                </span>
              </div>

              <div className="v2-info-banner">
                <span className="v2-info-icon">🛡️</span>
                <span className="v2-info-text">
                  <strong>Salvaguarda DEV Ativa:</strong> As contas vinculadas são salvas para prontidão operacional, mas nenhuma publicação real será executada neste ambiente.
                </span>
              </div>
            </div>
          )}

          {/* PASSO 4: IA, VOZ & SOM */}
          {step === 4 && (
            <div className="v2-wizard-step-content">
              <h4 className="v2-step-heading">4. Motores de IA, Voz Neural & Som Ambiente</h4>
              <p className="v2-step-desc">
                Configure a voz do narrador, geração visual via Google Flow e ambientação musical.
              </p>

              {/* Voz Neural */}
              <div className="v2-form-group">
                <label className="v2-form-label">Voz do Narrador (Azure Neural pt-BR)</label>
                <select
                  className="v2-select"
                  value={voiceName}
                  onChange={(e) => setVoiceName(e.target.value)}
                >
                  {voiceList.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label || v.name}
                    </option>
                  ))}
                </select>
                <span className="v2-form-hint">
                  Catálogo oficial de vozes neurais certificadas em português brasileiro.
                </span>
              </div>

              {/* Motores Visuais */}
              <div className="v2-section-card-mini">
                <h5 className="v2-mini-title">🎨 Geração Visual e Clipes</h5>
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

              {/* Som Ambiente / BGM */}
              <div className="v2-section-card-mini" style={{ marginTop: '14px' }}>
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
            </div>
          )}

          {/* PASSO 5: QUOTAS & LANÇAMENTO */}
          {step === 5 && (
            <div className="v2-wizard-step-content">
              <h4 className="v2-step-heading">5. Metas de Estoque, Automação & Revisão</h4>
              <p className="v2-step-desc">
                Defina as metas operacionais e revise o resumo antes de criar o canal.
              </p>

              <div className="v2-form-row-2">
                <div className="v2-form-group">
                  <label className="v2-form-label">Meta de Vídeos no Estoque Pronto</label>
                  <input
                    type="number"
                    className="v2-input-text"
                    min="1"
                    max="10"
                    value={targetStock}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (val === '') {
                        setTargetStock('');
                      } else {
                        const parsed = parseInt(val, 10);
                        setTargetStock(isNaN(parsed) ? 1 : Math.max(1, Math.min(10, parsed)));
                      }
                    }}
                    onBlur={() => {
                      if (!targetStock || Number(targetStock) < 1) {
                        setTargetStock(3);
                      }
                    }}
                    required
                  />
                  <span className="v2-form-hint">A fábrica produzirá vídeos até atingir esta meta.</span>
                </div>

                <div className="v2-form-group">
                  <label className="v2-form-label">Teto de Gerações em 24h</label>
                  <input
                    type="number"
                    className="v2-input-text"
                    min="1"
                    max="30"
                    value={dailyLimit}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (val === '') {
                        setDailyLimit('');
                      } else {
                        const parsed = parseInt(val, 10);
                        setDailyLimit(isNaN(parsed) ? 1 : Math.max(1, Math.min(30, parsed)));
                      }
                    }}
                    onBlur={() => {
                      if (!dailyLimit || Number(dailyLimit) < 1) {
                        setDailyLimit(5);
                      }
                    }}
                    required
                  />
                  <span className="v2-form-hint">Limite de segurança contra consumo excessivo de cotas.</span>
                </div>
              </div>

              {/* Autonomia Inicial (Safe Default) */}
              <div className="v2-autonomy-launch-box">
                <div className="v2-auto-toggle-row">
                  <div className="v2-auto-info">
                    <strong>Habilitar Produção Autônoma Imediatamente</strong>
                    <span>(Recomendado manter desligado na criação para revisão inicial pelo operador)</span>
                  </div>
                  <label className="v2-switch">
                    <input
                      type="checkbox"
                      checked={autonomousEnabled}
                      onChange={(e) => setAutonomousEnabled(e.target.checked)}
                    />
                    <span className="v2-slider round" />
                  </label>
                </div>
              </div>

              {/* Resumo Final */}
              <div className="v2-summary-box">
                <h5 className="v2-summary-title">📋 Resumo das Configurações do Canal:</h5>
                <ul className="v2-summary-list">
                  <li><strong>Canal:</strong> {name} ({niche || 'Nicho Geral'})</li>
                  <li><strong>Formato:</strong> {currentTemplate?.title || formatType}</li>
                  <li><strong>Voz:</strong> {voiceName}</li>
                  <li><strong>Visual:</strong> {flowEnabled ? `Google Flow (${flowSceneCount} cenas)` : 'Clipes de Stock'} + Visual Director</li>
                  <li><strong>BGM:</strong> {musicEnabled ? `Ativo (${musicMood}, ${Math.round(musicVolume * 100)}%)` : 'Desativado'}</li>
                  <li><strong>Meta de Estoque:</strong> {targetStock} vídeos prontos (Teto 24h: {dailyLimit})</li>
                  <li><strong>Destinos:</strong> {selectedYtAccountId ? 'YouTube vinculado' : 'Sem YouTube'} / {selectedTtAccountId ? 'TikTok vinculado' : 'Sem TikTok'}</li>
                  <li><strong>Status Inicial:</strong> {autonomousEnabled ? '🟢 Autônomo Ativado' : '🟡 Manual / Pausado (Seguro)'}</li>
                </ul>
              </div>
            </div>
          )}

          {/* Footer de Ações do Wizard */}
          <div className="v2-modal-actions v2-wizard-footer">
            <button
              type="button"
              className="v2-btn-secondary"
              onClick={step === 1 ? onClose : handlePrevStep}
              disabled={isSubmitting}
            >
              {step === 1 ? 'Cancelar' : '← Voltar'}
            </button>

            {step < 5 ? (
              <button
                type="button"
                className="v2-btn-primary"
                onClick={handleNextStep}
                disabled={isSubmitting}
              >
                Próximo Passo →
              </button>
            ) : (
              <button
                type="button"
                className="v2-btn-primary v2-btn-create-submit"
                onClick={handleSubmit}
                disabled={isSubmitting}
              >
                {isSubmitting ? 'Criando Canal...' : '🚀 Concluir e Criar Canal'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
