/**
 * stageVisuals.js — Centralized semantic theme, personas, and stage metadata for Factory Live.
 * FASE R6A.5:
 * - Rich tonal fill and unique visual identity per stage.
 * - Tech-Factory Avatar / Persona system for autonomous agents.
 * - State-aware connection edge semantics (running, completed, blocked, failed, dimmed).
 * - Zero hardcoding in JSX components.
 */

export const STAGE_DEFINITIONS = [
  {
    step: 1,
    code: 'TOPIC',
    label: 'Tema / Pauta',
    icon: '💡',
    category: 'editorial',
    categoryLabel: 'Pauta',
    accentColor: '#6366f1',
    tonalBg: 'rgba(99, 102, 241, 0.16)',
    tonalBorder: 'rgba(99, 102, 241, 0.45)',
    persona: {
      code: 'Scout-01',
      name: 'Scout',
      role: 'Radar de Tendências',
      avatar: '🧭',
      badge: 'IDEATOR',
      bio: 'Varredor de nichos e formulador de temas de alta retenção.',
    },
  },
  {
    step: 2,
    code: 'SCRIPT',
    label: 'Roteiro',
    icon: '📝',
    category: 'editorial',
    categoryLabel: 'Roteiro',
    accentColor: '#8b5cf6',
    tonalBg: 'rgba(139, 92, 246, 0.16)',
    tonalBorder: 'rgba(139, 92, 246, 0.45)',
    persona: {
      code: 'Scribe-02',
      name: 'Scribe',
      role: 'Roteirista Algorítmico',
      avatar: '🖋️',
      badge: 'WRITER',
      bio: 'Estruturação narrativa, ganchos nos primeiros 3s e pacing rítmico.',
    },
  },
  {
    step: 3,
    code: 'NARRATION',
    label: 'Narração',
    icon: '🎙️',
    category: 'audio',
    categoryLabel: 'Voz',
    accentColor: '#c084fc',
    tonalBg: 'rgba(192, 132, 252, 0.16)',
    tonalBorder: 'rgba(192, 132, 252, 0.45)',
    persona: {
      code: 'Vocal-03',
      name: 'Vocal',
      role: 'Sintetizador de Voz',
      avatar: '🎧',
      badge: 'VOICE',
      bio: 'Síntese de voz neural Edge/TTS com prosódia calibrada e clareza acústica.',
    },
  },
  {
    step: 4,
    code: 'VISUALS',
    label: 'Visuais / Clipes',
    icon: '🎬',
    category: 'visuals',
    categoryLabel: 'Clipes Flow',
    accentColor: '#38bdf8',
    tonalBg: 'rgba(56, 189, 248, 0.16)',
    tonalBorder: 'rgba(56, 189, 248, 0.45)',
    persona: {
      code: 'Cine-04',
      name: 'Cine',
      role: 'Diretor Visual Flow',
      avatar: '🎥',
      badge: 'DIRECTOR',
      bio: 'Composição de prompts cinematográficos e geração via Google Flow pool.',
    },
  },
  {
    step: 5,
    code: 'RENDER',
    label: 'Renderização',
    icon: '⚡',
    category: 'visuals',
    categoryLabel: 'GPU Render',
    accentColor: '#0ea5e9',
    tonalBg: 'rgba(14, 165, 233, 0.16)',
    tonalBorder: 'rgba(14, 165, 233, 0.45)',
    persona: {
      code: 'Forge-05',
      name: 'Forge',
      role: 'Motor de Render GPU',
      avatar: '⚙️',
      badge: 'FOUNDRY',
      bio: 'Pipeline FFmpeg acelerado, composição multitrack e sincronia de legendas.',
    },
  },
  {
    step: 6,
    code: 'SAFETY',
    label: 'Safety Gate',
    icon: '🛡️',
    category: 'gates',
    categoryLabel: 'Segurança',
    accentColor: '#f59e0b',
    tonalBg: 'rgba(245, 158, 11, 0.16)',
    tonalBorder: 'rgba(245, 158, 11, 0.45)',
    persona: {
      code: 'Sentinel-06',
      name: 'Sentinel',
      role: 'Guardião de Políticas',
      avatar: '🛡️',
      badge: 'SAFETY',
      bio: 'Inspeção de conformidade de termos sensíveis, políticas e diretrizes.',
    },
  },
  {
    step: 7,
    code: 'QUALITY',
    label: 'Quality Gate',
    icon: '✨',
    category: 'gates',
    categoryLabel: 'Qualidade',
    accentColor: '#10b981',
    tonalBg: 'rgba(16, 185, 129, 0.16)',
    tonalBorder: 'rgba(16, 185, 129, 0.45)',
    persona: {
      code: 'Auditor-07',
      name: 'Auditor',
      role: 'Avaliador de Retenção',
      avatar: '💎',
      badge: 'QUALITY',
      bio: 'Auditoria algorítmica de retenção e score técnico (threshold 70.0).',
    },
  },
  {
    step: 8,
    code: 'COPYRIGHT',
    label: 'Copyright Gate',
    icon: '⚖️',
    category: 'gates',
    categoryLabel: 'Copyright',
    accentColor: '#d97706',
    tonalBg: 'rgba(217, 119, 6, 0.16)',
    tonalBorder: 'rgba(217, 119, 6, 0.45)',
    persona: {
      code: 'Notary-08',
      name: 'Notary',
      role: 'Custodiante de Autoria',
      avatar: '📜',
      badge: 'NOTARY',
      bio: 'Verificação de proveniência de mídia, hashes SHA-256 e licenças originais.',
    },
  },
  {
    step: 9,
    code: 'READY_STOCK',
    label: 'Estoque Pronto',
    icon: '📦',
    category: 'distribution',
    categoryLabel: 'Estoque',
    accentColor: '#06b6d4',
    tonalBg: 'rgba(6, 182, 212, 0.16)',
    tonalBorder: 'rgba(6, 182, 212, 0.45)',
    persona: {
      code: 'Vault-09',
      name: 'Vault',
      role: 'Guarda-Estoque',
      avatar: '🗄️',
      badge: 'VAULT',
      bio: 'Armazenamento de vídeos finalizados aprovados aguardando janela de agendamento.',
    },
  },
  {
    step: 10,
    code: 'SCHEDULER',
    label: 'Agendamento',
    icon: '📅',
    category: 'distribution',
    categoryLabel: 'Agenda',
    accentColor: '#6366f1',
    tonalBg: 'rgba(99, 102, 241, 0.16)',
    tonalBorder: 'rgba(99, 102, 241, 0.45)',
    persona: {
      code: 'Chronos-10',
      name: 'Chronos',
      role: 'Despachante Temporal',
      avatar: '⏱️',
      badge: 'PLANNER',
      bio: 'Cálculo de slots horários ótimos por nicho respeitando cooldowns.',
    },
  },
  {
    step: 11,
    code: 'PUBLISHER',
    label: 'Publicação',
    icon: '🚀',
    category: 'publishing',
    categoryLabel: 'Upload',
    accentColor: '#ec4899',
    tonalBg: 'rgba(236, 72, 153, 0.16)',
    tonalBorder: 'rgba(236, 72, 153, 0.45)',
    persona: {
      code: 'Relay-11',
      name: 'Relay',
      role: 'Transmissor Multi-Rede',
      avatar: '🛰️',
      badge: 'UPLINK',
      bio: 'Despacho seguro para orquestrador de publicação Post For Me.',
    },
  },
  {
    step: 12,
    code: 'YOUTUBE',
    label: 'YouTube',
    icon: '▶️',
    category: 'publishing',
    categoryLabel: 'YouTube',
    accentColor: '#ef4444',
    tonalBg: 'rgba(239, 68, 68, 0.16)',
    tonalBorder: 'rgba(239, 68, 68, 0.45)',
    persona: {
      code: 'Herald-12',
      name: 'Herald',
      role: 'Embaixador do Canal',
      avatar: '📺',
      badge: 'BROADCAST',
      bio: 'Confirmação terminal de publicação ao vivo e rastreabilidade da URL final.',
    },
  },
];

