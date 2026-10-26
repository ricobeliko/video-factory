import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatFactoryState,
  formatInstanceRole,
  formatHeartbeat,
  canToggleFactory,
  formatApiError,
  formatProviderValue,
  formatQuotasDisplay,
  formatScheduleDisplay,
} from '../components/System/systemLogic.js';

test('1. formatFactoryState: rotula estados operacionais e de pausa com texto explicito', () => {
  // Estado RUNNING
  const running = formatFactoryState({ factory_state: 'RUNNING', is_paused: false });
  assert.equal(running.label, 'EM OPERAÇÃO');
  assert.equal(running.isPaused, false);
  assert.equal(running.variant, 'running');

  // Estado PAUSED via is_paused
  const pausedByFlag = formatFactoryState({ factory_state: 'RUNNING', is_paused: true });
  assert.equal(pausedByFlag.label, 'PAUSADA');
  assert.equal(pausedByFlag.isPaused, true);
  assert.equal(pausedByFlag.variant, 'paused');

  // Estado PAUSED via factory_state
  const pausedByState = formatFactoryState({ factory_state: 'PAUSED', is_paused: false });
  assert.equal(pausedByState.label, 'PAUSADA');
  assert.equal(pausedByState.isPaused, true);

  // String direta
  assert.equal(formatFactoryState('RUNNING').label, 'EM OPERAÇÃO');
  assert.equal(formatFactoryState('PAUSED').label, 'PAUSADA');

  // Estados degradado e erro
  const degraded = formatFactoryState({ factory_state: 'DEGRADED', is_paused: false });
  assert.equal(degraded.label, 'EM OPERAÇÃO (DEGRADADA)');
  assert.equal(degraded.variant, 'degraded');

  const errorState = formatFactoryState({ factory_state: 'ERROR', is_paused: false });
  assert.equal(errorState.label, 'ERRO CRÍTICO');
  assert.equal(errorState.variant, 'error');

  // Nulo / vazio
  const nullState = formatFactoryState(null);
  assert.equal(nullState.label, 'DESCONHECIDO');
  assert.equal(nullState.isPaused, false);
});

test('2. formatInstanceRole: mapeia PRIMARY e SECONDARY_VIEW_ONLY com descricoes', () => {
  // Instância primária objeto
  const primaryObj = formatInstanceRole({ local_role: 'PRIMARY', is_primary: true });
  assert.equal(primaryObj.role, 'PRIMARY');
  assert.equal(primaryObj.isPrimary, true);
  assert.match(primaryObj.description, /Primária/);

  // Instância secundária objeto
  const secondaryObj = formatInstanceRole({ local_role: 'SECONDARY_VIEW_ONLY', is_primary: false });
  assert.equal(secondaryObj.role, 'SECONDARY_VIEW_ONLY');
  assert.equal(secondaryObj.isPrimary, false);
  assert.match(secondaryObj.description, /Somente Leitura/);

  // String direta
  assert.equal(formatInstanceRole('PRIMARY').isPrimary, true);
  assert.equal(formatInstanceRole('SECONDARY_VIEW_ONLY').isPrimary, false);

  // Nulo / indefinido
  const nullRole = formatInstanceRole(null);
  assert.equal(nullRole.isPrimary, false);
  assert.equal(nullRole.role, 'UNKNOWN');
});

test('3. formatHeartbeat: formata intervalos em segundos, minutos ou horas legiveis', () => {
  assert.equal(formatHeartbeat(0), 'há 0 s');
  assert.equal(formatHeartbeat(14), 'há 14 s');
  assert.equal(formatHeartbeat(59), 'há 59 s');
  assert.equal(formatHeartbeat(60), 'há 1 min');
  assert.equal(formatHeartbeat(125), 'há 2 min');
  assert.equal(formatHeartbeat(3600), 'há 1 h');
  assert.equal(formatHeartbeat(7250), 'há 2 h');

  // Casos nulos ou invalidos
  assert.equal(formatHeartbeat(null), '—');
  assert.equal(formatHeartbeat(undefined), '—');
  assert.equal(formatHeartbeat(''), '—');
  assert.equal(formatHeartbeat('invalido'), '—');
  assert.equal(formatHeartbeat(-5), '—');
});

