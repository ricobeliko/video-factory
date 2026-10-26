import test from 'node:test';
import assert from 'node:assert';
import {
  stageToStationIndex,
  resolveActiveExecution,
  computeStationStates,
  formatElapsedTime,
  computeCourierState,
} from '../components/Fleet/workshopLogic.js';

// -----------------------------------------------------------------------------
// 1. Mapeamento de etapas para estações (0 a 5)
// -----------------------------------------------------------------------------
test('1. stageToStationIndex maps real pipeline stages into 6 stations', () => {
  // Roteiro [TOPIC, SCRIPT] -> 0
  assert.strictEqual(stageToStationIndex('TOPIC'), 0);
  assert.strictEqual(stageToStationIndex('SCRIPT'), 0);
  assert.strictEqual(stageToStationIndex('script'), 0);

  // Narração [NARRATION] -> 1
  assert.strictEqual(stageToStationIndex('NARRATION'), 1);

  // Cenas [VISUALS, MATERIALS] -> 2
  assert.strictEqual(stageToStationIndex('VISUALS'), 2);
  assert.strictEqual(stageToStationIndex('MATERIALS'), 2);

  // Render [RENDER, VIDEO] -> 3
  assert.strictEqual(stageToStationIndex('RENDER'), 3);
  assert.strictEqual(stageToStationIndex('VIDEO'), 3);

  // Gates [SAFETY, QUALITY, COPYRIGHT] -> 4
  assert.strictEqual(stageToStationIndex('SAFETY'), 4);
  assert.strictEqual(stageToStationIndex('QUALITY'), 4);
  assert.strictEqual(stageToStationIndex('COPYRIGHT'), 4);
  assert.strictEqual(stageToStationIndex('HELD_SAFETY_REVIEW'), 4);

  // Publicar [READY_STOCK, SCHEDULER, PUBLISHER, YOUTUBE] -> 5
  assert.strictEqual(stageToStationIndex('READY_STOCK'), 5);
  assert.strictEqual(stageToStationIndex('SCHEDULER'), 5);
  assert.strictEqual(stageToStationIndex('PUBLISHER'), 5);
  assert.strictEqual(stageToStationIndex('YOUTUBE'), 5);

  // Desconhecido ou nulo
  assert.strictEqual(stageToStationIndex('UNKNOWN_STAGE'), -1);
  assert.strictEqual(stageToStationIndex(null), -1);
  assert.strictEqual(stageToStationIndex(''), -1);
});

// -----------------------------------------------------------------------------
// 2. Escolha da execução ativa (múltiplas RUNNING, ordenação por started_at)
// -----------------------------------------------------------------------------
test('2. resolveActiveExecution selects most recent RUNNING and sets badgeExtra', () => {
  const channels = [
    {
      profile_id: 'p1',
      channel_name: 'Canal Antigo',
      status: 'RUNNING',
      execution: {
        task_id: 't1',
        pipeline_stage: 'SCRIPT',
        started_at: '2026-10-25T12:00:00Z',
        status: 'RUNNING',
      },
    },
    {
      profile_id: 'p2',
      channel_name: 'Canal Novo',
      status: 'RUNNING',
      execution: {
        task_id: 't2',
        pipeline_stage: 'RENDER',
        started_at: '2026-10-25T12:15:00Z',
        status: 'RUNNING',
      },
    },
    {
      profile_id: 'p3',
      channel_name: 'Canal Mais Recente',
      status: 'RUNNING',
      execution: {
        task_id: 't3',
        pipeline_stage: 'VISUALS',
        started_at: '2026-10-25T12:30:00Z',
        status: 'RUNNING',
      },
    },
  ];

  const res = resolveActiveExecution(channels);
  assert.strictEqual(res.mode, 'RUNNING');
  assert.strictEqual(res.execution.task_id, 't3');
  assert.strictEqual(res.execution.channel_name, 'Canal Mais Recente');
  assert.strictEqual(res.runningCount, 3);
  assert.strictEqual(res.badgeExtra, '+2 em produção');
});

