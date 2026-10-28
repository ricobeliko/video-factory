/**
 * Funções puras de validação, cálculo de diff, construção de payloads
 * e navegação direta para edição de ajustes por canal (SIS2 + Controles Únicos).
 */

export const EDITABLE_FIELD_BOUNDS = {
  target_ready_stock: { min: 3, max: 10, label: 'Meta de Estoque Pronto', unit: 'vídeos' },
  max_generations_24h: { min: 1, max: 10, label: 'Gerações Aprovadas (24h)', unit: 'vídeos/24h' },
  posts_per_day: { min: 1, max: 10, label: 'Publicações por Dia', unit: 'posts/dia' },
  publish_start_hour: { min: 0, max: 23, label: 'Horário Inicial da Janela', unit: 'h' },
  publish_end_hour: { min: 0, max: 23, label: 'Horário Final da Janela', unit: 'h' },
  min_interval_hours: { min: 1, max: 24, label: 'Intervalo Mínimo', unit: 'h' },
};

export const ALLOWED_GROWTH_MODES = ['WARMUP', 'SCALE'];

const REQUIRED_BASE_NUMERIC_FIELDS = [
  'target_ready_stock',
  'posts_per_day',
  'publish_start_hour',
  'publish_end_hour',
  'min_interval_hours',
];

/**
 * Normaliza booleano de modo autônomo aceitando boolean ou string ('true'/'false').
 */
export function normalizeAutonomousEnabled(value) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const clean = value.trim().toLowerCase();
    if (clean === 'true' || clean === '1') return true;
    if (clean === 'false' || clean === '0') return false;
  }
  return null;
}

/**
 * 1. Valida um campo individual contra suas regras e limites.
 */
export function validateChannelField(fieldName, value) {
  if (fieldName === 'growth_mode') {
    const cleanMode = String(value ?? '').trim().toUpperCase();
    if (!ALLOWED_GROWTH_MODES.includes(cleanMode)) {
      return {
        isValid: false,
        error: 'Modo de Crescimento deve ser WARMUP ou SCALE.',
      };
    }
    return { isValid: true, error: null };
  }

  if (fieldName === 'autonomous_enabled') {
    const norm = normalizeAutonomousEnabled(value);
    if (norm === null) {
      return {
        isValid: false,
        error: 'Modo Autônomo deve ser Ativo (SIM) ou Desligado (NÃO).',
      };
    }
    return { isValid: true, error: null };
  }

  const bounds = EDITABLE_FIELD_BOUNDS[fieldName];
  if (!bounds) {
    return { isValid: true, error: null };
  }

  if (value === null || value === undefined || value === '') {
    return { isValid: false, error: `${bounds.label} é obrigatório.` };
  }

  const num = Number(value);
  if (!Number.isInteger(num)) {
    return { isValid: false, error: `${bounds.label} deve ser um número inteiro.` };
  }

  if (num < bounds.min || num > bounds.max) {
    return {
      isValid: false,
      error: `${bounds.label} deve estar entre ${bounds.min} e ${bounds.max}.`,
    };
  }

  return { isValid: true, error: null };
}

/**
 * 2. Valida a janela de publicação (start <= end).
 * O backend não aceita janelas que atravessam a meia-noite (publish_end_hour < publish_start_hour).
 */
export function validateScheduleWindow(startHour, endHour) {
  const start = Number(startHour);
  const end = Number(endHour);

  if (Number.isNaN(start) || Number.isNaN(end)) {
    return { isValid: false, error: 'Horários inicial e final devem ser números válidos.' };
  }

  if (end < start) {
    return {
      isValid: false,
      error: 'O horário final da janela não pode ser menor que o horário inicial.',
    };
  }

  return { isValid: true, error: null };
}

/**
 * 3. Validação completa do formulário de edição de canal.
 */
export function validateChannelForm(formData) {
  const errors = {};
  const data = formData || {};

  for (const field of REQUIRED_BASE_NUMERIC_FIELDS) {
    const res = validateChannelField(field, data[field]);
    if (!res.isValid) {
      errors[field] = res.error;
    }
  }

  for (const optionalField of ['max_generations_24h', 'growth_mode', 'autonomous_enabled']) {
    if (Object.prototype.hasOwnProperty.call(data, optionalField)) {
      const res = validateChannelField(optionalField, data[optionalField]);
      if (!res.isValid) {
        errors[optionalField] = res.error;
      }
    }
  }

  // Validação de janela cruzada caso start e end estejam presentes e sem erro individual
  if (!errors.publish_start_hour && !errors.publish_end_hour) {
    const winRes = validateScheduleWindow(data.publish_start_hour, data.publish_end_hour);
    if (!winRes.isValid) {
      errors.publish_end_hour = winRes.error;
    }
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  };
}

/**
 * 4. Calcula o diff (ANTES -> DEPOIS) para cada campo alterado.
 */
