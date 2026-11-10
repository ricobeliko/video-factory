import React, { useState } from 'react';
import { refreshFlowAccountCredits, refreshAllFlowAccountsCredits } from '../api';

/**
 * Mapeamento semântico centralizado de status do Google Flow (R6A.5).
 * Design system de sala de controle / AI Compute Vault.
 */
const STATUS_CONFIG = {
  AVAILABLE: {
    label: 'Disponível',
    dotColor: '#10b981',
    badgeClass: 'status-available',
  },
  AVAILABLE_UNKNOWN_CREDITS: {
    label: 'Disponível (Saldo a checar)',
    dotColor: '#a3e635',
    badgeClass: 'status-unknown-credits',
  },
  BUSY: {
    label: 'Ocupada em Geração',
    dotColor: '#38bdf8',
    badgeClass: 'status-busy',
  },
  LOW_CREDITS: {
    label: 'Créditos Baixos',
    dotColor: '#f59e0b',
    badgeClass: 'status-low-credits',
  },
  COOLDOWN: {
    label: 'Cooldown de Segurança',
    dotColor: '#f97316',
    badgeClass: 'status-cooldown',
  },
  EXHAUSTED: {
    label: 'Esgotada',
    dotColor: '#ef4444',
    badgeClass: 'status-exhausted',
  },
  AUTH_REQUIRED: {
    label: 'Login Necessário',
    dotColor: '#ef4444',
    badgeClass: 'status-auth-required',
  },
  AUTH_FAILED: {
    label: 'Falha Auth',
    dotColor: '#ef4444',
    badgeClass: 'status-auth-failed',
  },
  DISABLED: {
    label: 'Desativada',
    dotColor: '#64748b',
    badgeClass: 'status-disabled',
  },
};

function getStatusDetails(status, creditsSource, creditsRemaining) {
  if (status === 'AVAILABLE' && (creditsSource === 'UNKNOWN' || creditsRemaining === null)) {
    return STATUS_CONFIG.AVAILABLE_UNKNOWN_CREDITS;
  }
  return STATUS_CONFIG[status] || {
    label: status || 'Desconhecido',
    dotColor: '#64748b',
    badgeClass: 'status-disabled',
  };
}

/**
 * Regra canônica de créditos (R6A.5):
 * NUNCA exibir percentual de plano ou denominador inventado (sem credit_limit canônico).
 * Exibir com destaque numérico claro.
 */
function getCreditDisplay(remaining, source, status) {
  if (status === 'AUTH_FAILED' || status === 'AUTH_REQUIRED') {
    return {
      formattedNumber: remaining !== null && remaining !== undefined ? Number(remaining).toLocaleString('pt-BR') : '—',
      unit: 'créditos (bloqueados)',
      sourceLabel: 'HISTÓRICO BLOQUEADO',
      sourceClass: 'source-unknown',
      isKnown: false,
    };
  }

  if (source === 'FLOW_UI_VERIFIED' && remaining !== null && remaining !== undefined) {
    return {
      formattedNumber: Number(remaining).toLocaleString('pt-BR'),
      unit: 'créditos',
      sourceLabel: 'VERIFIED',
      sourceClass: 'source-verified',
      isKnown: true,
    };
  }

  if (source === 'LOCAL_ESTIMATE' && remaining !== null && remaining !== undefined) {
    return {
      formattedNumber: `~${Number(remaining).toLocaleString('pt-BR')}`,
      unit: 'créditos (est.)',
      sourceLabel: 'ESTIMATED',
      sourceClass: 'source-estimated',
      isKnown: true,
    };
  }

  return {
    formattedNumber: '—',
    unit: 'saldo não lido',
    sourceLabel: 'UNKNOWN',
    sourceClass: 'source-unknown',
    isKnown: false,
  };
}

function formatCurrentTask(taskId) {
  if (!taskId) {
    return { label: 'Livre para dispatch', isBusy: false };
  }
  const compactId = taskId.length > 10 ? `${taskId.slice(0, 8)}...` : taskId;
  return { label: `Ocupada (${compactId})`, isBusy: true, fullId: taskId };
}

/**
 * FlowAccountsSection — AI Compute Vault / Google Flow Pool (R6A.5).
 * Read-only visual upgrade with prominent balance metrics and structured capacity layout.
 */
