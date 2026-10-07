"""
app/services/monitor_lite.py
============================
Serviço central de coleta e agregação de dados do Monitor Lite (Fase V15 / Monitor Lite).

PRINCÍPIOS ARQUITETURAIS:
- Estritamente somente leitura (READ-ONLY): zero INSERT, UPDATE, DELETE ou mutação.
- Zero acionamento de workers, threads em background ou APIs externas.
- Fail-soft total: ausência de tabelas, registros ou dados retorna fallbacks sem quebrar.
- Reutiliza integralmente production_observability.py, scheduler.py, operator_console.py
  e local_ai_shadow_runs sem duplicar regras de negócio.
- Isolamento estrito por canal mantido.
- Semântica de Local AI preservada (FACT_PACK_INSUFFICIENT não é erro de servidor).
"""

from __future__ import annotations

import os
import socket
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    production_observability,
    scheduler,
)
from app.services.local_ai import LocalAIConfig, get_shadow_db_path


def _get_ro_connection(db_path: Optional[str] = None) -> Optional[sqlite3.Connection]:
    """Retorna conexão SQLite estritamente somente leitura (mode=ro) ou None se DB não existir."""
    target = scheduler.get_db_path(db_path)
    abs_path = os.path.abspath(target)
    if not os.path.isfile(abs_path):
        return None
    try:
        conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as exc:
        logger.debug(f"[MonitorLite] Falha ao abrir conexão read-only: {exc}")
        return None


