/**
 * workshopLogic.js — Funções puras e configurações da Oficina ao Vivo da Frota (webui-v2).
 * BACKEND = SOURCE OF TRUTH / FRONTEND = PRESENTATION ONLY
 */

export const STATIONS_CONFIG = [
  {
    index: 0,
    id: 'roteiro',
    name: 'Roteiro',
    numLabel: '1 · ROTEIRO',
    stages: ['TOPIC', 'SCRIPT'],
    sprite: 'roteiro',
    hue: '#FF4FD8',
    pos: [20, 40],
    defaultBubble: 'escrevendo roteiro…',
  },
  {
    index: 1,
    id: 'narracao',
    name: 'Narração',
    numLabel: '2 · NARRAÇÃO',
    stages: ['NARRATION'],
    sprite: 'narracao',
    hue: '#2DE2A6',
    pos: [300, 40],
    defaultBubble: 'gravando a voz…',
  },
  {
    index: 2,
    id: 'cenas',
    name: 'Cenas',
    numLabel: '3 · CENAS',
    stages: ['VISUALS', 'MATERIALS'],
    sprite: 'cenas',
    hue: '#FFC53D',
    pos: [580, 40],
    defaultBubble: 'montando as cenas…',
  },
  {
    index: 3,
    id: 'render',
    name: 'Render',
    numLabel: '4 · RENDER',
    stages: ['RENDER', 'VIDEO'],
    sprite: 'render',
    hue: '#4DA3FF',
    pos: [580, 226],
    defaultBubble: 'renderizando vídeo…',
  },
  {
    index: 4,
    id: 'gates',
    name: 'Gates de segurança',
    numLabel: '5 · GATES',
    stages: ['SAFETY', 'QUALITY', 'COPYRIGHT', 'HELD_SAFETY_REVIEW'],
    sprite: 'gates',
    hue: '#8B5CFF',
    pos: [300, 226],
    defaultBubble: 'conferindo segurança…',
  },
  {
    index: 5,
    id: 'publicar',
    name: 'Publicação',
    numLabel: '6 · PUBLICAR',
    stages: ['READY_STOCK', 'SCHEDULER', 'PUBLISHER', 'YOUTUBE'],
    sprite: 'publicar',
    hue: '#FF7A59',
    pos: [20, 226],
    defaultBubble: 'preparando publicação…',
  },
];

/**
 * Mapeia o nome canônico do estágio do pipeline para o índice da estação (0 a 5).
 * Retorna -1 se o estágio não for reconhecido.
 */
export function stageToStationIndex(stage) {
  if (!stage) return -1;
  const clean = String(stage).toUpperCase().trim();
  for (const st of STATIONS_CONFIG) {
    if (st.stages.includes(clean)) {
      return st.index;
    }
  }
  return -1;
}

/**
 * Escolhe deterministamente qual execução exibir na Oficina:
 * 1. RUNNING com started_at mais recente.
 *    Se houver mais de uma, adiciona aviso "+N em produção".
 * 2. Se nenhuma RUNNING, busca FAILED recente (com pose de erro e motivo).
 * 3. Caso contrário, estado IDLE ("Nenhum canal produzindo agora").
 */
