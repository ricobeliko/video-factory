"""Módulo de Console Operacional e Prontidão para Produção (Fase V8).

Centraliza o monitoramento, governança e resiliência operacional da Video Factory:
- Estado Global da Fábrica (RUNNING / PAUSED) com Pause / Resume não-destrutivo
- Parada de Emergência (Emergency Pause)
- Cancelamento Seguro de Tarefas com verificação em checkpoints
- Resumo e Métricas de Filas (Generation Queue & Scheduler Queue)
- Estoque de Vídeos Prontos (Ready Stock) e alertas de limite mínimo
- Health Checks leves e passivos de Provedores (sem chamadas pagas)
- Central de Erros e Registro de Eventos Operacionais (operational_events)
- Reconciliação e Recuperação de Tarefas Órfãs pós-restart
- Telemetria de Heartbeats dos Workers
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from app.config import config
from app.models import const
from app.utils import utils

# Estados Globais da Fábrica
FACTORY_STATE_RUNNING = "RUNNING"
FACTORY_STATE_PAUSED = "PAUSED"
FACTORY_STATES = {FACTORY_STATE_RUNNING, FACTORY_STATE_PAUSED}

# Níveis de Severidade de Eventos
SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"
SEVERITIES = {SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL}

# Estados de Saúde dos Provedores
PROVIDER_HEALTHY = "HEALTHY"
PROVIDER_DEGRADED = "DEGRADED"
PROVIDER_UNAVAILABLE = "UNAVAILABLE"
PROVIDER_UNKNOWN = "UNKNOWN"

# Configuração Padrão de Estoque Mínimo
DEFAULT_MINIMUM_READY_STOCK = 3

# Registro em memória de tarefas com cancelamento solicitado
_cancel_lock = threading.RLock()
_cancel_requested_tasks: Set[str] = set()

# Telemetria do Generation Worker
_gen_heartbeat_lock = threading.RLock()
_last_gen_heartbeat: Optional[datetime] = None


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho do banco SQLite central da Video Factory."""
    if custom_path:
        return custom_path
    from app.services import scheduler
    return scheduler.get_db_path()


def get_connection(db_path: Optional[str] = None):
    """Obtém conexão com SQLite em modo WAL garantindo integridade e timeout."""
    from app.services import scheduler
    return scheduler.get_connection(db_path)


