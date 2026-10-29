import test from 'node:test';
import assert from 'node:assert';
import {
  formatStatus,
  formatVideoFormat,
  formatRelativeTime,
  formatApprovalRate,
  formatReadyStock,
  formatTotalReadyStock,
  sortChannelsBySeverity,
  getAttentionList,
  filterChannels,
} from '../components/Fleet/fleetLogic.js';

test('1. formatStatus returns accurate Portuguese labels, glyphs and semantic colors', () => {
  const ok = formatStatus('ok');
  assert.strictEqual(ok.label, 'Saudável');
  assert.strictEqual(ok.glyph, '✓');
  assert.strictEqual(ok.color, '#34D399');

  const running = formatStatus('running');
  assert.strictEqual(running.label, 'Produzindo');
  assert.strictEqual(running.glyph, '•');

  const attention = formatStatus('attention');
  assert.strictEqual(attention.label, 'Atenção');
  assert.strictEqual(attention.glyph, '!');

  const blocked = formatStatus('blocked');
  assert.strictEqual(blocked.label, 'Bloqueado');
  assert.strictEqual(blocked.glyph, '×');

  const paused = formatStatus('paused');
  assert.strictEqual(paused.label, 'Pausado');
  assert.strictEqual(paused.glyph, '⏸');

  const unknown = formatStatus('weird_state');
  assert.strictEqual(unknown.label, 'weird_state');
});

test('2. formatVideoFormat correctly maps specific formats and defaults cleanly', () => {
  const dilemma = formatVideoFormat('quiz_dilemma');
  assert.strictEqual(dilemma.label, 'Quiz · Escolhas difíceis');

  const paper = formatVideoFormat('quiz_paper');
  assert.strictEqual(paper.label, 'Quiz · Papel');

  const trad = formatVideoFormat('traditional');
  assert.strictEqual(trad.label, 'Tradicional');

  const other = formatVideoFormat('custom_style');
  assert.strictEqual(other.label, 'custom_style');

  const empty = formatVideoFormat(null);
  assert.strictEqual(empty.label, '—');
});

test('3. formatRelativeTime formats elapsed time intervals or returns placeholder', () => {
  const now = new Date('2026-10-25T12:00:00Z');

  assert.strictEqual(formatRelativeTime(null, now), '—');
  assert.strictEqual(formatRelativeTime(undefined, now), '—');
  assert.strictEqual(formatRelativeTime('invalid-date', now), '—');

  // 15 seconds ago -> agora
  const t30s = new Date('2026-10-25T11:59:45Z').toISOString();
  assert.strictEqual(formatRelativeTime(t30s, now), 'agora');

  // 12 minutes ago -> há 12 min
  const t12m = new Date('2026-10-25T11:48:00Z').toISOString();
  assert.strictEqual(formatRelativeTime(t12m, now), 'há 12 min');

  // 3 hours ago -> há 3 h
  const t3h = new Date('2026-10-25T09:00:00Z').toISOString();
  assert.strictEqual(formatRelativeTime(t3h, now), 'há 3 h');

  // 1 day ago -> há 1 dia
  const t1d = new Date('2026-10-24T12:00:00Z').toISOString();
  assert.strictEqual(formatRelativeTime(t1d, now), 'há 1 dia');

  // 4 days ago -> há 4 dias
  const t4d = new Date('2026-10-21T12:00:00Z').toISOString();
  assert.strictEqual(formatRelativeTime(t4d, now), 'há 4 dias');
});

test('4. formatApprovalRate handles fractions, percentages and null cases', () => {
  const n1 = formatApprovalRate(null);
  assert.strictEqual(n1.text, '—');
  assert.strictEqual(n1.isNull, true);

  const n2 = formatApprovalRate(undefined);
  assert.strictEqual(n2.text, '—');

  const frac = formatApprovalRate(0.83);
  assert.strictEqual(frac.text, '83%');
  assert.strictEqual(frac.color, '#E8EBF1');

  const lowFrac = formatApprovalRate(0.5);
  assert.strictEqual(lowFrac.text, '50%');
  assert.strictEqual(lowFrac.color, '#FF8A7A');

  const highPct = formatApprovalRate(94);
  assert.strictEqual(highPct.text, '94%');
});

