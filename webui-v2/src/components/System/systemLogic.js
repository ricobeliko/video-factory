/**
 * Funções puras de formatação e lógica de apresentação para a tela Sistema (V2)
 * Fonte da verdade: Backend API.
 */

/**
 * 1. Formata o estado operacional da fábrica.
 * Retorna rótulo em texto legível (não apenas cor) e indicador de pausa.
 */
export function formatFactoryState(systemDataOrState) {
  if (!systemDataOrState) {
    return {
      label: 'DESCONHECIDO',
      text: 'Desconhecido',
      isPaused: false,
      variant: 'unknown',
    };
  }

  let state = '';
  let isPaused = false;

  if (typeof systemDataOrState === 'string') {
    state = systemDataOrState.toUpperCase();
    isPaused = state === 'PAUSED';
  } else if (typeof systemDataOrState === 'object') {
    isPaused = Boolean(systemDataOrState.is_paused);
    state = String(systemDataOrState.factory_state || systemDataOrState.state || (isPaused ? 'PAUSED' : 'RUNNING')).toUpperCase();
  }

  if (isPaused || state === 'PAUSED') {
    return {
      label: 'PAUSADA',
      text: 'Fábrica Pausada',
      isPaused: true,
      variant: 'paused',
    };
  }

  if (state === 'RUNNING' || state === 'IDLE' || state === 'ACTIVE') {
    return {
      label: 'EM OPERAÇÃO',
      text: 'Em Operação',
      isPaused: false,
      variant: 'running',
    };
  }

  if (state === 'DEGRADED') {
    return {
      label: 'EM OPERAÇÃO (DEGRADADA)',
      text: 'Em Operação (Degradada)',
      isPaused: false,
      variant: 'degraded',
    };
  }

  if (state === 'ERROR') {
    return {
      label: 'ERRO CRÍTICO',
      text: 'Erro Crítico',
      isPaused: false,
      variant: 'error',
    };
  }

  return {
    label: state || 'DESCONHECIDO',
    text: state || 'Desconhecido',
    isPaused: false,
    variant: 'unknown',
  };
}

/**
 * 2. Formata o papel da instância (PRIMARY vs SECONDARY_VIEW_ONLY).
 */
export function formatInstanceRole(instanceOrRole) {
  if (!instanceOrRole) {
    return {
      role: 'UNKNOWN',
      label: 'Desconhecido',
      description: 'Estado da instância indisponível',
      isPrimary: false,
    };
  }

  let role = '';
  let isPrimary = false;

  if (typeof instanceOrRole === 'string') {
    role = instanceOrRole.toUpperCase();
    isPrimary = role === 'PRIMARY';
  } else if (typeof instanceOrRole === 'object') {
    role = String(instanceOrRole.local_role || instanceOrRole.role || (instanceOrRole.is_primary ? 'PRIMARY' : 'SECONDARY_VIEW_ONLY')).toUpperCase();
    isPrimary = Boolean(instanceOrRole.is_primary ?? (role === 'PRIMARY'));
  }

  if (role === 'PRIMARY' || isPrimary) {
    return {
      role: 'PRIMARY',
      label: 'PRIMARY',
      description: 'Instância Primária (Controle Total)',
      isPrimary: true,
    };
  }

  return {
    role: role || 'SECONDARY_VIEW_ONLY',
    label: role || 'SECONDARY_VIEW_ONLY',
    description: 'Instância Secundária (Somente Leitura)',
    isPrimary: false,
  };
}

/**
 * 3. Formata heartbeat em segundos ou minutos legíveis ("há X s", "há X min").
 */
export function formatHeartbeat(secondsAgo) {
  if (secondsAgo === null || secondsAgo === undefined || secondsAgo === '') {
    return '—';
  }

  const num = Number(secondsAgo);
  if (Number.isNaN(num) || num < 0) {
    return '—';
  }

  const s = Math.round(num);
  if (s < 60) {
    return `há ${s} s`;
  }

  const m = Math.floor(s / 60);
  if (m < 60) {
    return `há ${m} min`;
  }

  const h = Math.floor(m / 60);
  return `há ${h} h`;
}

/**
 * 4. Valida se a instância atual tem autorização para pausar/retomar a fábrica.
 * Apenas instâncias PRIMARY podem alterar o estado operacional.
 */
