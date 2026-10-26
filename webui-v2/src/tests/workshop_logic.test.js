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
// 6. Poses por estação em falha (FAILED)
// -----------------------------------------------------------------------------
test('6. computeStationStates marks failure station as error (-432px) with error reason', () => {
  // Failed at SAFETY (station 4: Gates)
  const exec = {
    task_id: 't2',
    pipeline_stage: 'SAFETY',
    gate_reason: 'Roteiro viola moderação prévia',
  };

  const stations = computeStationStates(exec, 'FAILED');
  assert.strictEqual(stations.length, 6);

  // 0, 1, 2, 3: completed -> happy
  for (let i = 0; i <= 3; i++) {
    assert.strictEqual(stations[i].pose, 'happy');
    assert.strictEqual(stations[i].bgPos, '-288px 0px');
  }

  // 4: Gates -> error (-432px)
  assert.strictEqual(stations[4].pose, 'error');
  assert.strictEqual(stations[4].bgPos, '-432px 0px');
  assert.strictEqual(stations[4].isWorking, false);
  assert.strictEqual(stations[4].bubble, 'Roteiro viola moderação prévia');

  // 5: Publicar -> idle
  assert.strictEqual(stations[5].pose, 'idle');
  assert.strictEqual(stations[5].bgPos, '0px 0px');
});

// -----------------------------------------------------------------------------
// 7. Poses em estado de espera (IDLE)
// -----------------------------------------------------------------------------
test('7. computeStationStates sets all stations to idle (0px 0px) when IDLE', () => {
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
// 8. Cálculo de tempo decorrido formatElapsedTime
// -----------------------------------------------------------------------------
test('8. formatElapsedTime calculates human readable elapsed time accurately', () => {
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
// 9. Estado e coordenadas do courier
// -----------------------------------------------------------------------------
test('9. computeCourierState positions courier at active station coordinates with initials', () => {
  const exec = {
    channel_name: 'Fatos Curiosos',
    provider: 'Google Flow',
  };

  const courier = computeCourierState(exec, 'RUNNING', 2);
  // Station 2: pos = [580, 40] -> left: 582px, top: 102px
  assert.strictEqual(courier.left, '582px');
  assert.strictEqual(courier.top, '102px');
  assert.strictEqual(courier.ini, 'FC');
  assert.strictEqual(courier.chipColor, '#C7A9FF'); // Flow purple chip
  assert.strictEqual(courier.bgPos, '-304px 0px'); // Frame 4 (stopped)
});
