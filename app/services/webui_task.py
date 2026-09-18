import threading
from collections import deque

from loguru import logger

from app.config import config
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.models import const
from app.models.schema import VideoParams
from app.services import state as sm
from app.services import task as tm
from app.services.loomloom import LoomLoomConfirmedVideoRequest
from app.utils.logging_utils import format_log_record


# WebUI 的配置保存在进程级全局字典中。原来的同步实现会在完整生成期间持有
# runtime_config_lock，因此不同浏览器会话实际上也是串行执行。这里把并发数固定
# 为 1，既延续原有配置一致性，也避免多个线程只是在配置锁外无意义地等待。
_task_manager = InMemoryTaskManager(
    max_concurrent_tasks=1,
    max_queued_tasks=max(1, int(config.app.get("max_queued_tasks", 100))),
)
_task_logs: dict[str, deque[str]] = {}
_task_logs_lock = threading.RLock()
_active_task_ids: list[str] = []
_active_task_ids_lock = threading.RLock()
_MAX_LOG_TASKS = 20
_MAX_LOG_RECORDS_PER_TASK = 1000
# Streamlit 无法由后台线程直接推送组件更新，只能通过 Fragment 轮询。0.5 秒
# 足以让 WebUI 日志接近终端实时输出，又不会像高频刷新那样持续占用浏览器资源。
TASK_LOG_REFRESH_INTERVAL_SECONDS = 0.5


def _append_task_log(task_id: str, message: str) -> None:
    """按任务保存有限数量的日志，供 Streamlit Fragment 安全轮询。"""
    with _task_logs_lock:
        records = _task_logs.get(task_id)
        if records is None:
            # 只保留最近任务的日志，避免 WebUI 服务长时间运行后持续占用内存。
            # dict 保持插入顺序；任务日志仅用于界面诊断，淘汰最早记录不影响任务。
            if len(_task_logs) >= _MAX_LOG_TASKS:
                oldest_task_id = next(iter(_task_logs))
                _task_logs.pop(oldest_task_id, None)
            records = deque(maxlen=_MAX_LOG_RECORDS_PER_TASK)
            _task_logs[task_id] = records
        records.append(message.rstrip())


def get_task_logs(task_id: str) -> list[str]:
    """返回日志快照，避免页面渲染期间持有后台线程使用的锁。"""
    with _task_logs_lock:
        return list(_task_logs.get(task_id, ()))


def _run_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
) -> dict:
    """
    在后台线程中执行现有视频流水线。

    Loguru 的 sink 是进程级资源，因此必须按当前工作线程过滤。否则同时运行的
    API 任务或其它页面日志会混入当前任务。页面只读取普通列表快照，不会从后台
    线程访问 Streamlit session_state，从根源上避免刷新时的 delta 路径错乱。
    """
    log_handler_id = None
    worker_thread_id = threading.get_ident()
    from app.services import operator_console
    operator_console.record_generation_heartbeat()
    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=0,
    )
    try:
        if capture_logs:
            log_handler_id = logger.add(
                lambda message: _append_task_log(task_id, str(message)),
                level="DEBUG",
                format=format_log_record,
                colorize=False,
                filter=lambda record: record["thread"].id == worker_thread_id,
            )

        # 完整任务仍使用原来的配置锁，防止另一个 WebUI 会话在生成中途修改
        # Provider、密钥等进程级配置，造成同一条视频前后使用不同设置。
        with config.runtime_config_lock():
            operator_console.record_generation_heartbeat()
            return tm.start(
                task_id=task_id,
                params=params,
                voice_preview=voice_preview,
                loomloom_video_request=loomloom_video_request,
            )
    except Exception as exc:
        # tm.start 已负责把流水线异常转换成失败状态；这里额外保护日志 sink、
        # 配置锁等 WebUI 包装层。任何后台线程异常都必须留下终态，不能让任务
        # 管理器在工作线程退出后仍永久显示“生成中”。
        error = f"{type(exc).__name__}: {exc}"
        failure = {
            "task_id": task_id,
            "state": const.TASK_STATE_FAILED,
            "progress": 0,
            "failed_stage": "webui_worker",
            "error": error,
        }
        sm.state.update_task(
            task_id,
            state=failure["state"],
            progress=failure["progress"],
            failed_stage=failure["failed_stage"],
            error=failure["error"],
        )
        logger.exception(
            f"unexpected WebUI generation worker failure, "
            f"task_id={task_id}, error={exc}"
        )
        return failure
    finally:
        with _active_task_ids_lock:
            if task_id in _active_task_ids:
                _active_task_ids.remove(task_id)
        if log_handler_id is not None:
            try:
                logger.remove(log_handler_id)
            except ValueError:
                logger.debug(
                    f"WebUI task log handler already removed: task_id={task_id}"
                )


