"""Fonte canônica única do status operacional do canal (V2).

Princípio regente ("Um controle = um lugar. Uma informação = uma fonte."):
- `evaluate_canonical_channel_status` é a ÚNICA função que decide o status
  operacional de um canal na V2.
- É uma função estritamente pura: não acessa banco de dados nem estado global;
  recebe todos os indicadores já calculados pelo chamador.
- Vocabulário (códigos em minúsculas compatíveis com a Frota):
  {"paused", "blocked", "running", "attention", "ok"}
- Ordem estrita de prioridade:
  paused > blocked > running > attention > ok
"""

from typing import Any, Dict, List, Literal, Optional

CanonicalChannelStatusCode = Literal["paused", "blocked", "running", "attention", "ok"]

STATUS_LABELS: Dict[CanonicalChannelStatusCode, str] = {
    "paused": "Pausado",
    "blocked": "Bloqueado",
    "running": "Gerando",
    "attention": "Atenção",
    "ok": "OK",
}


def evaluate_canonical_channel_status(
    *,
    is_factory_paused: bool = False,
    factory_state: Optional[str] = None,
    is_channel_active: bool = True,
    autonomous_enabled: bool = True,
    has_publish_destination: bool = True,
    auto_state: str = "",
    auto_message: Optional[str] = None,
    auto_last_error: Optional[str] = None,
    ready_stock: Optional[int] = None,
    target_stock: int = 3,
    pending_proc: int = 0,
    consec_rejections: int = 0,
    max_rejections: int = 10,
    approved_24h: int = 0,
    max_generations_24h: int = 0,
    failed_24h: int = 0,
    global_cost_guard_blocked: bool = False,
    diagnoses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Decide de forma determinística o status operacional do canal.

    Ordem estrita de prioridade:
      1. paused   (fábrica pausada, canal inativo ou modo autônomo desligado)
      2. blocked  (disjuntor de rejeições, estado autônomo blocked/error, fábrica em erro,
                   guarda global de custo ou diagnóstico crítico)
      3. running  (geração/planejamento em andamento ou tarefa ativa na fila)
      4. attention (estoque None/desconhecido, teto diário NÃO atingido com estoque abaixo
                    da meta, cooldown, falhas em 24h ou diagnóstico warning)
      5. ok       (canal saudável; se atingiu o teto diário de aprovações com estoque < meta,
                   retorna status="ok", reason_code="DAILY_GOAL_REACHED", reason="Meta diária atingida")

    Retorna:
      {
          "status": "paused" | "blocked" | "running" | "attention" | "ok",
          "label": "Pausado" | "Bloqueado" | "Gerando" | "Atenção" | "OK",
          "reason_code": str,
          "reason": Optional[str],
      }
    """
    norm_factory = str(factory_state or "").strip().upper()
    factory_paused = bool(
        is_factory_paused or norm_factory in ("PAUSED", "EMERGENCY_PAUSED")
    )
    norm_auto_state = str(auto_state or "").strip().lower()
    clean_msg = str(auto_message or "").strip()
    clean_err = str(auto_last_error or "").strip()
    diag_list = diagnoses or []

    # -----------------------------------------------------------------------
    # 1. PRIORIDADE MÁXIMA: PAUSED (pausa intencional sempre prevalece)
    # -----------------------------------------------------------------------
    if factory_paused:
        return {
            "status": "paused",
            "label": STATUS_LABELS["paused"],
            "reason_code": "FACTORY_PAUSED",
            "reason": "Fábrica pausada pelo operador",
        }

    if not is_channel_active:
        return {
            "status": "paused",
            "label": STATUS_LABELS["paused"],
            "reason_code": "CHANNEL_INACTIVE",
            "reason": "Canal desativado pelo operador",
        }

    if not autonomous_enabled:
        return {
            "status": "paused",
            "label": STATUS_LABELS["paused"],
            "reason_code": "AUTONOMOUS_DISABLED",
            "reason": "Modo autônomo desligado",
        }

    # -----------------------------------------------------------------------
    # 2. PRIORIDADE 2: BLOCKED (impedimento operacional ativo)
    # -----------------------------------------------------------------------
    if norm_factory == "ERROR":
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": "FACTORY_ERROR",
            "reason": "Fábrica em estado de erro",
        }

    if not has_publish_destination:
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": "NO_PUBLISH_DESTINATION",
            "reason": "Sem destino de publicação habilitado (YouTube ou TikTok)",
        }

    if global_cost_guard_blocked:
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": "GLOBAL_COST_GUARD",
            "reason": "Guarda global de custo atingida",
        }

    if max_rejections > 0 and consec_rejections >= max_rejections:
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": "REJECTION_BREAKER",
            "reason": f"Disjuntor acionado: {consec_rejections} rejeições consecutivas",
        }

    if norm_auto_state in ("blocked", "error"):
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": "AUTONOMOUS_BLOCKED",
            "reason": clean_msg or clean_err or "Produção autônoma bloqueada",
        }

    critical_diag = next(
        (d for d in diag_list if str(d.get("severity", "")).lower() == "critical"),
        None,
    )
    if critical_diag is not None:
        return {
            "status": "blocked",
            "label": STATUS_LABELS["blocked"],
            "reason_code": str(critical_diag.get("code") or "CRITICAL_DIAGNOSIS"),
            "reason": str(critical_diag.get("title") or "Produção bloqueada por diagnóstico crítico"),
        }

    # -----------------------------------------------------------------------
    # 3. PRIORIDADE 3: RUNNING (execução ativa neste canal)
    # -----------------------------------------------------------------------
    if norm_auto_state in ("generating", "planning") or pending_proc > 0:
        return {
            "status": "running",
            "label": STATUS_LABELS["running"],
            "reason_code": "GENERATING",
            "reason": None,
        }

    # -----------------------------------------------------------------------
    # 4. PRIORIDADE 4 & 5: ATTENTION vs OK
    # Regra crítica 1: Estoque desconhecido (None) NUNCA vira ok -> sempre attention
    # Regra crítica 2: Canal que já atingiu o teto diário de aprovações
    #                  (approved_24h >= max_generations_24h, quando max_generations_24h > 0)
    #                  com estoque < meta é "ok" com reason_code DAILY_GOAL_REACHED
    #                  e reason "Meta diária atingida".
    # -----------------------------------------------------------------------
    if ready_stock is None:
        return {
            "status": "attention",
            "label": STATUS_LABELS["attention"],
            "reason_code": "STOCK_UNKNOWN",
            "reason": "Estoque desconhecido (falha na leitura)",
        }

    daily_goal_reached = (
        max_generations_24h > 0 and approved_24h >= max_generations_24h
    )

    if norm_auto_state == "cooldown" and not daily_goal_reached:
        return {
            "status": "attention",
            "label": STATUS_LABELS["attention"],
            "reason_code": "COOLDOWN",
            "reason": "Em período de espera (cooldown)",
        }

    warning_diag = next(
        (d for d in diag_list if str(d.get("severity", "")).lower() == "warning"),
        None,
    )
    if warning_diag is not None:
        return {
            "status": "attention",
            "label": STATUS_LABELS["attention"],
            "reason_code": str(warning_diag.get("code") or "WARNING_DIAGNOSIS"),
            "reason": str(warning_diag.get("title") or "Canal requer atenção"),
        }

    if ready_stock < target_stock:
        if daily_goal_reached:
            return {
                "status": "ok",
                "label": STATUS_LABELS["ok"],
                "reason_code": "DAILY_GOAL_REACHED",
                "reason": "Meta diária atingida",
            }
        if ready_stock == 0:
            return {
                "status": "attention",
                "label": STATUS_LABELS["attention"],
                "reason_code": "STOCK_EMPTY",
                "reason": "Estoque esgotado (0 vídeos prontos)",
            }
        return {
            "status": "attention",
            "label": STATUS_LABELS["attention"],
            "reason_code": "STOCK_BELOW_TARGET",
            "reason": f"Estoque abaixo da meta ({ready_stock}/{target_stock})",
        }

    if failed_24h > 0:
        return {
            "status": "attention",
            "label": STATUS_LABELS["attention"],
            "reason_code": "RECENT_FAILURES",
            "reason": f"Atenção: {failed_24h} falha(s) registrada(s)",
        }

    if daily_goal_reached:
        return {
            "status": "ok",
            "label": STATUS_LABELS["ok"],
            "reason_code": "DAILY_GOAL_REACHED",
            "reason": "Meta diária atingida",
        }

    return {
        "status": "ok",
        "label": STATUS_LABELS["ok"],
        "reason_code": "OK",
        "reason": None,
    }
