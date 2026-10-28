import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  sortDiagnosesBySeverity,
  formatTimeAgo,
  getStatusBadgeInfo,
  getSeverityBadgeInfo,
  formatOutcome,
  formatSafeValue,
  calculateFactorySummary,
  formatLimits,
  getAutonomousSwitchBadge,
} from '../components/Diagnostics/diagnosticsLogic.js';

test('sortDiagnosesBySeverity: ordena estritamente critical > warning > info', () => {
  const input = [
    { code: 'D1', severity: 'info' },
    { code: 'D2', severity: 'critical' },
    { code: 'D3', severity: 'warning' },
    { code: 'D4', severity: 'info' },
    { code: 'D5', severity: 'critical' },
  ];

  const sorted = sortDiagnosesBySeverity(input);
  assert.equal(sorted.length, 5);
  assert.equal(sorted[0].code, 'D2');
  assert.equal(sorted[1].code, 'D5');
  assert.equal(sorted[2].code, 'D3');
  assert.equal(sorted[3].code, 'D1');
  assert.equal(sorted[4].code, 'D4');
});

test('sortDiagnosesBySeverity: trata entradas nulas ou vazias graciosamente', () => {
  assert.deepEqual(sortDiagnosesBySeverity(null), []);
  assert.deepEqual(sortDiagnosesBySeverity([]), []);
});

test('formatTimeAgo: formata intervalos em pt-BR corretamente', () => {
  const base = new Date('2026-10-27T16:00:00Z');

  // Menos de 1 min
  const justNow = new Date('2026-10-27T15:59:30Z').toISOString();
  assert.equal(formatTimeAgo(justNow, base), 'há menos de 1 min');

  // Minutos
  const min15 = new Date('2026-10-27T15:45:00Z').toISOString();
  assert.equal(formatTimeAgo(min15, base), 'há 15 min');

  // Horas
  const hours2 = new Date('2026-10-27T14:00:00Z').toISOString();
  assert.equal(formatTimeAgo(hours2, base), 'há 2h');

  // Horas e minutos
  const hours3min20 = new Date('2026-10-27T12:40:00Z').toISOString();
  assert.equal(formatTimeAgo(hours3min20, base), 'há 3h 20m');

  // Dias
  const days2 = new Date('2026-10-25T16:00:00Z').toISOString();
  assert.equal(formatTimeAgo(days2, base), 'há 2d');

  // Nulo ou inválido
  assert.equal(formatTimeAgo(null, base), '—');
  assert.equal(formatTimeAgo('invalid-date', base), '—');
});

test('getStatusBadgeInfo: retorna rótulo, ícone e cores corretas para cada status', () => {
  const ok = getStatusBadgeInfo('OK');
  assert.equal(ok.label, 'Normal');
  assert.equal(ok.color, '#10b981');

  const atencao = getStatusBadgeInfo('ATENCAO');
  assert.equal(atencao.label, 'Atenção');
  assert.equal(atencao.color, '#f59e0b');

  const parado = getStatusBadgeInfo('PARADO');
  assert.equal(parado.label, 'Parado');
  assert.equal(parado.color, '#ef4444');

  const pausado = getStatusBadgeInfo('PAUSADO');
  assert.equal(pausado.label, 'Pausado');
  assert.equal(pausado.color, '#94a3b8');

  const unknown = getStatusBadgeInfo('UNKNOWN');
  assert.equal(unknown.label, 'Desconhecido');
});

test('getSeverityBadgeInfo: info NUNCA aparece como alerta (isAlert=false)', () => {
  const info = getSeverityBadgeInfo('info');
  assert.equal(info.isAlert, false, 'info não pode ser classificado como alerta');
  assert.equal(info.label, 'Informação');

  const warning = getSeverityBadgeInfo('warning');
  assert.equal(warning.isAlert, true);
  assert.equal(warning.label, 'Alerta');

  const critical = getSeverityBadgeInfo('critical');
  assert.equal(critical.isAlert, true);
  assert.equal(critical.label, 'Crítico');
});