export function calculateSettingsDiff(originalSettings, formData) {
  if (!formData) return [];

  const diffs = [];

  if (
    formData.growth_mode !== undefined &&
    formData.growth_mode !== null &&
    originalSettings &&
    originalSettings.growth_mode !== undefined &&
    originalSettings.growth_mode !== null
  ) {
    const oldMode = String(originalSettings.growth_mode).trim().toUpperCase();
    const newMode = String(formData.growth_mode).trim().toUpperCase();
    if (oldMode !== newMode) {
      diffs.push({
        field: 'growth_mode',
        label: 'Modo de Crescimento',
        oldValue: oldMode,
        newValue: newMode,
        unit: '',
      });
    }
  }

  if (
    formData.autonomous_enabled !== undefined &&
    formData.autonomous_enabled !== null &&
    originalSettings &&
    originalSettings.autonomous_enabled !== undefined &&
    originalSettings.autonomous_enabled !== null
  ) {
    const oldAuto = normalizeAutonomousEnabled(originalSettings.autonomous_enabled);
    const newAuto = normalizeAutonomousEnabled(formData.autonomous_enabled);
    if (oldAuto !== null && newAuto !== null && oldAuto !== newAuto) {
      diffs.push({
        field: 'autonomous_enabled',
        label: 'Modo Autônomo',
        oldValue: oldAuto,
        newValue: newAuto,
        unit: '',
      });
    }
  }

  const fields = Object.keys(EDITABLE_FIELD_BOUNDS);
  for (const field of fields) {
    const oldVal = originalSettings ? originalSettings[field] : undefined;
    const newVal = formData[field];

    if (newVal !== undefined && newVal !== null && oldVal !== undefined && oldVal !== null) {
      const numOld = Number(oldVal);
      const numNew = Number(newVal);

      if (numOld !== numNew) {
        diffs.push({
          field,
          label: EDITABLE_FIELD_BOUNDS[field].label,
          oldValue: numOld,
          newValue: numNew,
          unit: EDITABLE_FIELD_BOUNDS[field].unit,
        });
      }
    }
  }

  return diffs;
}

/**
 * 5. Constrói os payloads para os endpoints existentes de canal
 * contendo SOMENTE os campos que realmente mudaram.
 */
export function buildPatchPayloads(diffList) {
  if (!Array.isArray(diffList) || diffList.length === 0) {
    return {
      growthModePayload: null,
      autonomousPayload: null,
      quotasPayload: null,
      schedulePayload: null,
      hasChanges: false,
    };
  }

  let growthModePayload = null;
  let autonomousPayload = null;
  const quotas = {};
  const schedule = {};

  for (const item of diffList) {
    const { field, newValue } = item;
    if (field === 'growth_mode') {
      growthModePayload = String(newValue).trim().toLowerCase();
    } else if (field === 'autonomous_enabled') {
      autonomousPayload = Boolean(normalizeAutonomousEnabled(newValue));
    } else if (field === 'target_ready_stock') {
      quotas.target_ready_stock = newValue;
    } else if (field === 'max_generations_24h') {
      quotas.max_generations_24h = newValue;
    } else if (field === 'posts_per_day') {
      // posts_per_day existe em quotas e schedule; o backend sincroniza ambos
      quotas.posts_per_day = newValue;

    } else if (field === 'publish_start_hour') {
      schedule.publish_start_hour = newValue;
    } else if (field === 'publish_end_hour') {
      schedule.publish_end_hour = newValue;
    } else if (field === 'min_interval_hours') {
      schedule.min_interval_hours = newValue;
    }
  }

  return {
    growthModePayload,
    autonomousPayload,
    quotasPayload: Object.keys(quotas).length > 0 ? quotas : null,
    schedulePayload: Object.keys(schedule).length > 0 ? schedule : null,
    hasChanges: true,
  };
}

/**
 * 6. Formata valor de diff para exibição amigável no diálogo de confirmação.
 */
export function formatDiffValueDisplay(field, value) {
  if (value === null || value === undefined) return '—';

  if (field === 'growth_mode') {
    const clean = String(value).trim().toUpperCase();
    return clean === 'SCALE' ? 'SCALE (Escala)' : 'WARMUP (Aquecimento)';
  }
  if (field === 'autonomous_enabled') {
    const norm = normalizeAutonomousEnabled(value);
    return norm ? 'SIM (Ativo)' : 'NÃO (Desligado)';
  }

  const num = Number(value);

  if (field === 'publish_start_hour' || field === 'publish_end_hour') {
    return `${String(num).padStart(2, '0')}:00`;
  }
  if (field === 'min_interval_hours') {
    return `${num}h`;
  }
  if (field === 'target_ready_stock') {
    return `${num} vídeos`;
  }
  if (field === 'max_generations_24h') {
    return `${num} vídeos/24h`;
  }
  if (field === 'posts_per_day') {
    return `${num} posts/dia`;
  }
  return String(num);
}

/**
 * 7. Constrói o hash de navegação direta para editar um canal na tela Sistema.
 */
export function buildSystemChannelHash(profileId) {
  const clean = String(profileId ?? '').trim();
  if (!clean) return '#sistema';
  return `#sistema?channel=${encodeURIComponent(clean)}`;
}

/**
 * 8. Extrai o profile_id alvo do hash da URL (ex.: '#sistema?channel=profile-historias').
 */
export function parseSystemChannelFromHash(hash) {
  const raw = String(hash ?? '').trim();
  if (!raw.startsWith('#sistema')) return null;
  const qIndex = raw.indexOf('?');
  if (qIndex === -1) return null;
  const params = new URLSearchParams(raw.slice(qIndex + 1));
  const channel = params.get('channel');
  return channel && channel.trim() ? channel.trim() : null;
}
