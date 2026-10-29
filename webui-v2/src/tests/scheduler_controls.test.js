import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('1. Fonte Única de Edição: Sistema concentra switches e Produção concentra botões de ação', () => {
  const systemPath = path.resolve(__dirname, '../components/System/SystemView.jsx');
  const prodPath = path.resolve(__dirname, '../components/Production/ProductionView.jsx');
  const headerPath = path.resolve(__dirname, '../components/FactoryHeader.jsx');
  const apiPath = path.resolve(__dirname, '../api.js');

  const systemSource = fs.readFileSync(systemPath, 'utf8');
  const prodSource = fs.readFileSync(prodPath, 'utf8');
  const headerSource = fs.readFileSync(headerPath, 'utf8');
  const apiSource = fs.readFileSync(apiPath, 'utf8');

  // api.js deve expor as 3 funções canônicas
  assert.equal(apiSource.includes('export async function updateSchedulerSettings'), true);
  assert.equal(apiSource.includes('export async function runSchedulerCycle'), true);
  assert.equal(apiSource.includes('export async function planSchedule'), true);

  // SystemView é o ÚNICO lugar com switches de configuração do agendador
  assert.equal(systemSource.includes('updateSchedulerSettings'), true);
  assert.equal(systemSource.includes('sys-switch'), true);
  assert.equal(systemSource.includes('handleToggleSchedulerSetting'), true);
  assert.equal(systemSource.includes('auto_publish_enabled'), true);
  assert.equal(systemSource.includes('scheduler_enabled'), true);
  assert.equal(systemSource.includes('dry_run'), true);

  // ProductionView tem os botões de ação e modal de confirmação, e ZERO switches
  assert.equal(prodSource.includes('runSchedulerCycle'), true);
  assert.equal(prodSource.includes('planSchedule'), true);
  assert.equal(prodSource.includes('Publicar Agora'), true);
  assert.equal(prodSource.includes('Replanejar Agenda'), true);
  assert.equal(prodSource.includes('prod-modal-overlay'), true);
  // Zero switches em Produção
  assert.equal(prodSource.includes('updateSchedulerSettings'), false);
  assert.equal(prodSource.includes('sys-switch'), false);
  assert.equal(prodSource.includes('<input type="checkbox"'), false);

  // FactoryHeader é estritamente LEITURA (sem botões de mutação de settings ou de disparo)
  assert.equal(headerSource.includes('updateSchedulerSettings'), false);
  assert.equal(headerSource.includes('runSchedulerCycle'), false);
  assert.equal(headerSource.includes('planSchedule'), false);
});

test('2. Resolução Coerente de Valores Canônicos (booleanos estritos, sem falso positivo em string OFF)', () => {
  // Simula a resolução canônica feita em SystemView e FactoryHeader
  function resolveSchedulerFlags(systemStatus) {
    const isSchedulerEnabled = Boolean(
      systemStatus?.scheduler_enabled ?? (systemStatus?.scheduler_active === 'ACTIVE')
    );

    const isAutoPublish = Boolean(
      systemStatus?.auto_publish_enabled ??
      (systemStatus?.auto_publish === true || systemStatus?.auto_publish === 'ON')
    );

    const isDryRun = Boolean(
      systemStatus?.dry_run_enabled ??
      (systemStatus?.dry_run === true || systemStatus?.dry_run === 'ON')
    );

    return { isSchedulerEnabled, isAutoPublish, isDryRun };
  }

  // Caso 1: Flags canônicas booleanas vindas do backend
  const res1 = resolveSchedulerFlags({
    scheduler_enabled: true,
    auto_publish_enabled: false,
    dry_run_enabled: false,
  });
  assert.equal(res1.isSchedulerEnabled, true);
  assert.equal(res1.isAutoPublish, false);
  assert.equal(res1.isDryRun, false);

  // Caso 2: Backend legado retornando string "OFF" - NUNCA deve ser true
  const res2 = resolveSchedulerFlags({
    scheduler_active: 'INACTIVE',
    auto_publish: 'OFF',
    dry_run: 'OFF',
  });
  assert.equal(res2.isSchedulerEnabled, false);
  assert.equal(res2.isAutoPublish, false);
  assert.equal(res2.isDryRun, false);

  // Caso 3: Backend retornando string "ON" / "ACTIVE"
  const res3 = resolveSchedulerFlags({
    scheduler_active: 'ACTIVE',
    auto_publish: 'ON',
    dry_run: 'ON',
  });
  assert.equal(res3.isSchedulerEnabled, true);
  assert.equal(res3.isAutoPublish, true);
  assert.equal(res3.isDryRun, true);
});