def submit_generation(
    task_id: str,
    params: VideoParams,
    capture_logs: bool = True,
    voice_preview: dict | None = None,
    loomloom_video_request: LoomLoomConfirmedVideoRequest | None = None,
    profile_id: str | None = None,
) -> None:
    """
    登记并提交 WebUI 视频生成任务，调用后立即返回。

    任务状态必须在线程启动前写入。这样页面本次脚本执行结束时即可查询到任务，
    浏览器刷新或 WebSocket 重连也不依赖旧页面内存中的占位符。
    """
    task_params = params.model_copy(deep=True)
    from app.services import operator_console, profile_manager
    operator_console.require_primary_instance()
    if operator_console.is_factory_paused():
        logger.warning(f"Rejeitando geração: fábrica pausada. task_id={task_id}")
        raise ValueError("Fábrica pausada. A tarefa atual pode concluir; novas execuções estão bloqueadas.")

    # Resolução do Perfil Operacional e Hierarquia:
    # manual override > profile value > fallback atual
    assigned_profile_id = (
        profile_id
        or getattr(task_params, "profile_id", None)
        or profile_manager.get_active_profile_id()
    )
    task_params.profile_id = assigned_profile_id
    ctx = profile_manager.get_generation_profile_context(profile_id=assigned_profile_id)

    explicit_fields = (
        params.model_fields_set
        if hasattr(params, "model_fields_set")
        else getattr(params, "__fields_set__", set())
    )

    # 1. Niche
    if "niche" not in explicit_fields or not getattr(task_params, "niche", None):
        task_params.niche = ctx.get("niche")

    # 2. Language
    if "video_language" not in explicit_fields or not task_params.video_language:
        task_params.video_language = ctx.get("language")

    # 3. Region
    if "region" not in explicit_fields or not getattr(task_params, "region", None):
        task_params.region = ctx.get("region")

    # 4. Monetization Preset
    if "monetization_preset" not in explicit_fields or not task_params.monetization_preset:
        task_params.monetization_preset = ctx.get("default_preset")

    # Persistência imutável da associação task <-> profile
    profile_manager.save_task_profile(task_id, assigned_profile_id)

    # 预览载荷只包含不可变音频路径、参数快照和只读字幕时间轴。复制外层字典，
    # 避免页面后续 rerun 替换缓存字段时影响已经提交到后台队列的任务。
    voice_preview_snapshot = dict(voice_preview) if voice_preview else None
    # 已确认请求是冻结的数据对象，只在当前进程内传递。API Key 不会进入
    # VideoParams、任务状态、日志或落盘历史，也不会受后续页面 rerun 影响。
    loomloom_request_snapshot = loomloom_video_request
    is_queued = _task_manager.has_active_tasks()
    initial_state = (
        const.TASK_STATE_PENDING if is_queued else const.TASK_STATE_PROCESSING
    )
    sm.state.update_task(
        task_id,
        state=initial_state,
        progress=0,
        video_subject=task_params.video_subject or task_params.video_script or task_id,
        profile_id=assigned_profile_id,
        niche=task_params.niche,
    )

    with _active_task_ids_lock:
        if task_id not in _active_task_ids:
            _active_task_ids.append(task_id)
    try:
        _task_manager.add_task(
            _run_generation,
            task_id=task_id,
            params=task_params,
            capture_logs=capture_logs,
            voice_preview=voice_preview_snapshot,
            loomloom_video_request=loomloom_request_snapshot,
        )
    except Exception as exc:
        with _active_task_ids_lock:
            if task_id in _active_task_ids:
                _active_task_ids.remove(task_id)
        # 调度失败与流水线失败一样必须成为可查询状态，避免任务管理器永久显示
        # “生成中”。保留异常类型便于从 Docker 或本机日志快速定位队列问题。
        error = f"{type(exc).__name__}: {exc}"
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_FAILED,
            progress=0,
            failed_stage="scheduling",
            error=error,
        )
        logger.exception(
            f"failed to submit WebUI generation task, task_id={task_id}, error={exc}"
        )
        raise


def get_active_task_ids() -> list[str]:
    """Return a snapshot of all currently running and queued generation task IDs."""
    with _active_task_ids_lock:
        return list(_active_task_ids)


def has_active_generation_tasks() -> bool:
    """Check if any video generation task is currently running or queued in the task manager."""
    return _task_manager.has_active_tasks()


has_active_tasks = has_active_generation_tasks


def cancel_generation(task_id: str) -> bool:
    """Solicita cancelamento seguro de uma tarefa de geração em andamento ou na fila."""
    from app.services import operator_console
    operator_console.require_primary_instance()
    with _active_task_ids_lock:

        if task_id in _active_task_ids:
            # Se a tarefa ainda não começou a rodar (PENDING), remove dos ativos
            task_info = sm.state.get_task(task_id)
            if task_info and task_info.get("state") == const.TASK_STATE_PENDING:
                _active_task_ids.remove(task_id)
    return operator_console.request_task_cancel(task_id)


def parse_batch_topics(
    raw_text: str, max_limit: int = 10
) -> tuple[list[str], int, str | None]:
    """
    Parse multiline text into a list of clean, unique topics.

    Returns:
        (unique_topics, duplicates_count, error_code)
        error_code can be "empty", "limit_exceeded", or None.
    """
    if not raw_text or not raw_text.strip():
        return [], 0, "empty"

    lines = raw_text.splitlines()
    unique_topics = []
    seen = set()
    duplicates_count = 0

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            duplicates_count += 1
        else:
            seen.add(cleaned)
            unique_topics.append(cleaned)

    if not unique_topics:
        return [], 0, "empty"

    if len(unique_topics) > max_limit:
        return unique_topics, duplicates_count, "limit_exceeded"

    return unique_topics, duplicates_count, None
