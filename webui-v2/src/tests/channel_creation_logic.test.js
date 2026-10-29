import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateCreateChannelForm,
  buildCreateChannelPayload,
  VIDEO_FORMAT_OPTIONS,
} from '../components/Fleet/channelCreationLogic.js';

test('1. validateCreateChannelForm exige nome e nicho não-vazios', () => {
  const emptyRes = validateCreateChannelForm({});
  assert.equal(emptyRes.isValid, false);
  assert.equal(emptyRes.errors.name, 'Nome do canal é obrigatório.');
  assert.equal(emptyRes.errors.niche, 'Nicho é obrigatório.');

  const whitespaceRes = validateCreateChannelForm({ name: '   ', niche: '   ' });
  assert.equal(whitespaceRes.isValid, false);
  assert.equal(whitespaceRes.errors.name, 'Nome do canal é obrigatório.');
  assert.equal(whitespaceRes.errors.niche, 'Nicho é obrigatório.');
});

test('2. validateCreateChannelForm valida formatos aceitos (traditional, quiz_dilemma, quiz_paper)', () => {
  const invalidFormatRes = validateCreateChannelForm({
    name: 'Canal Teste',
    niche: 'jogos',
    video_format: 'invalido',
  });
  assert.equal(invalidFormatRes.isValid, false);
  assert.ok(invalidFormatRes.errors.video_format);

  for (const fmt of ['traditional', 'quiz_dilemma', 'quiz_paper']) {
    const validRes = validateCreateChannelForm({
      name: 'Canal Teste',
      niche: 'jogos',
      video_format: fmt,
    });
    assert.equal(validRes.isValid, true);
    assert.equal(validRes.errors.video_format, undefined);
  }
});

test('3. validateCreateChannelForm respeita limites máximos de tamanho', () => {
  const longName = 'A'.repeat(101);
  const longNiche = 'B'.repeat(101);
  const longTopic = 'C'.repeat(1001);

  const res = validateCreateChannelForm({
    name: longName,
    niche: longNiche,
    topic_brief: longTopic,
  });
  assert.equal(res.isValid, false);
  assert.equal(res.errors.name, 'Nome deve ter no máximo 100 caracteres.');
  assert.equal(res.errors.niche, 'Nicho deve ter no máximo 100 caracteres.');
  assert.equal(res.errors.topic_brief, 'Briefing editorial deve ter no máximo 1000 caracteres.');
});

test('4. buildCreateChannelPayload sanitiza campos e fixa idioma em pt-BR', () => {
  const payload = buildCreateChannelPayload({
    name: '  Histórias Estranhas  ',
    niche: '  curiosidades  ',
    video_format: 'quiz_dilemma',
    topic_brief: '  Contos misteriosos e enigmas  ',
  });

  assert.deepEqual(payload, {
    name: 'Histórias Estranhas',
    niche: 'curiosidades',
    video_format: 'quiz_dilemma',
    topic_brief: 'Contos misteriosos e enigmas',
    language: 'pt-BR',
  });
});

test('5. VIDEO_FORMAT_OPTIONS contém opções homologadas', () => {
  assert.equal(VIDEO_FORMAT_OPTIONS.length, 3);
  assert.equal(VIDEO_FORMAT_OPTIONS[0].value, 'traditional');
  assert.equal(VIDEO_FORMAT_OPTIONS[1].value, 'quiz_dilemma');
  assert.equal(VIDEO_FORMAT_OPTIONS[2].value, 'quiz_paper');
});
