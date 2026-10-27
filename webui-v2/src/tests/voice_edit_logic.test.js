import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getVoiceSourceInfo,
  validateVoiceField,
  validateVoiceForm,
  calculateVoiceDiff,
  buildVoicePatchPayload,
  formatVoiceDiffDisplay,
  QUIZ_VOICE_RATE_NOTICE,
} from '../components/System/voiceEditLogic.js';

test('1. validateVoiceField: valida limites de velocidade (0.5–2.0) e volume (0.0–1.0)', () => {
  // voice_rate: faixa 0.5 - 2.0
  assert.equal(validateVoiceField('voice_rate', 0.5).isValid, true);
  assert.equal(validateVoiceField('voice_rate', 1.0).isValid, true);
  assert.equal(validateVoiceField('voice_rate', 2.0).isValid, true);
  assert.equal(validateVoiceField('voice_rate', 0.49).isValid, false);
  assert.equal(validateVoiceField('voice_rate', 2.01).isValid, false);
  assert.equal(validateVoiceField('voice_rate', 'abc').isValid, false);
  assert.equal(validateVoiceField('voice_rate', '').isValid, false);

  // voice_volume: faixa 0.0 - 1.0
  assert.equal(validateVoiceField('voice_volume', 0.0).isValid, true);
  assert.equal(validateVoiceField('voice_volume', 0.5).isValid, true);
  assert.equal(validateVoiceField('voice_volume', 1.0).isValid, true);
  assert.equal(validateVoiceField('voice_volume', -0.01).isValid, false);
  assert.equal(validateVoiceField('voice_volume', 1.01).isValid, false);
  assert.equal(validateVoiceField('voice_volume', 'xyz').isValid, false);

  // voice_name: validação de lista homologada
  const allowed = ['pt-BR-FranciscaNeural', 'pt-BR-AntonioNeural', 'en-US-BrianMultilingualNeural'];
  assert.equal(validateVoiceField('voice_name', 'pt-BR-FranciscaNeural', { allowedVoiceIds: allowed }).isValid, true);
  assert.equal(validateVoiceField('voice_name', 'af-ZA-AdriNeural', { allowedVoiceIds: allowed }).isValid, false);
  assert.equal(validateVoiceField('voice_name', '', { allowedVoiceIds: allowed }).isValid, false);

  // Valor null (Voltar a herdar) é sempre válido
  assert.equal(validateVoiceField('voice_name', null).isValid, true);
  assert.equal(validateVoiceField('voice_rate', null).isValid, true);
  assert.equal(validateVoiceField('voice_volume', null).isValid, true);
});

test('2. validateVoiceField: regra de Quiz ignora velocidade', () => {
  // Para canal de quiz, voice_rate é ignorado / sempre válido
  assert.equal(validateVoiceField('voice_rate', 'inválido', { isQuiz: true }).isValid, true);
  assert.equal(validateVoiceField('voice_rate', 99, { isQuiz: true }).isValid, true);
});

test('3. getVoiceSourceInfo: mapeia corretamente selos de origem e herança', () => {
  const chInfo = getVoiceSourceInfo('channel');
  assert.equal(chInfo.label, 'Do canal');
  assert.equal(chInfo.isInherited, false);
  assert.equal(chInfo.canReset, true);

  const globInfo = getVoiceSourceInfo('global');
  assert.equal(globInfo.label, 'Global');
  assert.equal(globInfo.isInherited, true);
  assert.equal(globInfo.canReset, false);

  const defInfo = getVoiceSourceInfo('default');
  assert.equal(defInfo.label, 'Padrão');
  assert.equal(defInfo.isInherited, true);
  assert.equal(defInfo.canReset, false);
});

test('4. calculateVoiceDiff: monta diff apenas com campos alterados', () => {
  const effective = {
    voice_name: { value: 'pt-BR-FranciscaNeural', source: 'global' },
    voice_rate: { value: 1.0, source: 'global' },
    voice_volume: { value: 1.0, source: 'default' },
  };

  // Nenhuma alteração
  const diffEmpty = calculateVoiceDiff(effective, {
    voice_name: 'pt-BR-FranciscaNeural',
    voice_rate: 1.0,
    voice_volume: 1.0,
  });
  assert.equal(diffEmpty.length, 0);

  // Apenas voice_name alterado
  const diffVoiceOnly = calculateVoiceDiff(effective, {
    voice_name: 'pt-BR-AntonioNeural',
    voice_rate: 1.0,
    voice_volume: 1.0,
  });
  assert.equal(diffVoiceOnly.length, 1);
  assert.equal(diffVoiceOnly[0].field, 'voice_name');
  assert.equal(diffVoiceOnly[0].oldValue, 'pt-BR-FranciscaNeural');
  assert.equal(diffVoiceOnly[0].newValue, 'pt-BR-AntonioNeural');
  assert.equal(diffVoiceOnly[0].isReset, false);

  // Alteração de rate e volume
  const diffRateVol = calculateVoiceDiff(effective, {
    voice_name: 'pt-BR-FranciscaNeural',
    voice_rate: 1.15,
    voice_volume: 0.8,
  });
  assert.equal(diffRateVol.length, 2);
  const fields = diffRateVol.map((d) => d.field);
  assert.ok(fields.includes('voice_rate'));
  assert.ok(fields.includes('voice_volume'));
});

test('5. calculateVoiceDiff: regra de Quiz não altera velocidade', () => {
  const effective = {
    voice_name: { value: 'pt-BR-AntonioNeural', source: 'channel' },
    voice_rate: { value: 1.2, source: 'channel' },
    voice_volume: { value: 1.0, source: 'global' },
  };

  // Em canal de quiz, mesmo se formData passar voice_rate diferente, ela é ignorada
  const diff = calculateVoiceDiff(
    effective,
    { voice_name: 'pt-BR-FranciscaNeural', voice_rate: 0.8, voice_volume: 1.0 },
    { isQuiz: true }
  );
  assert.equal(diff.length, 1);
  assert.equal(diff[0].field, 'voice_name');
});

