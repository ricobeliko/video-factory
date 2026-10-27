/**
 * diagnosticsLogic.js — Lógica pura e determinística da tela Diagnóstico (Missão SIS3).
 * 
 * Regras:
 * - Sem efeitos colaterais, sem mutação de estado.
 * - Testável via node --test.
 * - Nunca inventa dados na tela: null/UNKNOWN exibidos como '—' ou 'desconhecido'.
 * - info não aparece como alerta (apenas critical e warning).
 */

export const SEVERITY_ORDER = {
  critical: 0,
  warning: 1,
  info: 2,
};

/**
 * Ordena lista de diagnósticos por gravidade: critical > warning > info.
 */
export function sortDiagnosesBySeverity(diagnoses) {
  if (!Array.isArray(diagnoses)) return [];
  return [...diagnoses].sort((a, b) => {
    const weightA = SEVERITY_ORDER[a?.severity] ?? 99;
    const weightB = SEVERITY_ORDER[b?.severity] ?? 99;
    return weightA - weightB;
  });
}

/**
 * Calcula 'há X' amigável em pt-BR a partir de uma data ISO UTC.
 * @param {string|null} isoString
 * @param {Date} [now]
 * @returns {string}
 */
export function formatTimeAgo(isoString, now = new Date()) {
  if (!isoString) return '—';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '—';

  const diffMs = now.getTime() - d.getTime();
  if (diffMs < 0) return 'agora';

  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) {
    return 'há menos de 1 min';
  }

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) {
    return `há ${diffMin} min`;
  }

  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) {
    const remMin = diffMin % 60;
    if (remMin > 0 && diffHours < 6) {
      return `há ${diffHours}h ${remMin}m`;
    }
    return `há ${diffHours}h`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return `há ${diffDays}d`;
}

/**
 * Retorna dados visuais para o selo de status do canal.
 * @param {string} status
 */
export function getStatusBadgeInfo(status) {
  const norm = String(status || '').toUpperCase().trim();
  switch (norm) {
    case 'OK':
      return {
        label: 'Normal',
        icon: '✓',
        color: '#10b981',
        bg: 'rgba(16, 185, 129, 0.12)',
        border: 'rgba(16, 185, 129, 0.35)',
      };
    case 'ATENCAO':
      return {
        label: 'Atenção',
        icon: '⚠',
        color: '#f59e0b',
        bg: 'rgba(245, 158, 11, 0.12)',
        border: 'rgba(245, 158, 11, 0.35)',
      };
    case 'PARADO':
      return {
        label: 'Parado',
        icon: '⏹',
        color: '#ef4444',
        bg: 'rgba(239, 68, 68, 0.14)',
        border: 'rgba(239, 68, 68, 0.4)',
      };
    case 'PAUSADO':
      return {
        label: 'Pausado',
        icon: '⏸',
        color: '#94a3b8',
        bg: 'rgba(148, 163, 184, 0.12)',
        border: 'rgba(148, 163, 184, 0.3)',
      };
    default:
      return {
        label: 'Desconhecido',
        icon: '?',
        color: '#64748b',
        bg: 'rgba(100, 116, 139, 0.12)',
        border: 'rgba(100, 116, 139, 0.25)',
      };
  }
}

/**
 * Retorna dados visuais para a severidade de um diagnóstico.
 * @param {string} severity
 */
export function getSeverityBadgeInfo(severity) {
  const norm = String(severity || '').toLowerCase().trim();
  switch (norm) {
    case 'critical':
      return {
        label: 'Crítico',
        isAlert: true,
        icon: '🚨',
        color: '#ef4444',
        bg: 'rgba(239, 68, 68, 0.12)',
        border: 'rgba(239, 68, 68, 0.35)',
      };
    case 'warning':
      return {
        label: 'Alerta',
        isAlert: true,
        icon: '⚠️',
        color: '#f59e0b',
        bg: 'rgba(245, 158, 11, 0.12)',
        border: 'rgba(245, 158, 11, 0.35)',
      };
    case 'info':
    default:
      return {
        label: 'Informação',
        isAlert: false, // info NUNCA aparece como alerta
        icon: 'ℹ️',
        color: '#38bdf8',
        bg: 'rgba(56, 189, 248, 0.1)',
        border: 'rgba(56, 189, 248, 0.25)',
      };
  }
}

/**
 * Formata desfecho de geração com ícone e cor.
 * @param {string} outcome
 */
export function formatOutcome(outcome) {
  const norm = String(outcome || '').toUpperCase().trim();
  switch (norm) {
    case 'APPROVED':
      return { label: 'Aprovado', icon: '✓', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' };
    case 'REJECTED':
      return { label: 'Reprovado', icon: '✕', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' };
    case 'INTERRUPTED':
      return { label: 'Interrompido', icon: '⚡', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' };
    case 'FAILED':
      return { label: 'Falhou', icon: '✖', color: '#f87171', bg: 'rgba(248, 113, 113, 0.15)' };
    case 'RUNNING':
      return { label: 'Em execução', icon: '▶', color: '#38bdf8', bg: 'rgba(56, 189, 248, 0.15)' };
    default:
      return { label: 'Desconhecido', icon: '—', color: '#64748b', bg: 'rgba(100, 116, 139, 0.15)' };
  }
}

/**
 * Exibe valor seguro sem inventar dados: null/undefined/UNKNOWN viram '—' ou 'desconhecido'.
 * @param {any} val
 * @param {string} [fallback]
 */
export function formatSafeValue(val, fallback = '—') {
  if (val === null || val === undefined || val === '') return fallback;
  if (typeof val === 'string' && val.trim().toUpperCase() === 'UNKNOWN') {
    return 'desconhecido';
  }
  return String(val);
}

/**
 * Calcula totais agregados para o resumo da fábrica no topo da tela.
 * @param {Array} channels
 */
export function calculateFactorySummary(channels) {
  if (!Array.isArray(channels)) {
    return { total: 0, ok: 0, atencao: 0, parado: 0, pausado: 0, criticalCount: 0, warningCount: 0 };
  }

  let ok = 0;
  let atencao = 0;
  let parado = 0;
  let pausado = 0;
  let criticalCount = 0;
  let warningCount = 0;

  for (const c of channels) {
    const st = String(c?.status || '').toUpperCase().trim();
    if (st === 'OK') ok++;
    else if (st === 'ATENCAO') atencao++;
    else if (st === 'PARADO') parado++;
    else if (st === 'PAUSADO') pausado++;

    const diags = Array.isArray(c?.diagnoses) ? c.diagnoses : [];
    for (const d of diags) {
      if (d?.severity === 'critical') criticalCount++;
      else if (d?.severity === 'warning') warningCount++;
    }
  }

  return {
    total: channels.length,
    ok,
    atencao,
    parado,
    pausado,
    criticalCount,
    warningCount,
  };
}