def init_operator_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas do Console Operacional de forma idempotente."""
    from app.services import scheduler
    scheduler.init_db(db_path)

    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT NOT NULL,
                metadata_json TEXT
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_events_ts ON operational_events(timestamp);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_events_comp ON operational_events(component);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_op_events_sev ON operational_events(severity);"
        )


# ---------------------------------------------------------------------------
# 1. Estado Global da Fábrica (RUNNING / PAUSED)
# ---------------------------------------------------------------------------

def get_factory_state(db_path: Optional[str] = None) -> str:
    """Retorna o estado operacional persistente da fábrica (RUNNING ou PAUSED)."""
    from app.services import scheduler
    val = scheduler.get_setting("factory_state", FACTORY_STATE_RUNNING, db_path=db_path)
    if val and str(val).strip().upper() in FACTORY_STATES:
        return str(val).strip().upper()
    return FACTORY_STATE_RUNNING


def set_factory_state(state: str, db_path: Optional[str] = None) -> None:
    """Define e persiste o estado operacional da fábrica no SQLite."""
    clean_state = str(state).strip().upper()
    if clean_state not in FACTORY_STATES:
        raise ValueError(f"Estado de fábrica inválido: '{state}'. Opções: {FACTORY_STATES}")
    from app.services import scheduler
    scheduler.set_setting("factory_state", clean_state, db_path=db_path)
    log_operational_event(
        component="factory",
        severity=SEVERITY_INFO,
        event_type="state_change",
        message=f"Estado da fábrica alterado para {clean_state}",
        db_path=db_path,
    )


def pause_factory(db_path: Optional[str] = None) -> None:
    """Pausa a fábrica de forma não-destrutiva.
    
    Tarefas em andamento concluem normalmente; novas execuções e ciclos são bloqueados.
    """
    set_factory_state(FACTORY_STATE_PAUSED, db_path=db_path)
    logger.warning("[OPERATOR_CONSOLE] Fábrica pausada. Novas execuções bloqueadas.")


def resume_factory(db_path: Optional[str] = None) -> None:
    """Retoma a fábrica para processamento normal."""
    set_factory_state(FACTORY_STATE_RUNNING, db_path=db_path)
    logger.info("[OPERATOR_CONSOLE] Fábrica retomada. Processamento normal reabilitado.")


def is_factory_paused(db_path: Optional[str] = None) -> bool:
    """Retorna True se a fábrica estiver pausada."""
    return get_factory_state(db_path=db_path) == FACTORY_STATE_PAUSED


def emergency_pause(db_path: Optional[str] = None) -> None:
    """Aciona a parada de emergência da fábrica."""
    set_factory_state(FACTORY_STATE_PAUSED, db_path=db_path)
    log_operational_event(
        component="factory",
        severity=SEVERITY_CRITICAL,
        event_type="emergency_pause",
        message="PARADA DE EMERGÊNCIA acionada pelo operador. Execuções interrompidas com segurança.",
        db_path=db_path,
    )
    logger.critical("[OPERATOR_CONSOLE] PARADA DE EMERGÊNCIA ACIONADA.")


# ---------------------------------------------------------------------------
# 2. Configurações Operacionais (Estoque Mínimo)
# ---------------------------------------------------------------------------

def get_minimum_ready_stock(db_path: Optional[str] = None) -> int:
    """Retorna o limite mínimo desejado para o estoque de vídeos prontos."""
    from app.services import scheduler
    val = scheduler.get_setting("minimum_ready_stock", str(DEFAULT_MINIMUM_READY_STOCK), db_path=db_path)
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return DEFAULT_MINIMUM_READY_STOCK


def set_minimum_ready_stock(val: int, db_path: Optional[str] = None) -> None:
    """Define e persiste o limite mínimo de estoque pronto."""
    from app.services import scheduler
    int_val = max(1, int(val))
    scheduler.set_setting("minimum_ready_stock", str(int_val), db_path=db_path)


# ---------------------------------------------------------------------------
# 3. Cancelamento Seguro de Tarefas
# ---------------------------------------------------------------------------

def request_task_cancel(task_id: str, db_path: Optional[str] = None) -> bool:
    """Registra intenção de cancelamento seguro para a tarefa especificada."""
    from app.services import state as sm
    with _cancel_lock:
        _cancel_requested_tasks.add(task_id)

    task_data = sm.state.get_task(task_id)
    if task_data:
        current_state = task_data.get("state")
        # Se estiver PENDING, cancela imediatamente
        if current_state == const.TASK_STATE_PENDING:
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_CANCELLED,
                progress=0,
                cancelled=True,
                error=None,
            )
            with _cancel_lock:
                _cancel_requested_tasks.discard(task_id)

    log_operational_event(
        component="task_manager",
        severity=SEVERITY_INFO,
        event_type="cancel_requested",
        message=f"Cancelamento seguro solicitado para a tarefa {task_id}",
        task_id=task_id,
        db_path=db_path,
    )
    return True


def is_cancel_requested(task_id: str) -> bool:
    """Verifica se há cancelamento solicitado para a tarefa."""
    with _cancel_lock:
        return task_id in _cancel_requested_tasks


def clear_task_cancel(task_id: str) -> None:
    """Limpa o registro de cancelamento da tarefa."""
    with _cancel_lock:
        _cancel_requested_tasks.discard(task_id)


# ---------------------------------------------------------------------------
# 4. Central de Erros e Eventos Operacionais (operational_events)
# ---------------------------------------------------------------------------

def log_operational_event(
    component: str,
    severity: str,
    event_type: str,
    message: str,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> int:
    """Registra um evento operacional no banco SQLite."""
    init_operator_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_sev = severity.strip().upper() if severity else SEVERITY_INFO
    if clean_sev not in SEVERITIES:
        clean_sev = SEVERITY_INFO

    meta_str = json.dumps(metadata) if metadata else None

    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO operational_events (
                timestamp, component, severity, event_type, task_id, message, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (now_iso, component, clean_sev, event_type, task_id, message[:1000], meta_str),
        )
        return cur.lastrowid


def get_operational_events(
    limit: int = 50,
    component: Optional[str] = None,
    severity: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera eventos operacionais recentes com filtros opcionais."""
    init_operator_db(db_path)
    query = "SELECT * FROM operational_events WHERE 1=1"
    params = []

    if component:
        query += " AND component = ?"
        params.append(component)
    if severity:
        query += " AND severity = ?"
        params.append(severity.upper())

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except Exception:
                    d["metadata"] = {}
            result.append(d)
        return result


