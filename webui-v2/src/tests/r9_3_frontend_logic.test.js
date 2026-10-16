import test from 'node:test';
import assert from 'node:assert';
import { sanitizeDisplayText, STAGE_DEFINITIONS } from '../utils/stageVisuals.js';

test('1. sanitizeDisplayText neutralizes raw HTML and scripts', () => {
  assert.strictEqual(sanitizeDisplayText('Normal topic text'), 'Normal topic text');
  assert.strictEqual(sanitizeDisplayText('<b>Bold</b> error'), 'Bold error');
  assert.strictEqual(sanitizeDisplayText('502 Bad Gateway: <script>alert("xss")</script> Try again'), '502 Bad Gateway: alert("xss") Try again');
  assert.strictEqual(sanitizeDisplayText('<div class="box"><span>Message</span></div>'), 'Message');
  assert.strictEqual(sanitizeDisplayText(''), '');
  assert.strictEqual(sanitizeDisplayText(null), '');
  assert.strictEqual(sanitizeDisplayText(undefined), '');
});

test('2. STAGE_DEFINITIONS has 12 discrete stages with personas and colors', () => {
  assert.strictEqual(STAGE_DEFINITIONS.length, 12);
  const codes = STAGE_DEFINITIONS.map(s => s.code);
  const expectedCodes = [
    'TOPIC', 'SCRIPT', 'NARRATION', 'VISUALS', 'RENDER',
    'SAFETY', 'QUALITY', 'COPYRIGHT', 'READY_STOCK',
    'SCHEDULER', 'PUBLISHER', 'YOUTUBE'
  ];
  assert.deepStrictEqual(codes, expectedCodes);

  STAGE_DEFINITIONS.forEach((stage, idx) => {
    assert.strictEqual(stage.step, idx + 1);
    assert.ok(stage.label, `Stage ${stage.code} missing label`);
    assert.ok(stage.persona?.code, `Stage ${stage.code} missing persona code`);
    assert.ok(stage.persona?.name, `Stage ${stage.code} missing persona name`);
    assert.ok(stage.accentColor, `Stage ${stage.code} missing accentColor`);
    assert.ok(stage.tonalBg, `Stage ${stage.code} missing tonalBg`);
  });
});

test('3. Gate verification evaluates strictly on factual verdicts', () => {
  const evaluateCompletedStage = (sDef, gates) => {
    if (sDef.step <= 5) return 'SUCCESS';
    if (sDef.code === 'SAFETY') {
      const sSt = String(gates?.safety_status || '').toUpperCase();
      return (sSt === 'APPROVED' || sSt === 'PASS' || sSt === 'GOOD') ? 'SUCCESS' : 'PENDING';
    }
    if (sDef.code === 'QUALITY') {
      const qScore = gates?.quality_score;
      return (typeof qScore === 'number' && qScore >= 70.0) ? 'SUCCESS' : 'PENDING';
    }
    if (sDef.code === 'COPYRIGHT') {
      const cSt = String(gates?.copyright_status || '').toUpperCase();
      return (cSt === 'PASS' || cSt === 'APPROVED') ? 'SUCCESS' : 'PENDING';
    }
    return 'SUCCESS';
  };

  const safetyStage = STAGE_DEFINITIONS.find(s => s.code === 'SAFETY');
  const qualityStage = STAGE_DEFINITIONS.find(s => s.code === 'QUALITY');
  const copyrightStage = STAGE_DEFINITIONS.find(s => s.code === 'COPYRIGHT');

  // Case: Gates are null/pending during early pipeline
  assert.strictEqual(evaluateCompletedStage(safetyStage, null), 'PENDING');
  assert.strictEqual(evaluateCompletedStage(qualityStage, null), 'PENDING');
  assert.strictEqual(evaluateCompletedStage(copyrightStage, null), 'PENDING');

  // Case: Quality rejected (< 70.0)
  const rejectedGates = { safety_status: 'PASS', quality_score: 67.8, copyright_status: 'PASS' };
  assert.strictEqual(evaluateCompletedStage(safetyStage, rejectedGates), 'SUCCESS');
  assert.strictEqual(evaluateCompletedStage(qualityStage, rejectedGates), 'PENDING');
  assert.strictEqual(evaluateCompletedStage(copyrightStage, rejectedGates), 'SUCCESS');

  // Case: All gates approved
  const approvedGates = { safety_status: 'PASS', quality_score: 74.5, copyright_status: 'PASS' };
  assert.strictEqual(evaluateCompletedStage(safetyStage, approvedGates), 'SUCCESS');
  assert.strictEqual(evaluateCompletedStage(qualityStage, approvedGates), 'SUCCESS');
  assert.strictEqual(evaluateCompletedStage(copyrightStage, approvedGates), 'SUCCESS');
});

test('4. Dynamic tracking vs manual focus persistence state machine', () => {
  let isManualFocusLocked = false;
  let selectedChannelId = 'profile-default';

  // Helper simulating App.jsx channel selection
  const updateSelectionOnPolling = (channels, currentSelectedId, isManualLocked) => {
    if (isManualLocked) {
      // Manual focus locked: stays on operator's choice
      return currentSelectedId;
    }
    // Dynamic tracking: auto-follow running channel
    const runningChannel = channels.find(c => c.status === 'RUNNING');
    if (runningChannel) {
      return runningChannel.profile_id;
    }
    return currentSelectedId;
  };

  const channelsMock = [
    { profile_id: 'profile-default', status: 'IDLE' },
    { profile_id: 'profile-b', status: 'RUNNING' }
  ];

  // In auto mode, polling switches focus to profile-b
  selectedChannelId = updateSelectionOnPolling(channelsMock, selectedChannelId, isManualFocusLocked);
  assert.strictEqual(selectedChannelId, 'profile-b');

  // Operator manually locks focus on profile-default
  isManualFocusLocked = true;
  selectedChannelId = 'profile-default';

  // Next polling cycle preserves operator's manual choice!
  selectedChannelId = updateSelectionOnPolling(channelsMock, selectedChannelId, isManualFocusLocked);
  assert.strictEqual(selectedChannelId, 'profile-default');
});