// -----------------------------------------------------------------------------
// 3. Fallback para FAILED se nenhuma estiver RUNNING
// -----------------------------------------------------------------------------
test('3. resolveActiveExecution chooses FAILED when no channels are RUNNING', () => {
  const channels = [
    {
      profile_id: 'p1',
      channel_name: 'Canal Idle',
      status: 'IDLE',
      execution: null,
    },
    {
      profile_id: 'p2',
      channel_name: 'Canal com Erro',
      status: 'FAILED',
      execution: {
        task_id: 'tfail',
        pipeline_stage: 'QUALITY',
        started_at: '2026-10-25T10:00:00Z',
        updated_at: '2026-10-25T10:02:00Z',
        error: 'Áudio fora de sincronia',
        gate_reason: 'Quality Gate: áudio desalinhado',
        status: 'FAILED',
      },
    },
  ];

  const res = resolveActiveExecution(channels);
  assert.strictEqual(res.mode, 'FAILED');
  assert.strictEqual(res.execution.task_id, 'tfail');
  assert.strictEqual(res.execution.channel_name, 'Canal com Erro');
  assert.strictEqual(res.badgeExtra, null);
});

// -----------------------------------------------------------------------------
// 4. Estado IDLE (nenhum canal produzindo ou com falha)
// -----------------------------------------------------------------------------
test('4. resolveActiveExecution returns IDLE state when no active executions exist', () => {
  const empty = resolveActiveExecution([]);
  assert.strictEqual(empty.mode, 'IDLE');
  assert.strictEqual(empty.execution, null);

  const channels = [
    { profile_id: 'p1', status: 'IDLE', execution: null },
    { profile_id: 'p2', status: 'WAITING', execution: { status: 'WAITING' } },
  ];
  const res = resolveActiveExecution(channels);
  assert.strictEqual(res.mode, 'IDLE');
  assert.strictEqual(res.execution, null);
});

// -----------------------------------------------------------------------------
// 5. Poses por estação em andamento (RUNNING)
// -----------------------------------------------------------------------------
test('5. computeStationStates sets completed=happy, current=working, remaining=idle in RUNNING mode', () => {
  // Current stage is VISUALS (station 2: Cenas)
  const exec = {
    task_id: 't1',
    pipeline_stage: 'VISUALS',
    progress: 45,
    provider: 'Google Flow',
  };

  const stations = computeStationStates(exec, 'RUNNING');
  assert.strictEqual(stations.length, 6);

  // 0: Roteiro -> happy (-288px)
  assert.strictEqual(stations[0].pose, 'happy');
  assert.strictEqual(stations[0].bgPos, '-288px 0px');
  assert.strictEqual(stations[0].isWorking, false);
  assert.strictEqual(stations[0].barPct, 100);

  // 1: Narração -> happy (-288px)
  assert.strictEqual(stations[1].pose, 'happy');
  assert.strictEqual(stations[1].bgPos, '-288px 0px');
  assert.strictEqual(stations[1].isWorking, false);
  assert.strictEqual(stations[1].barPct, 100);

  // 2: Cenas -> working (-144px)
  assert.strictEqual(stations[2].pose, 'working');
  assert.strictEqual(stations[2].bgPos, '-144px 0px');
  assert.strictEqual(stations[2].isWorking, true);
  assert.strictEqual(stations[2].barPct, 45);
  assert.strictEqual(stations[2].bubble, 'gerando no Google Flow…');

  // 3: Render -> idle (0px)
  assert.strictEqual(stations[3].pose, 'idle');
  assert.strictEqual(stations[3].bgPos, '0px 0px');
  assert.strictEqual(stations[3].isWorking, false);
  assert.strictEqual(stations[3].barPct, 0);

  // 4: Gates -> idle
  assert.strictEqual(stations[4].pose, 'idle');

  // 5: Publicar -> idle
  assert.strictEqual(stations[5].pose, 'idle');
});