def get_recent_errors(
    limit: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera os últimos erros e falhas críticas registradas."""
    init_operator_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM operational_events
            WHERE severity IN (?, ?)
            ORDER BY id DESC LIMIT ?;
            """,
            (SEVERITY_ERROR, SEVERITY_CRITICAL, limit),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except Exception:
                    d["metadata"] = {}
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# 5. Filas Operacionais (Generation Queue & Scheduler Queue)
# ---------------------------------------------------------------------------

def get_generation_queue_summary() -> Dict[str, Any]:
    """Retorna o resumo das tarefas de geração ativas, pendentes, concluídas e canceladas."""
    from app.services import state as sm
    tasks, _ = sm.state.get_all_tasks(1, 1000)

    summary = {
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "total": len(tasks),
        "recent_tasks": [],
    }

    for t in tasks:
        s = t.get("state")
        if s == const.TASK_STATE_PENDING:
            summary["pending"] += 1
        elif s == const.TASK_STATE_PROCESSING:
            summary["processing"] += 1
        elif s == const.TASK_STATE_COMPLETE:
            summary["completed"] += 1
        elif s == const.TASK_STATE_FAILED:
            summary["failed"] += 1
        elif s == const.TASK_STATE_CANCELLED:
            summary["cancelled"] += 1

    # Tarefas mais recentes (últimas 10)
    sorted_tasks = sorted(
        tasks,
        key=lambda x: x.get("created_at") or x.get("task_id", ""),
        reverse=True,
    )
    summary["recent_tasks"] = sorted_tasks[:10]
    return summary


def get_scheduler_queue_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o resumo da fila do Scheduler no SQLite."""
    from app.services import scheduler
    scheduler.init_db(db_path)

    with get_connection(db_path) as conn:
        counts = conn.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM scheduled_posts
            GROUP BY status;
            """
        ).fetchall()

        summary = {
            "planned": 0,
            "ready": 0,
            "processing": 0,
            "published": 0,
            "failed": 0,
            "cancelled": 0,
            "total": 0,
            "upcoming_posts": [],
        }

        for row in counts:
            st = row["status"]
            cnt = row["cnt"]
            if st in summary:
                summary[st] = cnt
            summary["total"] += cnt

        # Próximos posts planejados ou prontos
        upcoming = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, attempts
            FROM scheduled_posts
            WHERE status IN ('planned', 'ready')
            ORDER BY scheduled_at ASC
            LIMIT 5;
            """
        ).fetchall()
        summary["upcoming_posts"] = [dict(r) for r in upcoming]
        return summary


# ---------------------------------------------------------------------------
# 6. Estoque de Vídeos Prontos (Ready Stock)
# ---------------------------------------------------------------------------

def get_ready_stock(
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Calcula o estoque de vídeos completos, aprovados no Safety Gate e não publicados."""
    from app.services import scheduler
    from app.services import state as sm

    tasks, _ = sm.state.get_all_tasks(1, 1000)
    scheduler.init_db(db_path)

    # Identifica tarefas já publicadas por plataforma
    published_map = {}
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT task_id, platform FROM publication_events WHERE status = 'success'
            UNION
            SELECT task_id, platform FROM scheduled_posts WHERE status = 'published';
            """
        ).fetchall()
        for r in rows:
            published_map.setdefault(r["task_id"], set()).add(r["platform"].lower().strip())

    youtube_ready: List[Dict[str, Any]] = []
    tiktok_ready: List[Dict[str, Any]] = []
    cross_platform_ready: List[Dict[str, Any]] = []
    all_ready_task_ids = set()

    base_dir = task_base_dir or utils.task_dir()

    for t in tasks:
        task_id = t.get("task_id")
        if not task_id:
            continue
        if t.get("state") != const.TASK_STATE_COMPLETE:
            continue

        # Safety Gate: deve ter passado ou não reprovado
        safety_status = t.get("safety_status")
        if safety_status == "FAIL":
            continue

        # Verifica se o arquivo final de vídeo existe em disco
        final_video = scheduler.get_task_final_video(task_id, task_base_dir=base_dir)
        if not final_video or not os.path.isfile(final_video):
            continue

        already_published = published_map.get(task_id, set())

        is_yt_ready = "youtube" not in already_published
        is_tt_ready = "tiktok" not in already_published

        task_info = {
            "task_id": task_id,
            "topic": t.get("video_subject") or t.get("topic") or task_id,
            "safety_status": safety_status or "PASS",
            "video_path": final_video,
            "created_at": t.get("created_at"),
        }

        if is_yt_ready:
            youtube_ready.append(task_info)
        if is_tt_ready:
            tiktok_ready.append(task_info)
        if is_yt_ready and is_tt_ready:
            cross_platform_ready.append(task_info)

        if is_yt_ready or is_tt_ready:
            all_ready_task_ids.add(task_id)

    min_threshold = get_minimum_ready_stock(db_path=db_path)
    total_ready = len(all_ready_task_ids)

    return {
        "total_ready": total_ready,
        "youtube_count": len(youtube_ready),
        "tiktok_count": len(tiktok_ready),
        "cross_platform_count": len(cross_platform_ready),
        "minimum_threshold": min_threshold,
        "is_below_minimum": total_ready < min_threshold,
        "youtube_items": youtube_ready[:5],
        "tiktok_items": tiktok_ready[:5],
        "cross_platform_items": cross_platform_ready[:5],
    }


# ---------------------------------------------------------------------------
# 7. Saúde dos Provedores (Provider Health)
# ---------------------------------------------------------------------------

def get_provider_health_summary(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Avalia o status de saúde dos provedores de forma leve e estática (sem chamadas pagas)."""
    summary: Dict[str, Dict[str, Any]] = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    # Consulta eventos recentes no operational_events
    recent_events = get_operational_events(limit=50, db_path=db_path)
    errors_by_comp: Dict[str, List[Dict[str, Any]]] = {}
    for ev in recent_events:
        if ev.get("severity") in (SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL):
            c = ev.get("component", "").lower()
            errors_by_comp.setdefault(c, []).append(ev)

    # 1. FFmpeg
    ffmpeg_ok = utils.check_ffmpeg_ready()
    summary["FFmpeg"] = {
        "status": PROVIDER_HEALTHY if ffmpeg_ok else PROVIDER_UNAVAILABLE,
        "details": "Binário FFmpeg funcional e detectado no PATH" if ffmpeg_ok else "Binário FFmpeg não encontrado ou inoperante",
        "last_error": None if ffmpeg_ok else "FFmpeg não executável",
        "last_checked": now_iso,
    }

    # 2. Gemini LLM
    gemini_key = config.app.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    gemini_err = errors_by_comp.get("gemini")
    if gemini_key:
        summary["Gemini"] = {
            "status": PROVIDER_DEGRADED if gemini_err else PROVIDER_HEALTHY,
            "details": "Chave de API configurada",
            "last_error": gemini_err[0]["message"] if gemini_err else None,
            "last_checked": now_iso,
        }
    else:
        summary["Gemini"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": "API Key ausente no config.toml",
            "last_error": "Chave não configurada",
            "last_checked": now_iso,
        }

    # 3. Pexels
    pexels_key = config.app.get("pexels_api_key") or os.environ.get("PEXELS_API_KEY")
    pexels_err = errors_by_comp.get("pexels")
    if pexels_key:
        summary["Pexels"] = {
            "status": PROVIDER_DEGRADED if pexels_err else PROVIDER_HEALTHY,
            "details": "Chave de API configurada",
            "last_error": pexels_err[0]["message"] if pexels_err else None,
            "last_checked": now_iso,
        }
    else:
        summary["Pexels"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": "Chave ausente no config.toml",
            "last_error": "Chave não configurada",
            "last_checked": now_iso,
        }

    # 4. Edge TTS
    try:
        import edge_tts
        summary["Edge TTS"] = {
            "status": PROVIDER_HEALTHY,
            "details": f"Biblioteca edge-tts pronta (v{getattr(edge_tts, '__version__', 'ok')})",
            "last_error": None,
            "last_checked": now_iso,
        }
    except Exception as exc:
        summary["Edge TTS"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": f"Falha ao carregar edge_tts: {exc}",
            "last_error": str(exc),
            "last_checked": now_iso,
        }

    # 5. Google Trends
    trends_err = errors_by_comp.get("google_trends") or errors_by_comp.get("trend_radar")
    summary["Google Trends"] = {
        "status": PROVIDER_DEGRADED if trends_err else PROVIDER_HEALTHY,
        "details": "Feed e Radar de Tendências ativos",
        "last_error": trends_err[0]["message"] if trends_err else None,
        "last_checked": now_iso,
    }

    # 6. RSS Feeds
    rss_err = errors_by_comp.get("rss")
    summary["RSS"] = {
        "status": PROVIDER_DEGRADED if rss_err else PROVIDER_HEALTHY,
        "details": "Coleta RSS ativa",
        "last_error": rss_err[0]["message"] if rss_err else None,
        "last_checked": now_iso,
    }

    # 7. Reddit
    reddit_err = errors_by_comp.get("reddit")
    if reddit_err:
        summary["Reddit"] = {
            "status": PROVIDER_DEGRADED,
            "details": "Erros recentes registrados na coleta Reddit",
            "last_error": reddit_err[0]["message"],
            "last_checked": now_iso,
        }
    else:
        summary["Reddit"] = {
            "status": PROVIDER_HEALTHY,
            "details": "Coleta Reddit disponível",
            "last_error": None,
            "last_checked": now_iso,
        }

    # 8. Upload-Post
    try:
        from app.services import upload_post
        up_configured = upload_post.upload_post_service.is_configured()
        up_err = errors_by_comp.get("upload_post")
        if up_configured:
            summary["Upload-Post"] = {
                "status": PROVIDER_DEGRADED if up_err else PROVIDER_HEALTHY,
                "details": f"Configurado para plataformas: {list(upload_post.upload_post_service.platforms)}",
                "last_error": up_err[0]["message"] if up_err else None,
                "last_checked": now_iso,
            }
        else:
            summary["Upload-Post"] = {
                "status": PROVIDER_UNKNOWN,
                "details": "Upload-Post não configurado (publicação externa desativada)",
                "last_error": None,
                "last_checked": now_iso,
            }
    except Exception as exc:
        summary["Upload-Post"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": f"Erro de serviço: {exc}",
            "last_error": str(exc),
            "last_checked": now_iso,
        }

    return summary


