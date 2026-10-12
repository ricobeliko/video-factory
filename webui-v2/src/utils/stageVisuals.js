/**
 * stageVisuals.js — Centralized semantic theme and stage metadata for Factory Live.
 * Adheres to R6A.3 requirements:
 * - Status is the primary visual driver.
 * - Subtle category differentiation by stage (icons, category labels, subtle accents).
 * - Zero hardcoding in JSX components.
 */

export const STAGE_DEFINITIONS = [
  { step: 1, code: 'TOPIC', label: 'Tema / Pauta', icon: '💡', category: 'editorial', categoryLabel: 'Pauta', accentColor: '#818cf8' },
  { step: 2, code: 'SCRIPT', label: 'Roteiro', icon: '📝', category: 'editorial', categoryLabel: 'Roteiro', accentColor: '#a78bfa' },
  { step: 3, code: 'NARRATION', label: 'Narração', icon: '🎙️', category: 'audio', categoryLabel: 'Voz', accentColor: '#c084fc' },
  { step: 4, code: 'VISUALS', label: 'Visuais / Clipes', icon: '🎬', category: 'visuals', categoryLabel: 'Clipes', accentColor: '#38bdf8' },
  { step: 5, code: 'RENDER', label: 'Renderização', icon: '⚡', category: 'visuals', categoryLabel: 'Render', accentColor: '#0ea5e9' },
  { step: 6, code: 'SAFETY', label: 'Safety Gate', icon: '🛡️', category: 'gates', categoryLabel: 'Safety', accentColor: '#f59e0b' },
  { step: 7, code: 'QUALITY', label: 'Quality Gate', icon: '✨', category: 'gates', categoryLabel: 'Quality', accentColor: '#10b981' },
  { step: 8, code: 'COPYRIGHT', label: 'Copyright Gate', icon: '©️', category: 'gates', categoryLabel: 'Copyright', accentColor: '#f59e0b' },
  { step: 9, code: 'READY_STOCK', label: 'Estoque Pronto', icon: '📦', category: 'distribution', categoryLabel: 'Estoque', accentColor: '#06b6d4' },
  { step: 10, code: 'SCHEDULER', label: 'Agendamento', icon: '📅', category: 'distribution', categoryLabel: 'Agenda', accentColor: '#6366f1' },
  { step: 11, code: 'PUBLISHER', label: 'Publicação', icon: '🚀', category: 'publishing', categoryLabel: 'Upload', accentColor: '#ec4899' },
  { step: 12, code: 'YOUTUBE', label: 'YouTube', icon: '▶️', category: 'publishing', categoryLabel: 'YouTube', accentColor: '#ef4444' },
];

export const STAGE_BY_CODE = STAGE_DEFINITIONS.reduce((acc, stage) => {
  acc[stage.code] = stage;
  return acc;
}, {});

export const STATUS_THEME = {
  IDLE: {
    label: 'IDLE',
    color: '#94a3b8',
    bgColor: 'rgba(71, 85, 105, 0.14)',
    borderColor: '#334155',
    dotColor: '#64748b',
  },
  WAITING: {
    label: 'WAITING',
    color: '#60a5fa',
    bgColor: 'rgba(59, 130, 246, 0.12)',
    borderColor: 'rgba(59, 130, 246, 0.4)',
    dotColor: '#3b82f6',
  },
  QUEUED: {
    label: 'QUEUED',
    color: '#60a5fa',
    bgColor: 'rgba(59, 130, 246, 0.12)',
    borderColor: 'rgba(59, 130, 246, 0.4)',
    dotColor: '#3b82f6',
  },
  RUNNING: {
    label: 'RUNNING',
    color: '#38bdf8',
    bgColor: 'rgba(14, 165, 233, 0.16)',
    borderColor: '#0284c7',
    dotColor: '#0ea5e9',
  },
  PROCESSING: {
    label: 'PROCESSING',
    color: '#38bdf8',
    bgColor: 'rgba(14, 165, 233, 0.16)',
    borderColor: '#0284c7',
    dotColor: '#0ea5e9',
  },
  SUCCESS: {
    label: 'SUCCESS',
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.12)',
    borderColor: 'rgba(16, 185, 129, 0.5)',
    dotColor: '#10b981',
  },
  COMPLETE: {
    label: 'COMPLETE',
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.12)',
    borderColor: 'rgba(16, 185, 129, 0.5)',
    dotColor: '#10b981',
  },
  SCHEDULED: {
    label: 'SCHEDULED',
    color: '#a5b4fc',
    bgColor: 'rgba(99, 102, 241, 0.14)',
    borderColor: 'rgba(99, 102, 241, 0.45)',
    dotColor: '#6366f1',
  },
  RETRY: {
    label: 'RETRY',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.15)',
    borderColor: 'rgba(249, 115, 22, 0.5)',
    dotColor: '#f97316',
  },
  RETRYING: {
    label: 'RETRYING',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.15)',
    borderColor: 'rgba(249, 115, 22, 0.5)',
    dotColor: '#f97316',
  },
  COOLDOWN: {
    label: 'COOLDOWN',
    color: '#f97316',
    bgColor: 'rgba(249, 115, 22, 0.15)',
    borderColor: 'rgba(249, 115, 22, 0.5)',
    dotColor: '#f97316',
  },
  BLOCKED: {
    label: 'BLOCKED',
    color: '#fbbf24',
    bgColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: 'rgba(245, 158, 11, 0.5)',
    dotColor: '#f59e0b',
  },
  FAILED: {
    label: 'FAILED',
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.16)',
    borderColor: 'rgba(239, 68, 68, 0.55)',
    dotColor: '#ef4444',
  },
  PENDING: {
    label: 'PENDING',
    color: '#64748b',
    bgColor: 'rgba(100, 116, 139, 0.08)',
    borderColor: '#1e293b',
    dotColor: '#475569',
  },
};

export function getStatusStyle(status) {
  return STATUS_THEME[status] || STATUS_THEME.PENDING;
}