// -----------------------------------------------------------------------------
// 6. Progresso não numérico na estação em andamento (barPct = 0, sem fallback 50)
// -----------------------------------------------------------------------------
test('6. computeStationStates sets barPct = 0 when progress is not a number (removes default 50)', () => {
  // Cenário a: progress undefined
  const execUndefined = {
    task_id: 't_no_prog',
    pipeline_stage: 'SCRIPT',
  };
  const stUndef = computeStationStates(execUndefined, 'RUNNING');
  assert.strictEqual(stUndef[0].barPct, 0);
  assert.strictEqual(stUndef[0].isWorking, true);
  assert.strictEqual(stUndef[0].pose, 'working');

  // Cenário b: progress null
  const execNull = {
    task_id: 't_null_prog',
    pipeline_stage: 'NARRATION',
    progress: null,
  };
  const stNull = computeStationStates(execNull, 'RUNNING');
  assert.strictEqual(stNull[1].barPct, 0);

  // Cenário c: progress string (ex: "50%")
  const execStr = {
    task_id: 't_str_prog',
    pipeline_stage: 'RENDER',
    progress: '50%',
  };
  const stStr = computeStationStates(execStr, 'RUNNING');
  assert.strictEqual(stStr[3].barPct, 0);

  // Cenário d: progress NaN
  const execNaN = {
    task_id: 't_nan_prog',
    pipeline_stage: 'VISUALS',
    progress: NaN,
  };
  const stNaN = computeStationStates(execNaN, 'RUNNING');
  assert.strictEqual(stNaN[2].barPct, 0);

  // Cenário e: progress numérico 0 (deve manter 0)
  const execZero = {
    task_id: 't_zero_prog',
    pipeline_stage: 'SAFETY',
    progress: 0,
  };
  const stZero = computeStationStates(execZero, 'RUNNING');
  assert.strictEqual(stZero[4].barPct, 0);
});

// -----------------------------------------------------------------------------
// 7. Estágio não reconhecido (RUNNING ou FAILED): todas as 6 estações em idle
// -----------------------------------------------------------------------------
test('7. computeStationStates leaves all 6 stations in idle when pipeline_stage is unrecognized', () => {
  // RUNNING com estágio não mapeado (NÃO deve assumir Roteiro)
  const execUnknownRunning = {
    task_id: 't_unk_run',
    pipeline_stage: 'CUSTOM_PREPARATION_PHASE',
    status: 'RUNNING',
    progress: 60,
  };
  const stRun = computeStationStates(execUnknownRunning, 'RUNNING');
  assert.strictEqual(stRun.length, 6);
  for (const st of stRun) {
    assert.strictEqual(st.pose, 'idle');
    assert.strictEqual(st.bgPos, '0px 0px');
    assert.strictEqual(st.isWorking, false);
    assert.strictEqual(st.barPct, 0);
    assert.strictEqual(st.bubble, null);
  }

  // FAILED com estágio não mapeado (NÃO deve assumir Roteiro)
  const execUnknownFailed = {
    task_id: 't_unk_fail',
    pipeline_stage: 'UNKNOWN_INSPECTION',
    status: 'FAILED',
    error: 'Etapa personalizada abortada',
  };
  const stFail = computeStationStates(execUnknownFailed, 'FAILED');
  assert.strictEqual(stFail.length, 6);
  for (const st of stFail) {
    assert.strictEqual(st.pose, 'idle');
    assert.strictEqual(st.bgPos, '0px 0px');
    assert.strictEqual(st.isWorking, false);
    assert.strictEqual(st.barPct, 0);
    assert.strictEqual(st.bubble, null);
  }
});

