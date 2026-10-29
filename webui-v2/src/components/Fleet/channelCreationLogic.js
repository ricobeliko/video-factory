/**
 * Pure validation and formatting logic for Channel Creation modal (UI-006 / Paridade V1->V2 2.7).
 * Decoupled from React for deterministic unit testing.
 */

export const VIDEO_FORMAT_OPTIONS = [
  { value: 'traditional', label: 'Tradicional (Shorts Padrão)' },
  { value: 'quiz_dilemma', label: 'Quiz Dilema (Q0-R)' },
  { value: 'quiz_paper', label: 'Quiz de Papel (P1.3)' },
];

/**
 * Validates channel creation form fields.
 * Identity ONLY: name, niche, video_format, topic_brief, language.
 * Operational settings (growth_mode, quotas, schedule, voice, autonomous) are edited exclusively in Sistema.
 */
export function validateCreateChannelForm(values = {}) {
  const errors = {};
  const cleanName = String(values.name || '').trim();
  const cleanNiche = String(values.niche || '').trim();
  const format = String(values.video_format || 'traditional').trim().toLowerCase();
  const cleanTopic = String(values.topic_brief || '').trim();

  if (!cleanName) {
    errors.name = 'Nome do canal é obrigatório.';
  } else if (cleanName.length > 100) {
    errors.name = 'Nome deve ter no máximo 100 caracteres.';
  }

  if (!cleanNiche) {
    errors.niche = 'Nicho é obrigatório.';
  } else if (cleanNiche.length > 100) {
    errors.niche = 'Nicho deve ter no máximo 100 caracteres.';
  }

  const validFormats = ['traditional', 'quiz_dilemma', 'quiz_paper'];
  if (!validFormats.includes(format)) {
    errors.video_format = 'Formato de vídeo inválido. Escolha tradicional, quiz dilema ou quiz de papel.';
  }

  if (cleanTopic.length > 1000) {
    errors.topic_brief = 'Briefing editorial deve ter no máximo 1000 caracteres.';
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

/**
 * Builds the sanitized JSON payload for POST /api/v2/channels.
 */
export function buildCreateChannelPayload(values = {}) {
  const cleanName = String(values.name || '').trim();
  const cleanNiche = String(values.niche || '').trim();
  const format = String(values.video_format || 'traditional').trim().toLowerCase();
  const cleanTopic = String(values.topic_brief || '').trim();

  return {
    name: cleanName,
    niche: cleanNiche,
    video_format: format,
    topic_brief: cleanTopic || null,
    language: 'pt-BR',
  };
}
