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
import contextlib
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
EVENT_STALE_PRIMARY_LOCK_RELEASED = "STALE_PRIMARY_LOCK_RELEASED"

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

# Escopo efêmero de reutilização por passe de renderização (Thread-Local, ZERO cache persistente)
_render_pass_local = threading.local()


def get_render_pass_cache() -> Optional[Dict[str, Any]]:
    """Retorna o dicionário de cache efêmero da renderização atual, ou None se fora de escopo."""
    cache = getattr(_render_pass_local, "cache", None)
    return cache if isinstance(cache, dict) else None


def invalidate_render_pass_cache() -> None:
    """Limpa as entradas do cache efêmero da renderização atual se ativo."""
    cache = getattr(_render_pass_local, "cache", None)
    if isinstance(cache, dict):
        cache.clear()


@contextlib.contextmanager
def render_pass_scope():
    """Escopo efêmero por passe de renderização (thread-local).

    Reutiliza leituras idênticas durante uma única renderização da página
    e destrói o dicionário no bloco finally, garantindo ZERO cache persistente.
    """
    existing = getattr(_render_pass_local, "cache", None)
    if isinstance(existing, dict):
        yield existing
        return
    _render_pass_local.cache = {}
    try:
        yield _render_pass_local.cache
    finally:
        _render_pass_local.cache = None



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
    global _current_node_id, _current_role, _current_node_name, _current_started_at, _instance_initialized
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

                # Caso 2: É o mesmo processo re-confirmando o lock ou recuperando após perda de estado em memória
                if (
                    curr_status == INSTANCE_STATUS_ACTIVE
                    and curr_hostname == my_hostname
                    and curr_pid == my_pid
                ):
                    my_node_id = curr_node_id
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
            _instance_initialized = True

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
    global _current_role, _current_node_name, _instance_initialized
    _current_role = ROLE_SECONDARY_VIEW_ONLY
    _instance_initialized = True

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
    invalidate_render_pass_cache()
    clear_provider_health_cache()
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


def release_stale_instance_lock(
    lock_key: str = DEFAULT_INSTANCE_LOCK_KEY,
    stale_timeout_seconds: int = DEFAULT_INSTANCE_TIMEOUT_SECONDS,
    dry_run: bool = True,
    confirm_token: Optional[str] = None,
    db_path: Optional[str] = None,
    force_ignore_flags: bool = False,
) -> Dict[str, Any]:
    """Recupera administrativamente um lock de PRIMARY_FACTORY que ficou com status ACTIVE após parada do processo.

    OPERAÇÃO ADMINISTRATIVA FAIL-CLOSED (V16.4.2R.2):
    1. scheduler_enabled deve ser False (ou force_ignore_flags=True apenas em testes)
    2. auto_publish_enabled deve ser False (ou force_ignore_flags=True apenas em testes)
    3. Status em instance_locks deve ser ACTIVE
    4. Heartbeat deve ser mais antigo que stale_timeout_seconds (stale)
    5. Se o processo registrado pertencer ao host local, o PID NÃO pode estar vivo
    6. Requer confirm_token='RELEASE_STALE_PRIMARY' para execução real (dry_run=False)
    7. Zero deleção de linhas: realiza apenas UPDATE ACTIVE -> STOPPED
    8. Registra evento STALE_PRIMARY_LOCK_RELEASED em operational_events
    """
    from app.services import scheduler

    target_db = get_db_path(db_path)
    init_operator_db(target_db)

    # 1. Verificar flags de produção (scheduler_enabled e auto_publish_enabled)
    settings = scheduler.get_all_settings(db_path=target_db)
    sched_enabled = bool(settings.get("scheduler_enabled", False))
    auto_pub_enabled = bool(settings.get("auto_publish_enabled", False))

    flag_errors: List[str] = []
    if not force_ignore_flags:
        if sched_enabled:
            flag_errors.append("scheduler_enabled está ativo (True). Produção deve estar parada.")
        if auto_pub_enabled:
            flag_errors.append("auto_publish_enabled está ativo (True). Produção deve estar parada.")

    # 2. Consultar o registro do lock
    with get_connection(target_db) as conn:
        row = conn.execute(
            "SELECT * FROM instance_locks WHERE lock_key = ?;",
            (lock_key,),
        ).fetchone()

    if not row:
        return {
            "lock_found": False,
            "lock_key": lock_key,
            "status": None,
            "can_release": False,
            "would_release": False,
            "released": False,
            "reason": f"Lock '{lock_key}' não encontrado na tabela instance_locks.",
            "dry_run": dry_run,
        }

    r = dict(row)
    node_id = r.get("node_id")
    node_name = r.get("node_name")
    hostname = r.get("hostname")
    pid = r.get("pid") or 0
    last_heartbeat = r.get("last_heartbeat")
    status = r.get("status")

    # 3. Se status já não é ACTIVE (ex.: STOPPED) -> idempotente / no-op
    if status != INSTANCE_STATUS_ACTIVE:
        return {
            "lock_found": True,
            "lock_key": lock_key,
            "node_id": node_id,
            "node_name": node_name,
            "hostname": hostname,
            "pid": pid,
            "status": status,
            "previous_status": status,
            "resulting_status": status,
            "last_heartbeat": last_heartbeat,
            "stale_age_seconds": None,
            "process_alive": None,
            "is_heartbeat_stale": False,
            "can_release": False,
            "would_release": False,
            "released": False,
            "reason": f"Lock '{lock_key}' já está com status='{status}' (não está ACTIVE). Nenhuma ação necessária.",
            "dry_run": dry_run,
        }

    # 4. Avaliar tempo do heartbeat
    now_utc = datetime.now(timezone.utc)
    hb_dt = _parse_iso_utc(last_heartbeat)
    stale_age_seconds: Optional[float] = None
    is_heartbeat_stale = False

    if hb_dt:
        stale_age_seconds = (now_utc - hb_dt).total_seconds()
        if stale_age_seconds > stale_timeout_seconds:
            is_heartbeat_stale = True
    else:
        is_heartbeat_stale = True

    # 5. Avaliar vivacidade do processo se estiver no host local
    my_hostname = platform.node() or socket.gethostname() or "unknown_host"
    is_same_host = bool(hostname and my_hostname and hostname.lower() == my_hostname.lower())
    process_alive: Optional[bool] = None

    if is_same_host and pid > 0:
        process_alive = _is_local_pid_alive(pid)

    # 6. Avaliar se o release é permitido
    block_reasons: List[str] = []
    if flag_errors:
        block_reasons.extend(flag_errors)

    if not is_heartbeat_stale:
        age_str = f"{stale_age_seconds:.1f}s" if stale_age_seconds is not None else "indeterminado"
        block_reasons.append(
            f"Heartbeat recente ({age_str} <= threshold de {stale_timeout_seconds}s). Instância pode estar ativa."
        )

    if process_alive is True:
        block_reasons.append(
            f"Processo registrado (PID {pid} no host '{hostname}') ainda está vivo em execução."
        )

    can_release = (len(block_reasons) == 0)
    would_release = can_release
    reason = (
        f"Lock está stale (idade: {stale_age_seconds:.1f}s > {stale_timeout_seconds}s) e processo local não está em execução."
        if can_release
        else "; ".join(block_reasons)
    )

    if not dry_run:
        if not can_release:
            raise RuntimeError(f"Bloqueio de segurança: Não é seguro liberar o lock '{lock_key}': {reason}")
        if confirm_token != "RELEASE_STALE_PRIMARY":
            raise ValueError(
                "Confirmação obrigatória ausente. Use confirm_token='RELEASE_STALE_PRIMARY' para executar."
            )

        # Mutação segura: apenas UPDATE ACTIVE -> STOPPED. Zero deleção.
        with get_connection(target_db) as conn:
            conn.execute(
                """
                UPDATE instance_locks
                SET status = ?
                WHERE lock_key = ? AND status = ?;
                """,
                (INSTANCE_STATUS_STOPPED, lock_key, INSTANCE_STATUS_ACTIVE),
            )

        log_operational_event(
            component="InstanceLock",
            severity=SEVERITY_WARNING,
            event_type=EVENT_STALE_PRIMARY_LOCK_RELEASED,
            message=f"Lock primário stale '{lock_key}' (nó '{node_id}', PID {pid} em '{hostname}') foi liberado administrativamente (ACTIVE -> STOPPED).",
            metadata={
                "lock_key": lock_key,
                "node_id": node_id,
                "hostname": hostname,
                "pid": pid,
                "previous_status": INSTANCE_STATUS_ACTIVE,
                "resulting_status": INSTANCE_STATUS_STOPPED,
                "stale_age_seconds": stale_age_seconds,
                "reason": reason,
            },
            db_path=target_db,
        )

    resulting_status = INSTANCE_STATUS_STOPPED if (can_release and not dry_run) else status

    return {
        "lock_found": True,
        "lock_key": lock_key,
        "node_id": node_id,
        "node_name": node_name,
        "hostname": hostname,
        "pid": pid,
        "status": status,
        "previous_status": status,
        "resulting_status": resulting_status,
        "last_heartbeat": last_heartbeat,
        "stale_age_seconds": stale_age_seconds,
        "process_alive": process_alive,
        "is_heartbeat_stale": is_heartbeat_stale,
        "can_release": can_release,
        "would_release": would_release,
        "released": (can_release and not dry_run),
        "reason": reason,
        "dry_run": dry_run,
    }


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
    invalidate_render_pass_cache()
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
        row_id = cur.lastrowid

    invalidate_render_pass_cache()
    if clean_sev in (SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL):
        clear_provider_health_cache()

    return row_id


def get_closed_feedback_loop_enabled_op(db_path: Optional[str] = None) -> bool:
    """Read without initializing schemas or enabling the feature implicitly."""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute("SELECT value FROM autopilot_settings WHERE key=?",
                               ("closed_feedback_loop_enabled",)).fetchone()
        return bool(row and str(row[0]).lower() == "true")
    except Exception:
        return False


def set_closed_feedback_loop_enabled_op(enabled: bool, db_path: Optional[str] = None) -> None:
    """PRIMARY-only, atomic setting and audit; default remains absent/False."""
    require_primary_instance(db_path=db_path)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be bool")
    init_operator_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO autopilot_settings(key,value) VALUES (?,?)",
                     ("closed_feedback_loop_enabled", str(enabled)))
        conn.execute(
            "INSERT INTO operational_events(timestamp,component,severity,event_type,message,metadata_json) VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "closed_loop", "INFO", "CLOSED_LOOP_TOGGLED",
             "Closed feedback loop setting changed", json.dumps({"enabled": enabled})))


def get_closed_loop_submissions(platform: str, profile_id: str, channel_id: str, db_path=None):
    """Persistent successful submissions, with unresolved adaptation reservations.

    Missing completion after a crash must not permit another adaptation. Baseline
    generations still proceed; operator review can resolve an ambiguous reservation.
    """
    clean_platform = str(platform or "").strip().lower()
    clean_profile = str(profile_id or "").strip()
    clean_channel = str(channel_id or "").strip()
    if not clean_platform or not clean_profile or not clean_channel:
        return []
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT event_type,task_id,metadata_json FROM operational_events "
            "WHERE event_type IN ('CLOSED_LOOP_DECISION','CLOSED_LOOP_SUBMITTED') "
            "AND json_extract(metadata_json,'$.platform')=? "
            "AND json_extract(metadata_json,'$.profile_id')=? "
            "AND json_extract(metadata_json,'$.channel_id')=? ORDER BY id DESC",
            (clean_platform, clean_profile, clean_channel)).fetchall()
    submitted, completed = [], set()
    pending = False
    for row in rows:
        data = json.loads(row["metadata_json"])
        if row["event_type"] == "CLOSED_LOOP_SUBMITTED" and row["task_id"] not in completed:
            completed.add(row["task_id"])
            submitted.append(data)
        elif row["event_type"] == "CLOSED_LOOP_DECISION" and data.get("adapted") and row["task_id"] not in completed:
            pending = True
    if pending:
        submitted.insert(0, {"adapted": True, "pending": True})
    return submitted