test('formatOutcome: retorna ícones e labels corretos', () => {
  assert.equal(formatOutcome('APPROVED').label, 'Aprovado');
  assert.equal(formatOutcome('REJECTED').label, 'Reprovado');
  assert.equal(formatOutcome('INTERRUPTED').label, 'Interrompido');
  assert.equal(formatOutcome('FAILED').label, 'Falhou');
  assert.equal(formatOutcome('RUNNING').label, 'Em execução');
  assert.equal(formatOutcome(null).label, 'Desconhecido');
});

test('formatSafeValue: null/UNKNOWN exibidos como "—" ou "desconhecido"', () => {
  assert.equal(formatSafeValue(null), '—');
  assert.equal(formatSafeValue(undefined), '—');
  assert.equal(formatSafeValue(''), '—');
  assert.equal(formatSafeValue('UNKNOWN'), 'desconhecido');
  assert.equal(formatSafeValue('unknown'), 'desconhecido');
  assert.equal(formatSafeValue('10'), '10');
  assert.equal(formatSafeValue('Brian'), 'Brian');
});

test('calculateFactorySummary: totaliza corretamente canais e severidades', () => {
  const channels = [
    { status: 'OK', diagnoses: [{ severity: 'info' }] },
    { status: 'ATENCAO', diagnoses: [{ severity: 'warning' }] },
    { status: 'PARADO', diagnoses: [{ severity: 'critical' }, { severity: 'warning' }] },
    { status: 'PAUSADO', diagnoses: [] },
  ];

  const summary = calculateFactorySummary(channels);
  assert.equal(summary.total, 4);
  assert.equal(summary.ok, 1);
  assert.equal(summary.atencao, 1);
  assert.equal(summary.parado, 1);
  assert.equal(summary.pausado, 1);
  assert.equal(summary.criticalCount, 1);
  assert.equal(summary.warningCount, 2);
});

test('formatLimits: formata valores nulos com "—" e preserva valores preenchidos', () => {
  // Limites vazios / nulos
  const emptyRes = formatLimits(null);
  assert.equal(emptyRes.approvedText, '— / —');
  assert.equal(emptyRes.attemptsText, '— / —');
  assert.equal(emptyRes.rejectionsText, '— / —');
  assert.equal(emptyRes.growthMode, '—');
  assert.equal(emptyRes.isAutonomousDisabled, false);

  // Limites preenchidos (caso Quiz 10/10)
  const fullRes = formatLimits({
    growth_mode: 'scale',
    autonomous_enabled: true,
    approved_24h: { used: 10, cap: 10 },
    attempts_24h: { used: 15, cap: 30 },
    consecutive_rejections: { used: 2, limit: 10 },
  });
  assert.equal(fullRes.approvedText, '10 / 10');
  assert.equal(fullRes.attemptsText, '15 / 30');
  assert.equal(fullRes.rejectionsText, '2 / 10');
  assert.equal(fullRes.growthMode, 'SCALE');
  assert.equal(fullRes.isAutonomousEnabled, true);
  assert.equal(fullRes.isAutonomousDisabled, false);

  // Canal desligado
  const offRes = formatLimits({
    autonomous_enabled: false,
    growth_mode: 'warmup',
  });
  assert.equal(offRes.isAutonomousDisabled, true);
});

test('getAutonomousSwitchBadge: retorna selo Desligado para false e Ativo para true', () => {
  const off = getAutonomousSwitchBadge(false);
  assert.equal(off.label, 'Desligado');
  assert.equal(off.isOff, true);

  const on = getAutonomousSwitchBadge(true);
  assert.equal(on.label, 'Ativo');
  assert.equal(on.isOff, false);

  const unknown = getAutonomousSwitchBadge(null);
  assert.equal(unknown.label, '—');
  assert.equal(unknown.isOff, false);
});

test('getSeverityBadgeInfo: severidade info nunca é classificada como alerta (isAlert=false)', () => {
  const infoBadge = getSeverityBadgeInfo('info');
  assert.equal(infoBadge.isAlert, false, 'Diagnóstico info não pode disparar alerta visual');

  const warningBadge = getSeverityBadgeInfo('warning');
  assert.equal(warningBadge.isAlert, true);

  const criticalBadge = getSeverityBadgeInfo('critical');
  assert.equal(criticalBadge.isAlert, true);
});

