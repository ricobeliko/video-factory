/**
 * Funções puras de validação, cálculo de diff e construção de payload
 * para configuração de Voz e Velocidade por Canal (Missão M6b).
 */

export const VOICE_FIELD_BOUNDS = {
  voice_rate: { min: 0.5, max: 2.0, step: 0.05, label: 'Velocidade da Voz', unit: 'x' },
  voice_volume: { min: 0.0, max: 1.0, step: 0.05, label: 'Volume da Voz', unit: '%' },
};

export const VOICE_FIELD_LABELS = {
  voice_name: 'Voz do Canal',
  voice_rate: 'Velocidade da Voz',
  voice_volume: 'Volume da Voz',
};

export const QUIZ_VOICE_RATE_NOTICE = 'Ritmo definido pelo formato do quiz';

/**
 * 1. Obtém metadados visuais e rótulo amigável da origem (source).
 */
export function getVoiceSourceInfo(source) {
  const cleanSource = String(source || '').toLowerCase().trim();
  switch (cleanSource) {
    case 'channel':
      return {
        label: 'Do canal',
        badgeClass: 'sys-badge-channel',
        isInherited: false,
        canReset: true,
      };
    case 'global':
      return {
        label: 'Global',
        badgeClass: 'sys-badge-global',
        isInherited: true,
        canReset: false,
      };
    case 'default':
      return {
        label: 'Padrão',
        badgeClass: 'sys-badge-default',
        isInherited: true,
        canReset: false,
      };
    default:
      return {
        label: '—',
        badgeClass: 'sys-badge-default',
        isInherited: true,
        canReset: false,
      };
  }
}

/**
 * 2. Valida um campo individual de voz.
 */
export function validateVoiceField(fieldName, value, { isQuiz = false, allowedVoiceIds = [] } = {}) {
  // Se o valor for null, representa ação explícita de 'Voltar a herdar' (reset) -> sempre válido
  if (value === null) {
    return { isValid: true, error: null };
  }

  if (fieldName === 'voice_name') {
    if (value === undefined || value === '') {
      return { isValid: false, error: 'Voz é obrigatória.' };
    }
    const clean = String(value).trim();
    if (allowedVoiceIds && allowedVoiceIds.length > 0 && !allowedVoiceIds.includes(clean)) {
      return { isValid: false, error: 'Voz selecionada não está na lista de vozes homologadas.' };
    }
    return { isValid: true, error: null };
  }

  if (fieldName === 'voice_rate') {
    // Para canal de quiz, o campo de velocidade não é editado
    if (isQuiz) {
      return { isValid: true, error: null };
    }
    if (value === undefined || value === '') {
      return { isValid: false, error: 'Velocidade da voz é obrigatória.' };
    }
    const num = Number(value);
    if (Number.isNaN(num) || num < 0.5 || num > 2.0) {
      return { isValid: false, error: 'Velocidade da voz deve ser entre 0.5 e 2.0.' };
    }
    return { isValid: true, error: null };
  }

  if (fieldName === 'voice_volume') {
    if (value === undefined || value === '') {
      return { isValid: false, error: 'Volume da voz é obrigatório.' };
    }
    const num = Number(value);
    if (Number.isNaN(num) || num < 0.0 || num > 1.0) {
      return { isValid: false, error: 'Volume da voz deve ser entre 0.0 e 1.0.' };
    }
    return { isValid: true, error: null };
  }

  return { isValid: true, error: null };
}

/**
 * 3. Validação do formulário de voz.
 */
