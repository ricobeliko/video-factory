import React from 'react';

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
export default function FlowAccountsSection({ flowPool }) {
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

        {total_known_credits !== null && total_known_credits !== undefined && (
          <div className="flow-credits-summary" title="Total somado de saldos verificados em memória">
            <span className="summary-label">Pool Total Verificado:</span>
            <strong className="summary-value">
              {Number(total_known_credits).toLocaleString('pt-BR')} créditos
            </strong>
          </div>
        )}
      </div>

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
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
