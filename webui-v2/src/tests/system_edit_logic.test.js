import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  validateChannelField,
  validateScheduleWindow,
  validateChannelForm,
  calculateSettingsDiff,
  buildPatchPayloads,
  formatDiffValueDisplay,
  buildSystemChannelHash,
  parseSystemChannelFromHash,
} from '../components/System/systemEditLogic.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('1. validateChannelField: valida faixas estritas (incluindo target_ready_stock 3..10, max_generations_24h, growth_mode e autonomous_enabled)', () => {
  // target_ready_stock (3-10, alinhado ao setter canônico do backend)
  assert.equal(validateChannelField('target_ready_stock', 3).isValid, true);
  assert.equal(validateChannelField('target_ready_stock', 10).isValid, true);
  assert.equal(validateChannelField('target_ready_stock', 2).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 1).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 0).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 11).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 'abc').isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 3.5).isValid, false);

  // max_generations_24h (1-10)
  assert.equal(validateChannelField('max_generations_24h', 1).isValid, true);
  assert.equal(validateChannelField('max_generations_24h', 10).isValid, true);
  assert.equal(validateChannelField('max_generations_24h', 0).isValid, false);
  assert.equal(validateChannelField('max_generations_24h', 11).isValid, false);

  // growth_mode (WARMUP | SCALE)
  assert.equal(validateChannelField('growth_mode', 'WARMUP').isValid, true);
  assert.equal(validateChannelField('growth_mode', 'scale').isValid, true);
  assert.equal(validateChannelField('growth_mode', 'TURBO').isValid, false);
  assert.equal(validateChannelField('growth_mode', '').isValid, false);

  // autonomous_enabled (boolean / 'true' / 'false')
  assert.equal(validateChannelField('autonomous_enabled', true).isValid, true);
  assert.equal(validateChannelField('autonomous_enabled', false).isValid, true);
  assert.equal(validateChannelField('autonomous_enabled', 'true').isValid, true);
  assert.equal(validateChannelField('autonomous_enabled', 'false').isValid, true);
  assert.equal(validateChannelField('autonomous_enabled', 'talvez').isValid, false);

  // posts_per_day (1-10)
  assert.equal(validateChannelField('posts_per_day', 1).isValid, true);
  assert.equal(validateChannelField('posts_per_day', 10).isValid, true);
  assert.equal(validateChannelField('posts_per_day', 0).isValid, false);
  assert.equal(validateChannelField('posts_per_day', 15).isValid, false);

  // publish_start_hour e publish_end_hour (0-23)
  assert.equal(validateChannelField('publish_start_hour', 0).isValid, true);
  assert.equal(validateChannelField('publish_start_hour', 23).isValid, true);
  assert.equal(validateChannelField('publish_start_hour', -1).isValid, false);
  assert.equal(validateChannelField('publish_start_hour', 24).isValid, false);

  assert.equal(validateChannelField('publish_end_hour', 0).isValid, true);
  assert.equal(validateChannelField('publish_end_hour', 23).isValid, true);
  assert.equal(validateChannelField('publish_end_hour', 24).isValid, false);

  // min_interval_hours (1-24)
  assert.equal(validateChannelField('min_interval_hours', 1).isValid, true);
  assert.equal(validateChannelField('min_interval_hours', 24).isValid, true);
  assert.equal(validateChannelField('min_interval_hours', 0).isValid, false);
  assert.equal(validateChannelField('min_interval_hours', 25).isValid, false);
});

test('2. validateScheduleWindow: exige start <= end e rejeita janela invertida', () => {
  // Válidos: start < end ou start == end
  assert.equal(validateScheduleWindow(8, 22).isValid, true);
  assert.equal(validateScheduleWindow(10, 10).isValid, true);
  assert.equal(validateScheduleWindow('9', '18').isValid, true);

  // Inválido: start > end (janela que atravessa a meia-noite)
  const invalid = validateScheduleWindow(22, 6);
  assert.equal(invalid.isValid, false);
  assert.match(invalid.error, /não pode ser menor que o horário inicial/);
});