# ---------------------------------------------------------------------------
# 8. Telemetria e Heartbeats dos Workers
# ---------------------------------------------------------------------------

def record_generation_heartbeat() -> None:
    """Registra batimento cardíaco da thread de geração."""
    global _last_gen_heartbeat
    with _gen_heartbeat_lock:
        _last_gen_heartbeat = datetime.now(timezone.utc)


def get_heartbeats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna a telemetria de batimentos cardíacos do Generation Worker e Scheduler."""
    now = datetime.now(timezone.utc)
    from app.services import scheduler

    # 1. Generation Worker
    with _gen_heartbeat_lock:
        gen_dt = _last_gen_heartbeat
    gen_seconds_ago = (now - gen_dt).total_seconds() if gen_dt else None

    # 2. Scheduler Worker
    sched_tick_iso = scheduler.get_setting("executor_last_tick", None, db_path=db_path)
    sched_seconds_ago = None
    if sched_tick_iso:
        try:
            from app.services.scheduler import _from_iso
            tick_dt = _from_iso(sched_tick_iso)
            sched_seconds_ago = (now - tick_dt).total_seconds()
        except Exception:
            pass

    return {
        "generation_last_heartbeat": gen_dt.isoformat() if gen_dt else None,
        "generation_seconds_ago": round(gen_seconds_ago, 1) if gen_seconds_ago is not None else None,
        "scheduler_last_heartbeat": sched_tick_iso,
        "scheduler_seconds_ago": round(sched_seconds_ago, 1) if sched_seconds_ago is not None else None,
    }


# ---------------------------------------------------------------------------
# 9. Reconciliação e Recuperação de Tarefas Órfãs pós-restart
# ---------------------------------------------------------------------------

def reconcile_orphaned_tasks(
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Detecta tarefas que ficaram com estado PROCESSING após queda/restart e recupera com segurança.
    
    - Se o arquivo final de vídeo existe: reconcilia para COMPLETE.
    - Se a tarefa estava no meio do processo: marca FAILED com failed_stage='interrupted_by_restart'.
    """
    from app.services import scheduler
    from app.services import state as sm
    from app.services import webui_task

    active_ids = set(webui_task.get_active_task_ids())
    tasks, _ = sm.state.get_all_tasks(1, 1000)
    base_dir = task_base_dir or utils.task_dir()

    reconciled = []

    for t in tasks:
        task_id = t.get("task_id")
        if not task_id:
            continue
        if t.get("state") != const.TASK_STATE_PROCESSING:
            continue

        # Se a tarefa está viva no worker do processo atual, não é órfã
        if task_id in active_ids:
            continue

        final_video = scheduler.get_task_final_video(task_id, task_base_dir=base_dir)
        if final_video and os.path.isfile(final_video):
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_COMPLETE,
                progress=100,
                video_file=final_video,
            )
            item_rec = {"task_id": task_id, "action": "completed", "video_file": final_video}
            log_operational_event(
                component="task_manager",
                severity=SEVERITY_INFO,
                event_type="task_reconciled",
                message=f"Tarefa órfã {task_id} reconciliada para COMPLETE (vídeo existente encontrado)",
                task_id=task_id,
                db_path=db_path,
            )
        else:
            sm.state.update_task(
                task_id,
                state=const.TASK_STATE_FAILED,
                progress=t.get("progress", 0),
                failed_stage="interrupted_by_restart",
                error="Execução interrompida pela reinicialização do sistema",
            )
            item_rec = {"task_id": task_id, "action": "failed_recoverable"}
            log_operational_event(
                component="task_manager",
                severity=SEVERITY_WARNING,
                event_type="task_reconciled",
                message=f"Tarefa órfã {task_id} reconciliada para FAILED (interrompida por restart)",
                task_id=task_id,
                db_path=db_path,
            )
        reconciled.append(item_rec)

    return reconciled


