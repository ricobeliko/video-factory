/**
 * productionLogic.js — Funções puras e apresentação da tela de Produção (webui-v2).
 * BACKEND = SOURCE OF TRUTH / FRONTEND = PRESENTATION ONLY
 */

export const RUN_STATUS_CONFIG = {
  SUCCESS: {
    key: 'success',
    label: 'Sucesso',
    color: '#34D399',
    bg: 'rgba(52, 211, 153, 0.15)',
    border: 'rgba(52, 211, 153, 0.3)',
  },
  FAILED: {
    key: 'failed',
    label: 'Falha',
    color: '#FF8A7A',
    bg: 'rgba(255, 138, 122, 0.15)',
    border: 'rgba(255, 138, 122, 0.3)',
  },
  REJECTED: {
    key: 'rejected',
    label: 'Reprovado',
    color: '#F5B546',
    bg: 'rgba(245, 181, 70, 0.15)',
    border: 'rgba(245, 181, 70, 0.3)',
  },
  RUNNING: {
    key: 'running',
    label: 'Em execução',
    color: '#6AA8FF',
    bg: 'rgba(106, 168, 255, 0.15)',
    border: 'rgba(106, 168, 255, 0.3)',
  },
  UNKNOWN: {
    key: 'unknown',
    label: 'Desconhecido',
    color: '#9099AA',
    bg: 'rgba(144, 153, 170, 0.15)',
    border: 'rgba(144, 153, 170, 0.3)',
  },
};

export const STAGE_LABELS = {
  TOPIC: 'Roteiro',
  SCRIPT: 'Roteiro',
  NARRATION: 'Narração',
  VISUALS: 'Cenas',
  MATERIALS: 'Cenas',
  RENDER: 'Render',
  VIDEO: 'Render',
  SAFETY: 'Gates',
  QUALITY: 'Gates',
  COPYRIGHT: 'Gates',
  HELD_SAFETY_REVIEW: 'Gates',
  QUALITY_GATE: 'Gates',
  SAFETY_GATE: 'Gates',
  PUBLISH: 'Publicação',
};

/**
 * Formata a idade em horas em string legível.
 * Exemplos:
 * - 2 -> "2 h"
 * - 27 -> "1 d 3 h"
 * - 48 -> "2 d"
 * - 0.5 -> "< 1 h"
 * - null/undefined -> "—"
 */
export function formatAgeHours(hours) {
  if (hours == null || isNaN(hours) || Number(hours) < 0) {
    return '—';
  }
  const h = Number(hours);
  if (h >= 24) {
    const days = Math.floor(h / 24);
    const remHours = Math.floor(h % 24);
    if (remHours > 0) {
      return `${days} d ${remHours} h`;
    }
    return `${days} d`;
  }
  if (h < 1) {
    return '< 1 h';
  }
  return `${Math.floor(h)} h`;
}

/**
 * Formata a duração em segundos.
 * Exemplo: 42.5 -> "43s", 75 -> "1m 15s"
 */
export function formatDuration(seconds) {
  if (seconds == null || isNaN(seconds) || Number(seconds) <= 0) {
    return '—';
  }
  const s = Math.round(Number(seconds));
  if (s < 60) {
    return `${s}s`;
  }
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

/**
 * Formata status de direitos autorais (copyright_status).
 * REGRA: copyright_status null DEVE retornar "não verificado" neutro (nunca OK).
 */
export function formatCopyrightStatus(status) {
  if (!status) {
    return {
      label: 'não verificado',
      key: 'unverified',
      color: '#9099AA',
      bg: 'rgba(144, 153, 170, 0.15)',
      border: 'rgba(144, 153, 170, 0.25)',
    };
  }
  const norm = String(status).toUpperCase().trim();
  if (norm === 'PASS') {
    return {
      label: 'aprovado',
      key: 'pass',
      color: '#34D399',
      bg: 'rgba(52, 211, 153, 0.15)',
      border: 'rgba(52, 211, 153, 0.3)',
    };
  }
  if (norm === 'FAIL' || norm === 'BLOCK' || norm === 'BLOCKED') {
    return {
      label: 'bloqueado',
      key: 'fail',
      color: '#FF8A7A',
      bg: 'rgba(255, 138, 122, 0.15)',
      border: 'rgba(255, 138, 122, 0.3)',
    };
  }
  return {
    label: String(status).toLowerCase(),
    key: 'other',
    color: '#E8EBF1',
    bg: 'rgba(232, 235, 241, 0.12)',
    border: 'rgba(232, 235, 241, 0.25)',
  };
}

/**
 * Retorna metadados visuais de status da tarefa nas últimas 24h.
 */
export function formatRunStatus(status) {
  const norm = String(status || '').toUpperCase().trim();
  return (
    RUN_STATUS_CONFIG[norm] || {
      key: 'unknown',
      label: 'desconhecido',
      color: '#9099AA',
      bg: 'rgba(144, 153, 170, 0.15)',
      border: 'rgba(144, 153, 170, 0.25)',
    }
  );
}

/**
 * Mapeia etapa de falha para rótulo amigável.
 */
export function formatStage(stage) {
  if (!stage) return '—';
  const norm = String(stage).toUpperCase().trim();
  return STAGE_LABELS[norm] || stage;
}

/**
 * Traduz status de post agendado.
 */
export function formatScheduledStatus(status) {
  if (!status) return '—';
  const s = String(status).toLowerCase().trim();
  if (s === 'planned') return 'planejado';
  if (s === 'ready') return 'pronto';
  return status;
}

/**
 * Formata data/hora ISO para o fuso horário de São Paulo (America/Sao_Paulo).
 */
export function formatDateTimeBR(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(d);
  } catch {
    return '—';
  }
}