export const STAGE_BY_CODE = STAGE_DEFINITIONS.reduce((acc, stage) => {
  acc[stage.code] = stage;
  return acc;
}, {});

export const STATUS_THEME = {
  IDLE: {
    label: 'IDLE',
    color: '#94a3b8',
    bgColor: 'rgba(71, 85, 105, 0.18)',
    borderColor: '#334155',
    dotColor: '#64748b',
  },
  WAITING: {
    label: 'WAITING',
    color: '#60a5fa',
    bgColor: 'rgba(59, 130, 246, 0.18)',
    borderColor: 'rgba(59, 130, 246, 0.45)',
    dotColor: '#3b82f6',
  },
  QUEUED: {
    label: 'QUEUED',
    color: '#60a5fa',
    bgColor: 'rgba(59, 130, 246, 0.18)',
    borderColor: 'rgba(59, 130, 246, 0.45)',
    dotColor: '#3b82f6',
  },
  RUNNING: {
    label: 'RUNNING',
    color: '#38bdf8',
    bgColor: 'rgba(14, 165, 233, 0.22)',
    borderColor: '#0284c7',
    dotColor: '#0ea5e9',
  },
  PROCESSING: {
    label: 'PROCESSING',
    color: '#38bdf8',
    bgColor: 'rgba(14, 165, 233, 0.22)',
    borderColor: '#0284c7',
    dotColor: '#0ea5e9',
  },
  SUCCESS: {
    label: 'SUCCESS',
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.18)',
    borderColor: 'rgba(16, 185, 129, 0.55)',
    dotColor: '#10b981',
  },
  COMPLETE: {
    label: 'COMPLETE',
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.18)',
    borderColor: 'rgba(16, 185, 129, 0.55)',
    dotColor: '#10b981',
  },
  SCHEDULED: {
    label: 'SCHEDULED',
    color: '#a5b4fc',
    bgColor: 'rgba(99, 102, 241, 0.18)',
    borderColor: 'rgba(99, 102, 241, 0.5)',
    dotColor: '#6366f1',
  },
  RETRY: {
    label: 'RETRY',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.2)',
    borderColor: 'rgba(249, 115, 22, 0.55)',
    dotColor: '#f97316',
  },
  RETRYING: {
    label: 'RETRYING',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.2)',
    borderColor: 'rgba(249, 115, 22, 0.55)',
    dotColor: '#f97316',
  },
  COOLDOWN: {
    label: 'COOLDOWN',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.2)',
    borderColor: 'rgba(249, 115, 22, 0.55)',
    dotColor: '#f97316',
  },
  BLOCKED: {
    label: 'BLOCKED',
    color: '#fbbf24',
    bgColor: 'rgba(245, 158, 11, 0.2)',
    borderColor: 'rgba(245, 158, 11, 0.55)',
    dotColor: '#f59e0b',
  },
  FAILED: {
    label: 'FAILED',
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.2)',
    borderColor: 'rgba(239, 68, 68, 0.6)',
    dotColor: '#ef4444',
  },
  PENDING: {
    label: 'PENDING',
    color: '#64748b',
    bgColor: 'rgba(100, 116, 139, 0.10)',
    borderColor: '#1e293b',
    dotColor: '#475569',
  },
};