def check_local_ai_server(host: str = "127.0.0.1", port: int = 8089, timeout: float = 0.15) -> str:
    """Verifica de forma não-bloqueante e instantânea se o llama-server está ouvindo na porta local."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return "ONLINE"
    except Exception:
        return "OFFLINE"


def get_local_ai_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Coleta o estado e o último shadow run do Local AI de forma segura e fail-soft."""
    # 1. Configuração estática local
    cfg = LocalAIConfig()
    configured_mode = str(cfg.mode or "off").upper()

    # 2. Status do servidor local
    if configured_mode == "OFF":
        server_status = "OFF"
        server_badge = "⚪ OFF"
    else:
        srv_state = check_local_ai_server(timeout=0.15)
        server_status = srv_state
        server_badge = "🟢 ONLINE" if srv_state == "ONLINE" else "⚪ OFFLINE"

    last_run_info: Dict[str, Any] = {
        "has_data": False,
        "status": "SEM DADOS" if configured_mode != "OFF" else "OFF",
        "status_badge": "⚪ SEM DADOS" if configured_mode != "OFF" else "⚪ OFF",
        "fact_guard_status": "NÃO EXECUTADO",
        "latency_seconds": 0.0,
        "duration_text": "—",
        "words_text": "—",
        "total_calls": 0,
        "started_at": "—",
        "topic": "—",
        "model_name": cfg.model or "qwen3-8b",
        "error_type": None,
        "description": "Nenhuma execução shadow registrada.",
    }

    # 3. Consulta estritamente ao banco operacional resolvido (sem fallback para homologação/laboratório)
    target_db = scheduler.get_db_path(db_path)
    abs_target_db = os.path.abspath(target_db)
    found_row = None
    if os.path.isfile(abs_target_db):
        try:
            conn = sqlite3.connect(f"file:{abs_target_db}?mode=ro", uri=True, timeout=3.0)
            conn.row_factory = sqlite3.Row
            has_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_ai_shadow_runs';"
            ).fetchone()
            if has_table:
                row = conn.execute(
                    """
                    SELECT id, topic, model_name, started_at, finished_at, latency_seconds,
                           generation_success, json_valid, fact_guard_approved, rewrite_attempted,
                           error_type, error_message, script_word_count, requested_duration_seconds,
                           estimated_duration_seconds, candidate_script_word_count,
                           candidate_estimated_duration_seconds, total_llm_calls
                    FROM local_ai_shadow_runs
                    ORDER BY id DESC LIMIT 1;
                    """
                ).fetchone()
                if row:
                    found_row = row
            conn.close()
        except Exception as exc:
            logger.debug(f"[MonitorLite] Falha ao consultar local_ai_shadow_runs no DB operacional: {exc}")

    if found_row:
        last_run_info["has_data"] = True
        last_run_info["topic"] = str(found_row["topic"] or "—")
        last_run_info["model_name"] = str(found_row["model_name"] or cfg.model or "qwen3-8b")
        last_run_info["latency_seconds"] = round(float(found_row["latency_seconds"] or 0.0), 2)
        last_run_info["total_calls"] = int(found_row["total_llm_calls"] or 0)
        last_run_info["started_at"] = str(found_row["started_at"] or "—")
        err_type = found_row["error_type"]
        last_run_info["error_type"] = err_type

        fg_approved = bool(found_row["fact_guard_approved"])
        gen_success = bool(found_row["generation_success"])
        req_dur = float(found_row["requested_duration_seconds"] or 0.0)
        est_dur = float(found_row["estimated_duration_seconds"] or 0.0)
        cand_dur = float(found_row["candidate_estimated_duration_seconds"] or 0.0)
        words = int(found_row["script_word_count"] or 0)
        cand_words = int(found_row["candidate_script_word_count"] or 0)

        # Semântica estrita: FACT_PACK_INSUFFICIENT vs FAIL_CLOSED vs PASS vs OFF
        if err_type == "FACT_PACK_INSUFFICIENT":
            last_run_info["status"] = "FACT_PACK_INSUFFICIENT"
            last_run_info["status_badge"] = "🟡 FACT_PACK_INSUFFICIENT"
            last_run_info["fact_guard_status"] = "NÃO EXECUTADO"
            last_run_info["duration_text"] = f"0.0s / {req_dur:.1f}s alvo (retido)"
            last_run_info["words_text"] = "0 palavras (bloqueio preventivo)"
            last_run_info["description"] = "Gate de suficiência reteve a geração (fatos insuficientes para sustentar a duração solicitada)."
        elif fg_approved:
            last_run_info["status"] = "PASS"
            last_run_info["status_badge"] = "🟢 PASS"
            last_run_info["fact_guard_status"] = "APROVADO"
            last_run_info["duration_text"] = f"{est_dur:.1f}s faladas / {req_dur:.1f}s alvo"
            last_run_info["words_text"] = f"{words} palavras"
            last_run_info["description"] = "Conteúdo aprovado pelo FactGuard com 100% de sustentação nos fatos."
        elif gen_success:
            last_run_info["status"] = "FAIL_CLOSED"
            last_run_info["status_badge"] = "🔴 FAIL_CLOSED"
            last_run_info["fact_guard_status"] = "REPROVADO"
            disp_dur = cand_dur if cand_dur > 0 else est_dur
            disp_words = cand_words if cand_words > 0 else words
            last_run_info["duration_text"] = f"{disp_dur:.1f}s tentativa / {req_dur:.1f}s alvo"
            last_run_info["words_text"] = f"{disp_words} palavras (reprovado)"
            last_run_info["description"] = "Conteúdo rejeitado pelo FactGuard por afirmações não comprovadas (fail-closed)."
        elif err_type == "MODE_OFF":
            last_run_info["status"] = "OFF"
            last_run_info["status_badge"] = "⚪ OFF"
            last_run_info["fact_guard_status"] = "NÃO EXECUTADO"
            last_run_info["description"] = "Modo shadow desligado no momento da corrida."
        else:
            last_run_info["status"] = "ERROR"
            last_run_info["status_badge"] = f"🔴 ERRO ({err_type or 'FALHA'})"
            last_run_info["fact_guard_status"] = "NÃO EXECUTADO"
            last_run_info["description"] = str(found_row["error_message"] or "Falha de conexão ou formato.")

    return {
        "model": cfg.model or "Qwen3-8B",
        "configured_mode": configured_mode,
        "server_status": server_status,
        "server_badge": server_badge,
        "last_run": last_run_info,
    }


