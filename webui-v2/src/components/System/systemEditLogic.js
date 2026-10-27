/**
 * Funções puras de validação, cálculo de diff e construção de payloads
 * para edição de ajustes por canal (SIS2).
 */

export const EDITABLE_FIELD_BOUNDS = {
  target_ready_stock: { min: 1, max: 10, label: 'Meta de Estoque Pronto', unit: 'vídeos' },
  posts_per_day: { min: 1, max: 10, label: 'Publicações por Dia', unit: 'posts/dia' },
  publish_start_hour: { min: 0, max: 23, label: 'Horário Inicial da Janela', unit: 'h' },
  publish_end_hour: { min: 0, max: 23, label: 'Horário Final da Janela', unit: 'h' },
  min_interval_hours: { min: 1, max: 24, label: 'Intervalo Mínimo', unit: 'h' },
};

/**
 * 1. Valida um campo individual contra suas regras e limites.
 */
export function validateChannelField(fieldName, value) {
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

  for (const field of Object.keys(EDITABLE_FIELD_BOUNDS)) {
    const res = validateChannelField(field, formData[field]);
    if (!res.isValid) {
      errors[field] = res.error;
    }
  }

  // Validação de janela cruzada caso start e end estejam presentes e sem erro individual
  if (!errors.publish_start_hour && !errors.publish_end_hour) {
    const winRes = validateScheduleWindow(formData.publish_start_hour, formData.publish_end_hour);
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
 * 5. Constrói os payloads para os endpoints PATCH /quotas e /schedule
 * contendo SOMENTE os campos que realmente mudaram.
 */
export function buildPatchPayloads(diffList) {
  if (!Array.isArray(diffList) || diffList.length === 0) {
    return {
      quotasPayload: null,
      schedulePayload: null,
      hasChanges: false,
    };
  }

  const quotas = {};
  const schedule = {};

  for (const item of diffList) {
    const { field, newValue } = item;
    if (field === 'target_ready_stock') {
      quotas.target_ready_stock = newValue;
    } else if (field === 'posts_per_day') {
      // posts_per_day existe em quotas e schedule; o backend sincroniza ambos
      quotas.posts_per_day = newValue;
      schedule.posts_per_day = newValue;
    } else if (field === 'publish_start_hour') {
      schedule.publish_start_hour = newValue;
    } else if (field === 'publish_end_hour') {
      schedule.publish_end_hour = newValue;
    } else if (field === 'min_interval_hours') {
      schedule.min_interval_hours = newValue;
    }
  }

  return {
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
  if (field === 'posts_per_day') {
    return `${num} posts/dia`;
  }
  return String(num);
}