def record_closed_loop_decision(task_id: str, metadata: Dict[str, Any], db_path=None) -> int:
    """Reserve a decision atomically against competing submissions/toggle changes."""
    for k in ("platform", "profile_id", "channel_id"):
        if not metadata.get(k) or not str(metadata[k]).strip():
            raise ValueError(f"missing_scope_{k}")
    scope = {k: str(metadata[k]).strip() for k in ("platform", "profile_id", "channel_id")}
    with get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        flag = conn.execute("SELECT value FROM autopilot_settings WHERE key='closed_feedback_loop_enabled'").fetchone()
        if not flag or str(flag[0]).lower() != "true":
            raise ValueError("closed_loop_disabled")
        # BEGIN IMMEDIATE excludes writers while the second read connection checks
        # the same committed submission history used by the pure policy.
        recent = get_closed_loop_submissions(**scope, db_path=db_path)[:5]
        if recent != metadata["recent_submissions"]:
            raise ValueError("submission_history_changed")
        channel = conn.execute(
            "SELECT c.id FROM publishing_channels c JOIN content_profiles p ON p.id = c.profile_id "
            "WHERE c.id=? AND c.profile_id=? AND c.platform=? AND c.is_enabled=1 AND p.is_active=1",
            (scope["channel_id"], scope["profile_id"], scope["platform"])).fetchone()
        if not channel:
            raise ValueError("channel_changed")
        cursor = conn.execute(
            "INSERT INTO operational_events(timestamp,component,severity,event_type,task_id,message,metadata_json) VALUES (?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), "closed_loop", "INFO", "CLOSED_LOOP_DECISION",
             task_id, "Versioned content decision before submission", json.dumps(metadata, allow_nan=False)))
        return cursor.lastrowid


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
    rp_cache = get_render_pass_cache()
    cache_key = ("gen_queue_summary",)
    if rp_cache is not None and cache_key in rp_cache:
        return rp_cache[cache_key]

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
    if rp_cache is not None:
        rp_cache[cache_key] = summary
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


def get_profile_operations_overview(db_path: Optional[str] = None, task_base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
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
            "ready_stock": get_canonical_ready_stock(task_base_dir=task_base_dir, db_path=db_path, profile_id=pid)["total_ready"],
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

        # Safety Gate fail-closed: deve possuir status PASS explícito
        safety_status = t.get("safety_status")
        if not safety_status:
            try:
                from app.services import safety_gate
                safety_rec = safety_gate.get_safety_assessment(task_id, db_path=db_path)
                if safety_rec:
                    safety_status = safety_rec.get("safety_status")
            except Exception:
                safety_status = None

        if not safety_status or str(safety_status).upper() != const.SAFETY_STATUS_PASS:
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
            "safety_status": safety_status,
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
        "youtube_ready": youtube_ready,
        "tiktok_ready": tiktok_ready,
        "cross_platform_ready": cross_platform_ready,
        "youtube_tasks": youtube_ready,
        "tiktok_tasks": tiktok_ready,
        "cross_platform_tasks": cross_platform_ready,
    }