def format_actionable_alerts(warnings: List[str]) -> List[Dict[str, str]]:
    """Traduz códigos brutos de warnings observáveis em alertas acionáveis em pt-BR."""
    alerts: List[Dict[str, str]] = []
    seen = set()

    for w in warnings:
        if not w or w in seen:
            continue
        seen.add(w)

        parts = w.split(":")
        code = parts[0]
        scope = parts[1] if len(parts) > 1 else ""

        channel_prefix = "Canal Principal: " if scope == "default" else ("Histórias e Mistérios: " if scope == "profile-historias-misterio" else "")

        if code == "READY_STOCK_EMPTY":
            alerts.append({
                "code": w,
                "severity": "WARNING",
                "icon": "⚠️",
                "message": f"{channel_prefix}Estoque pronto zerado. A fábrica precisa gerar novos vídeos para manter o cronograma.",
            })
        elif code == "COPYRIGHT_BLOCKED":
            alerts.append({
                "code": w,
                "severity": "CRITICAL",
                "icon": "🚫",
                "message": f"{channel_prefix}Publicação recente possui bloqueio ou reivindicação de copyright pendente.",
            })
        elif code == "SCHEDULER_FAILURES_PRESENT":
            alerts.append({
                "code": w,
                "severity": "WARNING",
                "icon": "⚠️",
                "message": f"{channel_prefix}Existem falhas registradas no envio de posts agendados para publicação.",
            })
        elif code == "ANALYTICS_STALE":
            alerts.append({
                "code": w,
                "severity": "INFO",
                "icon": "⏳",
                "message": f"{channel_prefix}Métricas de analytics sem coleta nas últimas 24 horas.",
            })
        elif code == "GLOBAL_COST_GUARD_NEAR_LIMIT":
            alerts.append({
                "code": w,
                "severity": "WARNING",
                "icon": "🛡️",
                "message": "Cost Guard Global: Consumo diário de gerações ou tentativas atingiu 80% do limite seguro.",
            })
        elif code == "CLOSED_LOOP_BASELINE":
            alerts.append({
                "code": w,
                "severity": "INFO",
                "icon": "ℹ️",
                "message": f"{channel_prefix}Closed Feedback Loop operando em modo baseline (menos de 12 amostras coletadas).",
            })
        else:
            alerts.append({
                "code": w,
                "severity": "INFO",
                "icon": "ℹ️",
                "message": f"Aviso operacional: {w}",
            })

    return alerts


def get_recent_tasks_summary(db_path: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
    """Recupera as 5 a 10 tarefas mais recentes com status limpos e humanizados."""
    recent_tasks: List[Dict[str, Any]] = []

    # 1. Tenta carregar do estado em memória / storage
    try:
        from app.services import state as sm
        all_tasks, _ = sm.state.get_all_tasks(1, limit)
        for t in all_tasks[:limit]:
            st_val = t.get("state")
            if st_val == const.TASK_STATE_COMPLETE:
                icon = "✅"
                st_text = "Pronto"
            elif st_val == const.TASK_STATE_PROCESSING:
                icon = "🔄"
                st_text = "Renderizando"
            elif st_val == const.TASK_STATE_FAILED:
                icon = "❌"
                st_text = "Falhou"
            elif st_val == const.TASK_STATE_PENDING:
                icon = "⏳"
                st_text = "Na Fila"
            else:
                icon = "⚪"
                st_text = str(st_val or "Desconhecido")

            topic = t.get("video_subject") or t.get("topic") or "Vídeo Short"
            prof_id = t.get("profile_id") or "default"
            channel_label = "Canal Principal" if prof_id == "default" else "Histórias e Mistérios"

            recent_tasks.append({
                "task_id": str(t.get("task_id", ""))[:8],
                "topic": topic,
                "channel": channel_label,
                "status_icon": icon,
                "status_text": st_text,
                "progress": int(t.get("progress") or 0),
            })
    except Exception as exc:
        logger.debug(f"[MonitorLite] Falha ao ler tarefas de sm.state: {exc}")

    # 2. Se não houver tarefas, consulta scheduled_posts em SQLite
    if not recent_tasks:
        conn = _get_ro_connection(db_path)
        if conn:
            try:
                has_sched = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_posts';"
                ).fetchone()
                if has_sched:
                    rows = conn.execute(
                        """
                        SELECT id, task_id, status, scheduled_at, profile_id
                        FROM scheduled_posts
                        ORDER BY id DESC LIMIT ?;
                        """,
                        (limit,),
                    ).fetchall()
                    for r in rows:
                        s_status = str(r["status"] or "").lower()
                        if s_status == "published":
                            icon = "✅"
                            st_text = "Publicado"
                        elif s_status in ("ready", "planned"):
                            icon = "⏳"
                            st_text = "Agendado"
                        elif s_status == "failed":
                            icon = "❌"
                            st_text = "Falhou"
                        else:
                            icon = "⚪"
                            st_text = s_status.capitalize()

                        p_id = r["profile_id"] or "default"
                        ch_label = "Canal Principal" if p_id == "default" else "Histórias e Mistérios"
                        recent_tasks.append({
                            "task_id": str(r["task_id"] or r["id"])[:8],
                            "topic": f"Short #{r['id']}",
                            "channel": ch_label,
                            "status_icon": icon,
                            "status_text": st_text,
                            "progress": 100 if s_status == "published" else 0,
                        })
            except Exception as exc:
                logger.debug(f"[MonitorLite] Falha ao consultar scheduled_posts: {exc}")
            finally:
                conn.close()

    return recent_tasks[:limit]


