import React from 'react';

/**
 * Mapeamento semântico centralizado de status do Google Flow (R6A.3).
 * Cores harmonizadas com o design system do Factory Live.
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
    label: 'Ocupada',
    dotColor: '#3b82f6',
    badgeClass: 'status-busy',
  },
  LOW_CREDITS: {
    label: 'Créditos Baixos',
    dotColor: '#f59e0b',
    badgeClass: 'status-low-credits',
  },
  COOLDOWN: {
    label: 'Cooldown',
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
 * Regra canônica obrigatória de exibição de créditos (R6A.3 / FLOW-CREDIT-002):
 * - FLOW_UI_VERIFIED & != null -> "1.050 créditos" [VERIFIED]
 * - LOCAL_ESTIMATE & != null -> "~805 créditos" [ESTIMATED]
 * - UNKNOWN ou null -> "Saldo indisponível" [UNKNOWN]
 * NUNCA exibir percentual de plano ou denominador inventado (ex: NÃO mostrar 16% ou 100%).
 */
function formatCredits(remaining, source) {
  if (source === 'FLOW_UI_VERIFIED' && remaining !== null && remaining !== undefined) {
    return {
      text: `${Number(remaining).toLocaleString('pt-BR')} créditos`,
      sourceLabel: 'VERIFIED',
      sourceClass: 'source-verified',
    };
  }

  if (source === 'LOCAL_ESTIMATE' && remaining !== null && remaining !== undefined) {
    return {
      text: `~${Number(remaining).toLocaleString('pt-BR')} créditos`,
      sourceLabel: 'ESTIMATED',
      sourceClass: 'source-estimated',
    };
  }

  return {
    text: 'Saldo indisponível',
    sourceLabel: 'UNKNOWN',
    sourceClass: 'source-unknown',
  };
}

function formatCurrentTask(taskId) {
  if (!taskId) {
    return { label: 'Livre', isBusy: false };
  }
  const compactId = taskId.length > 10 ? `${taskId.slice(0, 8)}...` : taskId;
  return { label: `Em uso (${compactId})`, isBusy: true, fullId: taskId };
}

/**
 * FlowAccountsSection — Seção visual do Google Flow Multi-Account Pool no Factory Live.
 * Control room visual, estritamente READ-ONLY, zero percentuais artificiais.
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
          <span className="flow-title-icon">🎬</span>
          <span className="flow-title">Google Flow</span>
          <span className="flow-subtitle">Multi-Account Pool</span>
          <span className="flow-count-badge">
            {accounts.length} {accounts.length === 1 ? 'conta' : 'contas'}
          </span>
        </div>

        {total_known_credits !== null && total_known_credits !== undefined && (
          <div className="flow-credits-summary" title="Total somado de saldos conhecidos">
            <span className="summary-label">Créditos conhecidos:</span>
            <strong className="summary-value">
              {Number(total_known_credits).toLocaleString('pt-BR')}
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
            const creditsInfo = formatCredits(acct.credits_remaining, acct.credits_source);
            const taskInfo = formatCurrentTask(acct.current_task_id);

            return (
              <div
                key={acct.account_id}
                className={`flow-account-card ${isActive ? 'is-active-account' : ''} ${acct.enabled === false ? 'is-disabled' : ''}`}
              >
                {/* Discrete qualitative status accent line (Requirement 8: NOT a percentage bar) */}
                <div
                  className="flow-qualitative-status-bar"
                  style={{ backgroundColor: statusInfo.dotColor }}
                />

                {/* Cabeçalho do Card: Display Name + Active Badge + ID secundário */}
                <div className="flow-card-top">
                  <div className="flow-card-identity">
                    <div className="flow-display-name" title={acct.display_name || acct.account_id}>
                      {acct.display_name || acct.account_id}
                    </div>
                    <div className="flow-account-id" title={acct.account_id}>
                      {acct.account_id}
                    </div>
                  </div>

                  <div className="flow-card-badges">
                    {isActive && (
                      <span className="flow-badge-active" title="Conta ativa selecionada por maior saldo conhecido">
                        ★ ATIVA
                      </span>
                    )}
                    {acct.enabled === false && (
                      <span className="flow-badge-disabled">OFF</span>
                    )}
                  </div>
                </div>

                {/* Status Operacional */}
                <div className="flow-status-row">
                  <span
                    className="flow-status-dot"
                    style={{ backgroundColor: statusInfo.dotColor }}
                  />
                  <span className={`flow-status-text ${statusInfo.badgeClass}`}>
                    {statusInfo.label}
                  </span>
                </div>

                {/* Saldo de Créditos + Fonte (Verified / Estimated / Unknown) */}
                <div className="flow-credits-row">
                  <span className="flow-credits-value">
                    {creditsInfo.text}
                  </span>
                  <span className={`flow-source-badge ${creditsInfo.sourceClass}`}>
                    {creditsInfo.sourceLabel}
                  </span>
                </div>

                {/* Task Atual / Disponibilidade */}
                <div className="flow-task-row">
                  <span className="flow-task-label">Execução:</span>
                  <span
                    className={`flow-task-value ${taskInfo.isBusy ? 'in-use' : 'idle'}`}
                    title={taskInfo.fullId || 'Livre'}
                  >
                    {taskInfo.label}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