test('5. sortChannelsBySeverity prioritizes blocked > attention > running > paused > ok', () => {
  const channels = [
    { name: 'Channel E', status: 'ok' },
    { name: 'Channel A', status: 'paused' },
    { name: 'Channel B', status: 'attention' },
    { name: 'Channel D', status: 'blocked' },
    { name: 'Channel C', status: 'running' },
  ];

  const sorted = sortChannelsBySeverity(channels);
  assert.deepStrictEqual(
    sorted.map((c) => c.status),
    ['blocked', 'attention', 'running', 'paused', 'ok']
  );
});

test('6. getAttentionList filters blocked, then attention (excluding paused)', () => {
  const channels = [
    { name: 'Healthy 1', status: 'ok' },
    { name: 'Paused 1', status: 'paused' },
    { name: 'Blocked 1', status: 'blocked' },
    { name: 'Attention 1', status: 'attention' },
    { name: 'Healthy 2', status: 'ok' },
  ];

  const attentionList = getAttentionList(channels);
  assert.strictEqual(attentionList.length, 2);
  assert.strictEqual(attentionList[0].name, 'Blocked 1');
  assert.strictEqual(attentionList[1].name, 'Attention 1');

  // Empty when all are ok
  const allOk = [{ name: 'Ch 1', status: 'ok' }, { name: 'Ch 2', status: 'ok' }];
  assert.strictEqual(getAttentionList(allOk).length, 0);
});

test('7. filterChannels filters by chip and search term', () => {
  const channels = [
    { name: 'Quiz Escolhas', niche: 'dilemas', format: 'quiz_dilemma', status: 'blocked' },
    { name: 'Dose Internet', niche: 'curiosidades', format: 'traditional', status: 'attention' },
    { name: 'Quiz Papel', niche: 'conhecimento', format: 'quiz_paper', status: 'ok' },
    { name: 'GTA VI', niche: 'games', format: 'traditional', status: 'paused' },
  ];

  const searchResults = filterChannels(channels, { query: 'inter' });
  assert.strictEqual(searchResults.length, 1);
  assert.strictEqual(searchResults[0].name, 'Dose Internet');

  const quizChannels = filterChannels(channels, { filter: 'quiz' });
  assert.strictEqual(quizChannels.length, 2);

  const attentionChannels = filterChannels(channels, { filter: 'attention' });
  assert.strictEqual(attentionChannels.length, 2);
});

test('8. formatReadyStock and formatTotalReadyStock handle null/unknown without breaking math or colors', () => {
  // Unknown ready_stock (null) with valid target_stock
  const unk = formatReadyStock(null, 5);
  assert.strictEqual(unk.isUnknown, true);
  assert.strictEqual(unk.readyDisplay, '—');
  assert.strictEqual(unk.targetDisplay, '5');
  assert.strictEqual(unk.label, '—/5');
  assert.strictEqual(unk.pct, 0);
  assert.strictEqual(unk.barColor, '#6B7385');

  // Unknown ready_stock (undefined) without target_stock
  const unkNoTarget = formatReadyStock(undefined, null);
  assert.strictEqual(unkNoTarget.isUnknown, true);
  assert.strictEqual(unkNoTarget.label, '—');
  assert.strictEqual(unkNoTarget.pct, 0);

  // Low stock (0 or 1) -> warning color #F5B546
  const low = formatReadyStock(1, 5);
  assert.strictEqual(low.isUnknown, false);
  assert.strictEqual(low.readyDisplay, '1');
  assert.strictEqual(low.targetDisplay, '5');
  assert.strictEqual(low.label, '1/5');
  assert.strictEqual(low.pct, 20);
  assert.strictEqual(low.barColor, '#F5B546');

  // Healthy stock (3 of 5) -> accent color and 60%
  const ok = formatReadyStock(3, 5);
  assert.strictEqual(ok.isUnknown, false);
  assert.strictEqual(ok.label, '3/5');
  assert.strictEqual(ok.pct, 60);
  assert.strictEqual(ok.barColor, 'var(--fleet-accent)');

  // Total fleet stock null vs number
  const totUnk = formatTotalReadyStock(null, false);
  assert.strictEqual(totUnk.isUnknown, true);
  assert.strictEqual(totUnk.display, '—');
  assert.strictEqual(totUnk.barWidth, '0%');

  const totOk = formatTotalReadyStock(18, false);
  assert.strictEqual(totOk.isUnknown, false);
  assert.strictEqual(totOk.display, '18');
  assert.strictEqual(totOk.barWidth, '100%');
});