test('3. validateChannelForm: valida formulário completo agregando erros', () => {
  // Formulário válido completo
  const validForm = {
    growth_mode: 'SCALE',
    autonomous_enabled: true,
    target_ready_stock: 5,
    max_generations_24h: 5,
    posts_per_day: 2,
    publish_start_hour: 9,
    publish_end_hour: 21,
    min_interval_hours: 4,
  };
  const validRes = validateChannelForm(validForm);
  assert.equal(validRes.isValid, true);
  assert.equal(Object.keys(validRes.errors).length, 0);

  // Formulário com múltiplos erros (target_ready_stock < 3, growth_mode inválido e janela invertida)
  const invalidForm = {
    growth_mode: 'INVALID_MODE',
    autonomous_enabled: 'invalid_bool',
    target_ready_stock: 2, // abaixo do mínimo real 3
    max_generations_24h: 0,
    posts_per_day: 0,
    publish_start_hour: 18,
    publish_end_hour: 8,
    min_interval_hours: 4,
  };
  const invalidRes = validateChannelForm(invalidForm);
  assert.equal(invalidRes.isValid, false);
  assert.ok(invalidRes.errors.growth_mode);
  assert.ok(invalidRes.errors.autonomous_enabled);
  assert.ok(invalidRes.errors.target_ready_stock);
  assert.ok(invalidRes.errors.max_generations_24h);
  assert.ok(invalidRes.errors.posts_per_day);
  assert.ok(invalidRes.errors.publish_end_hour);
});

test('4. calculateSettingsDiff: detecta apenas campos com valores alterados (incluindo growth_mode, autonomous_enabled e max_generations_24h)', () => {
  const original = {
    growth_mode: 'WARMUP',
    autonomous_enabled: false,
    target_ready_stock: 3,
    max_generations_24h: 2,
    posts_per_day: 1,
    publish_start_hour: 10,
    publish_end_hour: 22,
    min_interval_hours: 4,
  };

  // Nenhuma alteração
  const noDiff = calculateSettingsDiff(original, { ...original });
  assert.equal(noDiff.length, 0);

  // Alteração de modo autônomo, growth_mode e max_generations_24h
  const diffModes = calculateSettingsDiff(original, {
    ...original,
    growth_mode: 'scale',
    autonomous_enabled: true,
    max_generations_24h: 5,
  });
  assert.equal(diffModes.length, 3);
  assert.deepEqual(
    diffModes.map((d) => ({ field: d.field, oldValue: d.oldValue, newValue: d.newValue })),
    [
      { field: 'growth_mode', oldValue: 'WARMUP', newValue: 'SCALE' },
      { field: 'autonomous_enabled', oldValue: false, newValue: true },
      { field: 'max_generations_24h', oldValue: 2, newValue: 5 },
    ]
  );

  // Apenas target_ready_stock alterado
  const diffQuotas = calculateSettingsDiff(original, {
    ...original,
    target_ready_stock: 5,
  });
  assert.equal(diffQuotas.length, 1);
  assert.equal(diffQuotas[0].field, 'target_ready_stock');
  assert.equal(diffQuotas[0].oldValue, 3);
  assert.equal(diffQuotas[0].newValue, 5);
});

test('5. buildPatchPayloads: gera payloads contendo SOMENTE campos alterados para as rotas existentes', () => {
  // Quando nada mudou: bloqueio total
  const emptyPayloads = buildPatchPayloads([]);
  assert.equal(emptyPayloads.hasChanges, false);
  assert.equal(emptyPayloads.growthModePayload, null);
  assert.equal(emptyPayloads.autonomousPayload, null);
  assert.equal(emptyPayloads.quotasPayload, null);
  assert.equal(emptyPayloads.schedulePayload, null);

  // Apenas modos e max_generations_24h alterados
  const modeAndQuotaDiff = [
    { field: 'growth_mode', oldValue: 'WARMUP', newValue: 'SCALE' },
    { field: 'autonomous_enabled', oldValue: false, newValue: true },
    { field: 'max_generations_24h', oldValue: 2, newValue: 5 },
  ];
  const modeRes = buildPatchPayloads(modeAndQuotaDiff);
  assert.equal(modeRes.hasChanges, true);
  assert.equal(modeRes.growthModePayload, 'scale');
  assert.equal(modeRes.autonomousPayload, true);
  assert.deepEqual(modeRes.quotasPayload, { max_generations_24h: 5 });
  assert.equal(modeRes.schedulePayload, null);

  // Apenas schedule alterado
  const schedDiff = [
    { field: 'publish_start_hour', oldValue: 10, newValue: 8 },
    { field: 'min_interval_hours', oldValue: 4, newValue: 6 },
  ];
  const schedRes = buildPatchPayloads(schedDiff);
  assert.equal(schedRes.hasChanges, true);
  assert.equal(schedRes.growthModePayload, null);
  assert.equal(schedRes.autonomousPayload, null);
  assert.equal(schedRes.quotasPayload, null);
  assert.deepEqual(schedRes.schedulePayload, {
    publish_start_hour: 8,
    min_interval_hours: 6,
  });

  // Quotas e schedule (incluindo posts_per_day)
  const bothDiff = [
    { field: 'target_ready_stock', oldValue: 3, newValue: 5 },
    { field: 'posts_per_day', oldValue: 1, newValue: 2 },
    { field: 'publish_start_hour', oldValue: 10, newValue: 9 },
  ];
  const bothRes = buildPatchPayloads(bothDiff);
  assert.equal(bothRes.hasChanges, true);
  assert.deepEqual(bothRes.quotasPayload, {
    target_ready_stock: 5,
    posts_per_day: 2,
  });
  assert.deepEqual(bothRes.schedulePayload, {
    posts_per_day: 2,
    publish_start_hour: 9,
  });
});

