import test from 'node:test';
import assert from 'node:assert/strict';

import { formatDestinationsSummary } from '../components/Fleet/fleetLogic.js';

test('1. formatDestinationsSummary formata ausência de destinos como "Sem destino"', () => {
  assert.equal(formatDestinationsSummary(null), 'Sem destino');
  assert.equal(formatDestinationsSummary(undefined), 'Sem destino');
  assert.equal(formatDestinationsSummary([]), 'Sem destino');
  assert.equal(formatDestinationsSummary({}), 'Sem destino');
  assert.equal(
    formatDestinationsSummary([
      { platform: 'youtube', is_enabled: false },
      { platform: 'tiktok', is_enabled: false },
    ]),
    'Sem destino'
  );
});

test('2. formatDestinationsSummary formata canal único com ou sem auto-pub', () => {
  assert.equal(
    formatDestinationsSummary([
      { platform: 'youtube', is_enabled: true, auto_publish_authorized: false },
    ]),
    'YouTube ✓ sem auto-pub'
  );

  assert.equal(
    formatDestinationsSummary([
      { platform: 'youtube', is_enabled: true, auto_publish_authorized: true },
    ]),
    'YouTube ✓'
  );

  assert.equal(
    formatDestinationsSummary([
      { platform: 'tiktok', is_enabled: true, auto_publish_authorized: false },
    ]),
    'TikTok ✓ sem auto-pub'
  );

  assert.equal(
    formatDestinationsSummary([
      { platform: 'tiktok', is_enabled: true, auto_publish_authorized: true },
    ]),
    'TikTok ✓'
  );
});

test('3. formatDestinationsSummary combina múltiplos destinos com ordenação estável (YouTube primeiro)', () => {
  const destsA = [
    { platform: 'youtube', is_enabled: true, auto_publish_authorized: true },
    { platform: 'tiktok', is_enabled: true, auto_publish_authorized: false },
  ];
  assert.equal(formatDestinationsSummary(destsA), 'YouTube ✓ · TikTok ✓ sem auto-pub');

  // Ordem invertida no array de entrada deve resultar na mesma saída estável
  const destsB = [
    { platform: 'tiktok', is_enabled: true, auto_publish_authorized: false },
    { platform: 'youtube', is_enabled: true, auto_publish_authorized: true },
  ];
  assert.equal(formatDestinationsSummary(destsB), 'YouTube ✓ · TikTok ✓ sem auto-pub');

  // Ambos com auto-pub autorizado
  const destsC = [
    { platform: 'youtube', is_enabled: true, auto_publish_authorized: true },
    { platform: 'tiktok', is_enabled: true, auto_publish_authorized: true },
  ];
  assert.equal(formatDestinationsSummary(destsC), 'YouTube ✓ · TikTok ✓');
});

test('4. Validação de ID do YouTube: prefixo UC obrigatório quando preenchido', () => {
  const validateYtId = (id) => {
    if (!id) return true;
    const clean = String(id).trim();
    if (!clean) return true;
    return clean.startsWith('UC');
  };

  assert.equal(validateYtId(''), true);
  assert.equal(validateYtId(null), true);
  assert.equal(validateYtId('UC1234567890abcdefghij'), true);
  assert.equal(validateYtId('invalid_id_not_uc'), false);
  assert.equal(validateYtId('12345678'), false);
});

test('5. Fonte Única: api.js expõe rotas canônicas de destinos e publishing accounts', async () => {
  const apiModule = await import('../api.js');
  assert.equal(typeof apiModule.getChannelDestinations, 'function');
  assert.equal(typeof apiModule.updateChannelDestinations, 'function');
  assert.equal(typeof apiModule.getPublishingAccounts, 'function');
});
