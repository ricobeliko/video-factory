import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { getLiveExecutions } from '../../api';
import {
  STATIONS_CONFIG,
  stageToStationIndex,
  resolveActiveExecution,
  computeStationStates,
  formatElapsedTime,
  computeCourierState,
} from './workshopLogic';
import { formatVideoFormat } from './fleetLogic';
import './workshop.css';

// Sprites dos robôs e elementos
import roteiroImg from '../../assets/fleet/roteiro.png';
import narracaoImg from '../../assets/fleet/narracao.png';
import cenasImg from '../../assets/fleet/cenas.png';
import renderImg from '../../assets/fleet/render.png';
import gatesImg from '../../assets/fleet/gates.png';
import publicarImg from '../../assets/fleet/publicar.png';
import courierImg from '../../assets/fleet/courier.png';
import deskImg from '../../assets/fleet/desk.png';

const SPRITE_MAP = {
  roteiro: roteiroImg,
  narracao: narracaoImg,
  cenas: cenasImg,
  render: renderImg,
  gates: gatesImg,
  publicar: publicarImg,
};

// Intervalo de polling: endpoint levou ~2.5s no DEV (> 2s), portanto usamos 8s (8000ms) conforme especificação
const POLLING_INTERVAL_MS = 8000;

const DEMO_STAGES = [
  { stage: 'SCRIPT', label: 'Roteiro', progress: 20, provider: 'GPT-4o', bubble: 'escrevendo roteiro…' },
  { stage: 'NARRATION', label: 'Narração', progress: 35, provider: 'Edge TTS (Antônio)', bubble: 'gravando narração…' },
  { stage: 'VISUALS', label: 'Cenas', progress: 60, provider: 'Google Flow', bubble: 'gerando no Google Flow…' },
  { stage: 'RENDER', label: 'Render', progress: 80, provider: 'FFmpeg', bubble: 'renderizando vídeo…' },
  { stage: 'SAFETY', label: 'Gates', progress: 95, provider: 'Safety Gate', bubble: 'conferindo segurança…' },
  { stage: 'READY_STOCK', label: 'Publicação', progress: 100, provider: 'YouTube Post', bubble: 'pronto para agendamento!' },
];

