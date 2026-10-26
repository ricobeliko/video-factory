import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  getSystemStatus,
  getProviderHealth,
  getHealth,
  getChannelsOverview,
  getProfileSettings,
  pauseFactory,
  resumeFactory,
} from '../../api';
import {
  formatFactoryState,
  formatInstanceRole,
  formatHeartbeat,
  canToggleFactory,
  formatApiError,
  formatProviderValue,
  formatQuotasDisplay,
  formatScheduleDisplay,
} from './systemLogic';
import '../Fleet/fleet.css';
import './system.css';

const POLL_INTERVAL_MS = 15000;

export default function SystemView({ onNavigate }) {
  // Dados de estado do sistema
  const [systemStatus, setSystemStatus] = useState(null);
  const [providersHealth, setProvidersHealth] = useState(null);
  const [apiHealth, setApiHealth] = useState(null);
  const [channelsData, setChannelsData] = useState([]);
  const [channelSettingsMap, setChannelSettingsMap] = useState({});

  // Estados de controle e ciclo de vida
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionFeedback, setActionFeedback] = useState(null);
  const [isActionPending, setIsActionPending] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null); // { type: 'pause' | 'resume' }

  // Temporizadores
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);
  const isFetchingRef = useRef(false);

  // Busca dados de todos os endpoints do sistema
  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const [sysRes, provRes, healthRes, chanRes] = await Promise.allSettled([
        getSystemStatus(),
        getProviderHealth(),
        getHealth(),
        getChannelsOverview(),
      ]);

      if (sysRes.status === 'fulfilled' && sysRes.value) {
        setSystemStatus(sysRes.value.data || sysRes.value);
      }
      if (provRes.status === 'fulfilled' && provRes.value) {
        setProvidersHealth(provRes.value.data || provRes.value);
      }
      if (healthRes.status === 'fulfilled' && healthRes.value) {
        setApiHealth(healthRes.value.data || healthRes.value);
      }
      if (chanRes.status === 'fulfilled' && chanRes.value) {
        const rawChannels = chanRes.value.data?.channels || chanRes.value.channels || [];
        setChannelsData(rawChannels);

        // Busca settings individuais para cada canal para garantir detalhes de workspace e agendamento
        const settingsPromises = rawChannels.map(async (c) => {
          const pid = c.profile_id || c.channel_id;
          try {
            const sRes = await getProfileSettings(pid);
            return { pid, settings: sRes.data || sRes };
          } catch {
            return { pid, settings: c.settings || null };
          }
        });

        Promise.all(settingsPromises).then((results) => {
          const newMap = {};
          results.forEach((r) => {
            if (r.pid) newMap[r.pid] = r.settings;
          });
          setChannelSettingsMap((prev) => ({ ...prev, ...newMap }));
        });
      }

      // Se todas falharem, reporta erro geral mantendo o último dado bom
      if (
        sysRes.status === 'rejected' &&
        provRes.status === 'rejected' &&
        healthRes.status === 'rejected'
      ) {
        throw new Error('Falha de conexão com os serviços do sistema.');
      }

      setError(null);
      setLastFetchTime(new Date());
      setSecondsSinceSync(0);
    } catch (err) {
      console.warn('Erro ao atualizar dados do sistema:', err.message);
      setError(err.message || 'Falha ao atualizar dados do sistema.');
    } finally {
      isFetchingRef.current = false;
      setIsLoading(false);
    }
  }, []);

  // Polling a cada 15 segundos, pausado com aba oculta
  useEffect(() => {
    fetchData();

    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchData();
      }
    }, POLL_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchData();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchData]);

  // Contador de segundos desde a última sincronização
  useEffect(() => {
    const timer = setInterval(() => {
      if (lastFetchTime) {
        const diff = Math.floor((Date.now() - lastFetchTime.getTime()) / 1000);
        setSecondsSinceSync(Math.max(0, diff));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [lastFetchTime]);

  const handleNavClick = (tab) => {
    if (onNavigate) {
      onNavigate(tab);
    } else {
      window.location.hash = `#${tab}`;
    }
  };

  // Resoluções de dados
  const instance = useMemo(() => systemStatus?.instance || {}, [systemStatus]);
  const factoryStateInfo = useMemo(() => formatFactoryState(systemStatus), [systemStatus]);
  const roleInfo = useMemo(() => formatInstanceRole(instance), [instance]);
  const togglePermission = useMemo(() => canToggleFactory(instance), [instance]);

  const isPaused = factoryStateInfo.isPaused;

  // Ações de Pausar / Retomar a Fábrica
  const handleOpenConfirm = (actionType) => {
    setActionFeedback(null);
    setConfirmDialog(actionType);
  };

  const handleCloseConfirm = () => {
    if (!isActionPending) {
      setConfirmDialog(null);
    }
  };

  const handleExecuteToggle = async () => {
    if (!confirmDialog) return;
    setIsActionPending(true);
    setActionFeedback(null);

    const action = confirmDialog;
    try {
      if (action === 'pause') {
        await pauseFactory();
        setActionFeedback({
          type: 'success',
          text: 'Fábrica pausada com sucesso. Tarefas em andamento continuam até o fim; novas tarefas foram bloqueadas.',
        });
      } else {
        await resumeFactory();
        setActionFeedback({
          type: 'success',
          text: 'Fábrica retomada com sucesso. Processamento e ciclos autônomos reabilitados.',
        });
      }
      setConfirmDialog(null);
      await fetchData();
    } catch (err) {
      const errText = formatApiError(err, action === 'pause' ? 'pausar a fábrica' : 'retomar a fábrica');
      setActionFeedback({
        type: 'error',
        text: errText,
      });
      setConfirmDialog(null);
    } finally {
      setIsActionPending(false);
    }
  };

  return (
    <div className="fleet-root">
      {/* 1. Header Bar com identidade visual idêntica à Frota e Produção */}
      <header className="fleet-header" aria-label="Cabeçalho do Sistema">
        <div className="fleet-brand">
          <div className="fleet-brand-logo" aria-hidden="true">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#0A0C11"
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 4l14 8-14 8z" />
            </svg>
          </div>
          <span className="fleet-brand-title">Video Factory</span>
          <span className="fleet-mono fleet-brand-badge">V2</span>
        </div>

        <nav className="fleet-nav" aria-label="Navegação da Aplicação">
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('frota')}
          >
            Frota
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('producao')}
          >
            Produção
          </button>
          <button type="button" className="fleet-nav-link" disabled title="Em breve">
            <span>Publicação</span>
            <span className="fleet-nav-soon">em breve</span>
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('video-review')}
          >
            Revisão
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('factory-live')}
          >
            Factory Live
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('agent-ops')}
          >
            Agent Ops
          </button>
          <button type="button" className="fleet-nav-link active">
            Sistema
          </button>
        </nav>

        <div className="fleet-header-right">
          <div className="fleet-sync-pill" title="Intervalo automático de 15 segundos">
            <span className="fleet-live-dot" aria-hidden="true" />
            <span className="fleet-sync-text">
              {lastFetchTime ? `atualizado há ${secondsSinceSync}s` : 'conectando...'}
            </span>
          </div>

          <button
            type="button"
            className="fleet-icon-btn"
            onClick={fetchData}
            title="Atualizar dados do sistema agora"
            aria-label="Atualizar dados agora"
          >
            ↻
          </button>
        </div>
      </header>

      {/* 2. Conteúdo Principal do Sistema */}
      <main className="sys-main">
        {/* Banner de Erro Global */}
        {error && (
          <div className="sys-error-banner" role="alert">
            <span>⚠️ {error}</span>
            <button type="button" className="sys-retry-btn" onClick={fetchData}>
              Tentar de novo
            </button>
          </div>
        )}

        {/* Feedback de Ação (Sucesso ou Erro) */}
        {actionFeedback && (
          <div
            className={`sys-action-feedback sys-action-feedback--${actionFeedback.type}`}
            role="status"
          >
            {actionFeedback.type === 'error' ? '⚠️ ' : '✓ '}
            {actionFeedback.text}
          </div>
        )}

        {/* Título da Tela */}
        <div className="fleet-title-bar">
          <div>
            <h1 className="fleet-title">Sistema</h1>
            <p className="fleet-subtitle">
              Estado operacional da fábrica, controle de execução, integridade de provedores e ajustes dos canais.
            </p>
          </div>
        </div>

        {/* 3. Grid Superior: Cartão Fábrica e Cartão Prontidão */}
        <div className="sys-grid-top">
          {/* Cartão 1: Fábrica */}
          <section className="sys-card" aria-labelledby="card-factory-title">
            <div className="sys-card-header">
              <div className="sys-card-title-group">
                <span className="sys-card-icon" aria-hidden="true">🏭</span>
                <h2 id="card-factory-title" className="sys-card-title">Fábrica</h2>
              </div>
              <span className={`sys-state-badge sys-state-badge--${factoryStateInfo.variant}`}>
                {factoryStateInfo.label}
              </span>
            </div>

            <div className="sys-card-body">
              <div className="sys-stat-row">
                <span className="sys-stat-label">Estado Operacional</span>
                <span className="sys-stat-value">
                  <strong>{factoryStateInfo.text}</strong>
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Papel da Instância</span>
                <span className="sys-stat-value">
                  <span
                    className={`sys-role-badge ${
                      roleInfo.isPrimary ? 'sys-role-badge--primary' : 'sys-role-badge--secondary'
                    }`}
                  >
                    {roleInfo.label}
                  </span>
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Worker de Geração</span>
                <span className="sys-stat-value">
                  {formatProviderValue(systemStatus?.generation_worker)}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Worker do Agendador</span>
                <span className="sys-stat-value">
                  {formatProviderValue(systemStatus?.scheduler_worker)}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Agendador Ativo</span>
                <span className="sys-stat-value">
                  {systemStatus?.scheduler_enabled ? 'ATIVO' : 'DESATIVADO'}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Auto Publicação</span>
                <span className="sys-stat-value">
                  {formatProviderValue(systemStatus?.auto_publish || (systemStatus?.auto_publish_enabled ? 'ON' : 'OFF'))}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Dry Run (Simulação)</span>
                <span className="sys-stat-value">
                  {formatProviderValue(systemStatus?.dry_run)}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Heartbeat Agendador</span>
                <span className="sys-stat-value">
                  {formatHeartbeat(systemStatus?.heartbeats?.scheduler_seconds_ago)}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Heartbeat Nó Primário</span>
                <span className="sys-stat-value">
                  {formatHeartbeat(instance?.heartbeat_seconds_ago)}
                </span>
              </div>

              {/* Botão Grande de Pausar/Retomar Fábrica */}
              <div className="sys-factory-action-area">
                <button
                  type="button"
                  className={`sys-big-btn ${
                    isPaused ? 'sys-big-btn--resume' : 'sys-big-btn--pause'
                  }`}
                  disabled={!togglePermission.canToggle || isActionPending}
                  onClick={() => handleOpenConfirm(isPaused ? 'resume' : 'pause')}
                  title={togglePermission.reason || (isPaused ? 'Retomar operações' : 'Pausar fábrica')}
                  aria-label={isPaused ? 'Retomar fábrica' : 'Pausar fábrica'}
                >
                  {isActionPending
                    ? 'Processando...'
                    : isPaused
                    ? '▶ Retomar Fábrica'
                    : '⏸ Pausar Fábrica'}
                </button>

                {!togglePermission.canToggle && (
                  <div className="sys-disabled-explanation" role="note">
                    {togglePermission.reason}
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Cartão 2: Prontidão */}
          <section className="sys-card" aria-labelledby="card-health-title">
            <div className="sys-card-header">
              <div className="sys-card-title-group">
                <span className="sys-card-icon" aria-hidden="true">🩺</span>
                <h2 id="card-health-title" className="sys-card-title">Prontidão</h2>
              </div>
              <span className="sys-pill-status sys-pill-status--healthy">
                {apiHealth?.status ? String(apiHealth.status).toUpperCase() : 'OK'}
              </span>
            </div>

            <div className="sys-card-body">
              <div className="sys-stat-row">
                <span className="sys-stat-label">Aplicação</span>
                <span className="sys-stat-value">{formatProviderValue(apiHealth?.app)}</span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Versão</span>
                <span className="sys-stat-value">{formatProviderValue(apiHealth?.version)}</span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Papel Operacional</span>
                <span className="sys-stat-value">{formatProviderValue(apiHealth?.role)}</span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Web UI V2 Pronta</span>
                <span className="sys-stat-value">
                  {apiHealth?.webui_v2_available ? 'SIM' : 'NÃO'}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Mesma Origem (Same Origin)</span>
                <span className="sys-stat-value">{apiHealth?.same_origin ? 'SIM' : 'NÃO'}</span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Nó Local</span>
                <span className="sys-stat-value">{formatProviderValue(instance?.node_name)}</span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Hostname / PID</span>
                <span className="sys-stat-value">
                  {instance?.hostname ? `${instance.hostname} (${instance.pid || '—'})` : '—'}
                </span>
              </div>

              <div className="sys-stat-row">
                <span className="sys-stat-label">Acesso Remoto</span>
                <span className="sys-stat-value" title={instance?.remote_access_url || ''}>
                  {formatProviderValue(instance?.remote_access_url)}
                </span>
              </div>
            </div>
          </section>
        </div>

        {/* 4. Cartão 3: Provedores */}
        <section className="sys-section" aria-labelledby="section-providers-title">
          <div className="sys-section-header">
            <h2 id="section-providers-title" className="sys-section-title">
              <span>🔌</span> Provedores
            </h2>
          </div>

          <div className="sys-table-container">
            <table className="sys-table" aria-label="Tabela de saúde dos provedores">
              <thead>
                <tr>
                  <th scope="col">Provedor</th>
                  <th scope="col">Estado / Saúde</th>
                  <th scope="col">Detalhes</th>
                  <th scope="col">Último Erro</th>
                  <th scope="col">Última Verificação</th>
                </tr>
              </thead>
              <tbody>
                {providersHealth && Object.keys(providersHealth).length > 0 ? (
                  Object.entries(providersHealth).map(([provName, info]) => {
                    const st = info?.status || '';
                    const stLower = String(st).toLowerCase();
                    const pillClass = stLower.includes('healthy')
                      ? 'sys-pill-status--healthy'
                      : stLower.includes('degraded')
                      ? 'sys-pill-status--degraded'
                      : stLower.includes('unavailable') || stLower.includes('error')
                      ? 'sys-pill-status--unavailable'
                      : stLower.includes('configured')
                      ? 'sys-pill-status--configured'
                      : '';

                    return (
                      <tr key={provName}>
                        <td>
                          <strong>{provName}</strong>
                        </td>
                        <td>
                          <span className={`sys-pill-status ${pillClass}`}>
                            {formatProviderValue(info?.status)}
                          </span>
                        </td>
                        <td>{formatProviderValue(info?.details)}</td>
                        <td>{formatProviderValue(info?.last_error)}</td>
                        <td>
                          <span className="fleet-mono">
                            {formatProviderValue(info?.last_checked)}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={5} style={{ textAlign: 'center', color: 'var(--fleet-muted)' }}>
                      Nenhum provedor listado ou dados indisponíveis.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* 5. Seção 4: Ajustes por canal (somente leitura) */}
        <section className="sys-section" aria-labelledby="section-channels-title">
          <div className="sys-section-header">
            <h2 id="section-channels-title" className="sys-section-title">
              <span>⚙️</span> Ajustes por Canal (Somente Leitura)
            </h2>
            <span className="sys-badge-readonly">Edição chega na próxima missão</span>
          </div>

          <div className="sys-channels-grid">
            {channelsData.length > 0 ? (
              channelsData.map((ch) => {
                const pid = ch.profile_id || ch.channel_id;
                const fullSettings = channelSettingsMap[pid] || ch.settings || {};
                const quotas = formatQuotasDisplay(fullSettings.quotas || ch.quotas);
                const schedule = formatScheduleDisplay(fullSettings.schedule || ch.schedule);
                const ws = fullSettings.workspace_settings || {};
                const growthMode = fullSettings.growth_mode || ch.growth_mode || 'WARMUP';
                const isAuto = Boolean(fullSettings.autonomous_enabled ?? ch.autonomous_enabled);

                return (
                  <article key={pid} className="sys-channel-card" aria-label={`Ajustes do canal ${ch.name || pid}`}>
                    <div className="sys-channel-header">
                      <div>
                        <h3 className="sys-channel-name">{ch.name || pid}</h3>
                        <span className="sys-channel-id">{pid}</span>
                      </div>
                      <span className="sys-role-badge">
                        {String(growthMode).toUpperCase()}
                      </span>
                    </div>

                    <div className="sys-card-body">
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Modo Autônomo</span>
                        <span className="sys-stat-value">
                          {isAuto ? 'SIM (Ativo)' : 'NÃO (Desligado)'}
                        </span>
                      </div>

                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Nicho / Formato</span>
                        <span className="sys-stat-value">
                          {formatProviderValue(ch.niche)} / {formatProviderValue(ch.format || ws.editorial?.video_format)}
                        </span>
                      </div>

                      {/* Subseção de Cotas */}
                      <h4 className="sys-channel-group-title">Cotas Operacionais</h4>
                      <div className="sys-channel-stats-grid">
                        <div className="sys-stat-row">
                          <span className="sys-stat-label">Meta Estoque</span>
                          <span className="sys-stat-value">{quotas.target_ready_stock}</span>
                        </div>
                        <div className="sys-stat-row">
                          <span className="sys-stat-label">Gerações/24h</span>
                          <span className="sys-stat-value">{quotas.max_generations_24h}</span>
                        </div>
                        <div className="sys-stat-row">
                          <span className="sys-stat-label">Tentativas/24h</span>
                          <span className="sys-stat-value">{quotas.max_attempts_24h}</span>
                        </div>
                        <div className="sys-stat-row">
                          <span className="sys-stat-label">Posts/Dia</span>
                          <span className="sys-stat-value">{quotas.posts_per_day}</span>
                        </div>
                      </div>

                      {/* Subseção de Agendamento */}
                      <h4 className="sys-channel-group-title">Janela de Publicação</h4>
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Janela Horária</span>
                        <span className="sys-stat-value">{schedule.window}</span>
                      </div>
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Fuso Horário</span>
                        <span className="sys-stat-value">{schedule.timezone}</span>
                      </div>
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Intervalo Mínimo</span>
                        <span className="sys-stat-value">{schedule.min_interval_hours}</span>
                      </div>

                      {/* Subseção de Workspace (Editorial, Voz, Visual) */}
                      <h4 className="sys-channel-group-title">Configurações de Workspace</h4>
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Voz Narrador</span>
                        <span className="sys-stat-value">
                          {formatProviderValue(ws.voice?.voice_name)}
                        </span>
                      </div>
                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Visual Director / Flow</span>
                        <span className="sys-stat-value">
                          {ws.visual?.visual_director_enabled != null
                            ? ws.visual.visual_director_enabled
                              ? 'Ativo'
                              : 'Desativado'
                            : '—'}
                        </span>
                      </div>
                    </div>
                  </article>
                );
              })
            ) : (
              <div style={{ color: 'var(--fleet-muted)', padding: '16px' }}>
                Nenhum canal carregado.
              </div>
            )}
          </div>
        </section>
      </main>

      {/* Diálogo de Confirmação para Pausar / Retomar */}
      {confirmDialog && (
        <div
          className="sys-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-modal-title"
        >
          <div className="sys-modal">
            <h3 id="confirm-modal-title" className="sys-modal-title">
              {confirmDialog === 'pause' ? '⏸ Pausar Fábrica' : '▶ Retomar Fábrica'}
            </h3>

            <p className="sys-modal-text">
              {confirmDialog === 'pause' ? (
                <>
                  Tem certeza que deseja pausar a fábrica?{' '}
                  <span className="sys-modal-highlight">
                    Isso não interrompe o vídeo em andamento; tarefas em processamento concluem normalmente, mas novas execuções e ciclos automáticos deixam de ser iniciados.
                  </span>
                </>
              ) : (
                <>
                  Deseja retomar a fábrica?{' '}
                  <span className="sys-modal-highlight">
                    O agendador e os ciclos autônomos voltarão a iniciar e processar novas tarefas normalmente.
                  </span>
                </>
              )}
            </p>

            <div className="sys-modal-actions">
              <button
                type="button"
                className="sys-btn-cancel"
                onClick={handleCloseConfirm}
                disabled={isActionPending}
              >
                Cancelar
              </button>

              <button
                type="button"
                className={
                  confirmDialog === 'pause' ? 'sys-btn-confirm-pause' : 'sys-btn-confirm-resume'
                }
                onClick={handleExecuteToggle}
                disabled={isActionPending}
              >
                {isActionPending
                  ? 'Processando...'
                  : confirmDialog === 'pause'
                  ? 'Confirmar Pausa'
                  : 'Confirmar Retomada'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