export function resolveActiveExecution(channels) {
  if (!Array.isArray(channels) || channels.length === 0) {
    return {
      execution: null,
      mode: 'IDLE',
      runningCount: 0,
      badgeExtra: null,
    };
  }

  const runningList = [];
  const failedList = [];

  for (const ch of channels) {
    const exec = ch.execution || (ch.status === 'RUNNING' || ch.status === 'FAILED' ? ch : null);
    if (!exec) continue;

    const status = String(exec.status || ch.status || '').toUpperCase();
    const enriched = {
      ...exec,
      channel_name: exec.channel_name || ch.channel_name || exec.profile_name || ch.profile_name,
      profile_name: exec.profile_name || ch.profile_name,
      profile_id: exec.profile_id || ch.profile_id,
      status,
    };

    if (status === 'RUNNING') {
      runningList.push(enriched);
    } else if (status === 'FAILED') {
      failedList.push(enriched);
    }
  }

  if (runningList.length > 0) {
    runningList.sort((a, b) => {
      const ta = a.started_at ? new Date(a.started_at).getTime() : 0;
      const tb = b.started_at ? new Date(b.started_at).getTime() : 0;
      return tb - ta;
    });

    const primary = runningList[0];
    const runningCount = runningList.length;
    const badgeExtra = runningCount > 1 ? `+${runningCount - 1} em produção` : null;

    return {
      execution: primary,
      mode: 'RUNNING',
      runningCount,
      badgeExtra,
    };
  }

  if (failedList.length > 0) {
    failedList.sort((a, b) => {
      const ta = a.updated_at || a.started_at ? new Date(a.updated_at || a.started_at).getTime() : 0;
      const tb = b.updated_at || b.started_at ? new Date(b.updated_at || b.started_at).getTime() : 0;
      return tb - ta;
    });

    return {
      execution: failedList[0],
      mode: 'FAILED',
      runningCount: 0,
      badgeExtra: null,
    };
  }

  return {
    execution: null,
    mode: 'IDLE',
    runningCount: 0,
    badgeExtra: null,
  };
}

/**
 * Formata o texto do balão de fala de uma estação de trabalho.
 */
export function formatStationBubble(station, execution) {
  if (!station) return null;
  const prov = String(execution?.provider || '').toLowerCase();
  const isFlow = prov.includes('flow');

  if (station.id === 'cenas' && isFlow) {
    return 'gerando no Google Flow…';
  }
  return station.defaultBubble || 'trabalhando…';
}

/**
 * Calcula o estado, pose (idle, working, happy, error) e progresso de cada uma das 6 estações.
 */
export function computeStationStates(activeExecution, mode) {
  if (mode === 'IDLE' || !activeExecution) {
    return STATIONS_CONFIG.map((st) => ({
      index: st.index,
      id: st.id,
      name: st.name,
      numLabel: st.numLabel,
      sprite: st.sprite,
      pose: 'idle',
      bgPos: '0px 0px',
      isWorking: false,
      alt: `${st.name}: aguardando`,
      barPct: 0,
      color: '#3A4262',
      bubble: null,
    }));
  }

  const rawStage = activeExecution.pipeline_stage;
  let currIdx = stageToStationIndex(rawStage);
  if (currIdx < 0) {
    currIdx = 0;
  }

  if (mode === 'RUNNING') {
    return STATIONS_CONFIG.map((st) => {
      const i = st.index;
      if (i < currIdx) {
        return {
          index: i,
          id: st.id,
          name: st.name,
          numLabel: st.numLabel,
          sprite: st.sprite,
          pose: 'happy',
          bgPos: '-288px 0px',
          isWorking: false,
          alt: `${st.name}: concluído`,
          barPct: 100,
          color: '#34D399',
          bubble: null,
        };
      }
      if (i === currIdx) {
        const bubble = formatStationBubble(st, activeExecution);
        const progressVal = typeof activeExecution.progress === 'number' ? activeExecution.progress : 50;
        return {
          index: i,
          id: st.id,
          name: st.name,
          numLabel: st.numLabel,
          sprite: st.sprite,
          pose: 'working',
          bgPos: '-144px 0px',
          isWorking: true,
          alt: `${st.name}: em andamento`,
          barPct: Math.min(100, Math.max(5, progressVal)),
          color: st.hue,
          bubble,
        };
      }
      return {
        index: i,
        id: st.id,
        name: st.name,
        numLabel: st.numLabel,
        sprite: st.sprite,
        pose: 'idle',
        bgPos: '0px 0px',
        isWorking: false,
        alt: `${st.name}: na fila`,
        barPct: 0,
        color: '#3A4262',
        bubble: null,
      };
    });
  }

  if (mode === 'FAILED') {
    return STATIONS_CONFIG.map((st) => {
      const i = st.index;
      if (i < currIdx) {
        return {
          index: i,
          id: st.id,
          name: st.name,
          numLabel: st.numLabel,
          sprite: st.sprite,
          pose: 'happy',
          bgPos: '-288px 0px',
          isWorking: false,
          alt: `${st.name}: concluído`,
          barPct: 100,
          color: '#34D399',
          bubble: null,
        };
      }
      if (i === currIdx) {
        const errReason =
          activeExecution.gate_reason ||
          activeExecution.gates?.gate_reason ||
          activeExecution.error ||
          'rejeitado na etapa';
        return {
          index: i,
          id: st.id,
          name: st.name,
          numLabel: st.numLabel,
          sprite: st.sprite,
          pose: 'error',
          bgPos: '-432px 0px',
          isWorking: false,
          alt: `${st.name}: falha`,
          barPct: 100,
          color: '#FF5A4D',
          bubble: errReason,
        };
      }
      return {
        index: i,
        id: st.id,
        name: st.name,
        numLabel: st.numLabel,
        sprite: st.sprite,
        pose: 'idle',
        bgPos: '0px 0px',
        isWorking: false,
        alt: `${st.name}: cancelado`,
        barPct: 0,
        color: '#3A4262',
        bubble: null,
      };
    });
  }

  // Fallback idle
  return STATIONS_CONFIG.map((st) => ({
    index: st.index,
    id: st.id,
    name: st.name,
    numLabel: st.numLabel,
    sprite: st.sprite,
    pose: 'idle',
    bgPos: '0px 0px',
    isWorking: false,
    alt: `${st.name}: aguardando`,
    barPct: 0,
    color: '#3A4262',
    bubble: null,
  }));
}

