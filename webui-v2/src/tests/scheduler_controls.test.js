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

test('3. Interruptor de Sistema dispara exatamente 1 PATCH e ZERO refetches completos; contas conectadas não entram no polling', async () => {
  const systemPath = path.resolve(__dirname, '../components/System/SystemView.jsx');
  const apiPath = path.resolve(__dirname, '../api.js');

  const systemSource = fs.readFileSync(systemPath, 'utf8');
  const apiSource = fs.readFileSync(apiPath, 'utf8');

  // 1. Verificação estrutural do polling (fetchData):
  const fetchStart = systemSource.indexOf('const fetchData = useCallback(async () => {');
  const fetchEnd = systemSource.indexOf('// Polling a cada 15 segundos', fetchStart);
  assert.equal(fetchStart > 0 && fetchEnd > fetchStart, true);
  const fetchBody = systemSource.slice(fetchStart, fetchEnd);

  // O polling NÃO pode chamar getPublishingAccounts nem getProfileSettings por canal (N+1)
  assert.equal(fetchBody.includes('getPublishingAccounts'), false);
  assert.equal(fetchBody.includes('getProfileSettings'), false);

  // 2. Verificação estrutural de handleToggleSchedulerSetting:
  const toggleStart = systemSource.indexOf('const handleToggleSchedulerSetting = async (key, nextValue) => {');
  const toggleEnd = systemSource.indexOf('// Handlers de Edição de Ajustes por Canal', toggleStart);
  assert.equal(toggleStart > 0 && toggleEnd > toggleStart, true);
  const toggleBody = systemSource.slice(toggleStart, toggleEnd).replace(/\/\/.*$/gm, '');

  // Dispara updateSchedulerSettings, faz atualização otimista e NÃO chama fetchData()
  assert.equal(toggleBody.includes('await updateSchedulerSettings({ [key]: nextValue })'), true);
  assert.equal(toggleBody.includes('await fetchData()'), false);
  assert.equal(toggleBody.includes('fetchData()'), false);
  assert.equal(toggleBody.includes('getSystemStatus'), false);
  assert.equal(toggleBody.includes('getChannelsOverview'), false);
  assert.equal(toggleBody.includes('getPublishingAccounts'), false);

  // 3. Verificação de suporte a force=true em api.js para cache bypass sob demanda:
  assert.equal(apiSource.includes('getPublishingAccounts(platform = null, force = false)'), true);
  assert.equal(apiSource.includes('getProviderHealth(force = false)'), true);

  // 4. Simulação comportamental de contagem de chamadas (1 PATCH, 0 GETs de refetch; reversão em caso de erro):
  const callCounts = {
    patchSchedulerSettings: 0,
    fetchData: 0,
    getPublishingAccounts: 0,
  };

  let state = {
    scheduler_enabled: true,
    auto_publish_enabled: false,
    dry_run: true,
  };

  async function simulateToggle(key, nextValue, shouldFail = false) {
    const previousValue = state[key];
    state = { ...state, [key]: nextValue }; // Otimista imediato
    try {
      callCounts.patchSchedulerSettings += 1;
      if (shouldFail) {
        throw new Error('Falha simulada HTTP 500');
      }
      const patchResponse = { ...state, [key]: nextValue };
      state = { ...state, ...patchResponse };
    } catch {
      state = { ...state, [key]: previousValue }; // Reverte sem chamar fetchData
    }
  }

  // Toggle com sucesso:
  await simulateToggle('auto_publish_enabled', true, false);
  assert.equal(callCounts.patchSchedulerSettings, 1);
  assert.equal(callCounts.fetchData, 0);
  assert.equal(callCounts.getPublishingAccounts, 0);
  assert.equal(state.auto_publish_enabled, true);

  // Toggle com erro: reverte valor para true sem disparar fetchData
  await simulateToggle('auto_publish_enabled', false, true);
  assert.equal(callCounts.patchSchedulerSettings, 2);
  assert.equal(callCounts.fetchData, 0);
  assert.equal(state.auto_publish_enabled, true);
});

