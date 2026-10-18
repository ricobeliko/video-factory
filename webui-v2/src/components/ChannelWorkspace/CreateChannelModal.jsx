import React, { useState, useEffect } from 'react';
import { createChannel, getVideoTemplates } from '../../api';

export default function CreateChannelModal({ isOpen, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [niche, setNiche] = useState('');
  const [formatType, setFormatType] = useState('traditional');
  const [targetStock, setTargetStock] = useState(3);
  const [autonomousEnabled, setAutonomousEnabled] = useState(false);
  const [voiceName, setVoiceName] = useState('pt-BR-AntonioNeural');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [templates, setTemplates] = useState([]);

  useEffect(() => {
    if (isOpen) {
      getVideoTemplates()
        .then((res) => {
          const list = res?.templates || res?.data?.templates || [];
          if (Array.isArray(list) && list.length > 0) {
            setTemplates(list);
          }
        })
        .catch(() => {
          // Fallback local se a API estiver offline
          setTemplates([
            {
              id: 'traditional',
              title: 'Vídeo Tradicional (Pexels / LLM)',
              description: 'Montagem dinâmica com clipes Pexels/Pixabay, narração flexível e legendas animadas.',
              locked_fields: [],
            },
            {
              id: 'quiz_dilemma',
              title: 'Quiz Q0-R — Escolhas Impossíveis',
              description: 'Template homologado com tela dividida (50/50), votação visual e barra de porcentagem.',
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
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const currentTemplate = templates.find((t) => t.id === formatType) || templates[0];

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Por favor, informe o nome do canal.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await createChannel({
        name: name.trim(),
        niche: niche.trim() || undefined,
        format_type: formatType,
        target_stock: Number(targetStock),
        autonomous_enabled: autonomousEnabled,
        voice_name: voiceName,
      });
      onCreated();
      onClose();
    } catch (err) {
      setError(err.message || 'Erro ao criar canal.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="v2-modal-overlay">
      <div className="v2-modal-container">
        <div className="v2-modal-header">
          <div>
            <h3 className="v2-modal-title">Novo Canal de Vídeo</h3>
            <p className="v2-modal-subtitle">
              Configure a identidade editorial e o formato congelado do canal.
            </p>
          </div>
          <button className="v2-btn-close" onClick={onClose}>
            ×
          </button>
        </div>

        {error && <div className="v2-alert-error">{error}</div>}

        <form onSubmit={handleSubmit} className="v2-modal-form">
          <div className="v2-form-group">
            <label className="v2-form-label">Nome do Canal *</label>
            <input
              type="text"
              className="v2-input-text"
              placeholder="Ex: Dose Diária de Escolhas"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="v2-form-group">
            <label className="v2-form-label">Nicho Editorial</label>
            <input
              type="text"
              className="v2-input-text"
              placeholder="Ex: Curiosidades, Dilemas Morais, História"
              value={niche}
              onChange={(e) => setNiche(e.target.value)}
            />
          </div>

          {/* Seleção Inteligente de Formato (Fase V2.5) */}
          <div className="v2-form-group">
            <label className="v2-form-label">Formato de Vídeo Homologado</label>
            <div className="v2-format-grid">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  className={`v2-format-card ${formatType === tpl.id ? 'selected' : ''}`}
                  onClick={() => setFormatType(tpl.id)}
                >
                  <div className="v2-format-title">{tpl.title}</div>
                  <div className="v2-format-desc">{tpl.description}</div>
                  {tpl.locked_fields?.length > 0 && (
                    <div className="v2-format-badge">
                      🔒 {tpl.locked_fields.length} parâmetros técnicos congelados
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Informativo de Parâmetros Congelados do Template */}
          {currentTemplate && currentTemplate.locked_fields?.length > 0 && (
            <div className="v2-locked-fields-box">
              <span className="v2-locked-icon">🔒</span>
              <div className="v2-locked-content">
                <strong>Parâmetros Congelados pelo Template:</strong>
                <p>
                  {formatType === 'quiz_paper'
                    ? 'Duração: 60-65s | Resolução: 1080x1920 (9:16) | Timer: Circular Pie | Layout: Perguntas e 4 opções no mesmo quadro rústico.'
                    : 'Resolução: 1080x1920 (9:16) | Layout: Split vertical 50/50 | Votação: Barra de porcentagem homologada.'}
                </p>
                <small className="v2-text-muted">
                  Essas propriedades são garantidas pelo motor de renderização e não podem ser alteradas acidentalmente.
                </small>
              </div>
            </div>
          )}

          <div className="v2-form-row">
            <div className="v2-form-group" style={{ flex: 1 }}>
              <label className="v2-form-label">Meta de Estoque (Vídeos Prontos)</label>
              <input
                type="number"
                min="1"
                max="10"
                className="v2-input-text"
                value={targetStock}
                onChange={(e) => setTargetStock(e.target.value)}
              />
            </div>

            <div className="v2-form-group" style={{ flex: 1 }}>
              <label className="v2-form-label">Voz Padrão do Canal</label>
              <select
                className="v2-select"
                value={voiceName}
                onChange={(e) => setVoiceName(e.target.value)}
              >
                <option value="pt-BR-AntonioNeural">pt-BR-AntonioNeural (Masculina - Firme)</option>
                <option value="pt-BR-FranciscaNeural">pt-BR-FranciscaNeural (Feminina - Clara)</option>
                <option value="pt-BR-FabioNeural">pt-BR-FabioNeural (Masculina - Calma)</option>
                <option value="pt-BR-ThalitaNeural">pt-BR-ThalitaNeural (Feminina - Jovem)</option>
              </select>
            </div>
          </div>

          <div className="v2-switch-row">
            <label className="v2-switch-label">
              <input
                type="checkbox"
                checked={autonomousEnabled}
                onChange={(e) => setAutonomousEnabled(e.target.checked)}
              />
              <span>Ativar Produção Autônoma Imediatamente</span>
            </label>
            <span className="v2-switch-hint">
              O Scheduler manterá a meta de estoque de {targetStock} vídeos automaticamente.
            </span>
          </div>

          <div className="v2-modal-actions">
            <button
              type="button"
              className="v2-btn-secondary"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="v2-btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Criando...' : 'Criar Canal'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
