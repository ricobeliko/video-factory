import test from 'node:test';
import assert from 'node:assert';
import {
  formatAgeHours,
  formatDuration,
  formatCopyrightStatus,
  formatRunStatus,
  formatStage,
  formatScheduledStatus,
  sortReadyStock,
  sortRecentRuns,
  filterByChannel,
  formatShowingCount,
  getAggregatedSectionData,
} from '../components/Production/productionLogic.js';

test('1. formatAgeHours: formata horas em string legível e trata nulos', () => {
  assert.strictEqual(formatAgeHours(2), '2 h');
  assert.strictEqual(formatAgeHours(27), '1 d 3 h');
  assert.strictEqual(formatAgeHours(48), '2 d');
  assert.strictEqual(formatAgeHours(0.5), '< 1 h');
  assert.strictEqual(formatAgeHours(null), '—');
  assert.strictEqual(formatAgeHours(undefined), '—');
  assert.strictEqual(formatAgeHours(-1), '—');
  assert.strictEqual(formatAgeHours('invalid'), '—');
});

test('2. sortReadyStock: ordena pelo mais antigo primeiro (maior age_hours ou menor timestamp)', () => {
  const items = [
    { task_id: 't-new', age_hours: 1.5, created_at: '2026-10-26T14:00:00Z' },
    { task_id: 't-oldest', age_hours: 48.0, created_at: '2026-10-24T12:00:00Z' },
    { task_id: 't-middle', age_hours: 12.0, created_at: '2026-10-26T03:00:00Z' },
  ];

  const sorted = sortReadyStock(items);
  assert.strictEqual(sorted[0].task_id, 't-oldest');
  assert.strictEqual(sorted[1].task_id, 't-middle');
  assert.strictEqual(sorted[2].task_id, 't-new');
});

test('3. sortRecentRuns: falhas e reprovados primeiro, depois mais recentes', () => {
  const runs = [
    { task_id: 't-succ-recent', status: 'SUCCESS', created_at: '2026-10-26T15:00:00Z' },
    { task_id: 't-fail-old', status: 'FAILED', created_at: '2026-10-26T10:00:00Z' },
    { task_id: 't-rej-new', status: 'REJECTED', created_at: '2026-10-26T14:00:00Z' },
    { task_id: 't-run-now', status: 'RUNNING', created_at: '2026-10-26T15:30:00Z' },
  ];

  const sorted = sortRecentRuns(runs);
  // Prioridade 1: FAILED / REJECTED (t-rej-new às 14h, t-fail-old às 10h)
  assert.strictEqual(sorted[0].task_id, 't-rej-new');
  assert.strictEqual(sorted[1].task_id, 't-fail-old');
  // Prioridade 2: demais ordenados por horário decrescente (t-run-now às 15:30, t-succ-recent às 15:00)
  assert.strictEqual(sorted[2].task_id, 't-run-now');
  assert.strictEqual(sorted[3].task_id, 't-succ-recent');
});

test('4. formatRunStatus: mapeia status conhecidos e desconhecido para rótulo em português', () => {
  assert.strictEqual(formatRunStatus('SUCCESS').label, 'Sucesso');
  assert.strictEqual(formatRunStatus('FAILED').label, 'Falha');
  assert.strictEqual(formatRunStatus('REJECTED').label, 'Reprovado');
  assert.strictEqual(formatRunStatus('RUNNING').label, 'Em execução');
  assert.strictEqual(formatRunStatus('UNKNOWN').label, 'Desconhecido');
  assert.strictEqual(formatRunStatus('ANYTHING_ELSE').label, 'desconhecido');
  assert.strictEqual(formatRunStatus(null).label, 'desconhecido');
});

test('5. formatCopyrightStatus: null retorna "não verificado" neutro (nunca OK)', () => {
  const nullStatus = formatCopyrightStatus(null);
  assert.strictEqual(nullStatus.label, 'não verificado');
  assert.strictEqual(nullStatus.key, 'unverified');

  const emptyStatus = formatCopyrightStatus('');
  assert.strictEqual(emptyStatus.label, 'não verificado');

  const passStatus = formatCopyrightStatus('PASS');
  assert.strictEqual(passStatus.label, 'aprovado');
  assert.strictEqual(passStatus.color, '#34D399');

  const failStatus = formatCopyrightStatus('FAIL');
  assert.strictEqual(failStatus.label, 'bloqueado');
  assert.strictEqual(failStatus.color, '#FF8A7A');

  const blockStatus = formatCopyrightStatus('BLOCK');
  assert.strictEqual(blockStatus.label, 'bloqueado');
});

test('6. filterByChannel: filtra por profile_id e "all" retorna todos', () => {
  const channels = [
    { profile_id: 'default', channel_name: 'Principal' },
    { profile_id: 'prof-quiz', channel_name: 'Quiz' },
    { profile_id: 'prof-curiosidades', channel_name: 'Curiosidades' },
  ];

  assert.strictEqual(filterByChannel(channels, 'all').length, 3);
  assert.strictEqual(filterByChannel(channels, null).length, 3);

  const filtered = filterByChannel(channels, 'prof-quiz');
  assert.strictEqual(filtered.length, 1);
  assert.strictEqual(filtered[0].channel_name, 'Quiz');
});

test('7. formatShowingCount: mostra "Mostrando X de Y" quando items < total', () => {
  assert.strictEqual(formatShowingCount(10, 50), 'Mostrando 10 de 50');
  assert.strictEqual(formatShowingCount(20, 20), '');
  assert.strictEqual(formatShowingCount(50, 20), '');
  assert.strictEqual(formatShowingCount(0, 0), '');
  assert.strictEqual(formatShowingCount(null, null), '');
});

test('8. getAggregatedSectionData: agrega seções enriquecendo itens com canal', () => {
  const channels = [
    {
      profile_id: 'default',
      channel_name: 'Canal 1',
      ready_stock: {
        total: 2,
        items: [{ task_id: 't-1' }, { task_id: 't-2' }],
      },
    },
    {
      profile_id: 'prof-2',
      channel_name: 'Canal 2',
      ready_stock: {
        total: 1,
        items: [{ task_id: 't-3' }],
      },
    },
  ];

  const agg = getAggregatedSectionData(channels, 'ready_stock');
  assert.strictEqual(agg.total, 3);
  assert.strictEqual(agg.items.length, 3);
  assert.strictEqual(agg.items[0].channel_name, 'Canal 1');
  assert.strictEqual(agg.items[2].channel_name, 'Canal 2');
});