test('6. formatDiffValueDisplay: formata modos, horas e unidades para diálogo de confirmação', () => {
  assert.equal(formatDiffValueDisplay('growth_mode', 'SCALE'), 'SCALE (Escala)');
  assert.equal(formatDiffValueDisplay('growth_mode', 'WARMUP'), 'WARMUP (Aquecimento)');
  assert.equal(formatDiffValueDisplay('autonomous_enabled', true), 'SIM (Ativo)');
  assert.equal(formatDiffValueDisplay('autonomous_enabled', false), 'NÃO (Desligado)');
  assert.equal(formatDiffValueDisplay('publish_start_hour', 8), '08:00');
  assert.equal(formatDiffValueDisplay('publish_end_hour', 22), '22:00');
  assert.equal(formatDiffValueDisplay('target_ready_stock', 5), '5 vídeos');
  assert.equal(formatDiffValueDisplay('max_generations_24h', 4), '4 vídeos/24h');
  assert.equal(formatDiffValueDisplay('posts_per_day', 2), '2 posts/dia');
  assert.equal(formatDiffValueDisplay('min_interval_hours', 4), '4h');
  assert.equal(formatDiffValueDisplay('outro', null), '—');
});

test('7. Atalho "Editar em Sistema": buildSystemChannelHash e parseSystemChannelFromHash', () => {
  const hash = buildSystemChannelHash('profile-historias');
  assert.equal(hash, '#sistema?channel=profile-historias');
  assert.equal(parseSystemChannelFromHash(hash), 'profile-historias');
  assert.equal(parseSystemChannelFromHash('#sistema'), null);
  assert.equal(parseSystemChannelFromHash('#frota?channel=profile-historias'), null);
  assert.equal(buildSystemChannelHash(''), '#sistema');
});

test('8. Regra de Controle Único: ExecutionDrawer é somente leitura para configurações e SystemView concentra a edição', () => {
  const drawerPath = path.resolve(__dirname, '../components/ExecutionDrawer.jsx');
  const systemPath = path.resolve(__dirname, '../components/System/SystemView.jsx');
  const drawerSource = fs.readFileSync(drawerPath, 'utf8');
  const systemSource = fs.readFileSync(systemPath, 'utf8');

  // ExecutionDrawer NÃO pode conter mutação de configuração do canal
  assert.equal(drawerSource.includes('updateProfileGrowthMode'), false);
  assert.equal(drawerSource.includes('updateProfileAutonomousMode'), false);
  assert.equal(drawerSource.includes('updateProfileSettings'), false);
  assert.equal(drawerSource.includes('updateProfileQuotas'), false);
  assert.equal(drawerSource.includes('updateProfileSchedule'), false);
  assert.equal(drawerSource.includes('Salvar Quotas e Janela'), false);

  // ExecutionDrawer DEVE manter disparo de ciclo e o atalho "Editar em Sistema"
  assert.equal(drawerSource.includes('runFactoryCycle'), true);
  assert.equal(drawerSource.includes('Disparar Ciclo do Canal'), true);
  assert.equal(drawerSource.includes('Editar em Sistema'), true);

  // SystemView DEVE concentrar todos os controles editáveis e usar a faixa 3..10 para target_ready_stock
  assert.equal(systemSource.includes('updateProfileGrowthMode'), true);
  assert.equal(systemSource.includes('updateProfileAutonomousMode'), true);
  assert.equal(systemSource.includes('updateProfileQuotas'), true);
  assert.equal(systemSource.includes('updateProfileSchedule'), true);
  assert.equal(systemSource.includes('Meta Estoque (3–10 vídeos)'), true);
  assert.equal(systemSource.includes('Gerações/24h (1–10)'), true);
  assert.equal(systemSource.includes('sys-channel-${pid}'), true);
});