export default function Workshop({ fleetSummary = null }) {
  // 1. Verificação segura de Modo Demonstração (?demo=1 na query string ou hash)
  const isDemo = useMemo(() => {
    if (typeof window === 'undefined') return false;
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('demo') === '1') return true;
    if (window.location.hash.includes('demo=1')) return true;
    return false;
  }, []);

  const [channels, setChannels] = useState([]);
  const [isApiOffline, setIsApiOffline] = useState(false);
  const [demoStep, setDemoStep] = useState(0);
  const [isWalking, setIsWalking] = useState(false);
  const [nowTime, setNowTime] = useState(() => Date.now());

  const isFetchingRef = useRef(false);
  const prevStationIdxRef = useRef(-1);
  const walkTimeoutRef = useRef(null);

  // 2. Polling de /api/v2/executions/live sem sobreposição e pausado quando a aba estiver oculta
  const fetchLive = useCallback(async () => {
    if (isDemo) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    if (isFetchingRef.current) return;

    isFetchingRef.current = true;
    try {
      const res = await getLiveExecutions();
      const raw = res?.data || res;
      const list = Array.isArray(raw?.channels) ? raw.channels : [];
      setChannels(list);
      setIsApiOffline(false);
    } catch (err) {
      console.warn('[Workshop] Falha no polling de /executions/live:', err.message);
      setIsApiOffline(true);
    } finally {
      isFetchingRef.current = false;
    }
  }, [isDemo]);

  useEffect(() => {
    if (isDemo) return;

    fetchLive();
    const interval = setInterval(fetchLive, POLLING_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        fetchLive();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchLive, isDemo]);

  // Timer para atualização suave de tempo decorrido
  useEffect(() => {
    const t = setInterval(() => setNowTime(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Timer do modo demonstração (cicla as etapas a cada 3.5 segundos)
  useEffect(() => {
    if (!isDemo) return;
    const interval = setInterval(() => {
      setDemoStep((prev) => (prev + 1) % DEMO_STAGES.length);
    }, 3500);
    return () => clearInterval(interval);
  }, [isDemo]);

  // 3. Determinação da execução ativa
  const { activeExecution, mode, runningCount, badgeExtra } = useMemo(() => {
    if (isDemo) {
      const stepData = DEMO_STAGES[demoStep];
      return {
        activeExecution: {
          task_id: 'demo-task-1',
          profile_id: 'demo-curiosidades',
          channel_name: 'Canal de Exemplo',
          topic: 'As 10 maiores curiosidades sobre o universo profundo',
          pipeline_stage: stepData.stage,
          pipeline_stage_label: stepData.label,
          status: 'RUNNING',
          progress: stepData.progress,
          provider: stepData.provider,
          started_at: new Date(Date.now() - (demoStep * 20 + 15) * 1000).toISOString(),
          message: stepData.bubble,
          error: null,
          gates: null,
        },
        mode: 'RUNNING',
        runningCount: 1,
        badgeExtra: null,
      };
    }
    return resolveActiveExecution(channels);
  }, [isDemo, demoStep, channels]);

  // 4. Mapeamento de canal para formato no fleetSummary
  const channelFormat = useMemo(() => {
    if (!activeExecution || !fleetSummary?.channels) return null;
    const ch = fleetSummary.channels.find(
      (c) => c.profile_id === activeExecution.profile_id || c.name === activeExecution.channel_name
    );
    return ch?.format || null;
  }, [activeExecution, fleetSummary]);

  const activeStationIdx = useMemo(() => {
    if (mode === 'IDLE' || !activeExecution) return -1;
    return stageToStationIndex(activeExecution.pipeline_stage);
  }, [mode, activeExecution]);

  // 5. Animação de caminhada do courier quando o estágio mudar
  useEffect(() => {
    if (mode === 'IDLE' || !activeExecution || activeStationIdx < 0) {
      setIsWalking(false);
      prevStationIdxRef.current = activeStationIdx;
      return;
    }

    if (prevStationIdxRef.current !== -1 && prevStationIdxRef.current !== activeStationIdx) {
      setIsWalking(true);
      if (walkTimeoutRef.current) clearTimeout(walkTimeoutRef.current);
      walkTimeoutRef.current = setTimeout(() => {
        setIsWalking(false);
      }, 1000);
    }
    prevStationIdxRef.current = activeStationIdx;

    return () => {
      if (walkTimeoutRef.current) clearTimeout(walkTimeoutRef.current);
    };
  }, [activeStationIdx, mode, activeExecution]);

  const stationStates = useMemo(() => {
    return computeStationStates(activeExecution, mode);
  }, [activeExecution, mode]);

  const courierState = useMemo(() => {
    return computeCourierState(activeExecution, mode, activeStationIdx);
  }, [activeExecution, mode, activeStationIdx]);

  const elapsedTimeStr = useMemo(() => {
    return formatElapsedTime(activeExecution?.started_at, nowTime);
  }, [activeExecution?.started_at, nowTime]);

  // Acessibilidade
  const a11ySummary = useMemo(() => {
    if (mode === 'IDLE' || !activeExecution) {
      return 'Oficina ao vivo: Nenhum canal produzindo agora.';
    }
    const chName = activeExecution.channel_name || activeExecution.profile_name || 'Canal';
    const stLabel =
      activeExecution.pipeline_stage_label || activeExecution.pipeline_stage || 'Etapa';
    if (mode === 'FAILED') {
      const reason =
        activeExecution.gate_reason ||
        activeExecution.gates?.gate_reason ||
        activeExecution.error ||
        'Motivo não informado pela fábrica';
      return `Oficina ao vivo: Canal ${chName} com falha na etapa ${stLabel}. ${reason}`;
    }
    const progText =
      typeof activeExecution.progress === 'number' && !Number.isNaN(activeExecution.progress)
        ? `, progresso ${activeExecution.progress}%`
        : '';
    return `Oficina ao vivo: Canal ${chName}, etapa ${stLabel}${progText}.`;
  }, [mode, activeExecution]);

  return (
    <div className="fleet-ws-wrapper">
      {/* Faixa de Demonstração (quando ?demo=1) */}
      {isDemo && (
        <div className="fleet-ws-demo-banner" role="alert">
          <span className="fleet-ws-demo-badge">MODO DEMO</span>
          <span>DEMONSTRAÇÃO — dados de exemplo, não é a fábrica real</span>
        </div>
      )}

      {/* Leitor de tela (Live region) */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {a11ySummary}
      </div>

      <div className="fleet-ws-layout">
        {/* Lado Esquerdo: Canvas da Oficina dos Robôs */}
        <div className="fleet-ws-canvas-container" aria-label="Visualização gráfica da oficina de robôs">
          <div className="fleet-ws-canvas">
            {/* SVG da Linha de Produção Delineada (esteira mecânica) */}
            <svg
              width="780"
              height="420"
              className="fleet-ws-svg-conveyor"
              aria-hidden="true"
            >
              <path
                d="M110 168 H670 V350 H110"
                fill="none"
                stroke="var(--fleet-ws-conveyor)"
                strokeWidth="2"
                strokeDasharray="6 6"
              />
            </svg>

            {/* Cabeçalho do Canvas */}
            <div className="fleet-ws-canvas-header">
              <span className="fleet-ws-canvas-title">Oficina · Canal da Vez</span>
              {badgeExtra && <span className="fleet-ws-badge-extra">{badgeExtra}</span>}
              {isApiOffline && <span className="fleet-ws-badge-offline">sem conexão</span>}
            </div>

            {/* As 6 Estações de Trabalho */}
            {stationStates.map((st) => {
              const cfg = STATIONS_CONFIG[st.index];
              const spriteSrc = SPRITE_MAP[st.sprite];
              const isWorkingClass = st.isWorking ? 'fleet-ws-wk' : '';
              const deskClass = st.pose === 'idle' ? 'fleet-ws-desk fleet-ws-desk-idle' : 'fleet-ws-desk';

              return (
                <div
                  key={st.id}
                  className="fleet-ws-station"
                  style={{ left: `${cfg.pos[0]}px`, top: `${cfg.pos[1]}px` }}
                  aria-label={st.alt}
                >
                  {/* Balão de fala */}
                  {st.bubble && (
                    <div
                      className={`fleet-ws-bubble ${st.pose === 'error' ? 'fleet-ws-bubble-error' : ''}`}
                      title={st.bubble}
                    >
                      {st.bubble}
                    </div>
                  )}

                  {/* Mesa decorativa */}
                  <img
                    src={deskImg}
                    alt=""
                    className={deskClass}
                    aria-hidden="true"
                  />

                  {/* Sprite do Robô */}
                  <div
                    className={`fleet-ws-robot fleet-ws-robot-${st.pose} ${isWorkingClass}`}
                    role="img"
                    aria-label={st.alt}
                    style={{
                      backgroundImage: `url(${spriteSrc})`,
                      backgroundPosition: st.bgPos,
                    }}
                  />

                  {/* Rodapé da estação com label e mini barra de progresso */}
                  <div className="fleet-ws-station-footer">
                    <span
                      className="fleet-ws-station-label fleet-mono"
                      style={{
                        color:
                          st.pose === 'idle'
                            ? '#6F7DA8'
                            : st.pose === 'error'
                            ? '#FF8A7A'
                            : '#E8EBF1',
                      }}
                    >
                      {st.numLabel}
                    </span>
                    <span className="fleet-ws-station-bar-track">
                      {st.barPct > 0 ? (
                        <span
                          className="fleet-ws-station-bar-fill"
                          style={{
                            width: `${st.barPct}%`,
                            backgroundColor:
                              st.pose === 'error'
                                ? '#FF5A4D'
                                : st.pose === 'happy'
                                ? '#34D399'
                                : st.color,
                          }}
                        />
                      ) : null}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* Courier (Entregador carregando o vídeo) */}
            <div
              className="fleet-ws-courier"
              style={{
                left: courierState.left,
                top: courierState.top,
              }}
              aria-hidden="true"
            >
              <div
                className="fleet-ws-courier-chip fleet-mono"
                style={{ backgroundColor: courierState.chipColor }}
              >
                {courierState.ini}
              </div>
              <div
                className={`fleet-ws-courier-sprite ${isWalking ? 'fleet-ws-cw' : ''}`}
                style={{
                  backgroundImage: `url(${courierImg})`,
                  backgroundPosition: isWalking ? undefined : courierState.bgPos,
                }}
              />
            </div>
          </div>
        </div>

        {/* Lado Direito: Cartão de Identificação da Execução */}
        <div className="fleet-ws-panel">
          <div className="fleet-ws-card" aria-label="Identificação da produção atual">
            <div className="fleet-ws-card-header">
              <span className="fleet-ws-card-tag fleet-mono">Agora na Oficina</span>
              {mode === 'RUNNING' && (
                <span className="fleet-ws-status-badge fleet-ws-status-running fleet-mono">
                  PRODUZINDO
                </span>
              )}
              {mode === 'FAILED' && (
                <span className="fleet-ws-status-badge fleet-ws-status-failed fleet-mono">
                  FALHA
                </span>
              )}
              {mode === 'IDLE' && (
                <span className="fleet-ws-status-badge fleet-ws-status-idle fleet-mono">
                  EM ESPERA
                </span>
              )}
            </div>

            {mode === 'IDLE' || !activeExecution ? (
              <div className="fleet-ws-card-idle-msg">
                Nenhum canal produzindo agora.
                <br />
                A fábrica produz um canal por vez e ativará a oficina assim que a próxima tarefa
                entrar em processamento.
              </div>
            ) : (
              <>
                {/* Nome do Canal e Chips */}
                <div>
                  <div className="fleet-ws-card-channel-name">
                    {activeExecution.channel_name || activeExecution.profile_name || 'Canal Ativo'}
                  </div>
                  <div className="fleet-ws-card-meta-row">
                    {channelFormat && (
                      <span
                        className="fleet-ws-chip-format"
                        style={{ color: formatVideoFormat(channelFormat).color }}
                      >
                        {formatVideoFormat(channelFormat).label}
                      </span>
                    )}
                    {activeExecution.provider && (
                      <span className="fleet-ws-chip-provider">
                        {activeExecution.provider}
                      </span>
                    )}
                    {(activeExecution.pipeline_stage_label || activeExecution.pipeline_stage) && (
                      <span className="fleet-mono">
                        {activeExecution.pipeline_stage_label || activeExecution.pipeline_stage}
                      </span>
                    )}
                  </div>
                </div>

                {/* Assunto / Tópico do Vídeo */}
                {activeExecution.topic && (
                  <div className="fleet-ws-card-topic">
                    {activeExecution.topic}
                  </div>
                )}

                {/* Barra de Progresso */}
                {typeof activeExecution.progress === 'number' &&
                  !Number.isNaN(activeExecution.progress) && (
                    <div className="fleet-ws-card-progress-row">
                      <span className="fleet-ws-card-progress-track">
                        <span
                          className="fleet-ws-card-progress-fill"
                          style={{
                            width: `${Math.min(100, Math.max(0, activeExecution.progress))}%`,
                            backgroundColor: mode === 'FAILED' ? '#FF5A4D' : '#6AA8FF',
                          }}
                        />
                      </span>
                      <span className="fleet-ws-card-progress-val fleet-mono">
                        {Math.round(activeExecution.progress)}%
                      </span>
                    </div>
                  )}

                {/* Bloco de Falha em destaque */}
                {mode === 'FAILED' && (
                  <div className="fleet-ws-card-error-box" role="alert">
                    <div className="fleet-ws-card-error-title">
                      Motivo da falha:
                    </div>
                    <div>
                      {activeExecution.gate_reason ||
                        activeExecution.gates?.gate_reason ||
                        activeExecution.error ||
                        'Motivo não informado pela fábrica'}
                    </div>
                  </div>
                )}

                {/* Lista de Metadados Informativos */}
                <div className="fleet-ws-card-info-list fleet-mono">
                  {elapsedTimeStr && (
                    <div className="fleet-ws-card-info-row">
                      <span className="fleet-ws-card-info-label">Tempo decorrido:</span>
                      <span className="fleet-ws-card-info-value">{elapsedTimeStr}</span>
                    </div>
                  )}

                  {activeExecution.task_id && (
                    <div className="fleet-ws-card-info-row">
                      <span className="fleet-ws-card-info-label">Tarefa:</span>
                      <span className="fleet-ws-card-info-value" title={activeExecution.task_id}>
                        {activeExecution.task_id.slice(0, 12)}…
                      </span>
                    </div>
                  )}

                  {activeExecution.message && mode !== 'FAILED' && (
                    <div className="fleet-ws-card-info-row">
                      <span className="fleet-ws-card-info-label">Status:</span>
                      <span className="fleet-ws-card-info-value" title={activeExecution.message}>
                        {activeExecution.message}
                      </span>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