/**
 * Formata o tempo decorrido desde started_at no formato "45s", "2m 15s", "1h 10m".
 */
export function formatElapsedTime(startedAt, now = Date.now()) {
  if (!startedAt) return null;
  const t = new Date(startedAt).getTime();
  if (isNaN(t) || t <= 0) return null;

  const nowMs = typeof now === 'number' ? now : new Date(now).getTime();
  const diffSec = Math.max(0, Math.floor((nowMs - t) / 1000));

  if (diffSec < 60) {
    return `${diffSec}s`;
  }
  const mins = Math.floor(diffSec / 60);
  const secs = diffSec % 60;
  if (mins < 60) {
    return `${mins}m ${secs}s`;
  }
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hours}h ${remMins}m`;
}

/**
 * Retorna as coordenadas e visual do courier (entregador) entre as estações.
 */
export function computeCourierState(activeExecution, mode, activeStationIdx) {
  const safeIdx = Math.max(0, Math.min(5, typeof activeStationIdx === 'number' ? activeStationIdx : 0));
  const stConfig = STATIONS_CONFIG[safeIdx] || STATIONS_CONFIG[0];
  const pos = stConfig.pos;

  const left = `${pos[0] + 2}px`;
  const top = `${pos[1] + 62}px`;

  const name = activeExecution?.channel_name || activeExecution?.profile_name || '';
  const ini = name
    ? name
        .split(/[\s_]+/)
        .map((w) => w.charAt(0))
        .join('')
        .slice(0, 3)
        .toUpperCase()
    : 'VF';

  const prov = String(activeExecution?.provider || '').toLowerCase();
  const isFlow = prov.includes('flow');
  const chipColor = isFlow ? '#C7A9FF' : '#7BE3D0';

  const isFinished = mode === 'SUCCESS' || (activeStationIdx === 5 && mode === 'RUNNING' && activeExecution?.progress === 100);
  const bgPos = isFinished ? '-380px 0px' : '-304px 0px';

  return {
    left,
    top,
    ini,
    chipColor,
    bgPos,
    isFinished,
  };
}