export function validateVoiceForm(formData, { isQuiz = false, allowedVoiceIds = [] } = {}) {
  const errors = {};
  if (!formData) return { isValid: true, errors };

  const fieldsToCheck = isQuiz ? ['voice_name', 'voice_volume'] : ['voice_name', 'voice_rate', 'voice_volume'];

  for (const field of fieldsToCheck) {
    if (formData[field] !== undefined) {
      const res = validateVoiceField(field, formData[field], { isQuiz, allowedVoiceIds });
      if (!res.isValid) {
        errors[field] = res.error;
      }
    }
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

/**
 * 4. Calcula o diff (ANTES -> DEPOIS) para os campos de voz alterados.
 *
 * effectiveVoice: { voice_name: { value, source }, voice_rate: { value, source }, voice_volume: { value, source } }
 * formData: { voice_name, voice_rate, voice_volume }
 */
export function calculateVoiceDiff(effectiveVoice, formData, { isQuiz = false, pinned } = {}) {
  if (!formData) return [];

  const diffs = [];
  const fields = isQuiz ? ['voice_name', 'voice_volume'] : ['voice_name', 'voice_rate', 'voice_volume'];

  const isFieldPinned = (field) => {
    if (!pinned) return false;
    if (pinned instanceof Set) return pinned.has(field);
    if (Array.isArray(pinned)) return pinned.includes(field);
    if (typeof pinned === 'object') return Boolean(pinned[field]);
    return false;
  };

  for (const field of fields) {
    const currentEff = effectiveVoice && effectiveVoice[field] ? effectiveVoice[field].value : undefined;
    const currentSource = effectiveVoice && effectiveVoice[field] ? effectiveVoice[field].source : undefined;
    const formVal = formData[field];

    if (formVal === undefined) {
      continue;
    }

    // Caso 1: Usuário solicitou 'Voltar a herdar' (formVal === null)
    if (formVal === null) {
      if (currentSource === 'channel') {
        diffs.push({
          field,
          label: VOICE_FIELD_LABELS[field] || field,
          oldValue: currentEff,
          newValue: null,
          isReset: true,
          isPin: false,
        });
      }
      continue;
    }

    // Caso 2: Edição comum ou Fixação no canal (isPin)
    let isChanged = false;
    if (field === 'voice_name') {
      isChanged = String(formVal).trim() !== String(currentEff || '').trim();
    } else {
      const n1 = Number(formVal);
      const n2 = Number(currentEff);
      if (Number.isNaN(n1) || Number.isNaN(n2)) {
        isChanged = formVal !== currentEff;
      } else {
        isChanged = Math.abs(n1 - n2) > 0.001;
      }
    }

    const formattedNewVal = field === 'voice_name' ? String(formVal).trim() : Number(formVal);

    if (currentSource !== 'channel' && isFieldPinned(field)) {
      diffs.push({
        field,
        label: VOICE_FIELD_LABELS[field] || field,
        oldValue: currentEff,
        newValue: formattedNewVal,
        isReset: false,
        isPin: true,
      });
    } else if (isChanged) {
      diffs.push({
        field,
        label: VOICE_FIELD_LABELS[field] || field,
        oldValue: currentEff,
        newValue: formattedNewVal,
        isReset: false,
        isPin: false,
      });
    }
  }

  return diffs;
}

/**
 * 5. Constrói o payload para PATCH /api/v2/channels/{profile_id}/voice
 * contendo SOMENTE os campos que realmente mudaram.
 */
export function buildVoicePatchPayload(diffList) {
  if (!Array.isArray(diffList) || diffList.length === 0) {
    return {
      payload: null,
      hasChanges: false,
    };
  }

  const payload = {};
  for (const item of diffList) {
    // Se for reset (Voltar a herdar), envia explicitamente null para o backend limpar
    payload[item.field] = item.isReset ? null : item.newValue;
  }

  return {
    payload,
    hasChanges: Object.keys(payload).length > 0,
  };
}

/**
 * 6. Formata valor de diff de voz para exibição no diálogo de confirmação.
 */
export function formatVoiceDiffDisplay(field, value, allowedVoices = []) {
  if (value === null) {
    return 'Voltar a herdar (global)';
  }
  if (value === undefined || value === '') {
    return '—';
  }

  if (field === 'voice_name') {
    const found = Array.isArray(allowedVoices)
      ? allowedVoices.find((v) => v.id === value || v.voice_name === value)
      : null;
    return found ? found.name : String(value);
  }

  if (field === 'voice_rate') {
    const num = Number(value);
    return Number.isNaN(num) ? String(value) : `${num.toFixed(2)}x`;
  }

  if (field === 'voice_volume') {
    const num = Number(value);
    return Number.isNaN(num) ? String(value) : `${Math.round(num * 100)}%`;
  }

  return String(value);
}