// -----------------------------------------------------------------------------
// 8. Poses por estação em falha (FAILED) e fallback de motivo
// -----------------------------------------------------------------------------
test('8. computeStationStates marks failure station as error (-432px) and falls back safely', () => {
  // Failed at SAFETY com gate_reason
  const execWithReason = {
    task_id: 't2',
    pipeline_stage: 'SAFETY',
    gate_reason: 'Roteiro viola moderação prévia',
  };

  const stations = computeStationStates(execWithReason, 'FAILED');
  assert.strictEqual(stations.length, 6);

  // 0, 1, 2, 3: completed -> happy
  for (let i = 0; i <= 3; i++) {
    assert.strictEqual(stations[i].pose, 'happy');
    assert.strictEqual(stations[i].bgPos, '-288px 0px');
  }

  // 4: Gates -> error (-432px) com motivo
  assert.strictEqual(stations[4].pose, 'error');
  assert.strictEqual(stations[4].bgPos, '-432px 0px');
  assert.strictEqual(stations[4].isWorking, false);
  assert.strictEqual(stations[4].bubble, 'Roteiro viola moderação prévia');

  // 5: Publicar -> idle
  assert.strictEqual(stations[5].pose, 'idle');
  assert.strictEqual(stations[5].bgPos, '0px 0px');

  // Failed at SCRIPT sem gate_reason nem error -> fallback "Motivo não informado pela fábrica"
  const execNoReason = {
    task_id: 't3',
    pipeline_stage: 'SCRIPT',
  };
  const stNoReason = computeStationStates(execNoReason, 'FAILED');
  assert.strictEqual(stNoReason[0].pose, 'error');
  assert.strictEqual(stNoReason[0].bubble, 'Motivo não informado pela fábrica');
});

// -----------------------------------------------------------------------------
// 9. Poses em estado de espera (IDLE)
// -----------------------------------------------------------------------------
test('9. computeStationStates sets all stations to idle (0px 0px) when IDLE', () => {
  const stations = computeStationStates(null, 'IDLE');
  assert.strictEqual(stations.length, 6);
  for (const st of stations) {
    assert.strictEqual(st.pose, 'idle');
    assert.strictEqual(st.bgPos, '0px 0px');
    assert.strictEqual(st.isWorking, false);
    assert.strictEqual(st.barPct, 0);
  }
});

// -----------------------------------------------------------------------------
// 10. Cálculo de tempo decorrido formatElapsedTime
// -----------------------------------------------------------------------------
test('10. formatElapsedTime calculates human readable elapsed time accurately', () => {
  const now = 1761400000000;

  // 35 segundos atrás
  const t35s = new Date(now - 35 * 1000).toISOString();
  assert.strictEqual(formatElapsedTime(t35s, now), '35s');

  // 2 minutos e 15 segundos atrás
  const t2m15s = new Date(now - (2 * 60 + 15) * 1000).toISOString();
  assert.strictEqual(formatElapsedTime(t2m15s, now), '2m 15s');

  // 1 hora e 10 minutos atrás
  const t1h10m = new Date(now - (70 * 60) * 1000).toISOString();
  assert.strictEqual(formatElapsedTime(t1h10m, now), '1h 10m');

  // Casos nulos ou inválidos
  assert.strictEqual(formatElapsedTime(null, now), null);
  assert.strictEqual(formatElapsedTime(undefined, now), null);
  assert.strictEqual(formatElapsedTime('invalid_date_str', now), null);
});

// -----------------------------------------------------------------------------
// 11. Estado e coordenadas do courier (incluindo posição inicial para etapa desconhecida)
// -----------------------------------------------------------------------------
test('11. computeCourierState positions courier at active station or initial position when unknown', () => {
  const exec = {
    channel_name: 'Fatos Curiosos',
    provider: 'Google Flow',
  };

  // Estação 2: pos = [580, 40] -> left: 582px, top: 102px
  const courier = computeCourierState(exec, 'RUNNING', 2);
  assert.strictEqual(courier.left, '582px');
  assert.strictEqual(courier.top, '102px');
  assert.strictEqual(courier.ini, 'FC');
  assert.strictEqual(courier.chipColor, '#C7A9FF'); // Flow purple chip
  assert.strictEqual(courier.bgPos, '-304px 0px'); // Frame 4 (parado)

  // Estágio desconhecido (-1): Courier fica na posição inicial (Estação 0: pos = [20, 40] -> left: 22px, top: 102px)
  const courierUnknown = computeCourierState(exec, 'RUNNING', -1);
  assert.strictEqual(courierUnknown.left, '22px');
  assert.strictEqual(courierUnknown.top, '102px');

  // Sem índice (undefined) -> Posição inicial (Estação 0)
  const courierDefault = computeCourierState(exec, 'IDLE', undefined);
  assert.strictEqual(courierDefault.left, '22px');
  assert.strictEqual(courierDefault.top, '102px');
});