def get_monitor_lite_summary(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Agrega de forma 100% read-only todos os dados do painel executivo do Monitor Lite.
    Pode ser chamado sem Streamlit, permitindo testes unitários determinísticos.
    """
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    today_midnight = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # 1. Checagem de disponibilidade do banco de dados operacional
    target_db = scheduler.get_db_path(db_path)
    abs_db = os.path.abspath(target_db)
    db_available = False
    if os.path.isfile(abs_db):
        test_ro = _get_ro_connection(db_path)
        if test_ro is not None:
            test_ro.close()
            db_available = True

    # 2. Obter snapshot da observabilidade V15 (reuso integral)
    obs_available = True
    try:
        obs_snapshot = production_observability.get_production_observability_snapshot(
            db_path=db_path,
            task_base_dir=task_base_dir,
        )
    except Exception as exc:
        logger.warning(f"[MonitorLite] Falha ao carregar observabilidade V15: {exc}")
        obs_available = False
        obs_snapshot = {
            "generated_at": now_iso,
            "profiles": {},
            "global": {"warnings": [f"OBSERVABILITY_UNAVAILABLE:{exc}"]},
        }

    raw_global = obs_snapshot.get("global", {})
    worker_st = raw_global.get("worker", {})
    profiles = obs_snapshot.get("profiles", {})
    raw_warnings = raw_global.get("warnings", [])

    if any("OBSERVABILITY_UNAVAILABLE" in str(w) for w in raw_warnings) or worker_st.get("status") == "unavailable":
        obs_available = False
    if not db_available:
        obs_available = False

    # 3. Avaliação Estrita de Saúde do Sistema
    is_primary = bool(worker_st.get("is_primary", True))
    factory_state = str(worker_st.get("factory_state", "RUNNING")).upper()
    has_crit_warnings = any("COPYRIGHT_BLOCKED" in str(w) or "FAILURES" in str(w) for w in raw_warnings)

    if factory_state in ("STOPPED", "FAILED"):
        sys_status = "OFFLINE"
        sys_badge = "⚪ OFFLINE"
        role_label = "Fábrica offline / parada"
        sys_text = "Fábrica parada"
    elif (not db_available) or (not obs_available):
        sys_status = "DEGRADED"
        sys_badge = "🟡 ATENÇÃO"
        role_label = "Dados operacionais indisponíveis"
        sys_text = "Dados operacionais indisponíveis"
    elif has_crit_warnings or factory_state == "PAUSED":
        sys_status = "DEGRADED"
        sys_badge = "🟡 ATENÇÃO"
        role_label = "Instância Primária (Master)" if is_primary else "Visualização Secundária (View Only)"
        sys_text = "Atenção operacional"
    else:
        sys_status = "ONLINE"
        sys_badge = "🟢 ONLINE"
        role_label = "Instância Primária (Master)" if is_primary else "Visualização Secundária (View Only)"
        sys_text = "Operação normal"

    # 4. Métricas de Hoje (Produzidos, Publicados, Fila, Alertas)
    # Aprovados últimas 24h em todos os canais
    cost_global = raw_global.get("cost_guard", {})
    produced_today = int(cost_global.get("global_approved_24h", 0))

    # Publicados hoje e Fila agendada via SQLite read-only
    published_today = 0
    queue_count = 0
    conn = _get_ro_connection(db_path)
    if conn:
        try:
            has_posts = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_posts';"
            ).fetchone()
            if has_posts:
                row_queue = conn.execute(
                    """
                    SELECT count(*) AS cnt FROM scheduled_posts
                    WHERE platform = 'youtube' AND status IN ('planned', 'ready');
                    """
                ).fetchone()
                if row_queue:
                    queue_count = int(row_queue["cnt"] or 0)

            has_pubs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_events';"
            ).fetchone()
            if has_pubs:
                row_pub = conn.execute(
                    """
                    SELECT count(*) AS cnt FROM publication_events
                    WHERE platform = 'youtube' AND status IN ('published', 'success') AND published_at >= ?;
                    """,
                    (today_midnight,),
                ).fetchone()
                if row_pub:
                    published_today = int(row_pub["cnt"] or 0)

            # Fallback seguro para contagem de publicados se publication_events não tiver linhas hoje
            if published_today == 0 and has_posts:
                row_pub2 = conn.execute(
                    """
                    SELECT count(*) AS cnt FROM scheduled_posts
                    WHERE platform = 'youtube' AND status = 'published' AND created_at >= ?;
                    """,
                    (today_midnight,),
                ).fetchone()
                if row_pub2:
                    published_today = int(row_pub2["cnt"] or 0)
        except Exception as exc:
            logger.debug(f"[MonitorLite] Falha ao contabilizar posts: {exc}")
        finally:
            conn.close()

    # 4. Produção Atual
    current_prod: Dict[str, Any] = {
        "is_active": False,
        "status_label": "Ocioso (Aguardando ciclo)",
        "topic": "Nenhuma geração em andamento",
        "stage": "IDLE",
        "progress_percent": 0,
        "task_id": None,
        "profile_name": "Video Factory",
    }
    try:
        from app.services import state as sm
        all_tasks, _ = sm.state.get_all_tasks(1, 20)
        for t in all_tasks:
            if t.get("state") == const.TASK_STATE_PROCESSING:
                current_prod["is_active"] = True
                current_prod["status_label"] = "Renderizando / Processando"
                current_prod["topic"] = t.get("video_subject") or t.get("topic") or "Geração de Vídeo Short"
                current_prod["stage"] = "Processando etapa do pipeline"
                current_prod["progress_percent"] = int(t.get("progress") or 50)
                current_prod["task_id"] = t.get("task_id")
                p_id = t.get("profile_id")
                current_prod["profile_name"] = "Canal Principal" if (not p_id or p_id == "default") else "Histórias e Mistérios"
                break
    except Exception as exc:
        logger.debug(f"[MonitorLite] Falha ao ler active_task de sm.state: {exc}")

    # 5. Canais (Dose Diária & Histórias e Mistérios)
    channel_list: List[Dict[str, Any]] = []
    p_keys = [
        (production_observability.PROFILE_DEFAULT, "Dose Diária de Internet (Principal)"),
        (production_observability.PROFILE_MYSTERY, "Histórias e Mistérios (Secundário)"),
    ]

    for p_id, default_display_name in p_keys:
        p_data = profiles.get(p_id, {})
        if not isinstance(p_data, dict) or p_data.get("status") == "unavailable":
            channel_list.append({
                "id": p_id,
                "name": default_display_name,
                "status": "OFFLINE",
                "status_badge": "⚪",
                "ready_stock": 0,
                "target_stock": 3,
                "stock_label": "Sem dados",
                "stock_status": "UNKNOWN",
                "last_published": {"title": "Sem publicações recentes", "published_at": None, "time_ago": "—"},
                "next_slot": {"scheduled_at": None, "time_until": "—"},
                "learning_evidence": "INSUFFICIENT_DATA",
            })
            continue

        p_info = p_data.get("profile", {})
        p_stock = p_data.get("ready_stock", {})
        p_sched = p_data.get("scheduler", {})
        p_pubs = p_data.get("publications", {}).get("recent_publications", [])
        p_cl = p_data.get("closed_feedback_loop", {})

        stock_cnt = int(p_stock.get("count", 0))
        stock_tgt = int(p_stock.get("target", 3))
        is_low = stock_cnt < stock_tgt

        # Nome de apresentação amigável e consistente
        if p_id == production_observability.PROFILE_DEFAULT:
            ch_name = "Dose Diária de Internet (Principal)"
        elif p_id == production_observability.PROFILE_MYSTERY:
            ch_name = "Histórias e Mistérios (Secundário)"
        else:
            ch_name = p_info.get("name") or default_display_name

        # Última publicação
        last_pub_info = {"title": "Nenhum vídeo publicado ainda", "published_at": None, "time_ago": "—"}
        if p_pubs:
            fp = p_pubs[0]
            last_pub_info = {
                "title": f"Short publicado ({str(fp.get('task_id', ''))[:8]})",
                "published_at": fp.get("published_at"),
                "time_ago": str(fp.get("published_at") or "recente"),
            }

        # Próximo slot
        next_slot_info = {"scheduled_at": None, "time_until": "Nenhum slot agendado"}
        n_slot = p_sched.get("next_slot")
        if n_slot and n_slot.get("scheduled_at"):
            next_slot_info = {
                "scheduled_at": n_slot.get("scheduled_at"),
                "time_until": str(n_slot.get("scheduled_at")),
            }

        ch_status = "ONLINE" if not is_low else "WARNING"
        ch_badge = "🟢" if not is_low else "🟡"

        channel_list.append({
            "id": p_id,
            "name": ch_name,
            "status": ch_status,
            "status_badge": ch_badge,
            "ready_stock": stock_cnt,
            "target_stock": stock_tgt,
            "stock_label": f"{stock_cnt} / {stock_tgt} prontos",
            "stock_status": "LOW" if is_low else "NORMAL",
            "last_published": last_pub_info,
            "next_slot": next_slot_info,
            "learning_evidence": p_cl.get("evidence_state", "INSUFFICIENT_DATA"),
        })

    # 6. Local AI
    local_ai_data = get_local_ai_summary(db_path=db_path)

    # 7. Aprendizado & Analytics
    analytics_sched = raw_global.get("analytics_scheduler", {})
    auto_an_enabled = bool(analytics_sched.get("auto_collection_enabled", False))
    auto_an_badge = "✅ Ativo" if auto_an_enabled else "⚠️ Inativo"

    # Feedback loop do canal padrão como referência
    cl_p1 = profiles.get(production_observability.PROFILE_DEFAULT, {}).get("closed_feedback_loop", {})
    cl_mode = cl_p1.get("mode", "baseline")
    cl_samples = int(cl_p1.get("sample_count", 0))
    cl_badge = "✅ Adaptativo" if cl_mode == "adaptive" and cl_samples >= 12 else "⚠️ Baseline"

    learning_data = {
        "analytics_auto": {
            "status": "ACTIVE" if auto_an_enabled else "INACTIVE",
            "badge": auto_an_badge,
            "snapshots_today": int(analytics_sched.get("snapshots_today", 0)),
            "last_cycle": str(analytics_sched.get("last_cycle_at") or "—"),
        },
        "closed_loop": {
            "status": "ADAPTIVE" if cl_mode == "adaptive" else "BASELINE",
            "badge": cl_badge,
            "mode": cl_mode,
            "sample_count": cl_samples,
            "evidence_state": str(cl_p1.get("evidence_state", "INSUFFICIENT_DATA")),
            "isolation": "Garantido por canal",
        },
    }

    # 8. Alertas Acionáveis
    actionable_alerts = format_actionable_alerts(raw_warnings)

    # 9. Últimas Tarefas
    recent_tasks = get_recent_tasks_summary(db_path=db_path, limit=8)

    return {
        "generated_at": now_iso,
        "system": {
            "status": sys_status,
            "badge": sys_badge,
            "text": sys_text,
            "factory_state": factory_state,
            "is_primary": is_primary,
            "role_label": role_label,
            "db_healthy": db_available,
            "scheduler_enabled": bool(worker_st.get("scheduler_enabled", False)),
            "auto_publish_enabled": bool(worker_st.get("auto_publish_enabled", False)),
        },
        "today": {
            "produced_count": produced_today,
            "published_count": published_today,
            "queue_count": queue_count,
            "alerts_count": len(actionable_alerts),
        },
        "current_production": current_prod,
        "channels": channel_list,
        "local_ai": local_ai_data,
        "learning": learning_data,
        "alerts": actionable_alerts,
        "recent_tasks": recent_tasks,
        "raw_observability": obs_snapshot,
    }