export function canToggleFactory(instance) {
  if (!instance) {
    return {
      canToggle: false,
      reason: 'Informações da instância indisponíveis. Apenas nó PRIMARY pode alterar o estado da fábrica.',
    };
  }

  const isPrimary = Boolean(instance.is_primary ?? (String(instance.local_role).toUpperCase() === 'PRIMARY'));

  if (!isPrimary) {
    return {
      canToggle: false,
      reason: 'Apenas a instância primária (PRIMARY) pode pausar ou retomar a fábrica. Instância atual em modo somente leitura.',
    };
  }

  return {
    canToggle: true,
    reason: null,
  };
}

/**
 * 5. Formata mensagens de erro da API em português sem omitir o detalhe original.
 * Preserva o tratamento específico de 409 (ciclo já em execução, fábrica pausada) e 403 (nó primário).
 */
export function formatApiError(err, actionContext = 'executar ação') {
  if (!err) {
    return `Falha ao ${actionContext}: Erro desconhecido`;
  }

  const message = typeof err === 'string' ? err : err.message || JSON.stringify(err);
  const status = err?.status;

  if (status === 403) {
    return `Operação bloqueada (403): Somente o nó primário (PRIMARY) tem permissão para ${actionContext}. (${message})`;
  }

  if (status === 409) {
    const msgLower = String(message).toLowerCase();
    if (
      msgLower.includes('already in progress') ||
      msgLower.includes('cycle_in_progress') ||
      msgLower.includes('active_tasks_generating')
    ) {
      return `Conflito operacional (409): Ciclo de produção já em andamento em segundo plano ao ${actionContext}. (${message})`;
    }
    if (msgLower.includes('paused') || msgLower.includes('pausada')) {
      return `Conflito operacional (409): Fábrica pausada — retome para disparar ao ${actionContext}. (${message})`;
    }
    return `Conflito operacional (409): Fábrica ocupada ou já no estado solicitado ao ${actionContext}. (${message})`;
  }

  return `Falha ao ${actionContext}: ${message}`;
}

/**
 * 6. Formata valor genérico para exibição (trata nulo/vazio com '—').
 */
export function formatProviderValue(val) {
  if (val === null || val === undefined || val === '') {
    return '—';
  }
  return String(val);
}

/**
 * 7. Extrai e formata cotas por canal para leitura.
 */
export function formatQuotasDisplay(quotas) {
  if (!quotas || typeof quotas !== 'object') {
    return {
      target_ready_stock: '—',
      max_generations_24h: '—',
      max_attempts_24h: '—',
      posts_per_day: '—',
    };
  }

  return {
    target_ready_stock: quotas.target_ready_stock != null ? String(quotas.target_ready_stock) : '—',
    max_generations_24h: quotas.max_generations_24h != null ? String(quotas.max_generations_24h) : '—',
    max_attempts_24h: quotas.max_attempts_24h != null ? String(quotas.max_attempts_24h) : '—',
    posts_per_day: quotas.posts_per_day != null ? String(quotas.posts_per_day) : '—',
  };
}

/**
 * 8. Extrai e formata janela de publicação de agendamento.
 */
export function formatScheduleDisplay(schedule) {
  if (!schedule || typeof schedule !== 'object') {
    return {
      window: '—',
      timezone: '—',
      min_interval_hours: '—',
      posts_per_day: '—',
    };
  }

  const start = schedule.publish_start_hour != null ? `${String(schedule.publish_start_hour).padStart(2, '0')}:00` : null;
  const end = schedule.publish_end_hour != null ? `${String(schedule.publish_end_hour).padStart(2, '0')}:00` : null;
  const tz = schedule.timezone || '—';
  const minInterval = schedule.min_interval_hours != null ? `${schedule.min_interval_hours}h` : '—';
  const postsPerDay = schedule.posts_per_day != null ? String(schedule.posts_per_day) : '—';

  let windowStr = '—';
  if (start && end) {
    windowStr = `${start} às ${end}`;
  } else if (start) {
    windowStr = `a partir de ${start}`;
  }

  return {
    window: windowStr,
    timezone: tz,
    min_interval_hours: minInterval,
    posts_per_day: postsPerDay,
  };
}
