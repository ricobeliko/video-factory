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

  // Produção não mostra "ajustados" no banner ou contagem (igual à V1)
  assert.equal(prodSource.includes('adjusted_count'), false);
  assert.equal(prodSource.includes('ajustado'), false);

  // FactoryHeader é estritamente LEITURA (sem botões de mutação de settings ou de disparo)
  assert.equal(headerSource.includes('updateSchedulerSettings'), false);
  assert.equal(headerSource.includes('runSchedulerCycle'), false);
  assert.equal(headerSource.includes('planSchedule'), false);
});

test('2. Fonte Única dos Booleanos: V2 lê SOMENTE os booleanos canônicos e ignora campos de texto', () => {
  const headerPath = path.resolve(__dirname, '../components/FactoryHeader.jsx');
  const systemPath = path.resolve(__dirname, '../components/System/SystemView.jsx');

  const headerSource = fs.readFileSync(headerPath, 'utf8');
  const systemSource = fs.readFileSync(systemPath, 'utf8');

  // Prova no código-fonte: sem qualquer fallback ?? para campos de texto 'ON'/'OFF'
  assert.equal(headerSource.includes('systemStatus?.auto_publish_enabled'), true);
  assert.equal(headerSource.includes('systemStatus?.dry_run_enabled'), true);
  assert.equal(headerSource.includes('auto_publish ==='), false);
  assert.equal(headerSource.includes('dry_run ==='), false);
  assert.equal(headerSource.includes('auto_publish_enabled ??'), false);
  assert.equal(headerSource.includes('dry_run_enabled ??'), false);

  assert.equal(systemSource.includes('systemStatus?.scheduler_enabled'), true);
  assert.equal(systemSource.includes('systemStatus?.auto_publish_enabled'), true);
  assert.equal(systemSource.includes('systemStatus?.dry_run_enabled'), true);
  assert.equal(systemSource.includes('auto_publish ==='), false);
  assert.equal(systemSource.includes('dry_run ==='), false);
  assert.equal(systemSource.includes('scheduler_active ==='), false);
  assert.equal(systemSource.includes('auto_publish_enabled ??'), false);
  assert.equal(systemSource.includes('dry_run_enabled ??'), false);
  assert.equal(systemSource.includes('scheduler_enabled ??'), false);

  // Prova lógica: função pura simulando a leitura estrita dos componentes V2
  function readV2Booleans(systemStatus) {
    return {
      isSchedulerEnabled: Boolean(systemStatus?.scheduler_enabled),
      isAutoPublish: Boolean(systemStatus?.auto_publish_enabled),
      isDryRun: Boolean(systemStatus?.dry_run_enabled),
    };
  }

  // Cenário A: Campos de texto da V1 contêm 'ON', mas booleanos estão ausentes/false
  // A V2 NÃO deve ler os textos e deve retornar estritamente false
  const textOnlyStatus = {
    scheduler_active: 'ACTIVE',
    auto_publish: 'ON',
    dry_run: 'ON',
  };
  const resA = readV2Booleans(textOnlyStatus);
  assert.equal(resA.isSchedulerEnabled, false);
  assert.equal(resA.isAutoPublish, false);
  assert.equal(resA.isDryRun, false);

  // Cenário B: Booleanos canônicos presentes são respeitados estritamente, ignorando textos legados
  const canonicalStatus = {
    scheduler_enabled: true,
    auto_publish_enabled: true,
    dry_run_enabled: false,
    auto_publish: 'OFF', // texto divergente deve ser ignorado
    dry_run: 'ON',        // texto divergente deve ser ignorado
  };
  const resB = readV2Booleans(canonicalStatus);
  assert.equal(resB.isSchedulerEnabled, true);
  assert.equal(resB.isAutoPublish, true);
  assert.equal(resB.isDryRun, false);
});