def reexecute_task(task_id: str, task_base_dir: Optional[str] = None) -> Optional[str]:
    """Cria uma nova execução controlada reutilizando os parâmetros originais da tarefa."""
    from app.models.schema import VideoParams
    from app.services import state as sm
    from app.services import webui_task

    task_data = sm.state.get_task(task_id)
    if not task_data:
        return None

    # Tenta obter parâmetros do script.json em disco ou da memória
    base_dir = task_base_dir or utils.task_dir()
    script_file = os.path.join(base_dir, task_id, "script.json")
    params = None

    if os.path.isfile(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "params" in data:
                    params = VideoParams(**data["params"])
        except Exception as exc:
            logger.warning(f"Erro ao ler script.json para reexecutar {task_id}: {exc}")

    if not params:
        # Cria parâmetros mínimos usando o tema original
        subj = task_data.get("video_subject") or task_data.get("topic") or "Tema"
        params = VideoParams(video_subject=subj)

    new_task_id = utils.get_uuid()
    webui_task.submit_generation(new_task_id, params)
    log_operational_event(
        component="task_manager",
        severity=SEVERITY_INFO,
        event_type="task_reexecuted",
        message=f"Tarefa {task_id} reexecutada com novo task_id {new_task_id}",
        task_id=new_task_id,
    )
    return new_task_id


# ---------------------------------------------------------------------------
# 10. Status Global Consolidado (System Status)
# ---------------------------------------------------------------------------

def get_system_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Consolida o status completo da Video Factory para o cabeçalho do Operator Console."""
    from app.services import scheduler
    from app.services import webui_task

    factory_state = get_factory_state(db_path=db_path)
    scheduler_status = scheduler.get_executor_status(db_path=db_path)
    sched_settings = scheduler.get_all_settings(db_path=db_path)
    growth_mode = scheduler.get_growth_mode(db_path=db_path)
    heartbeats = get_heartbeats(db_path=db_path)
    providers = get_provider_health_summary(db_path=db_path)
    recent_errors = get_recent_errors(limit=1, db_path=db_path)

    # Worker de Geração
    gen_active = webui_task.has_active_generation_tasks()
    gen_worker_state = "ACTIVE" if gen_active else "IDLE"

    # Worker do Scheduler
    sched_worker_state = "ACTIVE" if scheduler_status.get("worker_active") else "IDLE"
    if scheduler_status.get("state") == "error":
        sched_worker_state = "ERROR"

    # Status consolidado da Factory
    if factory_state == FACTORY_STATE_PAUSED:
        consolidated_factory = FACTORY_STATE_PAUSED
    elif any(p.get("status") == PROVIDER_UNAVAILABLE for k, p in providers.items() if k == "FFmpeg"):
        consolidated_factory = "ERROR"
    elif any(p.get("status") in (PROVIDER_DEGRADED, PROVIDER_UNAVAILABLE) for p in providers.values()):
        consolidated_factory = "DEGRADED"
    else:
        consolidated_factory = FACTORY_STATE_RUNNING

    # Última geração concluída
    gen_summary = get_generation_queue_summary()
    completed_tasks = [t for t in gen_summary.get("recent_tasks", []) if t.get("state") == const.TASK_STATE_COMPLETE]
    last_gen_iso = completed_tasks[0].get("created_at") if completed_tasks else None

    # Última publicação
    with get_connection(db_path) as conn:
        last_pub_row = conn.execute(
            "SELECT published_at, platform, task_id FROM publication_events WHERE status = 'success' ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        last_pub_info = dict(last_pub_row) if last_pub_row else None

    # Alertas operacionais ativos
    alerts = []
    if heartbeats.get("scheduler_seconds_ago") is not None and heartbeats["scheduler_seconds_ago"] > 120:
        alerts.append("⚠ Scheduler sem heartbeat há mais de 2 minutos")
    if sched_settings.get("auto_publish_enabled") and not sched_settings.get("dry_run"):
        alerts.append("ℹ️ Auto Publish ativo com modo de publicação REAL (Dry Run desligado)")
    
    # Checa se há tarefas com falhas recentes (últimos 3 erros)
    errs_3 = get_recent_errors(limit=3, db_path=db_path)
    if len(errs_3) >= 3:
        alerts.append("⚠ 3 ou mais falhas recentes registradas na Central de Erros")

    ready_stock = get_ready_stock(db_path=db_path)
    if ready_stock["is_below_minimum"]:
        alerts.append(f"⚠ Estoque de vídeos prontos ({ready_stock['total_ready']}) abaixo do mínimo configurado ({ready_stock['minimum_threshold']})")

    for prov_name, prov_info in providers.items():
        if prov_info.get("status") == PROVIDER_UNAVAILABLE:
            alerts.append(f"⚠ Provedor {prov_name} INDISPONÍVEL: {prov_info.get('last_error') or prov_info.get('details')}")

    return {
        "factory_state": consolidated_factory,
        "is_paused": factory_state == FACTORY_STATE_PAUSED,
        "generation_worker": gen_worker_state,
        "scheduler_worker": sched_worker_state,
        "auto_publish": "ON" if sched_settings.get("auto_publish_enabled") else "OFF",
        "dry_run": "ON" if sched_settings.get("dry_run") else "OFF",
        "growth_mode": growth_mode.upper(),
        "heartbeats": heartbeats,
        "last_generation_at": last_gen_iso,
        "last_publication": last_pub_info,
        "last_error": recent_errors[0] if recent_errors else None,
        "alerts": alerts,
    }
