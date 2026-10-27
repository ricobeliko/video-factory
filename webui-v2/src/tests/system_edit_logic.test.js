import test from 'node:test';
import assert from 'node:assert/strict';

import {
  validateChannelField,
  validateScheduleWindow,
  validateChannelForm,
  calculateSettingsDiff,
  buildPatchPayloads,
  formatDiffValueDisplay,
} from '../components/System/systemEditLogic.js';

test('1. validateChannelField: valida faixas estritas dos campos editáveis', () => {
  // target_ready_stock (1-10)
  assert.equal(validateChannelField('target_ready_stock', 1).isValid, true);
  assert.equal(validateChannelField('target_ready_stock', 10).isValid, true);
  assert.equal(validateChannelField('target_ready_stock', 0).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 11).isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 'abc').isValid, false);
  assert.equal(validateChannelField('target_ready_stock', 3.5).isValid, false);

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
  // Formulário válido
  const validForm = {
    target_ready_stock: 5,
    posts_per_day: 2,
    publish_start_hour: 9,
    publish_end_hour: 21,
    min_interval_hours: 4,
  };
  const validRes = validateChannelForm(validForm);
  assert.equal(validRes.isValid, true);
  assert.equal(Object.keys(validRes.errors).length, 0);

  // Formulário com múltiplos erros (faixa e janela invertida)
  const invalidForm = {
    target_ready_stock: 12, // erro faixa
    posts_per_day: 0, // erro faixa
    publish_start_hour: 18,
    publish_end_hour: 8, // erro janela
    min_interval_hours: 4,
  };
  const invalidRes = validateChannelForm(invalidForm);
  assert.equal(invalidRes.isValid, false);
  assert.ok(invalidRes.errors.target_ready_stock);
  assert.ok(invalidRes.errors.posts_per_day);
  assert.ok(invalidRes.errors.publish_end_hour);
});

test('4. calculateSettingsDiff: detecta apenas campos com valores alterados', () => {
  const original = {
    target_ready_stock: 3,
    posts_per_day: 1,
    publish_start_hour: 10,
    publish_end_hour: 22,
    min_interval_hours: 4,
  };

  // Nenhuma alteração
  const noDiff = calculateSettingsDiff(original, { ...original });
  assert.equal(noDiff.length, 0);

  // Apenas target_ready_stock alterado
  const diffQuotas = calculateSettingsDiff(original, {
    ...original,
    target_ready_stock: 5,
  });
  assert.equal(diffQuotas.length, 1);
  assert.equal(diffQuotas[0].field, 'target_ready_stock');
  assert.equal(diffQuotas[0].oldValue, 3);
  assert.equal(diffQuotas[0].newValue, 5);

  // Apenas janela alterada
  const diffSchedule = calculateSettingsDiff(original, {
    ...original,
    publish_start_hour: 8,
    publish_end_hour: 20,
  });
  assert.equal(diffSchedule.length, 2);
  const fields = diffSchedule.map(d => d.field);
  assert.ok(fields.includes('publish_start_hour'));
  assert.ok(fields.includes('publish_end_hour'));
});

test('5. buildPatchPayloads: gera payloads contendo SOMENTE campos alterados e bloqueia quando nada mudou', () => {
  // Quando nada mudou: bloqueio total
  const emptyPayloads = buildPatchPayloads([]);
  assert.equal(emptyPayloads.hasChanges, false);
  assert.equal(emptyPayloads.quotasPayload, null);
  assert.equal(emptyPayloads.schedulePayload, null);

  // Apenas quotas alteradas
  const quotaDiff = [
    { field: 'target_ready_stock', oldValue: 3, newValue: 6 },
  ];
  const quotaRes = buildPatchPayloads(quotaDiff);
  assert.equal(quotaRes.hasChanges, true);
  assert.deepEqual(quotaRes.quotasPayload, { target_ready_stock: 6 });
  assert.equal(quotaRes.schedulePayload, null); // NÃO chama /schedule!

  // Apenas schedule alterado
  const schedDiff = [
    { field: 'publish_start_hour', oldValue: 10, newValue: 8 },
    { field: 'min_interval_hours', oldValue: 4, newValue: 6 },
  ];
  const schedRes = buildPatchPayloads(schedDiff);
  assert.equal(schedRes.hasChanges, true);
  assert.equal(schedRes.quotasPayload, null); // NÃO chama /quotas!
  assert.deepEqual(schedRes.schedulePayload, {
    publish_start_hour: 8,
    min_interval_hours: 6,
  });

  // Ambos alterados (incluindo posts_per_day)
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

test('6. formatDiffValueDisplay: formata horas e unidades para diálogo de confirmação', () => {
  assert.equal(formatDiffValueDisplay('publish_start_hour', 8), '08:00');
  assert.equal(formatDiffValueDisplay('publish_end_hour', 22), '22:00');
  assert.equal(formatDiffValueDisplay('target_ready_stock', 5), '5 vídeos');
  assert.equal(formatDiffValueDisplay('posts_per_day', 2), '2 posts/dia');
  assert.equal(formatDiffValueDisplay('min_interval_hours', 4), '4h');
  assert.equal(formatDiffValueDisplay('outro', null), '—');
});