test('4. canToggleFactory: habilita apenas para PRIMARY e gera explicacao para SECONDARY', () => {
  // PRIMARY habilitado
  const primary = canToggleFactory({ local_role: 'PRIMARY', is_primary: true });
  assert.equal(primary.canToggle, true);
  assert.equal(primary.reason, null);

  // SECONDARY_VIEW_ONLY desabilitado com motivo claro
  const secondary = canToggleFactory({ local_role: 'SECONDARY_VIEW_ONLY', is_primary: false });
  assert.equal(secondary.canToggle, false);
  assert.match(secondary.reason, /Apenas a instância primária/);
  assert.match(secondary.reason, /somente leitura/);

  // Instancia ausente
  const absent = canToggleFactory(null);
  assert.equal(absent.canToggle, false);
  assert.match(absent.reason, /indisponíveis/);
});

test('5. formatApiError: formata erros em portugues preservando mensagem original da API', () => {
  // Erro 403 (Permissão)
  const err403 = { status: 403, message: 'Operation blocked: only primary instance can change factory operational state' };
  const formatted403 = formatApiError(err403, 'pausar a fábrica');
  assert.match(formatted403, /Operação bloqueada \(403\)/);
  assert.match(formatted403, /nó primário/);
  assert.match(formatted403, /Operation blocked: only primary instance/);

  // Erro 409 (Conflito)
  const err409 = { status: 409, message: 'Operation blocked: factory is paused' };
  const formatted409 = formatApiError(err409, 'retomar');
  assert.match(formatted409, /Conflito operacional \(409\)/);
  assert.match(formatted409, /Operation blocked: factory is paused/);

  // Erro 500 genérico
  const err500 = new Error('Database disk image is malformed');
  const formatted500 = formatApiError(err500, 'pausar');
  assert.match(formatted500, /Falha ao pausar/);
  assert.match(formatted500, /Database disk image is malformed/);

  // Erro nulo
  assert.match(formatApiError(null, 'pausar'), /Erro desconhecido/);
});

test('6. formatProviderValue e formatQuotasDisplay: tratam ausentes com travessao', () => {
  assert.equal(formatProviderValue(null), '—');
  assert.equal(formatProviderValue(undefined), '—');
  assert.equal(formatProviderValue(''), '—');
  assert.equal(formatProviderValue('HEALTHY'), 'HEALTHY');

  // Cotas completas
  const qFull = formatQuotasDisplay({
    target_ready_stock: 5,
    max_generations_24h: 3,
    max_attempts_24h: 10,
    posts_per_day: 1,
  });
  assert.equal(qFull.target_ready_stock, '5');
  assert.equal(qFull.max_generations_24h, '3');
  assert.equal(qFull.max_attempts_24h, '10');
  assert.equal(qFull.posts_per_day, '1');

  // Cotas vazias
  const qEmpty = formatQuotasDisplay(null);
  assert.equal(qEmpty.target_ready_stock, '—');
  assert.equal(qEmpty.max_generations_24h, '—');
});

test('7. formatScheduleDisplay: formata janela e fuso horario de agendamento', () => {
  const sched = formatScheduleDisplay({
    publish_start_hour: 10,
    publish_end_hour: 22,
    timezone: 'America/Sao_Paulo',
    min_interval_hours: 4,
    posts_per_day: 2,
  });
  assert.equal(sched.window, '10:00 às 22:00');
  assert.equal(sched.timezone, 'America/Sao_Paulo');
  assert.equal(sched.min_interval_hours, '4h');
  assert.equal(sched.posts_per_day, '2');

  const emptySched = formatScheduleDisplay(null);
  assert.equal(emptySched.window, '—');
  assert.equal(emptySched.timezone, '—');
});