test('6. calculateVoiceDiff e buildVoicePatchPayload: Voltar a herdar gera null', () => {
  const effective = {
    voice_name: { value: 'pt-BR-AntonioNeural', source: 'channel' },
    voice_rate: { value: 1.15, source: 'channel' },
    voice_volume: { value: 0.9, source: 'channel' },
  };

  // O operador clicou em 'Voltar a herdar' na voz (formVal === null)
  const diff = calculateVoiceDiff(effective, {
    voice_name: null,
    voice_rate: 1.15,
    voice_volume: 0.9,
  });
  assert.equal(diff.length, 1);
  assert.equal(diff[0].field, 'voice_name');
  assert.equal(diff[0].newValue, null);
  assert.equal(diff[0].isReset, true);

  const { payload, hasChanges } = buildVoicePatchPayload(diff);
  assert.equal(hasChanges, true);
  assert.deepEqual(payload, { voice_name: null });
});

test('7. buildVoicePatchPayload: envia apenas campos modificados', () => {
  const diffList = [
    { field: 'voice_name', newValue: 'en-US-BrianMultilingualNeural', isReset: false },
    { field: 'voice_rate', newValue: 1.1, isReset: false },
  ];

  const { payload, hasChanges } = buildVoicePatchPayload(diffList);
  assert.equal(hasChanges, true);
  assert.deepEqual(payload, {
    voice_name: 'en-US-BrianMultilingualNeural',
    voice_rate: 1.1,
  });
  assert.equal('voice_volume' in payload, false);
});

test('8. formatVoiceDiffDisplay: formata rótulos amigáveis e percentuais', () => {
  const allowed = [
    { id: 'pt-BR-FranciscaNeural', name: 'Francisca (pt-BR, Feminina)' },
    { id: 'pt-BR-AntonioNeural', name: 'Antônio (pt-BR, Masculina)' },
  ];

  assert.equal(formatVoiceDiffDisplay('voice_name', 'pt-BR-FranciscaNeural', allowed), 'Francisca (pt-BR, Feminina)');
  assert.equal(formatVoiceDiffDisplay('voice_name', null, allowed), 'Voltar a herdar (global)');
  assert.equal(formatVoiceDiffDisplay('voice_rate', 1.15), '1.15x');
  assert.equal(formatVoiceDiffDisplay('voice_volume', 0.8), '80%');
  assert.equal(formatVoiceDiffDisplay('voice_volume', null), 'Voltar a herdar (global)');
});

test('9. calculateVoiceDiff e buildVoicePatchPayload: campo herdado com mesmo valor + pinned gera diff isPin e payload com o campo', () => {
  const effective = {
    voice_name: { value: 'en-US-BrianMultilingualNeural', source: 'global' },
    voice_rate: { value: 1.0, source: 'global' },
    voice_volume: { value: 1.0, source: 'default' },
  };

  const diff = calculateVoiceDiff(
    effective,
    { voice_name: 'en-US-BrianMultilingualNeural', voice_rate: 1.0, voice_volume: 1.0 },
    { pinned: new Set(['voice_name']) }
  );

  assert.equal(diff.length, 1);
  assert.equal(diff[0].field, 'voice_name');
  assert.equal(diff[0].isPin, true);
  assert.equal(diff[0].oldValue, 'en-US-BrianMultilingualNeural');
  assert.equal(diff[0].newValue, 'en-US-BrianMultilingualNeural');

  const { payload, hasChanges } = buildVoicePatchPayload(diff);
  assert.equal(hasChanges, true);
  assert.deepEqual(payload, { voice_name: 'en-US-BrianMultilingualNeural' });
});

test('10. calculateVoiceDiff: mesmo caso herdado com mesmo valor SEM pinned não gera diff', () => {
  const effective = {
    voice_name: { value: 'en-US-BrianMultilingualNeural', source: 'global' },
    voice_rate: { value: 1.0, source: 'global' },
    voice_volume: { value: 1.0, source: 'default' },
  };

  const diff = calculateVoiceDiff(
    effective,
    { voice_name: 'en-US-BrianMultilingualNeural', voice_rate: 1.0, voice_volume: 1.0 },
    { pinned: new Set() }
  );

  assert.equal(diff.length, 0);
});

test('11. calculateVoiceDiff: campo com source "channel" e mesmo valor + pinned não gera diff', () => {
  const effective = {
    voice_name: { value: 'pt-BR-AntonioNeural', source: 'channel' },
    voice_rate: { value: 1.1, source: 'channel' },
    voice_volume: { value: 1.0, source: 'channel' },
  };

  const diff = calculateVoiceDiff(
    effective,
    { voice_name: 'pt-BR-AntonioNeural', voice_rate: 1.1, voice_volume: 1.0 },
    { pinned: new Set(['voice_name', 'voice_rate']) }
  );

  assert.equal(diff.length, 0);
});

test('12. calculateVoiceDiff: quiz com pinned em voice_rate não gera diff de velocidade', () => {
  const effective = {
    voice_name: { value: 'pt-BR-FranciscaNeural', source: 'global' },
    voice_rate: { value: 1.0, source: 'global' },
    voice_volume: { value: 1.0, source: 'default' },
  };

  const diff = calculateVoiceDiff(
    effective,
    { voice_name: 'pt-BR-FranciscaNeural', voice_rate: 1.0, voice_volume: 1.0 },
    { isQuiz: true, pinned: new Set(['voice_rate']) }
  );

  assert.equal(diff.length, 0);
});
