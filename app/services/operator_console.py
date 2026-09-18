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

import atexit
import json
import os
import platform
import socket
import sqlite3
import threading
import uuid
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

# Papéis de Instância (Fase V8.1)
ROLE_PRIMARY = "PRIMARY"
ROLE_SECONDARY_VIEW_ONLY = "SECONDARY_VIEW_ONLY"
ROLES = {ROLE_PRIMARY, ROLE_SECONDARY_VIEW_ONLY}

# Estados da Instância
INSTANCE_STATUS_ACTIVE = "ACTIVE"
INSTANCE_STATUS_STALE = "STALE"
INSTANCE_STATUS_STOPPED = "STOPPED"
INSTANCE_STATUSES = {INSTANCE_STATUS_ACTIVE, INSTANCE_STATUS_STALE, INSTANCE_STATUS_STOPPED}

# Eventos Operacionais de Instância
EVENT_INSTANCE_PRIMARY_ACQUIRED = "INSTANCE_PRIMARY_ACQUIRED"
EVENT_INSTANCE_VIEW_ONLY_STARTED = "INSTANCE_VIEW_ONLY_STARTED"
EVENT_INSTANCE_HEARTBEAT_STALE = "INSTANCE_HEARTBEAT_STALE"
EVENT_INSTANCE_TAKEOVER = "INSTANCE_TAKEOVER"
EVENT_INSTANCE_STOPPED = "INSTANCE_STOPPED"

DEFAULT_INSTANCE_LOCK_KEY = "PRIMARY_FACTORY"
DEFAULT_INSTANCE_TIMEOUT_SECONDS = 90
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15
DEFAULT_FACTORY_NODE_NAME = "VIDEO-FACTORY-PROD"

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

