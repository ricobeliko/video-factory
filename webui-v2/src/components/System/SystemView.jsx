import { formatStatus } from '../Fleet/fleetLogic';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  getSystemStatus,
  getProviderHealth,
  getHealth,
  getChannelsOverview,
  getProfileSettings,
  updateProfileGrowthMode,
  updateProfileAutonomousMode,
  updateProfileQuotas,
  updateProfileSchedule,
  updateProfileVoice,
  getAllowedVoices,
  pauseFactory,
  resumeFactory,
  runFactoryCycle,
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
import {
  validateChannelForm,
  calculateSettingsDiff,
  buildPatchPayloads,
  formatDiffValueDisplay,
  parseSystemChannelFromHash,
} from './systemEditLogic';
import {
  getVoiceSourceInfo,
  validateVoiceField,
  validateVoiceForm,
  calculateVoiceDiff,
  buildVoicePatchPayload,
  formatVoiceDiffDisplay,
  QUIZ_VOICE_RATE_NOTICE,
} from './voiceEditLogic';
import '../Fleet/fleet.css';
import './system.css';

const POLL_INTERVAL_MS = 15000;

export default function SystemView({ onNavigate, focusChannelId }) {
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
  const [confirmDialog, setConfirmDialog] = useState(null); // 'pause' | 'resume' | 'run-cycle' | null

  // Estados de Edição de Ajustes por Canal (SIS2 + Controles Únicos)
  const [editingChannelId, setEditingChannelId] = useState(null);
  const [channelFormData, setChannelFormData] = useState({});
  const [channelFormErrors, setChannelFormErrors] = useState({});
  const [channelConfirmDialog, setChannelConfirmDialog] = useState(null); // { profileId, profileName, diffList, payloads }
  const [isSavingChannel, setIsSavingChannel] = useState(false);
  const [allowedVoices, setAllowedVoices] = useState([]);
  const [pinnedVoiceFields, setPinnedVoiceFields] = useState(new Set());
  const handledFocusChannelRef = useRef(null);

  // Temporizadores
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);
  const isFetchingRef = useRef(false);

  // Busca dados de todos os endpoints do sistema
  const fetchData = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;

    try {
      const [sysRes, provRes, healthRes, chanRes, voiceRes] = await Promise.allSettled([
        getSystemStatus(),
        getProviderHealth(),
        getHealth(),
        getChannelsOverview(),
        getAllowedVoices(),
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
      if (voiceRes.status === 'fulfilled' && voiceRes.value) {
        const rawV = voiceRes.value.data || voiceRes.value || [];
        setAllowedVoices(Array.isArray(rawV) ? rawV : []);
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

  // Polling a cada 15 segundos, pausado com aba oculta ou enquanto edita
  useEffect(() => {
    fetchData();

    const interval = setInterval(() => {
      // Não sobrescreve enquanto o usuário estiver ativamente editando um canal
      if (document.visibilityState === 'visible' && !editingChannelId) {
        fetchData();
      }
    }, POLL_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && !editingChannelId) {
        fetchData();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchData, editingChannelId]);

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
      } else if (action === 'resume') {
        await resumeFactory();
        setActionFeedback({
          type: 'success',
          text: 'Fábrica retomada com sucesso. Processamento e ciclos autônomos reabilitados.',
        });
      } else if (action === 'run-cycle') {
        await runFactoryCycle({ force: true, oneShot: true });
        setActionFeedback({
          type: 'success',
          text: 'Ciclo disparado com sucesso. Processamento autônomo supervisionado iniciado em segundo plano.',
        });
      }
      setConfirmDialog(null);
      await fetchData();
    } catch (err) {
      const actionLabel =
        action === 'pause'
          ? 'pausar a fábrica'
          : action === 'resume'
          ? 'retomar a fábrica'
          : 'rodar 1 ciclo da fábrica';
      const errText = formatApiError(err, actionLabel);
      setActionFeedback({
        type: 'error',
        text: errText,
      });
      setConfirmDialog(null);
    } finally {
      setIsActionPending(false);
    }
  };

  // -------------------------------------------------------------
  // Handlers de Edição de Ajustes por Canal (SIS2 + Controles Únicos)
  // -------------------------------------------------------------
  const handleStartEdit = useCallback(
    (channel) => {
      if (!togglePermission.canToggle) return;
      setActionFeedback(null);

      const pid = channel.profile_id || channel.channel_id;
      const fullSettings = channelSettingsMap[pid] || channel.settings || {};
      const quotas = fullSettings.quotas || channel.quotas || {};
      const schedule = fullSettings.schedule || channel.schedule || {};
      const effVoice = fullSettings.effective_voice || {};
      const isQuiz = Boolean(fullSettings.is_quiz ?? channel.is_quiz);
      const growthMode = String(fullSettings.growth_mode || channel.growth_mode || 'WARMUP').toUpperCase();
      const isAuto = Boolean(fullSettings.autonomous_enabled ?? channel.autonomous_enabled);

      setEditingChannelId(pid);
      setPinnedVoiceFields(new Set());
      setChannelFormData({
        growth_mode: growthMode,
        autonomous_enabled: isAuto,
        target_ready_stock: quotas.target_ready_stock ?? 3,
        max_generations_24h: quotas.max_generations_24h ?? (growthMode === 'SCALE' ? 5 : 2),
        posts_per_day: quotas.posts_per_day ?? schedule.posts_per_day ?? 1,
        publish_start_hour: schedule.publish_start_hour ?? 10,
        publish_end_hour: schedule.publish_end_hour ?? 22,
        min_interval_hours: schedule.min_interval_hours ?? 4,
        voice_name: effVoice.voice_name?.value || (allowedVoices[0]?.id || ''),
        voice_rate: isQuiz ? null : (effVoice.voice_rate?.value ?? 1.0),
        voice_volume: effVoice.voice_volume?.value ?? 1.0,
      });
      setChannelFormErrors({});
    },
    [togglePermission.canToggle, channelSettingsMap, allowedVoices]
  );

  // Rola e abre a edição do canal quando acionado pelo atalho "Editar em Sistema"
  useEffect(() => {
    const targetId =
      focusChannelId ||
      (typeof window !== 'undefined' ? parseSystemChannelFromHash(window.location.hash) : null);

    if (!targetId || channelsData.length === 0) return;
    if (handledFocusChannelRef.current === targetId) return;

    const targetChannel = channelsData.find((c) => (c.profile_id || c.channel_id) === targetId);
    if (!targetChannel) return;

    // Aguarda carregamento de settings do canal para popular o formulário com valores reais
    if (!channelSettingsMap[targetId] && isLoading) return;

    handledFocusChannelRef.current = targetId;

    if (typeof document !== 'undefined') {
      const cardEl = document.getElementById(`sys-channel-${targetId}`);
      if (cardEl && typeof cardEl.scrollIntoView === 'function') {
        cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }

    if (togglePermission.canToggle) {
      handleStartEdit(targetChannel);
    }
  }, [focusChannelId, channelsData, channelSettingsMap, isLoading, togglePermission.canToggle, handleStartEdit]);

  const handleCancelEdit = () => {
    setEditingChannelId(null);
    setPinnedVoiceFields(new Set());
    setChannelFormData({});
    setChannelFormErrors({});
  };

  const handleTogglePinVoice = (field) => {
    setPinnedVoiceFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
  };

  const handleResetVoiceInherit = (field) => {
    setChannelFormData((prev) => ({
      ...prev,
      [field]: null,
    }));
    setChannelFormErrors((prev) => {
      const copy = { ...prev };
      delete copy[field];
      return copy;
    });
  };

  const handleFieldChange = (field, value) => {
    const normalizedVal =
      field === 'autonomous_enabled'
        ? value === true || value === 'true'
        : value;
    const updated = { ...channelFormData, [field]: normalizedVal };
    setChannelFormData(updated);

    if (['voice_name', 'voice_rate', 'voice_volume'].includes(field)) {
      const activeChannel = channelsData.find((c) => (c.profile_id || c.channel_id) === editingChannelId);
      const fullSettings = channelSettingsMap[editingChannelId] || activeChannel?.settings || {};
      const isQuiz = Boolean(fullSettings.is_quiz ?? activeChannel?.is_quiz);
      const valRes = validateVoiceField(field, normalizedVal, {
        isQuiz,
        allowedVoiceIds: allowedVoices.map((v) => v.id),
      });
      setChannelFormErrors((prev) => {
        const copy = { ...prev };
        if (valRes.isValid) {
          delete copy[field];
        } else {
          copy[field] = valRes.error;
        }
        return copy;
      });
    } else {
      const valResult = validateChannelForm(updated);
      setChannelFormErrors((prev) => {
        const copy = { ...prev };
        // Atualiza erros de modo, cota e agendamento
        for (const k of [
          'growth_mode',
          'autonomous_enabled',
          'target_ready_stock',
          'max_generations_24h',
          'posts_per_day',
          'publish_start_hour',
          'publish_end_hour',
          'min_interval_hours',
        ]) {
          if (valResult.errors[k]) {
            copy[k] = valResult.errors[k];
          } else {
            delete copy[k];
          }
        }
        return copy;
      });
    }
  };

  const handleSaveClick = (channel) => {
    const valResult = validateChannelForm(channelFormData);
    const pid = channel.profile_id || channel.channel_id;
    const fullSettings = channelSettingsMap[pid] || channel.settings || {};
    const isQuiz = Boolean(fullSettings.is_quiz ?? channel.is_quiz);
    const voiceValResult = validateVoiceForm(channelFormData, {
      isQuiz,
      allowedVoiceIds: allowedVoices.map((v) => v.id),
    });

    const combinedErrors = { ...valResult.errors, ...voiceValResult.errors };
    if (Object.keys(combinedErrors).length > 0) {
      setChannelFormErrors(combinedErrors);
      return;
    }

    const origQuotas = fullSettings.quotas || channel.quotas || {};
    const origSchedule = fullSettings.schedule || channel.schedule || {};
    const origGrowthMode = String(fullSettings.growth_mode || channel.growth_mode || 'WARMUP').toUpperCase();
    const origAuto = Boolean(fullSettings.autonomous_enabled ?? channel.autonomous_enabled);
    const orig = {
      growth_mode: origGrowthMode,
      autonomous_enabled: origAuto,
      target_ready_stock: origQuotas.target_ready_stock ?? 3,
      max_generations_24h: origQuotas.max_generations_24h ?? (origGrowthMode === 'SCALE' ? 5 : 2),
      posts_per_day: origQuotas.posts_per_day ?? origSchedule.posts_per_day ?? 1,
      publish_start_hour: origSchedule.publish_start_hour ?? 10,
      publish_end_hour: origSchedule.publish_end_hour ?? 22,
      min_interval_hours: origSchedule.min_interval_hours ?? 4,
    };

    const settingsDiffList = calculateSettingsDiff(orig, channelFormData);
    const voiceDiffList = calculateVoiceDiff(fullSettings.effective_voice, channelFormData, {
      isQuiz,
      pinned: pinnedVoiceFields,
    });

    if (settingsDiffList.length === 0 && voiceDiffList.length === 0) {
      setActionFeedback({
        type: 'error',
        text: 'Nenhum campo foi alterado.',
      });
      return;
    }

    const payloads = buildPatchPayloads(settingsDiffList);
    const voicePayloadResult = buildVoicePatchPayload(voiceDiffList);

    setChannelConfirmDialog({
      profileId: pid,
      profileName: channel.name || pid,
      diffList: [...settingsDiffList, ...voiceDiffList],
      payloads: {
        ...payloads,
        voicePayload: voicePayloadResult.payload,
      },
    });
  };

  const handleCloseChannelConfirm = () => {
    if (!isSavingChannel) {
      setChannelConfirmDialog(null);
    }
  };

  const handleConfirmSaveChannel = async () => {
    if (!channelConfirmDialog) return;
    setIsSavingChannel(true);
    setActionFeedback(null);

    const { profileId, profileName, payloads } = channelConfirmDialog;

    try {
      // Dispara PATCH apenas para as seções que sofreram alteração, reaproveitando as rotas existentes
      if (payloads.growthModePayload !== null && payloads.growthModePayload !== undefined) {
        await updateProfileGrowthMode(profileId, payloads.growthModePayload);
      }
      if (payloads.autonomousPayload !== null && payloads.autonomousPayload !== undefined) {
        await updateProfileAutonomousMode(profileId, payloads.autonomousPayload);
      }
      if (payloads.quotasPayload) {
        await updateProfileQuotas(profileId, payloads.quotasPayload);
      }
      if (payloads.schedulePayload) {
        await updateProfileSchedule(profileId, payloads.schedulePayload);
      }
      if (payloads.voicePayload) {
        await updateProfileVoice(profileId, payloads.voicePayload);
      }

      setActionFeedback({
        type: 'success',
        text: `Ajustes do canal "${profileName}" gravados com sucesso! Entram em vigor imediatamente no próximo ciclo.`,
      });
      setChannelConfirmDialog(null);
      setEditingChannelId(null);
      setPinnedVoiceFields(new Set());
      setChannelFormData({});
      setChannelFormErrors({});
      await fetchData();
    } catch (err) {
      const errText = formatApiError(err, `gravar ajustes do canal "${profileName}"`);
      setActionFeedback({
        type: 'error',
        text: errText,
      });
      setChannelConfirmDialog(null);
    } finally {
      setIsSavingChannel(false);
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
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('diagnostico')}
          >
            Diagnóstico
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
                <h2 id="card-factory-title" className="sys-card-title">Controle da Fábrica</h2>
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

              {/* Botões Globais de Controle da Fábrica (Pausar/Retomar e Rodar 1 ciclo) */}
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
                  {isActionPending && confirmDialog !== 'run-cycle'
                    ? 'Processando...'
                    : isPaused
                    ? '▶ Retomar Fábrica'
                    : '⏸ Pausar Fábrica'}
                </button>

                <button
                  type="button"
                  className="sys-big-btn sys-big-btn--cycle"
                  disabled={!togglePermission.canToggle || isActionPending || isPaused}
                  onClick={() => handleOpenConfirm('run-cycle')}
                  title={
                    !togglePermission.canToggle
                      ? togglePermission.reason
                      : isPaused
                      ? 'Fábrica pausada — retome antes de disparar'
                      : 'Disparar ciclo de produção autônoma supervisionado'
                  }
                  aria-label="Rodar 1 ciclo global da fábrica"
                >
                  {isActionPending && confirmDialog === 'run-cycle'
                    ? 'Processando...'
                    : '⚡ Rodar 1 ciclo'}
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

        {/* 5. Seção 4: Ajustes por canal */}
        <section className="sys-section" aria-labelledby="section-channels-title">
          <div className="sys-section-header">
            <h2 id="section-channels-title" className="sys-section-title">
              <span>⚙️</span> Ajustes por Canal
            </h2>
            <span className="fleet-muted" style={{ fontSize: '13px' }}>
              Valores entram em vigor no próximo ciclo
            </span>
          </div>

          <div className="sys-channels-grid">
            {channelsData.length > 0 ? (
              channelsData.map((ch) => {
                const pid = ch.profile_id || ch.channel_id;
                const isEditing = editingChannelId === pid;
                const fullSettings = channelSettingsMap[pid] || ch.settings || {};
                const quotas = formatQuotasDisplay(fullSettings.quotas || ch.quotas);
                const schedule = formatScheduleDisplay(fullSettings.schedule || ch.schedule);
                const ws = fullSettings.workspace_settings || {};
                const growthMode = fullSettings.growth_mode || ch.growth_mode || 'WARMUP';
                const isAuto = Boolean(fullSettings.autonomous_enabled ?? ch.autonomous_enabled);
                const effectiveGrowthMode = isEditing
                  ? String(channelFormData.growth_mode || growthMode).toUpperCase()
                  : String(growthMode).toUpperCase();
                const isWarmup = effectiveGrowthMode === 'WARMUP';
                const isQuiz = Boolean(fullSettings.is_quiz ?? ch.is_quiz);
                const effVoice = fullSettings.effective_voice || {};
                const voiceSourceInfo = getVoiceSourceInfo(effVoice.voice_name?.source);
                const rateSourceInfo = getVoiceSourceInfo(effVoice.voice_rate?.source);
                const volSourceInfo = getVoiceSourceInfo(effVoice.voice_volume?.source);

                const isVoicePinned = pinnedVoiceFields.has('voice_name');
                const isVoiceValChanged = String(channelFormData.voice_name || '').trim() !== String(effVoice.voice_name?.value || '').trim();
                const showVoicePinned = voiceSourceInfo.isInherited && (isVoicePinned || isVoiceValChanged);

                const isRatePinned = pinnedVoiceFields.has('voice_rate');
                const isRateValChanged = Math.abs(Number(channelFormData.voice_rate) - Number(effVoice.voice_rate?.value)) > 0.001;
                const showRatePinned = rateSourceInfo.isInherited && (isRatePinned || isRateValChanged);

                const isVolPinned = pinnedVoiceFields.has('voice_volume');
                const isVolValChanged = Math.abs(Number(channelFormData.voice_volume) - Number(effVoice.voice_volume?.value)) > 0.001;
                const showVolPinned = volSourceInfo.isInherited && (isVolPinned || isVolValChanged);

                return (
                  <article
                    key={pid}
                    id={`sys-channel-${pid}`}
                    className={`sys-channel-card ${isEditing ? 'sys-channel-card--editing' : ''}`}
                    aria-label={`Ajustes do canal ${ch.name || pid}`}
                  >
                    <div className="sys-channel-header">
                      <div className="sys-channel-header-left">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <h3 className="sys-channel-name">{ch.name || pid}</h3>
                          {ch.channel_status ? (() => {
                            const st = formatStatus(ch.channel_status);
                            const label = ch.channel_status_label || st.label;
                            return (
                              <span
                                className="mini-badge"
                                style={{
                                  backgroundColor: st.tint,
                                  color: st.color,
                                  borderColor: st.sq,
                                  fontSize: '11px',
                                  padding: '2px 8px',
                                  fontWeight: 600,
                                }}
                                title={ch.channel_reason ? `Status: ${label} — ${ch.channel_reason}` : `Status: ${label}`}
                              >
                                {st.glyph} {label}
                              </span>
                            );
                          })() : (
                            <span className="mini-badge" style={{ color: '#9099AA', fontSize: '11px' }}>—</span>
                          )}
                        </div>
                        <span className="sys-channel-id">{pid}</span>
                      </div>
                      <div className="sys-channel-header-right">
                        <span className="sys-role-badge">
                          {effectiveGrowthMode}
                        </span>
                        {!isEditing && (
                          <button
                            type="button"
                            className="sys-btn-edit"
                            disabled={!togglePermission.canToggle}
                            onClick={() => handleStartEdit(ch)}
                            title={
                              togglePermission.canToggle
                                ? 'Editar configurações, cotas e horários deste canal'
                                : 'Apenas o nó primário (PRIMARY) pode editar ajustes de canal. Instância secundária em modo somente leitura.'
                            }
                            aria-label={`Editar canal ${ch.name || pid}`}
                          >
                            ✎ Editar
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="sys-card-body">
                      {/* Modo Operacional e Crescimento */}
                      {isEditing ? (
                        <div className="sys-input-group" style={{ marginBottom: '8px' }}>
                          <div className="sys-edit-row">
                            <label htmlFor={`auto-${pid}`} className="sys-stat-label">
                              Modo Autônomo
                            </label>
                            <select
                              id={`auto-${pid}`}
                              className={`sys-select ${channelFormErrors.autonomous_enabled ? 'sys-input--error' : ''}`}
                              value={channelFormData.autonomous_enabled ? 'true' : 'false'}
                              onChange={(e) => handleFieldChange('autonomous_enabled', e.target.value === 'true')}
                            >
                              <option value="true">SIM (Ativo)</option>
                              <option value="false">NÃO (Desligado)</option>
                            </select>
                          </div>
                          {channelFormErrors.autonomous_enabled && (
                            <span className="sys-field-error">{channelFormErrors.autonomous_enabled}</span>
                          )}

                          <div className="sys-edit-row">
                            <label htmlFor={`growth-${pid}`} className="sys-stat-label">
                              Modo de Crescimento
                            </label>
                            <select
                              id={`growth-${pid}`}
                              className={`sys-select ${channelFormErrors.growth_mode ? 'sys-input--error' : ''}`}
                              value={String(channelFormData.growth_mode || 'WARMUP').toUpperCase()}
                              onChange={(e) => handleFieldChange('growth_mode', e.target.value)}
                            >
                              <option value="WARMUP">🌱 WARMUP (Aquecimento)</option>
                              <option value="SCALE">🚀 SCALE (Escala)</option>
                            </select>
                          </div>
                          {channelFormErrors.growth_mode && (
                            <span className="sys-field-error">{channelFormErrors.growth_mode}</span>
                          )}
                        </div>
                      ) : (
                        <>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Modo Autônomo</span>
                            <span className="sys-stat-value">
                              {isAuto ? 'SIM (Ativo)' : 'NÃO (Desligado)'}
                            </span>
                          </div>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Modo de Crescimento</span>
                            <span className="sys-stat-value">
                              {String(growthMode).toUpperCase() === 'SCALE' ? 'SCALE (Escala)' : 'WARMUP (Aquecimento)'}
                            </span>
                          </div>
                        </>
                      )}

                      <div className="sys-stat-row">
                        <span className="sys-stat-label">Nicho / Formato</span>
                        <span className="sys-stat-value">
                          {formatProviderValue(ch.niche)} / {formatProviderValue(ch.format || ws.editorial?.video_format)}
                        </span>
                      </div>

                      {/* Subseção de Cotas Operacionais */}
                      <h4 className="sys-channel-group-title">Cotas Operacionais</h4>
                      {isEditing ? (
                        <div className="sys-input-group">
                          <div className="sys-edit-row">
                            <label htmlFor={`target-${pid}`} className="sys-stat-label">
                              Meta Estoque (3–10 vídeos)
                            </label>
                            <input
                              id={`target-${pid}`}
                              type="number"
                              min="3"
                              max="10"
                              className={`sys-input ${channelFormErrors.target_ready_stock ? 'sys-input--error' : ''}`}
                              value={channelFormData.target_ready_stock ?? ''}
                              onChange={(e) => handleFieldChange('target_ready_stock', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.target_ready_stock && (
                            <span className="sys-field-error">{channelFormErrors.target_ready_stock}</span>
                          )}

                          <div className="sys-edit-row">
                            <label htmlFor={`maxgen-${pid}`} className="sys-stat-label">
                              Gerações/24h (1–10)
                            </label>
                            <input
                              id={`maxgen-${pid}`}
                              type="number"
                              min="1"
                              max="10"
                              className={`sys-input ${channelFormErrors.max_generations_24h ? 'sys-input--error' : ''}`}
                              value={channelFormData.max_generations_24h ?? ''}
                              onChange={(e) => handleFieldChange('max_generations_24h', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.max_generations_24h && (
                            <span className="sys-field-error">{channelFormErrors.max_generations_24h}</span>
                          )}

                          <div className="sys-edit-row">
                            <label htmlFor={`posts-${pid}`} className="sys-stat-label">
                              Posts por Dia (1–10)
                            </label>
                            <input
                              id={`posts-${pid}`}
                              type="number"
                              min="1"
                              max="10"
                              className={`sys-input ${channelFormErrors.posts_per_day ? 'sys-input--error' : ''}`}
                              value={channelFormData.posts_per_day ?? ''}
                              onChange={(e) => handleFieldChange('posts_per_day', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.posts_per_day && (
                            <span className="sys-field-error">{channelFormErrors.posts_per_day}</span>
                          )}
                          {isWarmup && (
                            <div className="sys-warn-note">
                              ℹ O modo de crescimento do canal ({effectiveGrowthMode}) pode limitar este valor.
                            </div>
                          )}

                          {/* Cota Somente-Leitura (Tentativas) */}
                          <div className="sys-channel-stats-grid" style={{ marginTop: '6px' }}>
                            <div className="sys-stat-row">
                              <span className="sys-stat-label">Tentativas/24h</span>
                              <span className="sys-stat-value">{quotas.max_attempts_24h}</span>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="sys-channel-stats-grid">
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Meta Estoque</span>
                            <span className="sys-stat-value">{quotas.target_ready_stock}</span>
                          </div>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Posts/Dia</span>
                            <span className="sys-stat-value">{quotas.posts_per_day}</span>
                          </div>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Gerações/24h</span>
                            <span className="sys-stat-value">{quotas.max_generations_24h}</span>
                          </div>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Tentativas/24h</span>
                            <span className="sys-stat-value">{quotas.max_attempts_24h}</span>
                          </div>
                        </div>
                      )}

                      {/* Subseção de Janela de Publicação */}
                      <h4 className="sys-channel-group-title">Janela de Publicação</h4>
                      {isEditing ? (
                        <div className="sys-input-group">
                          <div className="sys-edit-row">
                            <label htmlFor={`start-${pid}`} className="sys-stat-label">
                              Início da Janela (0–23h)
                            </label>
                            <input
                              id={`start-${pid}`}
                              type="number"
                              min="0"
                              max="23"
                              className={`sys-input ${channelFormErrors.publish_start_hour ? 'sys-input--error' : ''}`}
                              value={channelFormData.publish_start_hour ?? ''}
                              onChange={(e) => handleFieldChange('publish_start_hour', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.publish_start_hour && (
                            <span className="sys-field-error">{channelFormErrors.publish_start_hour}</span>
                          )}

                          <div className="sys-edit-row">
                            <label htmlFor={`end-${pid}`} className="sys-stat-label">
                              Fim da Janela (0–23h)
                            </label>
                            <input
                              id={`end-${pid}`}
                              type="number"
                              min="0"
                              max="23"
                              className={`sys-input ${channelFormErrors.publish_end_hour ? 'sys-input--error' : ''}`}
                              value={channelFormData.publish_end_hour ?? ''}
                              onChange={(e) => handleFieldChange('publish_end_hour', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.publish_end_hour && (
                            <span className="sys-field-error">{channelFormErrors.publish_end_hour}</span>
                          )}

                          <div className="sys-edit-row">
                            <label htmlFor={`interval-${pid}`} className="sys-stat-label">
                              Intervalo Mínimo (1–24h)
                            </label>
                            <input
                              id={`interval-${pid}`}
                              type="number"
                              min="1"
                              max="24"
                              className={`sys-input ${channelFormErrors.min_interval_hours ? 'sys-input--error' : ''}`}
                              value={channelFormData.min_interval_hours ?? ''}
                              onChange={(e) => handleFieldChange('min_interval_hours', e.target.value)}
                            />
                          </div>
                          {channelFormErrors.min_interval_hours && (
                            <span className="sys-field-error">{channelFormErrors.min_interval_hours}</span>
                          )}

                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Fuso Horário</span>
                            <span className="sys-stat-value">America/Sao_Paulo (imutável)</span>
                          </div>
                        </div>
                      ) : (
                        <div>
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
                        </div>
                      )}

                      {/* Subseção de Voz e Velocidade (Missão M6b) */}
                      <h4 className="sys-channel-group-title">Voz e Velocidade</h4>
                      {isEditing ? (
                        <div className="sys-input-group">
                          {/* Campo Voz */}
                          <div className="sys-edit-row">
                            <label htmlFor={`voice-${pid}`} className="sys-stat-label">
                              Voz
                            </label>
                            <div className="sys-voice-field-group">
                              <select
                                id={`voice-${pid}`}
                                className={`sys-select ${channelFormErrors.voice_name ? 'sys-input--error' : ''}`}
                                value={channelFormData.voice_name ?? ''}
                                onChange={(e) => handleFieldChange('voice_name', e.target.value)}
                              >
                                {allowedVoices.map((v) => (
                                  <option key={v.id} value={v.id}>
                                    {v.name}
                                  </option>
                                ))}
                                {allowedVoices.length === 0 && (
                                  <option value={channelFormData.voice_name || ''}>
                                    {channelFormData.voice_name || 'Carregando...'}
                                  </option>
                                )}
                              </select>
                              {channelFormData.voice_name === null ? (
                                <span className="sys-badge sys-badge-global">Global (herdado)</span>
                              ) : showVoicePinned ? (
                                <span className="sys-badge sys-badge-pinned">Será fixado no canal</span>
                              ) : (
                                <span className={`sys-badge ${voiceSourceInfo.badgeClass}`}>
                                  {voiceSourceInfo.label}{voiceSourceInfo.isInherited ? ' (herdado)' : ''}
                                </span>
                              )}
                              {voiceSourceInfo.canReset && channelFormData.voice_name !== null && (
                                <button
                                  type="button"
                                  className="sys-btn-reset-inherit"
                                  onClick={() => handleResetVoiceInherit('voice_name')}
                                  title="Voltar a herdar voz global"
                                >
                                  Voltar a herdar
                                </button>
                              )}
                              {!voiceSourceInfo.canReset && channelFormData.voice_name !== null && (
                                <button
                                  type="button"
                                  className={`sys-btn-pin-channel ${isVoicePinned ? 'sys-btn-pin-channel--active' : ''}`}
                                  onClick={() => handleTogglePinVoice('voice_name')}
                                  title={isVoicePinned ? 'Desfazer fixação no canal' : 'Fixar este valor diretamente no canal'}
                                >
                                  {isVoicePinned ? 'Desfazer fixação' : 'Fixar no canal'}
                                </button>
                              )}
                            </div>
                          </div>
                          {channelFormErrors.voice_name && (
                            <span className="sys-field-error">{channelFormErrors.voice_name}</span>
                          )}

                          {/* Campo Velocidade */}
                          {isQuiz ? (
                            <div className="sys-edit-row">
                              <span className="sys-stat-label">Velocidade</span>
                              <span className="sys-quiz-notice">{QUIZ_VOICE_RATE_NOTICE}</span>
                            </div>
                          ) : (
                            <>
                              <div className="sys-edit-row">
                                <label htmlFor={`rate-${pid}`} className="sys-stat-label">
                                  Velocidade (0.5–2.0x)
                                </label>
                                <div className="sys-voice-field-group">
                                  <input
                                    id={`rate-${pid}`}
                                    type="number"
                                    step="0.05"
                                    min="0.5"
                                    max="2.0"
                                    className={`sys-input ${channelFormErrors.voice_rate ? 'sys-input--error' : ''}`}
                                    value={channelFormData.voice_rate ?? ''}
                                    onChange={(e) => handleFieldChange('voice_rate', e.target.value)}
                                  />
                                  {channelFormData.voice_rate === null ? (
                                    <span className="sys-badge sys-badge-global">Global (herdado)</span>
                                  ) : showRatePinned ? (
                                    <span className="sys-badge sys-badge-pinned">Será fixado no canal</span>
                                  ) : (
                                    <span className={`sys-badge ${rateSourceInfo.badgeClass}`}>
                                      {rateSourceInfo.label}{rateSourceInfo.isInherited ? ' (herdado)' : ''}
                                    </span>
                                  )}
                                  {rateSourceInfo.canReset && channelFormData.voice_rate !== null && (
                                    <button
                                      type="button"
                                      className="sys-btn-reset-inherit"
                                      onClick={() => handleResetVoiceInherit('voice_rate')}
                                      title="Voltar a herdar velocidade global"
                                    >
                                      Voltar a herdar
                                    </button>
                                  )}
                                  {!rateSourceInfo.canReset && channelFormData.voice_rate !== null && (
                                    <button
                                      type="button"
                                      className={`sys-btn-pin-channel ${isRatePinned ? 'sys-btn-pin-channel--active' : ''}`}
                                      onClick={() => handleTogglePinVoice('voice_rate')}
                                      title={isRatePinned ? 'Desfazer fixação no canal' : 'Fixar este valor diretamente no canal'}
                                    >
                                      {isRatePinned ? 'Desfazer fixação' : 'Fixar no canal'}
                                    </button>
                                  )}
                                </div>
                              </div>
                              {channelFormErrors.voice_rate && (
                                <span className="sys-field-error">{channelFormErrors.voice_rate}</span>
                              )}
                            </>
                          )}

                          {/* Campo Volume */}
                          <div className="sys-edit-row">
                            <label htmlFor={`vol-${pid}`} className="sys-stat-label">
                              Volume (0.0–1.0)
                            </label>
                            <div className="sys-voice-field-group">
                              <input
                                id={`vol-${pid}`}
                                type="number"
                                step="0.05"
                                min="0.0"
                                max="1.0"
                                className={`sys-input ${channelFormErrors.voice_volume ? 'sys-input--error' : ''}`}
                                value={channelFormData.voice_volume ?? ''}
                                onChange={(e) => handleFieldChange('voice_volume', e.target.value)}
                              />
                              {channelFormData.voice_volume === null ? (
                                <span className="sys-badge sys-badge-global">Global (herdado)</span>
                              ) : showVolPinned ? (
                                <span className="sys-badge sys-badge-pinned">Será fixado no canal</span>
                              ) : (
                                <span className={`sys-badge ${volSourceInfo.badgeClass}`}>
                                  {volSourceInfo.label}{volSourceInfo.isInherited ? ' (herdado)' : ''}
                                </span>
                              )}
                              {volSourceInfo.canReset && channelFormData.voice_volume !== null && (
                                <button
                                  type="button"
                                  className="sys-btn-reset-inherit"
                                  onClick={() => handleResetVoiceInherit('voice_volume')}
                                  title="Voltar a herdar volume global"
                                >
                                  Voltar a herdar
                                </button>
                              )}
                              {!volSourceInfo.canReset && channelFormData.voice_volume !== null && (
                                <button
                                  type="button"
                                  className={`sys-btn-pin-channel ${isVolPinned ? 'sys-btn-pin-channel--active' : ''}`}
                                  onClick={() => handleTogglePinVoice('voice_volume')}
                                  title={isVolPinned ? 'Desfazer fixação no canal' : 'Fixar este valor diretamente no canal'}
                                >
                                  {isVolPinned ? 'Desfazer fixação' : 'Fixar no canal'}
                                </button>
                              )}
                            </div>
                          </div>
                          {channelFormErrors.voice_volume && (
                            <span className="sys-field-error">{channelFormErrors.voice_volume}</span>
                          )}
                        </div>
                      ) : (
                        <div>
                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Voz</span>
                            <div className="sys-voice-field-group">
                              <span className="sys-stat-value">
                                {formatVoiceDiffDisplay('voice_name', effVoice.voice_name?.value, allowedVoices)}
                              </span>
                              <span className={`sys-badge ${voiceSourceInfo.badgeClass}`}>
                                {voiceSourceInfo.label}{voiceSourceInfo.isInherited ? ' (herdado)' : ''}
                              </span>
                            </div>
                          </div>

                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Velocidade</span>
                            {isQuiz ? (
                              <span className="sys-quiz-notice">{QUIZ_VOICE_RATE_NOTICE}</span>
                            ) : (
                              <div className="sys-voice-field-group">
                                <span className="sys-stat-value">
                                  {effVoice.voice_rate?.value != null ? `${Number(effVoice.voice_rate.value).toFixed(2)}x` : '—'}
                                </span>
                                <span className={`sys-badge ${rateSourceInfo.badgeClass}`}>
                                  {rateSourceInfo.label}{rateSourceInfo.isInherited ? ' (herdado)' : ''}
                                </span>
                              </div>
                            )}
                          </div>

                          <div className="sys-stat-row">
                            <span className="sys-stat-label">Volume</span>
                            <div className="sys-voice-field-group">
                              <span className="sys-stat-value">
                                {effVoice.voice_volume?.value != null ? `${Math.round(Number(effVoice.voice_volume.value) * 100)}%` : '—'}
                              </span>
                              <span className={`sys-badge ${volSourceInfo.badgeClass}`}>
                                {volSourceInfo.label}{volSourceInfo.isInherited ? ' (herdado)' : ''}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Subseção de Workspace (Somente Leitura) */}
                      <h4 className="sys-channel-group-title">Configurações de Workspace</h4>
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

                      {/* Botões de Ação na Edição */}
                      {isEditing && (
                        <div className="sys-edit-actions">
                          <button
                            type="button"
                            className="sys-btn-cancel-edit"
                            onClick={handleCancelEdit}
                          >
                            Cancelar
                          </button>
                          <button
                            type="button"
                            className="sys-btn-save"
                            disabled={Object.keys(channelFormErrors).length > 0 || isSavingChannel}
                            onClick={() => handleSaveClick(ch)}
                          >
                            Salvar
                          </button>
                        </div>
                      )}
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

      {/* Diálogo de Confirmação para Pausar / Retomar Fábrica */}
      {confirmDialog && (
        <div
          className="sys-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-modal-title"
        >
          <div className="sys-modal">
            <h3 id="confirm-modal-title" className="sys-modal-title">
              {confirmDialog === 'pause'
                ? '⏸ Pausar Fábrica'
                : confirmDialog === 'resume'
                ? '▶ Retomar Fábrica'
                : '⚡ Rodar 1 ciclo'}
            </h3>

            <p className="sys-modal-text">
              {confirmDialog === 'pause' ? (
                <>
                  Tem certeza que deseja pausar a fábrica?{' '}
                  <span className="sys-modal-highlight">
                    Isso não interrompe o vídeo em andamento; tarefas em processamento concluem normalmente, mas novas execuções e ciclos automáticos deixam de ser iniciados.
                  </span>
                </>
              ) : confirmDialog === 'resume' ? (
                <>
                  Deseja retomar a fábrica?{' '}
                  <span className="sys-modal-highlight">
                    O agendador e os ciclos autônomos voltarão a iniciar e processar novas tarefas normalmente.
                  </span>
                </>
              ) : (
                <>
                  Disparar ciclo autônomo agora?{' '}
                  <span className="sys-modal-highlight">
                    Isso executará 1 ciclo supervisionado global de produção autônoma para os canais elegíveis.
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
                  confirmDialog === 'pause'
                    ? 'sys-btn-confirm-pause'
                    : confirmDialog === 'resume'
                    ? 'sys-btn-confirm-resume'
                    : 'sys-btn-confirm-save'
                }
                onClick={handleExecuteToggle}
                disabled={isActionPending}
              >
                {isActionPending
                  ? 'Processando...'
                  : confirmDialog === 'pause'
                  ? 'Confirmar Pausa'
                  : confirmDialog === 'resume'
                  ? 'Confirmar Retomada'
                  : 'Confirmar Disparo'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Diálogo de Confirmação para Salvar Ajustes de Canal (SIS2) */}
      {channelConfirmDialog && (
        <div
          className="sys-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-channel-title"
        >
          <div className="sys-modal">
            <h3 id="confirm-channel-title" className="sys-modal-title">
              Confirmar Alterações de Ajustes
            </h3>

            <p className="sys-modal-text">
              Canal: <strong className="sys-modal-highlight">{channelConfirmDialog.profileName}</strong>
            </p>

            <table className="sys-diff-table" aria-label="Campos alterados">
              <thead>
                <tr>
                  <th scope="col">Campo</th>
                  <th scope="col">Antes</th>
                  <th scope="col" aria-hidden="true"></th>
                  <th scope="col">Depois</th>
                </tr>
              </thead>
              <tbody>
                {channelConfirmDialog.diffList.map((item) => {
                  const isVoice = ['voice_name', 'voice_rate', 'voice_volume'].includes(item.field);
                  const isPinSameVal = item.isPin && (
                    item.field === 'voice_name'
                      ? String(item.oldValue || '').trim() === String(item.newValue || '').trim()
                      : Math.abs(Number(item.oldValue) - Number(item.newValue)) < 0.001
                  );

                  if (isPinSameVal) {
                    return (
                      <tr key={item.field}>
                        <td><strong>{item.label}</strong></td>
                        <td colSpan="3" className="sys-diff-after">
                          Fixar no canal: {formatVoiceDiffDisplay(item.field, item.newValue, allowedVoices)}
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={item.field}>
                      <td><strong>{item.label}</strong></td>
                      <td className="sys-diff-before">
                        {isVoice
                          ? formatVoiceDiffDisplay(item.field, item.oldValue, allowedVoices)
                          : formatDiffValueDisplay(item.field, item.oldValue)}
                      </td>
                      <td className="sys-diff-arrow">→</td>
                      <td className="sys-diff-after">
                        {isVoice
                          ? formatVoiceDiffDisplay(item.field, item.newValue, allowedVoices)
                          : formatDiffValueDisplay(item.field, item.newValue)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <p className="sys-modal-text" style={{ fontSize: '13px', color: 'var(--fleet-muted)' }}>
              ℹ As alterações entram em vigor imediatamente no próximo ciclo operacional (sem necessidade de reiniciar o motor).
            </p>

            <div className="sys-modal-actions">
              <button
                type="button"
                className="sys-btn-cancel"
                onClick={handleCloseChannelConfirm}
                disabled={isSavingChannel}
              >
                Cancelar
              </button>

              <button
                type="button"
                className="sys-btn-confirm-save"
                onClick={handleConfirmSaveChannel}
                disabled={isSavingChannel}
              >
                {isSavingChannel ? 'Gravando...' : 'Confirmar e Gravar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