export default function FlowAccountsSection({ flowPool, onRefresh }) {
  const [isRefreshingAll, setIsRefreshingAll] = useState(false);
  const [refreshingAccounts, setRefreshingAccounts] = useState({});
  const [actionFeedback, setActionFeedback] = useState(null);

  const handleRefreshAll = async () => {
    setIsRefreshingAll(true);
    setActionFeedback(null);
    try {
      await refreshAllFlowAccountsCredits(true);
      setActionFeedback({ type: 'success', text: 'Reconciliação do pool de contas concluída com sucesso.' });
      if (onRefresh) onRefresh();
    } catch (err) {
      setActionFeedback({ type: 'error', text: `Falha ao reconciliar pool: ${err.message}` });
    } finally {
      setIsRefreshingAll(false);
    }
  };

  const handleRefreshAccount = async (accountId) => {
    setRefreshingAccounts((prev) => ({ ...prev, [accountId]: true }));
    setActionFeedback(null);
    try {
      const res = await refreshFlowAccountCredits(accountId, true);
      const data = res.data || res;
      const msg = data.message || `Saldo atualizado: ${data.credits_remaining ?? '—'} créditos`;
      setActionFeedback({
        type: data.success !== false ? 'success' : 'warning',
        text: `[${accountId}] ${msg}`,
      });
      if (onRefresh) onRefresh();
    } catch (err) {
      setActionFeedback({ type: 'error', text: `[${accountId}] Falha: ${err.message}` });
    } finally {
      setRefreshingAccounts((prev) => ({ ...prev, [accountId]: false }));
    }
  };

  if (!flowPool || flowPool.error) {
    return (
      <section className="flow-pool-section degraded" aria-label="Google Flow Provider Pool">
        <div className="flow-section-header">
          <div className="flow-title-group">
            <span className="flow-title-icon">🎬</span>
            <span className="flow-title">Google Flow</span>
            <span className="flow-subtitle">Provider Pool</span>
          </div>
          <span className="flow-degraded-badge">Telemetria indisponível</span>
        </div>
      </section>
    );
  }

  const {
    accounts = [],
    active_account_id = null,
    total_known_credits = null,
  } = flowPool;

  return (
    <section className="flow-pool-section" aria-label="Google Flow Provider Pool">
      <div className="flow-section-header">
        <div className="flow-title-group">
          <span className="flow-title-icon">⚡</span>
          <span className="flow-title">Google Flow</span>
          <span className="flow-subtitle">Multi-Account Pool</span>
          <span className="flow-count-badge">
            {accounts.length} {accounts.length === 1 ? 'conta' : 'contas'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {total_known_credits !== null && total_known_credits !== undefined && (
            <div className="flow-credits-summary" title="Total somado de saldos verificados em memória">
              <span className="summary-label">Pool Total Verificado:</span>
              <strong className="summary-value">
                {Number(total_known_credits).toLocaleString('pt-BR')} créditos
              </strong>
            </div>
          )}
          <button
            type="button"
            className="flow-refresh-btn"
            onClick={handleRefreshAll}
            disabled={isRefreshingAll}
            title="Reconcilia saldo real de todas as contas no Google Flow via headless (sem geração)"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: '500',
              borderRadius: '6px',
              border: '1px solid var(--fleet-border, #334155)',
              background: 'var(--fleet-card-bg, #1e293b)',
              color: 'var(--fleet-text, #f1f5f9)',
              cursor: isRefreshingAll ? 'wait' : 'pointer',
            }}
          >
            <span>{isRefreshingAll ? '⏳' : '🔄'}</span>
            <span>{isRefreshingAll ? 'Atualizando todas…' : 'Atualizar Todas'}</span>
          </button>
        </div>
      </div>

      {actionFeedback && (
        <div
          style={{
            margin: '0 0 12px 0',
            padding: '8px 12px',
            borderRadius: '6px',
            fontSize: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: actionFeedback.type === 'error' ? 'rgba(239, 68, 68, 0.15)' : actionFeedback.type === 'warning' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            border: `1px solid ${actionFeedback.type === 'error' ? '#ef4444' : actionFeedback.type === 'warning' ? '#f59e0b' : '#10b981'}`,
            color: 'var(--fleet-text, #f1f5f9)',
          }}
        >
          <span>{actionFeedback.text}</span>
          <button
            type="button"
            onClick={() => setActionFeedback(null)}
            style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '14px' }}
          >
            ✕
          </button>
        </div>
      )}

      <div className="flow-cards-deck">
        {accounts.length === 0 ? (
          <div className="flow-empty-state">
            Nenhuma conta Google Flow cadastrada no pool.
          </div>
        ) : (
          accounts.map((acct) => {
            const isActive = acct.account_id === active_account_id;
            const statusInfo = getStatusDetails(acct.status, acct.credits_source, acct.credits_remaining);
            const creditDisplay = getCreditDisplay(acct.credits_remaining, acct.credits_source, acct.status);
            const taskInfo = formatCurrentTask(acct.current_task_id);

            // Future-proof capacity percentage check (only if backend canonically sends credit_limit)
            const hasCanonicalLimit = typeof acct.credit_limit === 'number' && acct.credit_limit > 0;
            const canonicalPct = hasCanonicalLimit
              ? Math.min(100, Math.round((acct.credits_remaining / acct.credit_limit) * 100))
              : null;

            return (
              <div
                key={acct.account_id}
                className={`flow-account-card ${isActive ? 'is-active-account' : ''} ${acct.enabled === false ? 'is-disabled' : ''}`}
              >
                {/* Top Qualitative Status Bar */}
                <div
                  className="flow-qualitative-status-bar"
                  style={{ backgroundColor: statusInfo.dotColor }}
                />

                {/* Identity Header */}
                <div className="flow-card-top">
                  <div className="flow-card-identity">
                    <div className="flow-display-name-row">
                      <span className="flow-account-icon">{isActive ? '⚡' : '👤'}</span>
                      <span className="flow-display-name" title={acct.display_name || acct.account_id}>
                        {acct.display_name || acct.account_id}
                      </span>
                    </div>
                    <div className="flow-account-id" title={acct.account_id}>
                      <code>{acct.account_id}</code> • Prioridade: {acct.priority ?? 100}
                    </div>
                  </div>

                  <div className="flow-card-badges">
                    {isActive && (
                      <span className="flow-badge-active" title="Conta ativa prioritária (maior saldo verificado)">
                        ★ ATIVA
                      </span>
                    )}
                    {acct.enabled === false && (
                      <span className="flow-badge-disabled">OFF</span>
                    )}
                  </div>
                </div>

                {/* Prominent Balance Metric Box */}
                <div className="flow-balance-hero">
                  <div className="flow-balance-value-row">
                    <span className="balance-number">{creditDisplay.formattedNumber}</span>
                    <span className="balance-unit">{creditDisplay.unit}</span>
                  </div>
                  <span className={`flow-source-badge ${creditDisplay.sourceClass}`}>
                    {creditDisplay.sourceLabel}
                  </span>
                </div>

                {/* Qualitative / Future Capacity Track */}
                <div className="flow-capacity-slot">
                  <div className="flow-gauge-track">
                    <div
                      className="flow-gauge-fill"
                      style={{
                        width: canonicalPct !== null ? `${canonicalPct}%` : '100%',
                        backgroundColor: statusInfo.dotColor,
                        opacity: canonicalPct !== null ? 1 : 0.85,
                      }}
                    />
                  </div>
                  <div className="flow-capacity-subtext">
                    {canonicalPct !== null ? (
                      <span>{canonicalPct}% da cota ({acct.credits_remaining} / {acct.credit_limit})</span>
                    ) : (
                      <span>
                        {acct.status === 'AUTH_FAILED' || acct.status === 'AUTH_REQUIRED'
                          ? 'Saldo histórico inacessível até revalidação de autenticação'
                          : 'Saldo factual verificado no Google Flow'}
                      </span>
                    )}
                  </div>
                </div>

                {/* Operational Status & Active Task */}
                <div className="flow-footer-meta">
                  <div className="flow-status-row">
                    <span
                      className="flow-status-dot"
                      style={{ backgroundColor: statusInfo.dotColor }}
                    />
                    <span className={`flow-status-text ${statusInfo.badgeClass}`}>
                      {statusInfo.label}
                    </span>
                  </div>

                  <div
                    className={`flow-task-status ${taskInfo.isBusy ? 'in-use' : 'idle'}`}
                    title={taskInfo.fullId || 'Pronta'}
                  >
                    {taskInfo.label}
                  </div>
                </div>

                {/* Verification Action & Meta Row */}
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: '8px',
                    paddingTop: '8px',
                    borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                  }}
                >
                  <span
                    style={{ fontSize: '11px', color: 'var(--fleet-muted, #94a3b8)' }}
                    title={acct.credits_last_verified_at || ''}
                  >
                    {acct.last_verified_display || 'Nunca verificado'}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRefreshAccount(acct.account_id)}
                    disabled={refreshingAccounts[acct.account_id] || isRefreshingAll}
                    title="Reconcilia saldo real desta conta no Google Flow via headless"
                    style={{
                      padding: '2px 8px',
                      fontSize: '11px',
                      borderRadius: '4px',
                      border: '1px solid var(--fleet-border, #334155)',
                      background: 'transparent',
                      color: 'var(--fleet-text, #f1f5f9)',
                      cursor: refreshingAccounts[acct.account_id] ? 'wait' : 'pointer',
                    }}
                  >
                    {refreshingAccounts[acct.account_id] ? '⏳ Verificando…' : '🔄 Atualizar'}
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