export function getStatusStyle(status) {
  return STATUS_THEME[status] || STATUS_THEME.PENDING;
}

/**
 * Edge state semantics helper for Factory Live flow (R6A.5 requirement 4):
 * - Dimmed / apagado = not reached / future
 * - Pulsing = running / in-flight
 * - Green = completed
 * - Amber = waiting / blocked
 * - Red = failure
 */
export function getEdgeSemantics(fromStatus, toStatus) {
  const isFromDone = fromStatus === 'SUCCESS' || fromStatus === 'COMPLETE';
  const isToDone = toStatus === 'SUCCESS' || toStatus === 'COMPLETE';
  const isToRunning = toStatus === 'RUNNING' || toStatus === 'PROCESSING';
  const isFromRunning = fromStatus === 'RUNNING' || fromStatus === 'PROCESSING';

  if (isFromDone && isToDone) {
    return {
      type: 'completed',
      stroke: '#10b981',
      strokeWidth: 2,
      animated: false,
      markerColor: '#10b981',
      strokeDasharray: undefined,
      className: 'edge-completed',
    };
  }

  if ((isFromDone && isToRunning) || (isFromRunning && toStatus === 'RUNNING')) {
    return {
      type: 'running',
      stroke: '#38bdf8',
      strokeWidth: 2.5,
      animated: true,
      markerColor: '#38bdf8',
      strokeDasharray: undefined,
      className: 'edge-running active-edge',
    };
  }

  if (fromStatus === 'BLOCKED' || toStatus === 'BLOCKED') {
    return {
      type: 'blocked',
      stroke: '#f59e0b',
      strokeWidth: 2,
      animated: false,
      markerColor: '#f59e0b',
      strokeDasharray: '4 4',
      className: 'edge-blocked',
    };
  }

  if (fromStatus === 'FAILED' || toStatus === 'FAILED') {
    return {
      type: 'failed',
      stroke: '#ef4444',
      strokeWidth: 2,
      animated: false,
      markerColor: '#ef4444',
      strokeDasharray: undefined,
      className: 'edge-failed',
    };
  }

  if (toStatus === 'RETRY' || toStatus === 'RETRYING' || fromStatus === 'RETRY' || fromStatus === 'RETRYING') {
    return {
      type: 'retry',
      stroke: '#f97316',
      strokeWidth: 2.5,
      animated: true,
      markerColor: '#f97316',
      strokeDasharray: '6 3',
      className: 'edge-retry active-edge',
    };
  }

  if (isFromDone && toStatus === 'SCHEDULED') {
    return {
      type: 'scheduled',
      stroke: '#a5b4fc',
      strokeWidth: 2,
      animated: false,
      markerColor: '#a5b4fc',
      strokeDasharray: '4 4',
      className: 'edge-scheduled',
    };
  }

  if (isFromDone && (toStatus === 'WAITING' || toStatus === 'QUEUED')) {
    return {
      type: 'waiting',
      stroke: '#60a5fa',
      strokeWidth: 2,
      animated: false,
      markerColor: '#60a5fa',
      strokeDasharray: '3 3',
      className: 'edge-waiting',
    };
  }

  // Dimmed / Not reached
  return {
    type: 'dimmed',
    stroke: '#334155',
    strokeWidth: 1.5,
    animated: false,
    markerColor: '#475569',
    strokeDasharray: '3 3',
    className: 'edge-dimmed',
  };
}