def get_canonical_ready_stock(
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna o estoque pronto usando a fonte canônica da produção autônoma (YouTube-first, fail-closed).

    Alinha a telemetria do Operator Console com o buffer real da Produção Autônoma,
    reconstruindo o estoque a partir das tabelas persistentes (monetization_safety PASS,
    Quality >= 70, canal YouTube ativo e arquivo de vídeo existente), com suporte a isolamento por perfil e canal.
    """
    from app.services import autonomous_production, profile_manager
    target_prof = profile_id if profile_id is not None else profile_manager.get_active_profile_id(db_path=db_path)
    target_chan = channel_id if channel_id is not None else autonomous_production.resolve_autonomous_youtube_channel(target_prof, db_path=db_path)
    auto_stock = autonomous_production.get_autonomous_ready_stock(
        task_base_dir=task_base_dir,
        db_path=db_path,
        profile_id=target_prof,
        channel_id=target_chan,
    )
    ready_total = auto_stock.get("ready_count", 0)
    target = auto_stock.get("target_stock", 3)
    is_low = auto_stock.get("is_below_target", ready_total < target)
    youtube_items = auto_stock.get("youtube_ready", [])
    return {
        "total_ready": ready_total,
        "youtube_count": auto_stock.get("youtube_count", ready_total),
        "tiktok_count": 0,
        "cross_platform_count": 0,
        "minimum_threshold": target,
        "is_below_minimum": is_low,
        "youtube_items": youtube_items[:5],
        "tiktok_items": [],
        "cross_platform_items": [],
        "youtube_ready": youtube_items,
        "tiktok_ready": [],
        "cross_platform_ready": [],
        "youtube_tasks": youtube_items,
        "tiktok_tasks": [],
        "cross_platform_tasks": [],
    }


# ---------------------------------------------------------------------------
# 7. Saúde dos Provedores (Provider Health)
# ---------------------------------------------------------------------------

_PROVIDER_HEALTH_CACHE = {"data": None, "timestamp": 0.0, "db_path": None}
_PROVIDER_HEALTH_TTL = 15.0  # 15 segundos


def clear_provider_health_cache():
    """Limpa o cache de saúde dos provedores."""
    global _PROVIDER_HEALTH_CACHE
    invalidate_render_pass_cache()
    _PROVIDER_HEALTH_CACHE = {"data": None, "timestamp": 0.0, "db_path": None}


def get_provider_health_summary(db_path: Optional[str] = None, force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Avalia o status de saúde dos provedores de forma leve e estática (sem chamadas pagas)."""
    global _PROVIDER_HEALTH_CACHE
    import time
    now_ts = time.monotonic()
    if (
        not force
        and _PROVIDER_HEALTH_CACHE["data"] is not None
        and _PROVIDER_HEALTH_CACHE["db_path"] == db_path
        and (now_ts - _PROVIDER_HEALTH_CACHE["timestamp"] < _PROVIDER_HEALTH_TTL)
    ):
        return _PROVIDER_HEALTH_CACHE["data"]

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

    # 3. Pexels (contrato canônico: pexels_api_keys)
    from app.services import material
    has_pexels = material.has_material_api_keys("pexels")
    pexels_err = errors_by_comp.get("pexels")
    if has_pexels:
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

    _PROVIDER_HEALTH_CACHE = {"data": summary, "timestamp": now_ts, "db_path": db_path}
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

def get_system_status(db_path: Optional[str] = None, profile_id: Optional[str] = None) -> Dict[str, Any]:
    """Consolida o status completo da Video Factory para o cabeçalho do Operator Console."""
    from app.services import scheduler
    from app.services import webui_task
    from app.services import profile_manager

    target_prof = profile_id if profile_id is not None else profile_manager.get_active_profile_id(db_path=db_path)
    rp_cache = get_render_pass_cache()
    cache_key = ("system_status", db_path, target_prof)
    if rp_cache is not None and cache_key in rp_cache:
        return rp_cache[cache_key]
    active_prof = profile_manager.get_profile(target_prof, db_path=db_path) if target_prof else None

    factory_state = get_factory_state(db_path=db_path)
    scheduler_status = scheduler.get_executor_status(db_path=db_path)
    sched_settings = scheduler.get_all_settings(db_path=db_path)
    growth_mode = active_prof.get("growth_mode") if (active_prof and active_prof.get("growth_mode")) else scheduler.get_growth_mode(db_path=db_path)
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

    ready_stock = get_canonical_ready_stock(db_path=db_path, profile_id=target_prof)
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

    result = {
        "factory_state": consolidated_factory,
        "is_paused": factory_state == FACTORY_STATE_PAUSED,
        "generation_worker": gen_worker_state,
        "scheduler_worker": sched_worker_state,
        "scheduler_enabled": bool(sched_settings.get("scheduler_enabled", False)),
        "auto_publish_enabled": bool(sched_settings.get("auto_publish_enabled", False)),
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
    if rp_cache is not None:
        rp_cache[cache_key] = result
    return result


# ---------------------------------------------------------------------------
# 11. Operações de Provedores de Analytics (Fase V10-B)
# ---------------------------------------------------------------------------

def test_analytics_provider_configuration(platform: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Testa estaticamente a configuração de um provedor de analytics sem chamadas externas.
    Permitido tanto em PRIMARY quanto em SECONDARY_VIEW_ONLY.
    """
    from app.services.analytics_providers import validate_provider_configuration
    return validate_provider_configuration(platform, db_path=db_path)


def fetch_real_metrics_for_publication_op(
    task_id: str,
    platform: str,
    channel_id: Optional[str] = None,
    persist: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executa coleta manual e controlada de métricas para uma publicação.
    Exige PRIMARY se persist=True. Em VIEW ONLY permite apenas persist=False.
    """
    if persist:
        require_primary_instance(db_path=db_path)
    from app.services.analytics_ingestion import fetch_real_metrics_for_publication
    return fetch_real_metrics_for_publication(
        task_id=task_id,
        platform=platform,
        channel_id=channel_id,
        persist=persist,
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# 12. Operações do Agendador de Analytics (Fase V10-C)
# ---------------------------------------------------------------------------

def get_analytics_scheduler_status(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Retorna o status operacional do agendador automático de analytics.
    Permitido tanto no PRIMARY quanto no SECONDARY_VIEW_ONLY (somente leitura).
    """
    from app.services import analytics_scheduler
    return analytics_scheduler.get_analytics_scheduler_status(db_path=db_path)


def set_analytics_auto_collection_enabled_op(
    enabled: bool,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ativa ou desativa a coleta automática de analytics.
    Exige estritamente PRIMARY role (VIEW ONLY rejeita).
    """
    require_primary_instance(db_path=db_path)
    from app.services import analytics_scheduler
    analytics_scheduler.set_analytics_auto_collection_enabled(enabled, db_path=db_path)
    log_operational_event(
        component="analytics",
        severity=SEVERITY_INFO,
        event_type="ANALYTICS_AUTO_COLLECTION_TOGGLED",
        message=f"Coleta automática de analytics {'ativada' if enabled else 'desativada'} pelo operador.",
        metadata={"enabled": bool(enabled)},
        db_path=db_path,
    )
    return {"success": True, "enabled": bool(enabled)}


def run_analytics_collection_cycle_op(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Executa sob demanda exatamente um ciclo leve de coleta de analytics.
    Exige estritamente PRIMARY role. Respeita limite unitário de coletas e rate-limit.
    """
    require_primary_instance(db_path=db_path)
    from app.services import analytics_scheduler
    return analytics_scheduler.run_analytics_collection_cycle(db_path=db_path, force=True)


RECOGNIZED_PUBLICATION_PRIVACY_STATUSES = ("public", "private", "unlisted")


def confirm_publication_privacy_op(
    publication_event_id: int,
    expected_task_id: str,
    expected_external_id: str,
    privacy_status: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Confirma manualmente e de forma auditável o `privacy_status` de um evento de
    publicação YouTube já existente (Fase V12-F.1C — ex.: homologar eventos legados
    sem `task.json`, como o evento real 16, sem raw SQL manual).

    Exige estritamente PRIMARY role. Localiza exatamente o `publication_event_id`
    informado e só aplica a mudança se TODAS as condições abaixo forem verdadeiras:
    - status do evento é 'success'
    - platform do evento é 'youtube'
    - task_id do evento corresponde a `expected_task_id`
    - external_id do evento corresponde a `expected_external_id`
    - `privacy_status` é um valor reconhecido ('public', 'private' ou 'unlisted')

    Atualiza SOMENTE a coluna `privacy_status` daquele evento. Não altera o status
    da publicação, não altera `scheduled_posts` e não executa nenhuma publicação.
    Registra um `operational_event` auditável sem expor segredos.
    """
    require_primary_instance(db_path=db_path)

    clean_privacy = str(privacy_status or "").strip().lower()
    if clean_privacy not in RECOGNIZED_PUBLICATION_PRIVACY_STATUSES:
        raise ValueError(
            f"privacy_status inválido: '{privacy_status}'. "
            f"Valores aceitos: {list(RECOGNIZED_PUBLICATION_PRIVACY_STATUSES)}."
        )

    from app.services import scheduler
    scheduler.init_db(db_path)

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM publication_events WHERE id = ?;",
            (publication_event_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"publication_event id={publication_event_id} não encontrado.")

        row_dict = dict(row)

        if (row_dict.get("status") or "").strip().lower() != "success":
            raise ValueError(
                f"publication_event id={publication_event_id} não está em status 'success' "
                f"(status={row_dict.get('status')})."
            )
        if (row_dict.get("platform") or "").strip().lower() != "youtube":
            raise ValueError(
                f"publication_event id={publication_event_id} não é da plataforma 'youtube' "
                f"(platform={row_dict.get('platform')})."
            )
        if str(row_dict.get("task_id") or "") != str(expected_task_id or ""):
            raise ValueError(
                f"task_id informado não corresponde ao publication_event id={publication_event_id}."
            )
        if str(row_dict.get("external_id") or "") != str(expected_external_id or ""):
            raise ValueError(
                f"external_id informado não corresponde ao publication_event id={publication_event_id}."
            )

        conn.execute(
            "UPDATE publication_events SET privacy_status = ? WHERE id = ?;",
            (clean_privacy, publication_event_id),
        )

    log_operational_event(
        component="analytics",
        severity=SEVERITY_INFO,
        event_type="PUBLICATION_PRIVACY_CONFIRMED",
        task_id=str(expected_task_id),
        message=(
            f"Privacidade confirmada manualmente para publication_event id={publication_event_id} "
            f"(task={expected_task_id}, platform=youtube): {clean_privacy}."
        ),
        metadata={
            "publication_event_id": publication_event_id,
            "task_id": expected_task_id,
            "platform": "youtube",
            "privacy_status": clean_privacy,
        },
        db_path=db_path,
    )

    return {
        "success": True,
        "publication_event_id": publication_event_id,
        "task_id": expected_task_id,
        "platform": "youtube",
        "privacy_status": clean_privacy,
    }


def set_publication_copyright_status_op(
    publication_event_id: Optional[int] = None,
    copyright_status: str = "unknown",
    note: Optional[str] = None,
    expected_task_id: Optional[str] = None,
    expected_external_id: Optional[str] = None,
    task_id: Optional[str] = None,
    source: str = "operator",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Define o status de direitos autorais de forma auditável e persistente (V14-B.2).

    Requisitos:
    - PRIMARY only: fail-closed via require_primary_instance.
    - Valida status permitido (unknown, clean_manual, claimed, blocked, strike).
    - Valida publication event existente em status 'success' e plataforma 'youtube'.
    - Valida source (padrão 'operator', aceita 'future_provider').
    - Idempotente: se já estiver no mesmo status com a mesma nota, não duplica evento.
    - Grava evento auditável em operational_events com metadata completo.
    - Zero rede / chamadas externas.
    """
    require_primary_instance(db_path=db_path)

    from app.services import copyright_gate, scheduler

    clean_status = str(copyright_status or "").strip().lower()
    if clean_status not in copyright_gate.ALLOWED_COPYRIGHT_STATUSES:
        raise ValueError(
            f"copyright_status inválido: '{copyright_status}'. "
            f"Valores aceitos: {sorted(copyright_gate.ALLOWED_COPYRIGHT_STATUSES)}."
        )

    clean_source = str(source or copyright_gate.COPYRIGHT_SOURCE_OPERATOR).strip().lower()
    if clean_source not in copyright_gate.ALLOWED_COPYRIGHT_SOURCES:
        raise ValueError(
            f"source inválida: '{source}'. "
            f"Valores aceitos: {sorted(copyright_gate.ALLOWED_COPYRIGHT_SOURCES)}."
        )

    clean_pub_id = int(publication_event_id) if publication_event_id is not None else None
    target_task = expected_task_id or task_id

    scheduler.init_db(db_path)
    init_operator_db(db_path)

    with get_connection(db_path) as conn:
        row = None
        if clean_pub_id is not None:
            row = conn.execute(
                "SELECT * FROM publication_events WHERE id = ?;",
                (clean_pub_id,),
            ).fetchone()
        elif target_task:
            row = conn.execute(
                "SELECT * FROM publication_events WHERE task_id = ? AND platform = 'youtube' AND status = 'success' ORDER BY id DESC LIMIT 1;",
                (str(target_task),),
            ).fetchone()

        if not row:
            identifier_desc = f"id={clean_pub_id}" if clean_pub_id is not None else f"task_id={target_task}"
            raise ValueError(f"publication_event {identifier_desc} não encontrado.")

        row_dict = dict(row)
        resolved_pub_id = int(row_dict["id"])

        if (row_dict.get("status") or "").strip().lower() != "success":
            raise ValueError(
                f"publication_event id={resolved_pub_id} não está em status 'success' "
                f"(status={row_dict.get('status')})."
            )
        if (row_dict.get("platform") or "").strip().lower() != "youtube":
            raise ValueError(
                f"publication_event id={resolved_pub_id} não é da plataforma 'youtube' "
                f"(platform={row_dict.get('platform')})."
            )
        if expected_task_id and str(row_dict.get("task_id") or "") != str(expected_task_id):
            raise ValueError(
                f"task_id informado não corresponde ao publication_event id={resolved_pub_id}."
            )
        if expected_external_id and str(row_dict.get("external_id") or "") != str(expected_external_id):
            raise ValueError(
                f"external_id informado não corresponde ao publication_event id={resolved_pub_id}."
            )

    # Verifica idempotência
    current = copyright_gate.get_publication_copyright_status(
        publication_event_id=resolved_pub_id, db_path=db_path
    )
    clean_note = str(note).strip() if note is not None else None
    current_note = current.get("note")

    if current.get("copyright_status") == clean_status and (clean_note is None or current_note == clean_note):
        return {
            "success": True,
            "idempotent": True,
            "publication_event_id": resolved_pub_id,
            "task_id": row_dict.get("task_id"),
            "platform": "youtube",
            "external_id": row_dict.get("external_id"),
            "copyright_status": clean_status,
            "source": current.get("source") or clean_source,
            "timestamp": current.get("timestamp"),
            "note": current_note,
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    task_id_val = str(row_dict.get("task_id") or "")
    ext_id_val = str(row_dict.get("external_id") or "")
    severity = SEVERITY_WARNING if clean_status in (
        copyright_gate.COPYRIGHT_STATUS_BLOCKED,
        copyright_gate.COPYRIGHT_STATUS_STRIKE,
        copyright_gate.COPYRIGHT_STATUS_CLAIMED,
    ) else SEVERITY_INFO

    log_operational_event(
        component="copyright",
        severity=severity,
        event_type="PUBLICATION_COPYRIGHT_STATUS_SET",
        task_id=task_id_val,
        message=(
            f"Status de copyright definido para '{clean_status}' no publication_event id={resolved_pub_id} "
            f"(task={task_id_val}, platform=youtube, external_id={ext_id_val}) por source='{clean_source}'."
        ),
        metadata={
            "publication_event_id": resolved_pub_id,
            "task_id": task_id_val,
            "platform": "youtube",
            "external_id": ext_id_val,
            "copyright_status": clean_status,
            "source": clean_source,
            "timestamp": now_iso,
            "optional_note": clean_note,
            "note": clean_note,
        },
        db_path=db_path,
    )

    return {
        "success": True,
        "idempotent": False,
        "publication_event_id": resolved_pub_id,
        "task_id": task_id_val,
        "platform": "youtube",
        "external_id": ext_id_val,
        "copyright_status": clean_status,
        "source": clean_source,
        "timestamp": now_iso,
        "note": clean_note,
    }


def get_publication_copyright_status_op(
    publication_event_id: Optional[int] = None,
    task_id: Optional[str] = None,
    external_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Consulta o status de copyright de uma publicação/tarefa (read-only, permitido em PRIMARY e VIEW ONLY)."""
    from app.services import copyright_gate
    return copyright_gate.get_publication_copyright_status(
        publication_event_id=publication_event_id,
        task_id=task_id,
        external_id=external_id,
        db_path=db_path,
    )


def approve_legacy_task_copyright_op(
    task_id: str,
    note: Optional[str] = None,
    confirm: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Aprova manualmente a proveniência e direitos autorais de um artefato final legado (V1.5E).

    OPERAÇÃO ADMINISTRATIVA DO OPERADOR (PRIMARY ONLY, AUDITÁVEL, FAIL-CLOSED):
    1. PRIMARY only: fail-closed via require_primary_instance.
    2. Exige confirmação explícita: confirm == 'APPROVE_LEGACY_COPYRIGHT'.
    3. Resolve final-1.mp4 canônico da tarefa: exige arquivo existente e tamanho > 0.
    4. Calcula SHA-256 de final-1.mp4 e vincula criptograficamente a aprovação.
    5. Pré-requisitos de segurança:
       - BGM deve ser segura (SAFE_NO_BGM ou SAFE_PROCEDURAL).
       - Zero evidência de claim, blocked ou strike.
       - Se houver Flow no manifesto, todas as cenas Flow premium devem ser válidas e íntegras.
       - Cenas stock legadas têm lacuna suprida pela revisão manual do operador.
    6. Idempotente para (task_id, final_video_sha256, clean_manual).
    7. Persiste evento auditável TASK_COPYRIGHT_MANUAL_APPROVAL em operational_events.
    """
    require_primary_instance(db_path=db_path)

    from app.services import copyright_gate, scheduler

    clean_task_id = str(task_id or "").strip()
    if not clean_task_id:
        raise ValueError("task_id inválido ou ausente.")

    clean_confirm = str(confirm or "").strip()
    if clean_confirm != "APPROVE_LEGACY_COPYRIGHT":
        raise ValueError(
            "Confirmação explícita 'APPROVE_LEGACY_COPYRIGHT' é obrigatória "
            "para aprovação manual de copyright legado."
        )

    task_dir_path = copyright_gate._resolve_task_dir(clean_task_id, task_base_dir)
    final_video_path = os.path.join(task_dir_path, "final-1.mp4")

    if not os.path.isfile(final_video_path):
        raise ValueError(
            f"Arquivo final-1.mp4 inexistente no disco para a task '{clean_task_id}': {final_video_path}"
        )

    try:
        file_size = os.path.getsize(final_video_path)
        if file_size <= 0:
            raise ValueError(
                f"Arquivo final-1.mp4 vazio (0 bytes) para a task '{clean_task_id}': {final_video_path}"
            )
    except OSError as exc:
        raise ValueError(f"Falha ao acessar tamanho do arquivo final-1.mp4: {exc}")

    final_video_sha256 = copyright_gate.calculate_file_sha256(final_video_path)

    # 1. Validação de BGM
    script_file = os.path.join(task_dir_path, "script.json")
    script_data: Dict[str, Any] = {}
    if os.path.isfile(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                script_data = json.load(f)
        except Exception as exc:
            raise ValueError(f"Falha ao ler script.json da task '{clean_task_id}': {exc}")

    params_data = script_data.get("params") or {}
    raw_asset_prov = copyright_gate._extract_raw_asset_provenance(script_data)
    asset_prov = copyright_gate.normalize_asset_provenance(
        raw_prov=raw_asset_prov,
        task_id=clean_task_id,
        params=params_data,
        material_sources=script_data.get("material_sources"),
        task_base_dir=task_base_dir,
    )
    if asset_prov.get("malformed_provenance"):
        raise ValueError(
            f"Proveniência de ativos malformada na task '{clean_task_id}' "
            f"({asset_prov.get('malformed_reason', 'invalid_format')})."
        )

    bgm_info = asset_prov.get("bgm") or {}
    bgm_type = str(copyright_gate._get_param(params_data, "bgm_type", "") or "").lower().strip()
    bgm_enabled = bool(bgm_info.get("enabled"))
    if bgm_enabled:
        bgm_source = str(bgm_info.get("source") or "").lower()
        bgm_prov = str(bgm_info.get("provenance_status") or "").upper()
        if not (bgm_type == "ambient_auto" and (bgm_source == "procedural" or bgm_prov == "SAFE_PROCEDURAL")):
            raise ValueError(
                f"BGM insegura ou não auditada para aprovação manual de copyright legado "
                f"(type={bgm_type}, source={bgm_source}, prov={bgm_prov}). "
                "Apenas SAFE_NO_BGM ou SAFE_PROCEDURAL são permitidas."
            )

    # 2. Verificação de Evidência Conhecida de Claim / Blocked / Strike
    scheduler.init_db(db_path)
    init_operator_db(db_path)

    pub_status = copyright_gate.get_publication_copyright_status(task_id=clean_task_id, db_path=db_path)
    if pub_status.get("copyright_status") in (
        copyright_gate.COPYRIGHT_STATUS_CLAIMED,
        copyright_gate.COPYRIGHT_STATUS_BLOCKED,
        copyright_gate.COPYRIGHT_STATUS_STRIKE,
    ):
        raise ValueError(
            f"Task '{clean_task_id}' possui status de copyright adverso registrado: "
            f"{pub_status.get('copyright_status')}"
        )

    with get_connection(db_path) as conn:
        try:
            adv_rows = conn.execute(
                "SELECT metadata_json FROM operational_events WHERE task_id = ? ORDER BY id DESC;",
                (clean_task_id,),
            ).fetchall()
            for r in adv_rows:
                try:
                    m = json.loads(r["metadata_json"] or "{}")
                    st = str(m.get("copyright_status") or "").lower().strip()
                    if st in (
                        copyright_gate.COPYRIGHT_STATUS_CLAIMED,
                        copyright_gate.COPYRIGHT_STATUS_BLOCKED,
                        copyright_gate.COPYRIGHT_STATUS_STRIKE,
                    ):
                        raise ValueError(
                            f"Task '{clean_task_id}' possui evidência de infração/claim "
                            f"({st}) registrada em operational_events."
                        )
                except (json.JSONDecodeError, TypeError):
                    continue
        except sqlite3.OperationalError:
            pass

    # 3. Validação de Cenas Flow Premium se Flow estiver presente
    manifest_path = os.path.join(task_dir_path, "flow", "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as mf:
                manifest = json.load(mf)
        except Exception as exc:
            raise ValueError(f"Manifesto Flow corrompido ou ilegível na task '{clean_task_id}': {exc}")

        if not isinstance(manifest, dict):
            raise ValueError(f"Manifesto Flow com estrutura inválida na task '{clean_task_id}'")

        flow_gen = manifest.get("flow_generation")
        if not isinstance(flow_gen, dict):
            raise ValueError(f"flow_generation ausente no manifesto Flow da task '{clean_task_id}'")

        if flow_gen.get("status") != "COMPLETE":
            raise ValueError(
                f"Geração Flow não está COMPLETE na task '{clean_task_id}' "
                f"(status={flow_gen.get('status')})"
            )

        if (
            flow_gen.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY"
            or manifest.get("status") == "FLOW_GENERATION_NEEDS_RECOVERY"
        ):
            raise ValueError(f"Geração Flow requer recovery pendente na task '{clean_task_id}'")

        completed_scenes = {str(s) for s in (flow_gen.get("completed_scenes") or [])}
        scenes = manifest.get("scenes") or []
        if not isinstance(scenes, list):
            raise ValueError(f"scenes com formato inválido no manifesto Flow da task '{clean_task_id}'")

        clips_dir = os.path.join(task_dir_path, "flow", "clips")
        for sc in scenes:
            if isinstance(sc, dict) and sc.get("is_flow_premium") is True:
                s_idx = sc.get("scene_index")
                if s_idx is None or str(s_idx) not in completed_scenes:
                    raise ValueError(
                        f"Cena Flow premium {s_idx} não consta em completed_scenes na task '{clean_task_id}'"
                    )
                expected_clip = str(sc.get("expected_clip") or "").strip()
                if not expected_clip:
                    raise ValueError(f"Cena Flow premium {s_idx} sem expected_clip na task '{clean_task_id}'")
                clip_path = os.path.join(clips_dir, expected_clip)
                if not os.path.isfile(clip_path) or os.path.getsize(clip_path) <= 0:
                    raise ValueError(
                        f"Clipe físico Flow inexistente ou vazio na task '{clean_task_id}': {clip_path}"
                    )
                clip_dict = {
                    "local_file": clip_path,
                    "scene_index": s_idx,
                }
                valid, reason = copyright_gate.validate_flow_clip_provenance(
                    clean_task_id, clip_dict, task_base_dir
                )
                if not valid:
                    raise ValueError(
                        f"Falha na validação de proveniência do clipe Flow '{expected_clip}' "
                        f"na task '{clean_task_id}': {reason}"
                    )

    # 4. Idempotência
    clean_note = str(note).strip() if note is not None else None
    existing = copyright_gate.get_legacy_task_copyright_approval(task_id=clean_task_id, db_path=db_path)
    if existing:
        if (
            existing.get("final_video_sha256") == final_video_sha256
            and existing.get("copyright_status") == copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL
            and (clean_note is None or existing.get("note") == clean_note)
        ):
            return {
                "success": True,
                "idempotent": True,
                "task_id": clean_task_id,
                "copyright_status": copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL,
                "source": copyright_gate.COPYRIGHT_SOURCE_OPERATOR,
                "scope": "legacy_final_artifact",
                "final_video_sha256": final_video_sha256,
                "final_video_size": file_size,
                "timestamp": existing.get("timestamp"),
                "note": existing.get("note"),
            }

    # 5. Persiste evento auditável
    now_iso = datetime.now(timezone.utc).isoformat()
    log_operational_event(
        component="copyright",
        severity=SEVERITY_INFO,
        event_type="TASK_COPYRIGHT_MANUAL_APPROVAL",
        task_id=clean_task_id,
        message=(
            f"Aprovação manual de copyright para artefato final legado da task {clean_task_id} "
            f"(sha256={final_video_sha256[:12]}..., size={file_size}B) por source='operator'."
        ),
        metadata={
            "task_id": clean_task_id,
            "copyright_status": copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL,
            "source": copyright_gate.COPYRIGHT_SOURCE_OPERATOR,
            "scope": "legacy_final_artifact",
            "final_video_sha256": final_video_sha256,
            "final_video_size": file_size,
            "timestamp": now_iso,
            "note": clean_note,
        },
        db_path=db_path,
    )

    return {
        "success": True,
        "idempotent": False,
        "task_id": clean_task_id,
        "copyright_status": copyright_gate.COPYRIGHT_STATUS_CLEAN_MANUAL,
        "source": copyright_gate.COPYRIGHT_SOURCE_OPERATOR,
        "scope": "legacy_final_artifact",
        "final_video_sha256": final_video_sha256,
        "final_video_size": file_size,
        "timestamp": now_iso,
        "note": clean_note,
    }


def get_legacy_task_copyright_approval_op(
    task_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Consulta aprovação manual de copyright de artefato legado da tarefa (read-only)."""
    from app.services import copyright_gate
    return copyright_gate.get_legacy_task_copyright_approval(task_id=task_id, db_path=db_path)



# ---------------------------------------------------------------------------
# 13. Operações de Clip Mode (Fase V11-A)
# ---------------------------------------------------------------------------

def list_clip_sources_op(
    profile_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista fontes de clip cadastradas (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_mode
    return clip_mode.list_clip_sources(profile_id=profile_id, status=status, db_path=db_path)


def get_clip_source_op(source_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera detalhes de uma fonte de clip por ID (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_mode
    return clip_mode.get_clip_source(source_id=source_id, db_path=db_path)


def import_clip_source_op(
    file_path: str,
    source_origin: str,
    authorization_confirmed: bool,
    profile_id: Optional[str] = None,
    authorization_note: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Importa vídeo-fonte local (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_mode
    return clip_mode.import_clip_source(
        file_path=file_path,
        source_origin=source_origin,
        authorization_confirmed=authorization_confirmed,
        profile_id=profile_id,
        authorization_note=authorization_note,
        db_path=db_path,
    )


def deactivate_clip_source_op(source_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Desativa fonte de clip (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_mode
    return clip_mode.deactivate_clip_source(source_id=source_id, db_path=db_path)


def list_clip_segments_op(
    source_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista segmentos de corte (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_mode
    return clip_mode.list_clip_segments(
        source_id=source_id,
        profile_id=profile_id,
        status=status,
        db_path=db_path,
    )


def create_clip_segment_op(
    source_id: str,
    start_seconds: float,
    end_seconds: float,
    title: Optional[str] = None,
    selection_method: str = "manual",
    selection_reason: Optional[str] = None,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria segmento de corte manual para fonte (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_mode
    return clip_mode.create_clip_segment(
        source_id=source_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        title=title,
        selection_method=selection_method,
        selection_reason=selection_reason,
        profile_id=profile_id,
        db_path=db_path,
    )


def update_clip_segment_status_op(
    segment_id: str,
    status: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza status de segmento de corte (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_mode
    return clip_mode.update_clip_segment_status(
        segment_id=segment_id,
        status=status,
        db_path=db_path,
    )


def transcribe_clip_source_op(
    source_id: str,
    language: str = "auto",
    model_name: str = "small",
    provider_name: str = "faster_whisper",
    force: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa transcrição de áudio de uma fonte autorizada (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_transcription
    return clip_transcription.transcribe_clip_source(
        source_id=source_id,
        language=language,
        model_name=model_name,
        provider_name=provider_name,
        force=force,
        db_path=db_path,
    )


def get_latest_transcript_op(
    source_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera transcrição concluída mais recente de uma fonte (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_transcription
    return clip_transcription.get_latest_successful_transcript(source_id=source_id, db_path=db_path)


def list_clip_transcript_segments_op(
    transcript_id: str,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista segmentos temporais da transcrição (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_transcription
    return clip_transcription.list_clip_transcript_segments(transcript_id=transcript_id, limit=limit, db_path=db_path)


def discover_clip_candidates_op(
    transcript_id: str,
    max_candidates: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Descobre e persiste cortes candidatos heuristicamente a partir de transcript (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_discovery
    return clip_discovery.discover_clip_candidates(
        transcript_id=transcript_id,
        max_candidates=max_candidates,
        db_path=db_path,
    )


def render_clip_segment_op(
    segment_id: str,
    strategy: str = "fit_blur",
    force: bool = False,
    timeout_seconds: int = 300,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Renderiza segmento SELECTED em vídeo vertical 9:16 (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_rendering
    return clip_rendering.render_clip_segment(
        segment_id=segment_id,
        strategy=strategy,
        force=force,
        timeout_seconds=timeout_seconds,
        db_path=db_path,
    )


def get_clip_render_op(
    render_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera render pelo ID (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_rendering
    return clip_rendering.get_clip_render(render_id=render_id, db_path=db_path)


def list_clip_renders_for_segment_op(
    segment_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista renders associados a um segmento (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_rendering
    return clip_rendering.list_clip_renders_for_segment(segment_id=segment_id, db_path=db_path)


def get_latest_completed_render_op(
    segment_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera render COMPLETED mais recente de um segmento (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_rendering
    return clip_rendering.get_latest_completed_render(segment_id=segment_id, db_path=db_path)


def get_render_warnings_op(
    source: Dict[str, Any],
    strategy: str,
) -> List[str]:
    """Calcula warnings contextuais para renderização de clip."""
    from app.services import clip_rendering
    return clip_rendering.get_render_warnings(source=source, strategy=strategy)


# ---------------------------------------------------------------------------
# Operações de Legendas (Fase V11-D — Captions)
# ---------------------------------------------------------------------------

def generate_clip_captions_op(
    segment_id: str,
    style: str = "CLEAN",
    force: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Gera faixa de legendas sincronizadas para um segmento SELECTED (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_captions
    return clip_captions.generate_clip_captions(
        segment_id=segment_id,
        style=style,
        force=force,
        db_path=db_path,
    )


def get_caption_track_op(
    track_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera faixa de legendas pelo ID (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_captions
    return clip_captions.get_caption_track(track_id=track_id, db_path=db_path)


def list_caption_tracks_for_segment_op(
    segment_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista faixas de legenda de um segmento (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_captions
    return clip_captions.list_caption_tracks_for_segment(segment_id=segment_id, db_path=db_path)


def get_caption_cues_op(
    caption_track_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera cues de uma faixa de legenda (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_captions
    return clip_captions.get_caption_cues(caption_track_id=caption_track_id, db_path=db_path)


# ---------------------------------------------------------------------------
# Operações de Revisão Final e Burn-In (Fase V11-D — Review)
# ---------------------------------------------------------------------------

def create_clip_review_output_op(
    render_id: str,
    caption_track_id: str,
    force: bool = False,
    timeout_seconds: int = 180,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Gera arquivo final com legendas burn-in para revisão do operador (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_review
    return clip_review.create_clip_review_output(
        render_id=render_id,
        caption_track_id=caption_track_id,
        force=force,
        timeout_seconds=timeout_seconds,
        db_path=db_path,
    )


def approve_clip_review_op(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Aprova artefato de revisão final (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_review
    return clip_review.approve_clip_review(review_id=review_id, db_path=db_path)


def reject_clip_review_op(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Rejeita artefato de revisão final (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import clip_review
    return clip_review.reject_clip_review(review_id=review_id, db_path=db_path)


def get_clip_review_op(
    review_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera artefato de revisão pelo ID (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_review
    return clip_review.get_clip_review(review_id=review_id, db_path=db_path)


def list_clip_reviews_for_segment_op(
    segment_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista revisões associadas a um segmento (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_review
    return clip_review.list_clip_reviews_for_segment(segment_id=segment_id, db_path=db_path)


def get_approved_clip_artifact_op(
    segment_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Recupera o artefato aprovado ativo de um segmento (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import clip_review
    return clip_review.get_approved_clip_artifact(segment_id=segment_id, db_path=db_path)


# ---------------------------------------------------------------------------
# 16. Produção Autônoma (Autonomous Production Loop - Fase V12-E)
# ---------------------------------------------------------------------------

def get_autonomous_production_status_op(
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna snapshot de status da produção autônoma (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import autonomous_production
    return autonomous_production.get_autonomous_status(
        db_path=db_path,
        profile_id=profile_id,
        channel_id=channel_id,
    )


def set_autonomous_mode_enabled_op(
    enabled: bool,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> None:
    """Ativa ou desativa a produção autônoma (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import autonomous_production
    if profile_id:
        autonomous_production.set_profile_autonomous_mode_enabled(
            profile_id=profile_id,
            enabled=enabled,
            db_path=db_path,
        )
    else:
        autonomous_production.set_autonomous_mode_enabled(enabled=enabled, db_path=db_path)


def run_autonomous_cycle_op(
    force: bool = True,
    one_shot: bool = True,
    db_path: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispara a execução imediata de um ciclo de produção autônoma controlado (exige PRIMARY)."""
    require_primary_instance(db_path=db_path)
    from app.services import autonomous_production
    return autonomous_production.run_autonomous_cycle(
        force=force,
        one_shot=one_shot,
        db_path=db_path,
        profile_id=profile_id,
        channel_id=channel_id,
        task_base_dir=task_base_dir,
    )


def get_global_cost_guard_status_op(
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna o estado agregado do Global Cost Guard somando todos os perfis."""
    from app.services import autonomous_production
    return autonomous_production.get_global_cost_guard_status(db_path=db_path)


# ---------------------------------------------------------------------------
# 17. Copyright & Asset Provenance (Fase V14-B)
# ---------------------------------------------------------------------------

def get_copyright_provenance_summary_op(
    task_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna o resumo de Copyright e Provenance (permitido em PRIMARY e VIEW ONLY)."""
    from app.services import copyright_gate
    return copyright_gate.get_copyright_provenance_summary(
        task_id=task_id,
        profile_id=profile_id,
        task_base_dir=task_base_dir,
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# 18. Publications Telemetry (Fase R5A)
# ---------------------------------------------------------------------------

def get_recent_publications(
    limit: int = 20,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retorna lista de eventos recentes de publicação ordenados por id DESC.

    Permite filtrar opcionalmente por profile_id e limita a quantidade de registros.
    Preserva a verdade canônica do status de publicação (ex: status='success').
    """
    from app.services import scheduler
    scheduler.init_db(db_path)

    query = """
        SELECT id, task_id, platform, published_at, status, external_id,
               error_code, provider_request_id, profile_id, channel_id,
               external_url, privacy_status
        FROM publication_events
    """
    params: List[Any] = []
    if profile_id:
        query += " WHERE profile_id = ?"
        params.append(profile_id)
    query += " ORDER BY id DESC LIMIT ?;"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 19. Live Multi-Channel Execution Telemetry (Fase R5B / UI-005)
# ---------------------------------------------------------------------------

STAGE_LABELS: Dict[str, str] = {
    "TOPIC": "Ideação do Tema",
    "SCRIPT": "Roteiro",
    "NARRATION": "Narração (TTS)",
    "VISUALS": "Materiais Visuais",
    "RENDER": "Renderização",
    "SAFETY": "Safety Gate",
    "QUALITY": "Quality Gate",
    "COPYRIGHT": "Copyright Gate",
    "READY_STOCK": "Estoque Pronto",
    "SCHEDULER": "Agendador",
    "PUBLISHER": "Publicador",
    "YOUTUBE": "Publicado no YouTube",
    "UNKNOWN": "Em Processamento",
}


def normalize_pipeline_stage(raw_stage: Optional[str]) -> Optional[str]:
    """Normaliza nomes reais de estágios persistidos para os 12 estágios canônicos.

    Retorna None se raw_stage for vazio/None. NUNCA infere estágio a partir de progresso!
    """
    if not raw_stage:
        return None
    s = str(raw_stage).strip().upper()
    if s in ("TOPIC", "PREFLIGHT"):
        return "TOPIC"
    if s in ("SCRIPT", "VIDEO_SCRIPT"):
        return "SCRIPT"
    if s in ("AUDIO", "TTS", "NARRATION"):
        return "NARRATION"
    if s in ("MATERIALS", "MATERIAL", "VISUALS", "FLOW_CLIPS", "DOWNLOAD_VIDEOS"):
        return "VISUALS"
    if s in (
        "RENDER", "SCENE_RENDER", "VIDEO", "SUBTITLE",
        "SCENE_RENDER_PREP", "SCENE_RENDER_CLIPS", "CONCAT",
        "FINAL_RENDER_AUDIO", "FINAL_RENDER_SUBTITLE",
        "FINAL_RENDER_ENCODE", "FINAL_RENDER"
    ):
        return "RENDER"
    if s in ("SAFETY", "SAFETY_GATE", "MONETIZATION_SAFETY"):
        return "SAFETY"
    if s in ("QUALITY", "QUALITY_GATE", "QUALITY_SCORE"):
        return "QUALITY"
    if s in ("COPYRIGHT", "COPYRIGHT_GATE", "PROVENANCE"):
        return "COPYRIGHT"
    if s in ("READY_STOCK", "READY", "STOCK"):
        return "READY_STOCK"
    if s in ("SCHEDULER", "SCHEDULED"):
        return "SCHEDULER"
    if s in ("PUBLISHER", "POST_FOR_ME"):
        return "PUBLISHER"
    if s in ("YOUTUBE", "PUBLISHED"):
        return "YOUTUBE"
    return "UNKNOWN"


def get_live_execution_overview(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna visão consolidada e em tempo real da execução de todos os perfis/canais ativos.

    Backend = Source of Truth.
    Frontend = Presentation Only.
    Zero inferência de stage ou provider.
    """
    init_operator_db(db_path)
    from app.services import autonomous_production, profile_manager, scheduler
    from app.services import state as sm

    profile_manager.init_profile_db(db_path)
    scheduler.init_db(db_path)

    profiles = profile_manager.list_profiles(db_path=db_path)
    channels_list = profile_manager.list_channels(db_path=db_path)

    # Mapeamento de canais por perfil
    channels_by_prof: Dict[str, List[Dict[str, Any]]] = {}
    for c in channels_list:
        pid = c.get("profile_id")
        if pid:
            channels_by_prof.setdefault(pid, []).append(c)

    results = []

    for prof in profiles:
        pid = prof.get("id")
        pname = prof.get("name")
        growth_mode = prof.get("growth_mode", "warmup")

        # Primary channel for this profile
        chans = channels_by_prof.get(pid, [])
        primary_ch = chans[0] if chans else None
        cid = primary_ch.get("id") if primary_ch else None
        cname = primary_ch.get("channel_name") if primary_ch else None
        platform = primary_ch.get("platform") if primary_ch else None

        auto_status = autonomous_production.get_autonomous_status(profile_id=pid, db_path=db_path)
        auto_enabled = auto_status.get("enabled", False)
        auto_state = auto_status.get("state", "disabled")
        auto_msg = auto_status.get("message", "")
        current_task_id = auto_status.get("current_task_id")
        waiting_task_id = auto_status.get("waiting_task_id")

        execution = None
        status = "IDLE"

        # 1. Verifica se há task em execução ativa (current_task_id ou fallback factual em webui_task/sm.state)
        if not current_task_id:
            try:
                from app.services import webui_task
                for aid in webui_task.get_active_task_ids():
                    t_obj = sm.state.get_task(aid) or {}
                    t_prof = t_obj.get("profile_id")
                    if not t_prof:
                        t_prof = profile_manager.get_task_profile_id(aid, db_path=db_path)
                    is_match = (
                        (t_prof == pid)
                        if pid and pid not in (profile_manager.DEFAULT_PROFILE_ID, "default")
                        else (not t_prof or t_prof in (profile_manager.DEFAULT_PROFILE_ID, "default"))
                    )
                    if is_match:
                        current_task_id = aid
                        break
            except Exception:
                pass

        if not current_task_id:
            try:
                all_tasks, _ = sm.state.get_all_tasks(1, 30)
                for t in all_tasks:
                    if t.get("state") == const.TASK_STATE_PROCESSING:
                        tid = t.get("task_id")
                        t_prof = t.get("profile_id") or profile_manager.get_task_profile_id(tid, db_path=db_path)
                        is_match = (
                            (t_prof == pid)
                            if pid and pid not in (profile_manager.DEFAULT_PROFILE_ID, "default")
                            else (not t_prof or t_prof in (profile_manager.DEFAULT_PROFILE_ID, "default"))
                        )
                        if is_match:
                            current_task_id = tid
                            break
            except Exception:
                pass

        if current_task_id:
            task = sm.state.get_task(current_task_id)
            if task:
                t_state = task.get("state")
                topic = task.get("video_subject") or task.get("topic") or "Geração em andamento"
                progress = task.get("progress")
                raw_stage = task.get("stage")
                failed_stage = task.get("failed_stage")
                error_msg = task.get("error")

                if t_state == const.TASK_STATE_PROCESSING:
                    status = "RUNNING"
                    # Regra de ouro: Não inventar stage se raw_stage for ausente!
                    if raw_stage:
                        pipeline_stage = normalize_pipeline_stage(raw_stage)
                        component = "task"
                        provider = task.get("provider")
                        if not provider:
                            if pipeline_stage == "RENDER":
                                provider = "ffmpeg"
                            elif pipeline_stage == "VISUALS":
                                if task.get("flow_enabled"):
                                    provider = "Google Flow"
                                else:
                                    provider = task.get("video_source") or "materials"
                            elif pipeline_stage == "NARRATION":
                                provider = task.get("voice_name") or "tts"

                        if pipeline_stage == "VISUALS" and provider in ("Google Flow", "google_flow"):
                            flow_aid = task.get("flow_account_id") or task.get("flow_account")
                            if flow_aid:
                                provider = f"Google Flow ({flow_aid})"
                            else:
                                try:
                                    from app.services import flow_account_pool
                                    pool_st = flow_account_pool.get_flow_accounts_status()
                                    for acct in pool_st.get("accounts", []):
                                        if acct.get("current_task_id") == current_task_id:
                                            provider = f"Google Flow ({acct.get('account_id')})"
                                            break
                                except Exception:
                                    pass

                        STAGE_ORDER = [
                            "TOPIC", "SCRIPT", "NARRATION", "VISUALS", "RENDER",
                            "SAFETY", "QUALITY", "COPYRIGHT", "READY_STOCK",
                            "SCHEDULER", "PUBLISHER", "YOUTUBE"
                        ]
                        if pipeline_stage in STAGE_ORDER:
                            idx = STAGE_ORDER.index(pipeline_stage)
                            next_stage = STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None
                        else:
                            next_stage = None
                    else:
                        pipeline_stage = None
                        component = "task"
                        provider = None
                        next_stage = None

                    gates_data = {
                        "safety_status": task.get("safety_status"),
                        "quality_score": task.get("quality_score"),
                        "copyright_status": task.get("copyright_status") or task.get("copyright_provenance_gate"),
                        "gate_status": task.get("gate_status"),
                        "gate_reason": task.get("gate_reason"),
                    }

                    execution = {
                        "task_id": current_task_id,
                        "profile_id": pid,
                        "profile_name": pname,
                        "channel_id": cid,
                        "channel_name": cname,
                        "topic": topic,
                        "pipeline_stage": pipeline_stage,
                        "pipeline_stage_label": STAGE_LABELS.get(pipeline_stage, "Em Processamento") if pipeline_stage else None,
                        "status": "RUNNING",
                        "progress": progress,
                        "component": component,
                        "provider": provider,
                        "started_at": task.get("created_at"),
                        "updated_at": None,
                        "elapsed_seconds": None,
                        "message": auto_msg or "Executando pipeline de vídeo",
                        "retry_state": None,
                        "fallback_state": None,
                        "next_stage": next_stage,
                        "error": None,
                        "gates": gates_data,
                        "publication_state": None,
                    }
                elif t_state == const.TASK_STATE_FAILED:
                    status = "FAILED"
                    pipeline_stage = normalize_pipeline_stage(failed_stage) if failed_stage else (normalize_pipeline_stage(raw_stage) if raw_stage else None)
                    failed_prov = task.get("provider")
                    if not failed_prov and pipeline_stage == "RENDER":
                        failed_prov = "ffmpeg"
                    elif not failed_prov and pipeline_stage == "VISUALS" and task.get("flow_enabled"):
                        failed_prov = f"Google Flow ({task.get('flow_account_id')})" if task.get("flow_account_id") else "Google Flow"
                    gates_data = {
                        "safety_status": task.get("safety_status"),
                        "quality_score": task.get("quality_score"),
                        "copyright_status": task.get("copyright_status") or task.get("copyright_provenance_gate"),
                        "gate_status": task.get("gate_status") or "rejected",
                        "gate_reason": task.get("gate_reason") or error_msg,
                    }
                    execution = {
                        "task_id": current_task_id,
                        "profile_id": pid,
                        "profile_name": pname,
                        "channel_id": cid,
                        "channel_name": cname,
                        "topic": topic,
                        "pipeline_stage": pipeline_stage,
                        "pipeline_stage_label": STAGE_LABELS.get(pipeline_stage, "Falha") if pipeline_stage else None,
                        "status": "FAILED",
                        "progress": progress,
                        "component": "task",
                        "provider": failed_prov,
                        "started_at": task.get("created_at"),
                        "updated_at": None,
                        "elapsed_seconds": None,
                        "message": error_msg or "Tarefa falhou",
                        "retry_state": None,
                        "fallback_state": None,
                        "next_stage": None,
                        "error": error_msg,
                        "gates": gates_data,
                        "publication_state": None,
                    }
                elif t_state == const.TASK_STATE_COMPLETE:
                    status = "WAITING"
                    safety_val = task.get("safety_status")
                    if not safety_val:
                        try:
                            from app.services import safety_gate
                            s_rec = safety_gate.get_safety_assessment(current_task_id)
                            if s_rec:
                                safety_val = s_rec.get("safety_status")
                        except Exception:
                            pass
                    c_val = task.get("copyright_status") or task.get("copyright_provenance_gate")
                    gates_data = {
                        "safety_status": safety_val,
                        "quality_score": task.get("quality_score"),
                        "copyright_status": c_val,
                        "gate_status": task.get("gate_status"),
                        "gate_reason": task.get("gate_reason"),
                    }
                    execution = {
                        "task_id": current_task_id,
                        "profile_id": pid,
                        "profile_name": pname,
                        "channel_id": cid,
                        "channel_name": cname,
                        "topic": topic,
                        "pipeline_stage": "READY_STOCK",
                        "pipeline_stage_label": STAGE_LABELS["READY_STOCK"],
                        "status": "WAITING",
                        "progress": 100,
                        "component": "autonomous_production",
                        "provider": None,
                        "started_at": task.get("created_at"),
                        "updated_at": None,
                        "elapsed_seconds": None,
                        "message": "Vídeo pronto aguardando agendamento",
                        "retry_state": None,
                        "fallback_state": None,
                        "next_stage": "SCHEDULER",
                        "error": None,
                        "gates": gates_data,
                        "publication_state": None,
                    }

        # 2. Se não há current_task ativo, verifica waiting_task_id
        if not execution and waiting_task_id:
            w_task = sm.state.get_task(waiting_task_id)
            w_topic = w_task.get("video_subject") if w_task else "Vídeo em estoque aguardando agendamento"
            status = "WAITING"
            execution = {
                "task_id": waiting_task_id,
                "profile_id": pid,
                "profile_name": pname,
                "channel_id": cid,
                "channel_name": cname,
                "topic": w_topic,
                "pipeline_stage": "READY_STOCK",
                "pipeline_stage_label": STAGE_LABELS["READY_STOCK"],
                "status": "WAITING",
                "progress": 100,
                "component": "autonomous_production",
                "provider": None,
                "started_at": w_task.get("created_at") if w_task else None,
                "updated_at": None,
                "elapsed_seconds": None,
                "message": auto_msg or "Aguardando próximo slot de publicação",
                "retry_state": None,
                "fallback_state": None,
                "next_stage": "SCHEDULER",
                "error": None,
                "publication_state": None,
            }

        # 3. Se não há task em geração/waiting, verifica agendamentos pendentes ou retrying em scheduled_posts
        if not execution:
            with get_connection(db_path) as conn:
                sched_row = conn.execute(
                    """
                    SELECT id, task_id, scheduled_at, status, attempts, last_error
                    FROM scheduled_posts
                    WHERE profile_id = ? AND status IN ('pending', 'failed', 'ready')
                    ORDER BY scheduled_at ASC LIMIT 1;
                    """,
                    (pid,)
                ).fetchone()

                if sched_row:
                    s_dict = dict(sched_row)
                    s_task_id = s_dict["task_id"]
                    s_attempts = s_dict.get("attempts", 0)
                    s_err = s_dict.get("last_error")

                    # REGRA 9 (STALE STATUS): Verifica se na verdade já houve publicação terminal com sucesso!
                    pub_row = conn.execute(
                        """
                        SELECT id, published_at, status, external_url
                        FROM publication_events
                        WHERE task_id = ? AND status = 'success'
                        ORDER BY id DESC LIMIT 1;
                        """,
                        (s_task_id,)
                    ).fetchone()

                    if pub_row:
                        p_dict = dict(pub_row)
                        status = "SUCCESS"
                        execution = {
                            "task_id": s_task_id,
                            "profile_id": pid,
                            "profile_name": pname,
                            "channel_id": cid,
                            "channel_name": cname,
                            "topic": "Publicado no YouTube",
                            "pipeline_stage": "YOUTUBE",
                            "pipeline_stage_label": STAGE_LABELS["YOUTUBE"],
                            "status": "SUCCESS",
                            "progress": 100,
                            "component": "scheduler_worker",
                            "provider": "post_for_me",
                            "started_at": None,
                            "updated_at": p_dict.get("published_at"),
                            "elapsed_seconds": None,
                            "message": "Publicado com sucesso no YouTube",
                            "retry_state": None,
                            "fallback_state": None,
                            "next_stage": None,
                            "error": None,
                            "publication_state": {
                                "status": "success",
                                "published_at": p_dict.get("published_at"),
                                "external_url": p_dict.get("external_url"),
                            },
                        }
                    else:
                        is_retrying = s_attempts > 0
                        status = "RETRYING" if is_retrying else "SCHEDULED"
                        pipeline_stage = "PUBLISHER" if is_retrying else "SCHEDULER"
                        execution = {
                            "task_id": s_task_id,
                            "profile_id": pid,
                            "profile_name": pname,
                            "channel_id": cid,
                            "channel_name": cname,
                            "topic": "Tentativa de publicação" if is_retrying else "Vídeo agendado",
                            "pipeline_stage": pipeline_stage,
                            "pipeline_stage_label": STAGE_LABELS.get(pipeline_stage, "Publicador") if is_retrying else STAGE_LABELS["SCHEDULER"],
                            "status": status,
                            "progress": 100,
                            "component": "scheduler_worker",
                            "provider": "post_for_me",
                            "started_at": s_dict.get("scheduled_at"),
                            "updated_at": None,
                            "elapsed_seconds": None,
                            "message": f"Retry {s_attempts}: {s_err}" if is_retrying and s_err else f"Agendado para {s_dict.get('scheduled_at')}",
                            "retry_state": {"attempts": s_attempts, "is_retrying": is_retrying, "error": s_err} if is_retrying else None,
                            "fallback_state": None,
                            "next_stage": "YOUTUBE" if is_retrying else "PUBLISHER",
                            "error": s_err if s_dict.get("status") == "failed" else None,
                            "publication_state": None,
                        }

        # 4. Se não há execução ativa ou agendada, canal está IDLE / BLOCKED / WAITING
        if not execution:
            if auto_state == "blocked":
                status = "BLOCKED"
            elif auto_state == "cooldown":
                status = "WAITING"
            elif not auto_enabled or auto_state == "disabled":
                status = "IDLE"
            else:
                status = "IDLE"

        stock_info = get_canonical_ready_stock(db_path=db_path, profile_id=pid)
        ready_stock_count = int(stock_info.get("total_ready", 0))
        target_stock_count = int(stock_info.get("minimum_threshold", 3))

        results.append({
            "profile_id": pid,
            "profile_name": pname,
            "channel_id": cid,
            "channel_name": cname,
            "platform": platform,
            "autonomous_enabled": auto_enabled,
            "growth_mode": growth_mode,
            "status": status,
            "ready_stock": ready_stock_count,
            "target_stock": target_stock_count,
            "execution": execution,
        })

    # Flow multi-account pool telemetry (FLOW-UI-001)
    flow_pool_data = None
    try:
        from app.services import flow_account_pool
        raw_pool = flow_account_pool.get_flow_accounts_status()
        allowed_fields = {
            "account_id",
            "display_name",
            "enabled",
            "priority",
            "status",
            "credits_remaining",
            "credits_source",
            "credits_last_verified_at",
            "is_stale",
            "staleness_reason",
            "staleness_hours",
            "last_verified_display",
            "current_task_id",
            "last_credit_cost",
            "last_success_at",
            "last_error",
        }
        sanitized_accounts = []
        for acct in raw_pool.get("accounts", []):
            sanitized_accounts.append({k: acct[k] for k in allowed_fields if k in acct})

        flow_pool_data = {
            "accounts": sanitized_accounts,
            "active_account_id": raw_pool.get("active_account_id"),
            "total_known_credits": raw_pool.get("total_known_credits"),
        }
    except Exception as exc:
        logger.warning(f"Failed to fetch flow accounts status for live overview: {exc}")
        flow_pool_data = {
            "accounts": [],
            "active_account_id": None,
            "total_known_credits": None,
            "error": "Telemetria indisponível",
        }

    return {
        "channels": results,
        "total": len(results),
        "flow_accounts": flow_pool_data,
        "flow_pool": flow_pool_data,
    }


def get_execution_detail(task_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retorna trace detalhado de execução de uma tarefa baseado estritamente em fatos persistidos."""
    init_operator_db(db_path)
    from app.services import profile_manager, scheduler
    from app.services import state as sm

    profile_manager.init_profile_db(db_path)
    scheduler.init_db(db_path)

    task = sm.state.get_task(task_id)
    profile_id = None
    if task:
        profile_id = task.get("profile_id")
    if not profile_id:
        profile_id = profile_manager.get_task_profile_id(task_id, db_path=db_path)

    profile = profile_manager.get_profile(profile_id, db_path=db_path) if profile_id else None
    channels = profile_manager.list_channels(profile_id=profile_id, db_path=db_path) if profile_id else []
    primary_ch = channels[0] if channels else None

    with get_connection(db_path) as conn:
        sched_row = conn.execute(
            "SELECT * FROM scheduled_posts WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
            (task_id,)
        ).fetchone()
        sched_dict = dict(sched_row) if sched_row else None

        pub_row = conn.execute(
            "SELECT * FROM publication_events WHERE task_id = ? ORDER BY id DESC LIMIT 1;",
            (task_id,)
        ).fetchone()
        pub_dict = dict(pub_row) if pub_row else None

        op_events = conn.execute(
            """
            SELECT id, timestamp, component, severity, event_type, message, metadata_json
            FROM operational_events
            WHERE task_id = ?
            ORDER BY id ASC;
            """,
            (task_id,)
        ).fetchall()
        events_timeline = []
        for r in op_events:
            d = dict(r)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except Exception:
                    d["metadata"] = {}
            events_timeline.append(d)

    if not task and not sched_dict and not pub_dict and not events_timeline:
        return None

    # Trace causal: CHANNEL -> AUTONOMOUS_PRODUCTION -> SERVICE -> PROVIDER -> RESULT -> NEXT_SERVICE
    trace = []

    trace.append({
        "node": "CHANNEL",
        "name": primary_ch.get("channel_name") if primary_ch else (profile.get("name") if profile else "Default Channel"),
        "profile_id": profile_id,
        "channel_id": primary_ch.get("id") if primary_ch else None,
        "growth_mode": profile.get("growth_mode") if profile else "warmup",
    })

    trace.append({
        "node": "AUTONOMOUS_PRODUCTION",
        "component": "autonomous_production",
        "action": "trigger_generation",
    })

    current_service = "task"
    if pub_dict and pub_dict.get("status") == "success":
        current_service = "youtube_publisher"
    elif sched_dict:
        current_service = "scheduler_worker"

    trace.append({
        "node": "SERVICE",
        "name": current_service,
        "stage": normalize_pipeline_stage(task.get("stage")) if task else None,
    })

    provider_name = None
    if pub_dict:
        provider_name = "post_for_me / youtube"
    elif task:
        norm_s = normalize_pipeline_stage(task.get("stage"))
        if norm_s == "RENDER":
            provider_name = "ffmpeg"
        elif norm_s == "VISUALS":
            provider_name = task.get("provider") or ("Google Flow" if task.get("flow_enabled") else task.get("video_source", "materials"))
        elif norm_s == "NARRATION":
            provider_name = f"tts ({task.get('voice_name')})" if task.get("voice_name") else (task.get("provider") or "tts")
        elif task.get("provider"):
            provider_name = task.get("provider")
        elif task.get("voice_name"):
            provider_name = f"tts ({task.get('voice_name')})"
    trace.append({
        "node": "PROVIDER",
        "name": provider_name or "internal",
    })

    final_status = "UNKNOWN"
    if pub_dict and pub_dict.get("status") == "success":
        final_status = "SUCCESS"
    elif task and task.get("state") == const.TASK_STATE_FAILED:
        final_status = "FAILED"
    elif task and task.get("state") == const.TASK_STATE_COMPLETE:
        final_status = "COMPLETE"
    elif task and task.get("state") == const.TASK_STATE_PROCESSING:
        final_status = "PROCESSING"
    elif sched_dict:
        final_status = sched_dict.get("status", "SCHEDULED").upper()

    trace.append({
        "node": "RESULT",
        "status": final_status,
        "error": task.get("error") if task else (sched_dict.get("last_error") if sched_dict else None),
    })

    next_srv = None
    if final_status == "PROCESSING":
        next_srv = "safety_gate"
    elif final_status == "COMPLETE" and not sched_dict and not pub_dict:
        next_srv = "scheduler"
    elif final_status in ("SCHEDULED", "PENDING"):
        next_srv = "publisher"

    trace.append({
        "node": "NEXT_SERVICE",
        "name": next_srv,
    })

    return {
        "task_id": task_id,
        "profile": profile,
        "channel": primary_ch,
        "topic": task.get("video_subject") if task else None,
        "task_snapshot": {
            "state": task.get("state") if task else None,
            "progress": task.get("progress") if task else None,
            "stage": task.get("stage") if task else None,
            "normalized_stage": normalize_pipeline_stage(task.get("stage")) if task else None,
            "failed_stage": task.get("failed_stage") if task else None,
            "error": task.get("error") if task else None,
            "created_at": task.get("created_at") if task else None,
            "has_script": bool(task.get("script") or task.get("video_script")) if task else False,
            "has_audio": bool(task.get("audio_file")) if task else False,
            "materials_count": len(task.get("video_materials", [])) if task else 0,
            "safety_status": task.get("safety_status") if task else None,
            "quality_score": task.get("quality_score") if task else None,
            "copyright_status": task.get("copyright_status") if task else None,
        } if task else None,
        "scheduler_entry": sched_dict,
        "publication_event": pub_dict,
        "events_timeline": events_timeline,
        "execution_trace": trace,
    }

# ---------------------------------------------------------------------------
# Operações do Google Flow Pool para Console Operacional
# ---------------------------------------------------------------------------

def get_flow_accounts_status_op(
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna estado consolidado do pool de contas Google Flow."""
    from app.services import flow_account_pool
    return flow_account_pool.get_flow_accounts_status(config_path=config_path, runtime_path=runtime_path)


def refresh_flow_account_credits_op(
    account_id: str,
    force: bool = False,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcilia saldo de uma conta Google Flow via Playwright headless."""
    from app.services import flow_account_pool
    return flow_account_pool.refresh_account_credits(
        account_id,
        force=force,
        config_path=config_path,
        runtime_path=runtime_path,
    )


def refresh_all_flow_accounts_credits_op(
    force: bool = False,
    config_path: Optional[str] = None,
    runtime_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconcilia saldo de todas as contas do pool Google Flow."""
    from app.services import flow_account_pool
    return flow_account_pool.refresh_all_accounts_credits(
        force=force,
        config_path=config_path,
        runtime_path=runtime_path,
    )



# ---------------------------------------------------------------------------
# 28. Fleet Operations Summary (Web UI V2 - Fase R5 / Missão C)
# ---------------------------------------------------------------------------

def _get_fleet_ro_connection(target_path: str) -> sqlite3.Connection:
    """Abre conexão SQLite em modo somente leitura (mode=ro) com fallback seguro."""
    abs_path = os.path.abspath(target_path)
    if os.path.isfile(abs_path):
        try:
            conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            pass
    conn = sqlite3.connect(abs_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def get_fleet_summary(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna visão consolidada e aditiva da frota de canais para a Web UI V2.

    Regras de Status (status):
    - 'paused': Fábrica pausada globalmente pelo operador (PAUSED/EMERGENCY_PAUSED),
      ou canal desativado (is_active=False), ou modo autônomo desligado para o canal.
    - 'blocked': Disjuntor acionado (>= limite configurado de rejeições consecutivas, padrão 10),
      ou estado autônomo em 'blocked' ou 'error'.
    - 'running': Canal atualmente gerando ou planejando tarefas ('generating'/'planning'
      ou tarefas em processamento).
    - 'attention': Canal em cooldown, ou estoque pronto abaixo da meta, ou falhas registradas nas últimas 24h.
    - 'ok': Canal ativo, modo autônomo ligado, estoque dentro da meta e sem bloqueios ou falhas.

    Regras de Métricas:
    - 'failed': Contabiliza exclusivamente falhas das últimas 24h consolidadas entre
      scheduled_posts, publication_events e tasks.
    - 'ready_stock': Estoque pronto usando a fonte canônica (get_canonical_ready_stock),
      alinhado com get_profile_operations_overview.

    Regras de Causa (issue):
    - Frase descritiva em português detalhando a causa raiz quando status != 'ok', ou None quando saudável.

    Desempenho:
    - Executa consultas agregadas (GROUP BY) em modo de leitura (a inicialização idempotente do banco ainda roda) no SQLite.
    - Zero consultas em laço por perfil (O(P + T) linear).
    - Não restringe tarefas a paginações legadas (ex: 200).
    """
    from datetime import timedelta
    from app.services import autonomous_production, profile_manager
    from app.services import state as sm

    effective_db = get_db_path(db_path)
    init_operator_db(effective_db)

    # 1. Conexão Read-Only com o banco
    conn = _get_fleet_ro_connection(effective_db)
    try:
        # A. Verifica tabelas existentes
        existing_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }

        if "content_profiles" not in existing_tables:
            return {
                "totals": {
                    "total_channels": 0,
                    "active_channels": 0,
                    "published_today": 0,
                    "goal_today": 0,
                    "total_ready_stock": 0,
                    "channels_running": 0,
                    "channels_attention": 0,
                    "channels_blocked": 0,
                    "channels_paused": 0,
                    "channels_ok": 0,
                },
                "channels": [],
            }

        # B. Perfis
        profiles = [
            dict(r) for r in conn.execute(
                """
                SELECT id, name, slug, niche, language, region, default_preset,
                       growth_mode, is_active, settings_json, created_at, updated_at
                FROM content_profiles
                ORDER BY created_at ASC;
                """
            ).fetchall()
        ]

        # C. Autopilot Settings
        settings_map: Dict[str, str] = {}
        if "autopilot_settings" in existing_tables:
            rows = conn.execute("SELECT key, value FROM autopilot_settings;").fetchall()
            settings_map = {r["key"]: str(r["value"]) for r in rows if r["key"] is not None}

        factory_state = str(settings_map.get("factory_state", FACTORY_STATE_RUNNING)).strip().upper()
        is_factory_paused = factory_state in ("PAUSED", "EMERGENCY_PAUSED")

        # Janela de tempo de 24 horas para falhas e aprovações
        now_utc = datetime.now(timezone.utc)
        today_prefix = now_utc.strftime("%Y-%m-%d")
        today_midnight_iso = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        h24_ago_iso = (now_utc - timedelta(hours=24)).isoformat()

        # D. Scheduled Posts (Agregado GROUP BY com janela de 24h para falhas)
        scheduled_counts: Dict[str, int] = {}
        sched_failed_counts: Dict[str, int] = {}
        if "scheduled_posts" in existing_tables:
            s_rows = conn.execute(
                """
                SELECT
                    COALESCE(profile_id, 'default') AS pid,
                    SUM(CASE WHEN status IN ('planned', 'ready') THEN 1 ELSE 0 END) AS sched_cnt,
                    SUM(CASE WHEN status = 'failed' AND (scheduled_at >= ? OR created_at >= ?) THEN 1 ELSE 0 END) AS failed_24h
                FROM scheduled_posts
                GROUP BY COALESCE(profile_id, 'default');
                """,
                (h24_ago_iso, h24_ago_iso),
            ).fetchall()
            for r in s_rows:
                pid = r["pid"]
                scheduled_counts[pid] = int(r["sched_cnt"] or 0)
                sched_failed_counts[pid] = int(r["failed_24h"] or 0)

        # E. Publication Events (Agregado GROUP BY com janela de 24h para falhas)
        published_today: Dict[str, int] = {}
        pub_failed_counts: Dict[str, int] = {}
        if "publication_events" in existing_tables:
            p_rows = conn.execute(
                """
                SELECT
                    COALESCE(profile_id, 'default') AS pid,
                    SUM(CASE WHEN (published_at >= ? OR published_at LIKE ?) AND status = 'success' THEN 1 ELSE 0 END) AS today_cnt,
                    SUM(CASE WHEN status = 'failed' AND published_at >= ? THEN 1 ELSE 0 END) AS failed_24h
                FROM publication_events
                GROUP BY COALESCE(profile_id, 'default');
                """,
                (today_midnight_iso, f"{today_prefix}%", h24_ago_iso),
            ).fetchall()
            for r in p_rows:
                pid = r["pid"]
                published_today[pid] = int(r["today_cnt"] or 0)
                pub_failed_counts[pid] = int(r["failed_24h"] or 0)

        # F. Ready Stock & Tasks agregados via SQLite
        sqlite_ready: Dict[str, int] = {}
        sqlite_pending: Dict[str, int] = {}
        sqlite_failed: Dict[str, int] = {}

        # 1) Via monetization_safety + task_profiles se existirem
        if "monetization_safety" in existing_tables:
            has_tp = "task_profiles" in existing_tables
            join_tp = "LEFT JOIN task_profiles tp ON tp.task_id = ms.task_id" if has_tp else ""
            col_pid = "COALESCE(tp.profile_id, 'default')" if has_tp else "'default'"

            sub_excl = ""
            if "publication_events" in existing_tables and "scheduled_posts" in existing_tables:
                sub_excl = """
                  AND ms.task_id NOT IN (
                      SELECT task_id FROM publication_events WHERE status = 'success'
                      UNION
                      SELECT task_id FROM scheduled_posts WHERE status IN ('published', 'cancelled')
                  )
                """

            ms_rows = conn.execute(
                f"""
                SELECT {col_pid} AS pid, COUNT(DISTINCT ms.task_id) AS cnt
                FROM monetization_safety ms
                {join_tp}
                WHERE UPPER(ms.safety_status) = 'PASS'
                {sub_excl}
                GROUP BY {col_pid};
                """
            ).fetchall()
            for r in ms_rows:
                sqlite_ready[r["pid"]] = int(r["cnt"])

        # 2) Via tabela tasks se existir (falhas filtradas nas últimas 24h)
        if "tasks" in existing_tables:
            task_cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks);").fetchall()}
            if "created_at" in task_cols and "updated_at" in task_cols:
                time_filter = "AND (created_at >= ? OR updated_at >= ?)"
                time_params = (h24_ago_iso, h24_ago_iso)
            elif "created_at" in task_cols:
                time_filter = "AND created_at >= ?"
                time_params = (h24_ago_iso,)
            elif "updated_at" in task_cols:
                time_filter = "AND updated_at >= ?"
                time_params = (h24_ago_iso,)
            else:
                time_filter = ""
                time_params = ()

            t_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(profile_id, 'default') AS pid,
                    SUM(CASE WHEN state = 2 AND (safety_status IS NULL OR UPPER(safety_status) != 'FAIL') THEN 1 ELSE 0 END) AS ready_cnt,
                    SUM(CASE WHEN state IN (0, 1) THEN 1 ELSE 0 END) AS pending_cnt,
                    SUM(CASE WHEN state = 3 {time_filter} THEN 1 ELSE 0 END) AS failed_cnt
                FROM tasks
                GROUP BY COALESCE(profile_id, 'default');
                """,
                time_params,
            ).fetchall()
            for r in t_rows:
                pid = r["pid"]
                sqlite_ready[pid] = max(sqlite_ready.get(pid, 0), int(r["ready_cnt"] or 0))
                sqlite_pending[pid] = max(sqlite_pending.get(pid, 0), int(r["pending_cnt"] or 0))
                sqlite_failed[pid] = max(sqlite_failed.get(pid, 0), int(r["failed_cnt"] or 0))

        # G. Aprovação 24h via operational_events se existir
        approved_24h: Dict[str, int] = {}
        attempts_24h: Dict[str, int] = {}
        if "operational_events" in existing_tables:
            has_tp = "task_profiles" in existing_tables
            join_tp = "LEFT JOIN task_profiles tp ON tp.task_id = o.task_id" if has_tp else ""
            col_pid = "COALESCE(tp.profile_id, json_extract(o.metadata_json, '$.profile_id'), 'default')" if has_tp else "COALESCE(json_extract(o.metadata_json, '$.profile_id'), 'default')"

            op_rows = conn.execute(
                f"""
                SELECT {col_pid} AS pid, o.event_type, COUNT(*) as cnt
                FROM operational_events o
                {join_tp}
                WHERE o.timestamp >= ?
                  AND o.event_type IN (
                      'generation_approved', 'task_approved_and_scheduled', 'task_waiting_schedule',
                      'task_gate_rejected', 'generation_failed', 'generation_started'
                  )
                GROUP BY {col_pid}, o.event_type;
                """,
                (h24_ago_iso,),
            ).fetchall()
            for r in op_rows:
                pid = r["pid"]
                ev = r["event_type"]
                cnt = int(r["cnt"])
                if ev in ("generation_approved", "task_approved_and_scheduled", "task_waiting_schedule"):
                    approved_24h[pid] = approved_24h.get(pid, 0) + cnt
                if ev in ("generation_approved", "task_approved_and_scheduled", "task_waiting_schedule", "task_gate_rejected", "generation_failed"):
                    attempts_24h[pid] = attempts_24h.get(pid, 0) + cnt
                elif ev == "generation_started":
                    attempts_24h[pid] = max(attempts_24h.get(pid, 0), cnt)

        # H. Mapeamento task_profiles para tarefas em memória
        task_prof_map = {}
        task_prof_time = {}
        if "task_profiles" in existing_tables:
            tp_rows = conn.execute("SELECT task_id, profile_id, created_at FROM task_profiles;").fetchall()
            task_prof_map = {r["task_id"]: r["profile_id"] for r in tp_rows}
            task_prof_time = {r["task_id"]: r["created_at"] for r in tp_rows if r["created_at"]}

    finally:
        conn.close()

    # 2. Leitura agregada de tarefas em memória (sem limite rígido 200)
    mem_ready: Dict[str, int] = {}
    mem_pending: Dict[str, int] = {}
    mem_failed: Dict[str, int] = {}

    state_obj = getattr(sm, "state", None)
    if state_obj:
        tasks_dict = getattr(state_obj, "_tasks", None)
        if isinstance(tasks_dict, dict):
            memory_tasks = list(tasks_dict.values())
        else:
            try:
                memory_tasks, _ = state_obj.get_all_tasks(1, 50000)
            except Exception:
                memory_tasks = []

        for t in memory_tasks:
            tid = t.get("task_id")
            pid = t.get("profile_id") or task_prof_map.get(tid, "default")
            st = t.get("state")
            if st in (const.TASK_STATE_PENDING, const.TASK_STATE_PROCESSING):
                mem_pending[pid] = mem_pending.get(pid, 0) + 1
            elif st == const.TASK_STATE_FAILED:
                t_time = t.get("failed_at") or t.get("updated_at") or t.get("created_at") or task_prof_time.get(tid)
                if not t_time or t_time >= h24_ago_iso:
                    mem_failed[pid] = mem_failed.get(pid, 0) + 1
            elif st == const.TASK_STATE_COMPLETE:
                if t.get("safety_status") != "FAIL":
                    mem_ready[pid] = mem_ready.get(pid, 0) + 1

    # 3. Consolidação por canal
    channels_data = []

    for p in profiles:
        pid = p["id"]
        is_default = (pid in ("default", profile_manager.DEFAULT_PROFILE_ID))

        # Contexto de geração via profile_manager (mesma fonte de verdade de autonomous_production)
        prof_ctx = profile_manager.get_generation_profile_context(profile_id=pid, db_path=effective_db)

        # Configurações brutas de fallback caso existam em settings_json
        settings_raw = p.get("settings_json") or "{}"
        settings_parsed = {}
        try:
            settings_parsed = json.loads(settings_raw)
        except Exception:
            pass

        schedule_cfg = settings_parsed.get("schedule", {})
        automation_cfg = settings_parsed.get("automation", {})

        # Formato (quiz_dilemma, quiz_paper, traditional, etc.)
        fmt = prof_ctx.get("video_format") or prof_ctx.get("content_style") or "traditional"

        # Autonomous enabled
        auto_key = "autonomous_mode_enabled" if is_default else f"autonomous_mode_enabled:{pid}"
        auto_val = settings_map.get(auto_key)
        if auto_val is not None:
            autonomous_enabled = str(auto_val).lower() in ("true", "1", "yes")
        else:
            autonomous_enabled = bool(prof_ctx.get("autonomous_enabled") if prof_ctx.get("autonomous_enabled") is not None else automation_cfg.get("autonomous_enabled", False))

        # Growth Mode
        growth_mode = (p.get("growth_mode") or prof_ctx.get("growth_mode") or "WARMUP").strip().upper()

        # Target Ready Stock
        target_key = "autonomous_target_ready_stock" if is_default else f"autonomous_target_ready_stock:{pid}"
        target_val = settings_map.get(target_key)
        if target_val is not None:
            try:
                target_stock = int(target_val)
            except (ValueError, TypeError):
                target_stock = 10 if growth_mode == "SCALE" else 3
        else:
            target_stock = prof_ctx.get("target_ready_stock") or automation_cfg.get("target_ready_stock") or (10 if growth_mode == "SCALE" else 3)

        # Goal Today (posts por dia configurados)
        goal_today = schedule_cfg.get("posts_per_day") or automation_cfg.get("posts_per_day") or prof_ctx.get("posts_per_day") or 1

        # Estoque pronto: fonte canônica alinhada com get_profile_operations_overview
        try:
            canon = get_canonical_ready_stock(db_path=effective_db, profile_id=pid)
            ready_stock = int(canon.get("total_ready", 0))
        except Exception:
            ready_stock = max(sqlite_ready.get(pid, 0), mem_ready.get(pid, 0))
        pending_proc = max(sqlite_pending.get(pid, 0), mem_pending.get(pid, 0))
        failed_count = (
            sched_failed_counts.get(pid, 0)
            + pub_failed_counts.get(pid, 0)
            + max(sqlite_failed.get(pid, 0), mem_failed.get(pid, 0))
        )
        sched_count = scheduled_counts.get(pid, 0)
        pub_today_count = published_today.get(pid, 0)

        # Taxa de aprovação 24h
        app_cnt = approved_24h.get(pid, 0)
        att_cnt = attempts_24h.get(pid, 0)
        approval_rate_24h = round(app_cnt / att_cnt, 2) if att_cnt > 0 else None

        # Last run at
        last_tick_key = "autonomous_last_tick" if is_default else f"autonomous_last_tick:{pid}"
        last_run_at = settings_map.get(last_tick_key) or None

        # Sinais de status e disjuntor com limite real configurado
        rejections_key = "autonomous_consecutive_rejections" if is_default else f"autonomous_consecutive_rejections:{pid}"
        try:
            consec_rejections = int(settings_map.get(rejections_key, 0))
        except (ValueError, TypeError):
            consec_rejections = 0

        max_rej_key = "autonomous_max_consecutive_rejections" if is_default else f"autonomous_max_consecutive_rejections:{pid}"
        max_rej_val = settings_map.get(max_rej_key) or settings_map.get("autonomous_max_consecutive_rejections")
        if max_rej_val is not None:
            try:
                max_rejections = int(max_rej_val)
            except (ValueError, TypeError):
                max_rejections = autonomous_production.DEFAULT_AUTONOMOUS_MAX_CONSECUTIVE_REJECTIONS
        else:
            max_rejections = autonomous_production.DEFAULT_AUTONOMOUS_MAX_CONSECUTIVE_REJECTIONS

        state_key = "autonomous_state" if is_default else f"autonomous_state:{pid}"
        auto_state = str(settings_map.get(state_key, "")).lower().strip()

        msg_key = "autonomous_message" if is_default else f"autonomous_message:{pid}"
        auto_msg = str(settings_map.get(msg_key, "")).strip()

        err_key = "autonomous_last_error" if is_default else f"autonomous_last_error:{pid}"
        auto_err = str(settings_map.get(err_key, "")).strip()

        is_active = bool(p.get("is_active", True))

        # Determinação determinística de status e issue
        if is_factory_paused:
            status = "paused"
            issue = "Fábrica pausada pelo operador"
        elif not is_active:
            status = "paused"
            issue = "Canal desativado pelo operador"
        elif not autonomous_enabled:
            status = "paused"
            issue = "Modo autônomo desligado"
        elif consec_rejections >= max_rejections:
            status = "blocked"
            issue = f"Disjuntor acionado: {consec_rejections} rejeições consecutivas"
        elif auto_state in ("blocked", "error"):
            status = "blocked"
            issue = auto_msg or auto_err or "Produção autônoma bloqueada"
        elif auto_state in ("generating", "planning") or pending_proc > 0:
            status = "running"
            issue = None
        elif auto_state == "cooldown":
            status = "attention"
            issue = "Em período de espera (cooldown)"
        elif ready_stock == 0:
            status = "attention"
            issue = "Estoque esgotado (0 vídeos prontos)"
        elif ready_stock < target_stock:
            status = "attention"
            issue = f"Estoque abaixo da meta ({ready_stock}/{target_stock})"
        elif failed_count > 0:
            status = "attention"
            issue = f"Atenção: {failed_count} falha(s) registrada(s)"
        else:
            status = "ok"
            issue = None

        channels_data.append({
            "profile_id": pid,
            "name": p.get("name"),
            "slug": p.get("slug"),
            "niche": p.get("niche") or "—",
            "format": fmt,
            "is_active": is_active,
            "autonomous_enabled": autonomous_enabled,
            "growth_mode": growth_mode,
            "ready_stock": ready_stock,
            "target_stock": target_stock,
            "pending_processing": pending_proc,
            "failed": failed_count,
            "scheduled": sched_count,
            "published_today": pub_today_count,
            "goal_today": goal_today,
            "approval_rate_24h": approval_rate_24h,
            "last_run_at": last_run_at,
            "status": status,
            "issue": issue,
        })

    # 4. Totais da Frota
    totals = {
        "total_channels": len(channels_data),
        "active_channels": sum(1 for c in channels_data if c["is_active"]),
        "published_today": sum(c["published_today"] for c in channels_data),
        "goal_today": sum(c["goal_today"] for c in channels_data),
        "total_ready_stock": sum(c["ready_stock"] for c in channels_data),
        "channels_running": sum(1 for c in channels_data if c["status"] == "running"),
        "channels_attention": sum(1 for c in channels_data if c["status"] == "attention"),
        "channels_blocked": sum(1 for c in channels_data if c["status"] == "blocked"),
        "channels_paused": sum(1 for c in channels_data if c["status"] == "paused"),
        "channels_ok": sum(1 for c in channels_data if c["status"] == "ok"),
    }

    return {
        "totals": totals,
        "channels": channels_data,
    }