/**
 * Ordena estoque pronto: mais antigo primeiro (mais tempo parado em estoque).
 */
export function sortReadyStock(items) {
  if (!Array.isArray(items)) return [];
  return [...items].sort((a, b) => {
    const ageA = Number(a?.age_hours ?? -1);
    const ageB = Number(b?.age_hours ?? -1);
    if (ageA !== ageB && ageA >= 0 && ageB >= 0) {
      return ageB - ageA; // maior idade = mais antigo = vem primeiro
    }
    const timeA = a?.created_at ? new Date(a.created_at).getTime() : Infinity;
    const timeB = b?.created_at ? new Date(b.created_at).getTime() : Infinity;
    return timeA - timeB; // menor timestamp = mais antigo = vem primeiro
  });
}

/**
 * Ordena tarefas recentes: falhas e reprovados primeiro, depois por horário mais recente.
 */
export function sortRecentRuns(runs) {
  if (!Array.isArray(runs)) return [];

  function getPriority(status) {
    const s = String(status || '').toUpperCase();
    if (s === 'FAILED' || s === 'REJECTED') return 1;
    return 2;
  }

  function getTime(r) {
    const t = r?.created_at || r?.finished_at;
    if (!t) return 0;
    const ms = new Date(t).getTime();
    return isNaN(ms) ? 0 : ms;
  }

  return [...runs].sort((a, b) => {
    const prioA = getPriority(a?.status);
    const prioB = getPriority(b?.status);
    if (prioA !== prioB) {
      return prioA - prioB; // 1 vem antes de 2
    }
    return getTime(b) - getTime(a); // mais recente primeiro
  });
}

/**
 * Filtra canais por profile_id selecionado.
 */
export function filterByChannel(channels, selectedProfileId) {
  if (!Array.isArray(channels)) return [];
  if (!selectedProfileId || selectedProfileId === 'all') {
    return channels;
  }
  return channels.filter((c) => c.profile_id === selectedProfileId);
}

/**
 * Retorna mensagem "Mostrando X de Y" quando items < total.
 */
export function formatShowingCount(count, total) {
  const c = Number(count || 0);
  const t = Number(total || 0);
  if (t > 0 && c < t) {
    return `Mostrando ${c} de ${t}`;
  }
  return '';
}

/**
 * Agrega itens de uma seção específica ('ready_stock' | 'scheduled' | 'recent_runs')
 * a partir de uma lista de canais, enriquecendo cada item com channel_name e profile_id.
 */
export function getAggregatedSectionData(channels, sectionKey) {
  if (!Array.isArray(channels)) return { items: [], total: 0 };
  let total = 0;
  const items = [];
  for (const ch of channels) {
    const sec = ch[sectionKey];
    if (sec) {
      total += Number(sec.total || 0);
      if (Array.isArray(sec.items)) {
        for (const item of sec.items) {
          items.push({
            ...item,
            channel_name: ch.channel_name || ch.profile_name || ch.profile_id,
            profile_id: ch.profile_id,
          });
        }
      }
    }
  }
  return { items, total };
}