# Controle de Instância em Memória (Singleton por Processo)
_instance_state_lock = threading.RLock()
_instance_initialized: bool = False
_current_node_id: Optional[str] = None
_current_role: str = ROLE_PRIMARY
_current_node_name: str = DEFAULT_FACTORY_NODE_NAME
_current_started_at: Optional[datetime] = None
_instance_heartbeat_thread: Optional[threading.Thread] = None
_instance_heartbeat_stop_event = threading.Event()

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
            """

            CREATE TABLE IF NOT EXISTS instance_locks (
                lock_key TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inst_lock_status ON instance_locks(status);"
        )


# ---------------------------------------------------------------------------
# 0. Governança de Instância Única e Nó Primário (Fase V8.1)
# ---------------------------------------------------------------------------

def _is_local_pid_alive(pid: int) -> bool:
    """Verifica se um processo com determinado PID ainda existe na máquina local."""
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                pid,
            )

            if handle:
                kernel32.CloseHandle(handle)
                return True

            return ctypes.get_last_error() == 5

        except Exception:
            return False

    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False


def _parse_iso_utc(ts: Optional[str]) -> Optional[datetime]:
    """Converte string ISO para datetime UTC timezone-aware."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def acquire_instance_lock(
    node_name: Optional[str] = None,
    timeout_seconds: int = DEFAULT_INSTANCE_TIMEOUT_SECONDS,
    db_path: Optional[str] = None,
    force_node_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Tenta adquirir ou renovar o lock de instância única da Video Factory.

    Garante atomicidade estrita no SQLite (evitando corrida de takeover).
    Se o lock for adquirido ou recuperado -> retorna (ROLE_PRIMARY, info).
    Se outra instância estiver ativa e saudável -> retorna (ROLE_SECONDARY_VIEW_ONLY, info).
    """
    global _current_node_id, _current_role, _current_node_name, _current_started_at
    init_operator_db(db_path)

    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    my_hostname = platform.node() or socket.gethostname() or "unknown_host"
    my_pid = os.getpid()
    chosen_node_name = (
        node_name
        or config.app.get("factory_node_name")
        or DEFAULT_FACTORY_NODE_NAME
    )
    my_node_id = force_node_id or _current_node_id or str(uuid.uuid4())

    events_to_log = []
    outcome_role = None
    outcome_dict = {}

    with _instance_state_lock:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM instance_locks WHERE lock_key = ?;",
                (DEFAULT_INSTANCE_LOCK_KEY,),
            ).fetchone()

            if row is None:
                # Caso 1: Tabela vazia. Tenta INSERT atômico como PRIMARY.
                try:
                    conn.execute(
                        """
                        INSERT INTO instance_locks (
                            lock_key, node_id, node_name, hostname, pid,
                            started_at, last_heartbeat, role, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            DEFAULT_INSTANCE_LOCK_KEY,
                            my_node_id,
                            chosen_node_name,
                            my_hostname,
                            my_pid,
                            now_iso,
                            now_iso,
                            ROLE_PRIMARY,
                            INSTANCE_STATUS_ACTIVE,
                        ),
                    )
                    res_row = conn.execute(
                        "SELECT * FROM instance_locks WHERE lock_key = ?;",
                        (DEFAULT_INSTANCE_LOCK_KEY,),
                    ).fetchone()
                    outcome_role = ROLE_PRIMARY
                    outcome_dict = dict(res_row) if res_row else {}
                    events_to_log.append({
                        "severity": SEVERITY_INFO,
                        "event_type": EVENT_INSTANCE_PRIMARY_ACQUIRED,
                        "message": f"Nó primário '{chosen_node_name}' (PID {my_pid}) assumiu o controle da fábrica.",
                        "metadata": {"node_id": my_node_id, "hostname": my_hostname, "pid": my_pid},
                    })
                except sqlite3.IntegrityError:
                    # Outra instância inseriu concorrentemente! Re-lê o lock.
                    row = conn.execute(
                        "SELECT * FROM instance_locks WHERE lock_key = ?;",
                        (DEFAULT_INSTANCE_LOCK_KEY,),
                    ).fetchone()

            if outcome_role is None:
                curr_dict = dict(row) if row else {}
                curr_status = curr_dict.get("status")
                curr_node_id = curr_dict.get("node_id")
                curr_hostname = curr_dict.get("hostname")
                curr_pid = int(curr_dict.get("pid") or 0)
                curr_last_hb = _parse_iso_utc(curr_dict.get("last_heartbeat"))

                # Caso 2: É o mesmo processo re-confirmando o lock
                if (
                    curr_status == INSTANCE_STATUS_ACTIVE
                    and curr_hostname == my_hostname
                    and curr_pid == my_pid
                    and curr_node_id == my_node_id
                ):
                    conn.execute(
                        """
                        UPDATE instance_locks
                        SET last_heartbeat = ?
                        WHERE lock_key = ? AND node_id = ?;
                        """,
                        (now_iso, DEFAULT_INSTANCE_LOCK_KEY, curr_node_id),
                    )
                    res_row = conn.execute(
                        "SELECT * FROM instance_locks WHERE lock_key = ?;",
                        (DEFAULT_INSTANCE_LOCK_KEY,),
                    ).fetchone()
                    outcome_role = ROLE_PRIMARY
                    outcome_dict = dict(res_row) if res_row else curr_dict

                # Caso 3: Lock liberado normalmente (status == STOPPED)
                elif curr_status == INSTANCE_STATUS_STOPPED:
                    cur = conn.execute(
                        """
                        UPDATE instance_locks
                        SET node_id = ?, node_name = ?, hostname = ?, pid = ?,
                            started_at = ?, last_heartbeat = ?, role = ?, status = ?
                        WHERE lock_key = ? AND status = ?;
                        """,
                        (
                            my_node_id,
                            chosen_node_name,
                            my_hostname,
                            my_pid,
                            now_iso,
                            now_iso,
                            ROLE_PRIMARY,
                            INSTANCE_STATUS_ACTIVE,
                            DEFAULT_INSTANCE_LOCK_KEY,
                            INSTANCE_STATUS_STOPPED,
                        ),
                    )
                    if cur.rowcount > 0:
                        res_row = conn.execute(
                            "SELECT * FROM instance_locks WHERE lock_key = ?;",
                            (DEFAULT_INSTANCE_LOCK_KEY,),
                        ).fetchone()
                        outcome_role = ROLE_PRIMARY
                        outcome_dict = dict(res_row) if res_row else {}
                        events_to_log.append({
                            "severity": SEVERITY_INFO,
                            "event_type": EVENT_INSTANCE_PRIMARY_ACQUIRED,
                            "message": f"Nó primário '{chosen_node_name}' (PID {my_pid}) assumiu o lock após liberação limpa.",
                            "metadata": {"node_id": my_node_id, "hostname": my_hostname, "pid": my_pid},
                        })

                # Caso 4: Verificar se o lock está stale ou se o processo local no mesmo host morreu
                if outcome_role is None:
                    is_stale = False
                    stale_reason = ""
                    if curr_last_hb:
                        delta_sec = (now_utc - curr_last_hb).total_seconds()
                        if delta_sec > timeout_seconds:
                            is_stale = True
                            stale_reason = f"heartbeat_timeout ({delta_sec:.1f}s > {timeout_seconds}s)"
                    else:
                        is_stale = True
                        stale_reason = "missing_heartbeat"

                    # Se no mesmo host, verifica se o PID local ainda está vivo
                    if not is_stale and curr_hostname == my_hostname:
                        if not _is_local_pid_alive(curr_pid):
                            is_stale = True
                            stale_reason = f"local_pid_dead (PID {curr_pid} não existe mais no host {my_hostname})"

                    if is_stale:
                        # Takeover Atômico no SQLite com WHERE last_heartbeat = ? (ou IS NULL)
                        last_hb_val = curr_dict.get("last_heartbeat")
                        if last_hb_val is None:
                            cur = conn.execute(
                                """
                                UPDATE instance_locks
                                SET node_id = ?, node_name = ?, hostname = ?, pid = ?,
                                    started_at = ?, last_heartbeat = ?, role = ?, status = ?
                                WHERE lock_key = ? AND last_heartbeat IS NULL;
                                """,
                                (
                                    my_node_id,
                                    chosen_node_name,
                                    my_hostname,
                                    my_pid,
                                    now_iso,
                                    now_iso,
                                    ROLE_PRIMARY,
                                    INSTANCE_STATUS_ACTIVE,
                                    DEFAULT_INSTANCE_LOCK_KEY,
                                ),
                            )
                        else:
                            cur = conn.execute(
                                """
                                UPDATE instance_locks
                                SET node_id = ?, node_name = ?, hostname = ?, pid = ?,
                                    started_at = ?, last_heartbeat = ?, role = ?, status = ?
                                WHERE lock_key = ? AND last_heartbeat = ?;
                                """,
                                (
                                    my_node_id,
                                    chosen_node_name,
                                    my_hostname,
                                    my_pid,
                                    now_iso,
                                    now_iso,
                                    ROLE_PRIMARY,
                                    INSTANCE_STATUS_ACTIVE,
                                    DEFAULT_INSTANCE_LOCK_KEY,
                                    last_hb_val,
                                ),
                            )
                        if cur.rowcount > 0:
                            res_row = conn.execute(
                                "SELECT * FROM instance_locks WHERE lock_key = ?;",
                                (DEFAULT_INSTANCE_LOCK_KEY,),
                            ).fetchone()
                            outcome_role = ROLE_PRIMARY
                            outcome_dict = dict(res_row) if res_row else {}
                            events_to_log.append({
                                "severity": SEVERITY_WARNING,
                                "event_type": EVENT_INSTANCE_HEARTBEAT_STALE,
                                "message": f"Lock da instância anterior identificado como stale ({stale_reason}). Nó anterior: {str(curr_node_id)[:8]}",
                                "metadata": {"stale_reason": stale_reason, "previous_node": curr_node_id},
                            })
                            events_to_log.append({
                                "severity": SEVERITY_WARNING,
                                "event_type": EVENT_INSTANCE_TAKEOVER,
                                "message": f"Nó '{chosen_node_name}' (PID {my_pid}) executou takeover atômico e assumiu como PRIMARY.",
                                "metadata": {"node_id": my_node_id, "hostname": my_hostname, "pid": my_pid},
                            })

                # Caso 5: Se ainda não virou PRIMARY, lê o PRIMARY vencedor e vira SECONDARY
                if outcome_role is None:
                    fresh_row = conn.execute(
                        "SELECT * FROM instance_locks WHERE lock_key = ?;",
                        (DEFAULT_INSTANCE_LOCK_KEY,),
                    ).fetchone()
                    outcome_role = ROLE_SECONDARY_VIEW_ONLY
                    outcome_dict = dict(fresh_row) if fresh_row else curr_dict

        # Fim do bloco "with get_connection" -> transação SQLite commitada e liberada!
        if outcome_role == ROLE_PRIMARY:
            _current_node_id = outcome_dict.get("node_id") or my_node_id
            _current_role = ROLE_PRIMARY
            _current_node_name = outcome_dict.get("node_name") or chosen_node_name
            _current_started_at = _parse_iso_utc(outcome_dict.get("started_at")) or now_utc

            for ev in events_to_log:
                log_operational_event(
                    component="InstanceLock",
                    severity=ev["severity"],
                    event_type=ev["event_type"],
                    message=ev["message"],
                    metadata=ev.get("metadata"),
                    db_path=db_path,
                )
            start_instance_heartbeat(db_path=db_path)
            return ROLE_PRIMARY, outcome_dict
        else:
            return _enter_view_only(chosen_node_name, my_hostname, my_pid, outcome_dict, db_path)


def _enter_view_only(
    node_name: str,
    hostname: str,
    pid: int,
    primary_dict: Dict[str, Any],
    db_path: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """Configura o processo atual para operar estritamente em SECONDARY_VIEW_ONLY."""
    global _current_role, _current_node_name
    _current_role = ROLE_SECONDARY_VIEW_ONLY
    _current_node_name = node_name
    stop_instance_heartbeat()

    log_operational_event(
        component="InstanceLock",
        severity=SEVERITY_INFO,
        event_type=EVENT_INSTANCE_VIEW_ONLY_STARTED,
        message=f"Instância iniciada em modo SECONDARY_VIEW_ONLY (PID {pid}). PRIMARY ativo no nó '{primary_dict.get('node_name')}' (PID {primary_dict.get('pid')}).",
        metadata_json=json.dumps({
            "primary_node_id": primary_dict.get("node_id"),
            "primary_hostname": primary_dict.get("hostname"),
            "primary_pid": primary_dict.get("pid"),
        }),
        db_path=db_path,
    )
    return ROLE_SECONDARY_VIEW_ONLY, primary_dict


def ensure_instance_initialized(
    node_name: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Garante a inicialização do estado da instância no processo (singleton).

    Novas abas, sessões ou reruns do Streamlit NÃO executam novo acquire
    nem renegociam o lock no SQLite.
    """
    global _instance_initialized, _current_role
    with _instance_state_lock:
        if _instance_initialized:
            return _current_role, get_instance_info(db_path=db_path)
        role, info = acquire_instance_lock(node_name=node_name, db_path=db_path)
        _instance_initialized = True
        return role, info


def reset_instance_for_testing() -> None:
    """Reseta o estado da instância em memória (exclusivo para testes unitários)."""
    global _instance_initialized, _current_node_id, _current_role, _current_node_name, _current_started_at
    stop_instance_heartbeat()
    with _instance_state_lock:
        _instance_initialized = False
        _current_node_id = None
        _current_role = ROLE_PRIMARY
        _current_node_name = DEFAULT_FACTORY_NODE_NAME
        _current_started_at = None


def is_primary_instance(db_path: Optional[str] = None) -> bool:
    """Retorna True se o processo atual for o PRIMARY da fábrica."""
    with _instance_state_lock:
        if not _instance_initialized:
            ensure_instance_initialized(db_path=db_path)
        return _current_role == ROLE_PRIMARY


def require_primary_instance(db_path: Optional[str] = None) -> None:
    """Valida se o processo atual é a instância primária operacional.

    Levanta PermissionError se for SECONDARY_VIEW_ONLY.
    """
    if not is_primary_instance(db_path=db_path):
        raise PermissionError(
            "Operação bloqueada: Esta instância está operando em modo VIEW ONLY. "
            "Apenas o nó primário pode executar gerações, agendamentos, publicações ou alterações de estado."
        )


def record_instance_heartbeat(db_path: Optional[str] = None) -> None:
    """Atualiza o timestamp de heartbeat da instância primária atual."""
    with _instance_state_lock:
        if _current_role != ROLE_PRIMARY or not _current_node_id:
            return
        curr_node_id = _current_node_id

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE instance_locks
                SET last_heartbeat = ?
                WHERE lock_key = ? AND node_id = ? AND role = ? AND status = ?;
                """,
                (now_iso, DEFAULT_INSTANCE_LOCK_KEY, curr_node_id, ROLE_PRIMARY, INSTANCE_STATUS_ACTIVE),
            )
    except Exception as exc:
        logger.warning(f"Erro ao registrar heartbeat de instância: {exc}")


def _instance_heartbeat_worker_loop(interval_seconds: int, db_path: Optional[str]) -> None:
    """Loop daemon em segundo plano que emite batimentos cardíacos periódicos do nó PRIMARY."""
    while not _instance_heartbeat_stop_event.wait(interval_seconds):
        with _instance_state_lock:
            if _current_role != ROLE_PRIMARY:
                break
        record_instance_heartbeat(db_path=db_path)


def start_instance_heartbeat(
    interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    db_path: Optional[str] = None,
) -> None:
    """Inicia a thread daemon de heartbeat para o nó primário."""
    global _instance_heartbeat_thread
    with _instance_state_lock:
        if _current_role != ROLE_PRIMARY:
            return
        if _instance_heartbeat_thread is not None and _instance_heartbeat_thread.is_alive():
            return
        _instance_heartbeat_stop_event.clear()
        _instance_heartbeat_thread = threading.Thread(
            target=_instance_heartbeat_worker_loop,
            args=(interval_seconds, db_path),
            name="InstanceHeartbeatWorker",
            daemon=True,
        )
        _instance_heartbeat_thread.start()


def stop_instance_heartbeat() -> None:
    """Para a thread de heartbeat de instância."""
    global _instance_heartbeat_thread
    _instance_heartbeat_stop_event.set()
    _instance_heartbeat_thread = None


def release_instance_lock(db_path: Optional[str] = None) -> None:
    """Libera o lock de instância no encerramento limpo da aplicação."""
    stop_instance_heartbeat()
    with _instance_state_lock:
        if _current_role == ROLE_PRIMARY and _current_node_id:
            try:
                with get_connection(db_path) as conn:
                    conn.execute(
                        """
                        UPDATE instance_locks
                        SET status = ?
                        WHERE lock_key = ? AND node_id = ?;
                        """,
                        (INSTANCE_STATUS_STOPPED, DEFAULT_INSTANCE_LOCK_KEY, _current_node_id),
                    )
                log_operational_event(
                    component="InstanceLock",
                    severity=SEVERITY_INFO,
                    event_type=EVENT_INSTANCE_STOPPED,
                    message=f"Nó primário '{_current_node_name}' (PID {os.getpid()}) liberou o lock de instância.",
                    db_path=db_path,
                )
            except Exception as exc:
                logger.warning(f"Erro ao liberar instance lock: {exc}")


atexit.register(release_instance_lock)


def get_instance_info(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna detalhes completos do nó, role, saúde do heartbeat e status de acesso remoto."""
    init_operator_db(db_path)
    now_utc = datetime.now(timezone.utc)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM instance_locks WHERE lock_key = ?;",
            (DEFAULT_INSTANCE_LOCK_KEY,),
        ).fetchone()

    with _instance_state_lock:
        local_role = _current_role
        local_name = _current_node_name
        local_started = _current_started_at

    info = {
        "local_role": local_role,
        "is_primary": (local_role == ROLE_PRIMARY),
        "node_name": local_name,
        "hostname": platform.node() or socket.gethostname() or "unknown_host",
        "pid": os.getpid(),
        "primary_node_id": None,
        "primary_node_name": None,
        "primary_hostname": None,
        "primary_pid": None,
        "primary_status": None,
        "last_heartbeat": None,
        "heartbeat_seconds_ago": None,
        "is_heartbeat_stale": False,
        "uptime_str": "—",
        "remote_access_url": "http://0.0.0.0:8501 (LAN / Tailscale)",
    }

    if local_started:
        up_sec = int((now_utc - local_started).total_seconds())
        hours = up_sec // 3600
        mins = (up_sec % 3600) // 60
        info["uptime_str"] = f"{hours}h {mins:02d}m" if hours > 0 else f"{mins}m"

    if row:
        r = dict(row)
        info["primary_node_id"] = r.get("node_id")
        info["primary_node_name"] = r.get("node_name")
        info["primary_hostname"] = r.get("hostname")
        info["primary_pid"] = r.get("pid")
        info["primary_status"] = r.get("status")
        info["last_heartbeat"] = r.get("last_heartbeat")

        hb_dt = _parse_iso_utc(r.get("last_heartbeat"))
        if hb_dt:
            diff = max(0, int((now_utc - hb_dt).total_seconds()))
            info["heartbeat_seconds_ago"] = diff
            info["is_heartbeat_stale"] = (diff > DEFAULT_INSTANCE_TIMEOUT_SECONDS)

    return info



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
    require_primary_instance(db_path=db_path)
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
    require_primary_instance(db_path=db_path)
    from app.services import scheduler
    int_val = max(1, int(val))
    scheduler.set_setting("minimum_ready_stock", str(int_val), db_path=db_path)


# ---------------------------------------------------------------------------
# 3. Cancelamento Seguro de Tarefas
# ---------------------------------------------------------------------------

def request_task_cancel(task_id: str, db_path: Optional[str] = None) -> bool:
    """Registra intenção de cancelamento seguro para a tarefa especificada."""
    require_primary_instance(db_path=db_path)
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
    metadata_json: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Registra um evento operacional no banco SQLite."""
    init_operator_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_sev = severity.strip().upper() if severity else SEVERITY_INFO
    if clean_sev not in SEVERITIES:
        clean_sev = SEVERITY_INFO

    meta_str = metadata_json if metadata_json is not None else (json.dumps(metadata) if metadata else None)

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
    event_type: Optional[str] = None,
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
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)

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


def get_scheduler_queue_summary(
    db_path: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Retorna o resumo da fila do Scheduler no SQLite com suporte a enriquecimento de perfil/canal."""
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

        # Próximos posts agendados
        upcoming = conn.execute(
            """
            SELECT id, task_id, platform, scheduled_at, status, attempts, profile_id, channel_id
            FROM scheduled_posts
            ORDER BY scheduled_at ASC
            LIMIT ?;
            """,
            (max(5, limit),),
        ).fetchall()
        from app.services import profile_manager
        all_profs = {p["id"]: p for p in profile_manager.list_profiles(db_path=db_path)}
        all_chans = {c["id"]: c for c in profile_manager.list_channels(db_path=db_path)}
        enriched_upcoming = []
        for r in upcoming:
            d = dict(r)
            pid = d.get("profile_id")
            cid = d.get("channel_id")
            if pid and pid in all_profs:
                d["profile_name"] = all_profs[pid].get("name")
            if cid and cid in all_chans:
                d["channel_name"] = all_chans[cid].get("channel_name")
            enriched_upcoming.append(d)
        summary["upcoming_posts"] = enriched_upcoming
        return summary


def get_profile_operations_overview(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retorna visão operacional resumida e leve por perfil (canais, estoque, tarefas e agendamentos)."""
    init_operator_db(db_path)
    from app.services import profile_manager, scheduler
    from app.services import state as sm

    profile_manager.init_profile_db(db_path)
    scheduler.init_db(db_path)

    profiles = profile_manager.list_profiles(db_path=db_path)
    channels = profile_manager.list_channels(db_path=db_path)

    enabled_ch_map = {}
    total_ch_map = {}
    for c in channels:
        pid = c.get("profile_id")
        total_ch_map[pid] = total_ch_map.get(pid, 0) + 1
        if c.get("is_enabled"):
            enabled_ch_map[pid] = enabled_ch_map.get(pid, 0) + 1

    sched_map = {}
    with get_connection(db_path) as conn:
        s_rows = conn.execute(
            """
            SELECT COALESCE(profile_id, 'default') AS pid, status, COUNT(*) AS cnt
            FROM scheduled_posts
            GROUP BY COALESCE(profile_id, 'default'), status;
            """
        ).fetchall()
        for r in s_rows:
            sched_map.setdefault(r["pid"], {})[r["status"]] = r["cnt"]

        tp_rows = conn.execute("SELECT task_id, profile_id FROM task_profiles;").fetchall()
        task_prof_map = {r["task_id"]: r["profile_id"] for r in tp_rows}

    all_tasks, _ = sm.state.get_all_tasks(1, 200)
    task_counts = {}
    for t in all_tasks:
        tid = t.get("task_id")
        pid = t.get("profile_id") or task_prof_map.get(tid, profile_manager.DEFAULT_PROFILE_ID)
        st = t.get("state")
        tc = task_counts.setdefault(pid, {"pending_processing": 0, "failed": 0, "ready_stock": 0})
        if st in (const.TASK_STATE_PENDING, const.TASK_STATE_PROCESSING):
            tc["pending_processing"] += 1
        elif st == const.TASK_STATE_FAILED:
            tc["failed"] += 1
        elif st == const.TASK_STATE_COMPLETE:
            if t.get("safety_status") != "FAIL":
                tc["ready_stock"] += 1

    active_id = profile_manager.get_active_profile_id(db_path=db_path)
    overview = []
    for p in profiles:
        pid = p["id"]
        s_counts = sched_map.get(pid, {})
        t_counts = task_counts.get(pid, {})

        overview.append({
            "profile_id": pid,
            "name": p.get("name"),
            "slug": p.get("slug"),
            "niche": p.get("niche") or "—",
            "language": p.get("language") or "pt-BR",
            "region": p.get("region") or "BR",
            "default_preset": p.get("default_preset") or const.DEFAULT_MONETIZATION_PRESET,
            "growth_mode": p.get("growth_mode") or const.DEFAULT_GROWTH_MODE,
            "is_active": bool(p.get("is_active")),
            "is_active_profile": (pid == active_id),
            "channels_count": total_ch_map.get(pid, 0),
            "channels_enabled": enabled_ch_map.get(pid, 0),
            "ready_stock": t_counts.get("ready_stock", 0),
            "pending_processing": t_counts.get("pending_processing", 0),
            "scheduled": s_counts.get("planned", 0) + s_counts.get("ready", 0),
            "failed": t_counts.get("failed", 0) + s_counts.get("failed", 0),
        })

    return overview


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

    # 9. YouTube Analytics Provider
    try:
        from app.services.analytics_providers import get_provider
        yt_prov = get_provider("youtube")
        yt_status = yt_prov.get_status(db_path=db_path)
        summary["YouTube Analytics"] = {
            "status": yt_status,
            "details": "Chave YouTube Data API configurada" if yt_status == "CONFIGURED" else "Credencial YouTube não configurada",
            "last_error": None,
            "last_checked": now_iso,
        }
    except Exception as exc:
        summary["YouTube Analytics"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": f"Erro do provedor: {exc}",
            "last_error": str(exc),
            "last_checked": now_iso,
        }

    # 10. TikTok Analytics Provider
    try:
        from app.services.analytics_providers import get_provider
        tt_prov = get_provider("tiktok")
        tt_status = tt_prov.get_status(db_path=db_path)
        summary["TikTok Analytics"] = {
            "status": tt_status,
            "details": "Token TikTok API configurado" if tt_status == "CONFIGURED" else "Credencial TikTok não configurada",
            "last_error": None,
            "last_checked": now_iso,
        }
    except Exception as exc:
        summary["TikTok Analytics"] = {
            "status": PROVIDER_UNAVAILABLE,
            "details": f"Erro do provedor: {exc}",
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
    require_primary_instance(db_path=db_path)
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
    require_primary_instance()
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

    inst_info = get_instance_info(db_path=db_path)
    if inst_info.get("is_heartbeat_stale"):
        alerts.append(f"⚠ Nó primário sem heartbeat há {inst_info.get('heartbeat_seconds_ago')}s (stale)")
    if not inst_info.get("is_primary"):
        alerts.append(f"ℹ️ Instância secundária em modo VIEW ONLY (Primário: {inst_info.get('primary_node_name')})")

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
        "instance": inst_info,
    }
