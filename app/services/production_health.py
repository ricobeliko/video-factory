"""
Serviço de Health Check e Readiness Check de Produção (Fase V12-A).

Fornece diagnósticos estruturados, estáticos e passivos sobre a saúde operacional
e a prontidão técnica da instalação para execução contínua em ambiente de produção.

PRINCÍPIOS:
- Estritamente passivo e somente leitura (read-only)
- Zero geração de vídeo
- Zero publicação
- Zero chamadas a APIs externas / de rede pagas
- Zero alteração de estado da fábrica (factory_state)
- Zero aquisição ou takeover de instâncias
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import config
from app.services import operator_console, scheduler
from app.utils import utils

HEALTH_STATUS_HEALTHY = "HEALTHY"
HEALTH_STATUS_DEGRADED = "DEGRADED"
HEALTH_STATUS_UNHEALTHY = "UNHEALTHY"

MINIMUM_PYTHON_VERSION = (3, 11)


def get_production_health(
    db_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Avalia e agrega a saúde dos componentes operacionais críticos do backend.

    Retorna status global (HEALTHY, DEGRADED, UNHEALTHY) e detalhes estruturados
    de banco de dados, storage, FFmpeg, scheduler, papel de instância e provedores.
    Operação estritamente passiva e somente leitura.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    overall_status = HEALTH_STATUS_HEALTHY
    degraded_reasons: List[str] = []
    unhealthy_reasons: List[str] = []

    # 1. Verificação Prévia do Banco de Dados SQLite (Evita auto-criação indevida)
    target_db_path = scheduler.get_db_path(db_path)
    db_exists = os.path.isfile(target_db_path)

    db_health: Dict[str, Any] = {
        "status": HEALTH_STATUS_HEALTHY,
        "accessible": False,
        "path": target_db_path,
        "journal_mode": None,
        "tables_count": 0,
        "error": None,
    }

    if not db_exists:
        db_health["status"] = HEALTH_STATUS_UNHEALTHY
        db_health["error"] = "Arquivo do banco SQLite não existe em disco"
        unhealthy_reasons.append("Banco de dados SQLite ausente")
        # Lê apenas estado em memória para evitar criar o arquivo
        with operator_console._instance_state_lock:
            instance_role = operator_console._current_role
        factory_state = operator_console.get_factory_state(db_path=None) if db_path is None else operator_console.FACTORY_STATE_RUNNING
    else:
        try:
            instance_info = operator_console.get_instance_info(db_path=db_path)
            instance_role = instance_info.get("local_role") or operator_console.ROLE_PRIMARY
        except Exception as exc:
            with operator_console._instance_state_lock:
                instance_role = operator_console._current_role
            degraded_reasons.append(f"Falha ao obter role de instância: {exc}")

        try:
            factory_state = operator_console.get_factory_state(db_path=db_path)
        except Exception as exc:
            factory_state = operator_console.FACTORY_STATE_RUNNING
            degraded_reasons.append(f"Falha ao obter factory_state: {exc}")

    if factory_state == operator_console.FACTORY_STATE_PAUSED:
        degraded_reasons.append("Fábrica em estado PAUSED (novas execuções suspensas)")

    if instance_role == operator_console.ROLE_SECONDARY_VIEW_ONLY:
        degraded_reasons.append("Instância operando em modo SECONDARY_VIEW_ONLY (mutações desabilitadas)")

    # 2. Verificação Detalhada do Banco de Dados SQLite se existente
    if db_exists:
        try:
            # Conexão rápida somente leitura para teste de acessibilidade
            conn = sqlite3.connect(f"file:{os.path.abspath(target_db_path)}?mode=ro", uri=True, timeout=5.0)
            try:
                cur = conn.execute("PRAGMA journal_mode;")
                row = cur.fetchone()
                db_health["journal_mode"] = row[0] if row else "unknown"

                cur_t = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
                cnt_row = cur_t.fetchone()
                db_health["tables_count"] = cnt_row[0] if cnt_row else 0
                db_health["accessible"] = True
            finally:
                conn.close()
        except Exception as exc:
            db_health["status"] = HEALTH_STATUS_UNHEALTHY
            db_health["error"] = str(exc)
            unhealthy_reasons.append(f"Banco SQLite inacessível: {exc}")

    # 3. Verificação do Storage Local
    storage_folder = utils.storage_dir()
    storage_health: Dict[str, Any] = {
        "status": HEALTH_STATUS_HEALTHY,
        "writable": False,
        "path": storage_folder,
        "free_bytes": 0,
        "error": None,
    }

    if not os.path.exists(storage_folder):
        try:
            os.makedirs(storage_folder, exist_ok=True)
        except Exception as exc:
            storage_health["status"] = HEALTH_STATUS_UNHEALTHY
            storage_health["error"] = f"Não foi possível criar diretório de storage: {exc}"
            unhealthy_reasons.append("Diretório de storage não existe e não pôde ser criado")

    if os.path.exists(storage_folder):
        try:
            usage = shutil.disk_usage(storage_folder)
            storage_health["free_bytes"] = usage.free

            # Teste atômico de escrita e remoção
            test_file = os.path.join(storage_folder, f".health_check_{os.getpid()}.tmp")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("health_ok")
            if os.path.exists(test_file):
                os.remove(test_file)
            storage_health["writable"] = True
        except Exception as exc:
            storage_health["status"] = HEALTH_STATUS_UNHEALTHY
            storage_health["error"] = str(exc)
            unhealthy_reasons.append(f"Storage não gravável: {exc}")

    # 4. Verificação do FFmpeg
    ffmpeg_bin = utils.get_ffmpeg_binary()
    ffmpeg_ready = utils.check_ffmpeg_ready()
    ffmpeg_health: Dict[str, Any] = {
        "status": HEALTH_STATUS_HEALTHY if ffmpeg_ready else HEALTH_STATUS_UNHEALTHY,
        "available": ffmpeg_ready,
        "path": ffmpeg_bin,
        "error": None if ffmpeg_ready else "Binário FFmpeg não executável ou ausente",
    }
    if not ffmpeg_ready:
        unhealthy_reasons.append("FFmpeg indisponível ou com falha na execução")

    # 5. Verificação do Scheduler
    try:
        sched_settings = scheduler.get_all_settings(db_path=db_path)
        worker_alive = scheduler.is_worker_alive()
        sched_enabled = bool(sched_settings.get("scheduler_enabled"))
        auto_pub = bool(sched_settings.get("auto_publish_enabled"))
        dry_run = bool(sched_settings.get("dry_run"))

        sched_status = HEALTH_STATUS_HEALTHY
        if not sched_enabled:
            sched_status = HEALTH_STATUS_DEGRADED
            degraded_reasons.append("Scheduler desabilitado nas configurações")
        elif not worker_alive and instance_role == operator_console.ROLE_PRIMARY:
            sched_status = HEALTH_STATUS_DEGRADED
            degraded_reasons.append("Thread do scheduler worker inativa na instância primária")

        scheduler_health: Dict[str, Any] = {
            "status": sched_status,
            "worker_alive": worker_alive,
            "scheduler_enabled": sched_enabled,
            "auto_publish_enabled": auto_pub,
            "dry_run": dry_run,
            "interval_seconds": 30,
        }
    except Exception as exc:
        scheduler_health = {
            "status": HEALTH_STATUS_DEGRADED,
            "worker_alive": False,
            "scheduler_enabled": False,
            "auto_publish_enabled": False,
            "dry_run": True,
            "error": str(exc),
        }
        degraded_reasons.append(f"Falha ao inspecionar scheduler: {exc}")

    # 6. Saúde dos Provedores (Passiva, sem chamadas de rede pagas)
    try:
        providers_health = operator_console.get_provider_health_summary(db_path=db_path)
    except Exception as exc:
        providers_health = {"error": str(exc)}
        degraded_reasons.append(f"Falha ao obter sumário de provedores: {exc}")

    # 7. Verificação Passiva de Backup de Produção (Fase V12-C)
    from app.services import production_backup
    try:
        backup_info = production_backup.get_latest_backup_info(backup_dir=backup_dir)
        b_status = backup_info.get("status")

        if b_status == "HEALTHY":
            age_sec = backup_info.get("latest_backup_age_seconds")
            if age_sec is not None and age_sec > 86400:
                backup_health_status = HEALTH_STATUS_DEGRADED
                degraded_reasons.append(f"Último backup do SQLite tem mais de 24 horas ({age_sec // 3600}h atrás)")
            else:
                backup_health_status = HEALTH_STATUS_HEALTHY
        elif b_status == "NONE":
            backup_health_status = HEALTH_STATUS_DEGRADED
            degraded_reasons.append("Nenhum backup do banco SQLite foi encontrado")
        elif b_status == "CORRUPT":
            backup_health_status = HEALTH_STATUS_UNHEALTHY
            unhealthy_reasons.append(f"Último backup do SQLite está corrompido: {backup_info.get('error')}")
        else:
            backup_health_status = HEALTH_STATUS_UNHEALTHY
            unhealthy_reasons.append(f"Falha ao inspecionar backups do SQLite: {backup_info.get('error')}")

        backup_health = {
            "status": backup_health_status,
            "latest_backup_at": backup_info.get("latest_backup_at"),
            "latest_backup_age_seconds": backup_info.get("latest_backup_age_seconds"),
            "valid_backups_count": backup_info.get("valid_backups_count", 0),
            "latest_integrity": backup_info.get("latest_integrity"),
            "path": backup_info.get("path"),
            "backup_dir": backup_info.get("backup_dir"),
            "error": backup_info.get("error"),
        }
    except Exception as exc:
        backup_health = {
            "status": HEALTH_STATUS_DEGRADED,
            "latest_backup_at": None,
            "latest_backup_age_seconds": None,
            "valid_backups_count": 0,
            "latest_integrity": None,
            "path": None,
            "backup_dir": None,
            "error": str(exc),
        }
        degraded_reasons.append(f"Falha ao consultar estado de backups: {exc}")

    # Determinação do Status Global
    if unhealthy_reasons:
        overall_status = HEALTH_STATUS_UNHEALTHY
    elif degraded_reasons:
        overall_status = HEALTH_STATUS_DEGRADED
    else:
        overall_status = HEALTH_STATUS_HEALTHY

    return {
        "status": overall_status,
        "timestamp": now_iso,
        "instance_role": instance_role,
        "factory_state": factory_state,
        "database": db_health,
        "storage": storage_health,
        "ffmpeg": ffmpeg_health,
        "scheduler": scheduler_health,
        "providers": providers_health,
        "backup": backup_health,
        "degraded_reasons": degraded_reasons,
        "unhealthy_reasons": unhealthy_reasons,
    }


def get_production_readiness(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Avalia se o ambiente do host está tecnicamente pronto para operar em produção.

    Verifica runtime Python, ambiente virtual (.venv), integridade do banco SQLite,
    permissões de storage, FFmpeg, configuração e presença de credenciais (apenas PRESENT/MISSING,
    sem expor valores e sem chamadas de rede).
    """
    target_db_path = scheduler.get_db_path(db_path)
    project_root = utils.root_dir()

    missing_critical: List[str] = []
    warnings: List[str] = []

    # 1. Runtime Python (>= 3.11)
    py_ver = sys.version_info
    py_ok = (py_ver.major == MINIMUM_PYTHON_VERSION[0] and py_ver.minor >= MINIMUM_PYTHON_VERSION[1])
    py_check = {
        "version": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        "required": f">={MINIMUM_PYTHON_VERSION[0]}.{MINIMUM_PYTHON_VERSION[1]}",
        "passed": py_ok,
    }
    if not py_ok:
        missing_critical.append("Python runtime < 3.11")

    # 2. Virtualenv (.venv)
    venv_dir = os.path.join(project_root, ".venv")
    venv_py = os.path.join(venv_dir, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_dir, "bin", "python")
    venv_exists = os.path.isdir(venv_dir) and os.path.isfile(venv_py)
    venv_check = {
        "path": venv_dir,
        "executable": venv_py,
        "passed": venv_exists,
    }
    if not venv_exists:
        warnings.append("Virtualenv '.venv' não detectado ou binário ausente")

    # 3. Banco de Dados SQLite
    db_exists = os.path.isfile(target_db_path)
    db_initialized = False
    if db_exists:
        try:
            with scheduler.get_connection(db_path) as conn:
                cur = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
                cnt = cur.fetchone()[0]
                db_initialized = cnt >= 5
        except Exception:
            db_initialized = False

    db_check = {
        "path": target_db_path,
        "exists": db_exists,
        "initialized": db_initialized,
        "passed": db_exists and db_initialized,
    }
    if not (db_exists and db_initialized):
        missing_critical.append("Banco de dados SQLite ausente ou não inicializado")

    # 4. Storage Writable
    storage_folder = utils.storage_dir()
    storage_writable = False
    if os.path.exists(storage_folder):
        try:
            test_f = os.path.join(storage_folder, f".readiness_test_{os.getpid()}.tmp")
            with open(test_f, "w", encoding="utf-8") as f:
                f.write("readiness")
            if os.path.exists(test_f):
                os.remove(test_f)
            storage_writable = True
        except Exception:
            storage_writable = False

    storage_check = {
        "path": storage_folder,
        "writable": storage_writable,
        "passed": storage_writable,
    }
    if not storage_writable:
        missing_critical.append("Diretório de storage não gravável")

    # 5. FFmpeg
    ffmpeg_ready = utils.check_ffmpeg_ready()
    ffmpeg_check = {
        "binary": utils.get_ffmpeg_binary(),
        "passed": ffmpeg_ready,
    }
    if not ffmpeg_ready:
        missing_critical.append("FFmpeg ausente ou inoperante")

    # 6. Configuração (config.toml)
    config_file_path = os.path.join(project_root, "config.toml")
    config_exists = os.path.isfile(config_file_path)
    config_check = {
        "path": config_file_path,
        "exists": config_exists,
        "passed": config_exists,
    }
    if not config_exists:
        warnings.append("config.toml não encontrado na raiz (usando defaults)")

    # 7. Single Instance Lock Queryable
    lock_queryable = False
    try:
        with operator_console.get_connection(db_path) as conn:
            cur = conn.execute("SELECT count(*) FROM sqlite_master WHERE name='instance_locks';")
            if cur.fetchone()[0] > 0:
                lock_queryable = True
    except Exception:
        lock_queryable = False

    single_instance_check = {
        "table": "instance_locks",
        "lock_key": operator_console.DEFAULT_INSTANCE_LOCK_KEY,
        "passed": lock_queryable,
    }
    if not lock_queryable:
        missing_critical.append("Infraestrutura de single-instance (instance_locks) inacessível")

    # 8. Scheduler Infra
    sched_tables_ready = False
    try:
        with scheduler.get_connection(db_path) as conn:
            cur = conn.execute("SELECT count(*) FROM sqlite_master WHERE name='scheduled_posts';")
            if cur.fetchone()[0] > 0:
                sched_tables_ready = True
    except Exception:
        sched_tables_ready = False

    scheduler_infra_check = {
        "table": "scheduled_posts",
        "passed": sched_tables_ready,
    }
    if not sched_tables_ready:
        missing_critical.append("Tabelas do scheduler não inicializadas")

    # 9. Verificação Passiva de Presença de Credenciais (Apenas PRESENT / MISSING, zero segredos expostos)
    def _check_secret_presence(val: Any) -> str:
        if isinstance(val, (list, tuple)):
            return "PRESENT" if any(bool(v) for v in val) else "MISSING"
        return "PRESENT" if bool(val and str(val).strip()) else "MISSING"

    credentials_status = {
        "gemini_api_key": _check_secret_presence(config.app.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")),
        "pexels_api_key": _check_secret_presence(config.app.get("pexels_api_key") or config.app.get("pexels_api_keys") or os.environ.get("PEXELS_API_KEY")),
        "upload_post_token": _check_secret_presence(config.app.get("upload_post_token") or os.environ.get("UPLOAD_POST_TOKEN")),
        "youtube_credentials": _check_secret_presence(config.app.get("youtube_client_secret") or os.path.exists(os.path.join(storage_folder, "youtube_token.json"))),
        "tiktok_credentials": _check_secret_presence(config.app.get("tiktok_access_token") or os.path.exists(os.path.join(storage_folder, "tiktok_token.json"))),
    }

    # 10. Verificação Passiva de Backup para Readiness (Apenas warning, nunca bloqueia boot)
    from app.services import production_backup
    try:
        b_info = production_backup.get_latest_backup_info()
        b_stat = b_info.get("status")
        if b_stat in ("NONE", "CORRUPT"):
            warnings.append("Nenhum backup válido de banco SQLite encontrado (recomendado gerar backup inicial)")
    except Exception:
        b_info = {"status": "UNKNOWN"}

    # Avaliação final
    is_ready = (len(missing_critical) == 0)

    return {
        "ready": is_ready,
        "status": "READY" if is_ready else "NOT_READY",
        "checks": {
            "python_runtime": py_check,
            "venv": venv_check,
            "database": db_check,
            "storage": storage_check,
            "ffmpeg": ffmpeg_check,
            "config": config_check,
            "single_instance": single_instance_check,
            "scheduler_infra": scheduler_infra_check,
            "credentials": credentials_status,
            "backup": {"status": b_info.get("status", "UNKNOWN"), "passed": True},
        },
        "missing_critical_requirements": missing_critical,
        "warnings": warnings,
    }


def main():
    """Ponto de entrada CLI para diagnóstico operacional e sanitizado da instalação."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo - Production Health & Readiness")
    parser.add_argument("--json", action="store_true", help="Formatar saída estritamente em JSON")
    parser.add_argument("--readiness", action="store_true", help="Executar apenas readiness check")
    parser.add_argument("--health", action="store_true", help="Executar apenas health check")
    args = parser.parse_args()

    health = get_production_health()
    readiness = get_production_readiness()

    if args.json:
        if args.health:
            print(json.dumps(health, indent=2))
        elif args.readiness:
            print(json.dumps(readiness, indent=2))
        else:
            print(json.dumps({"health": health, "readiness": readiness}, indent=2))
        sys.exit(0 if health["status"] != HEALTH_STATUS_UNHEALTHY else 1)

    print("======================================================")
    print(" MoneyPrinterTurbo - Diagnóstico Operacional (V12-C)")
    print("======================================================")
    print(f"Health Global     : {health['status']}")
    print(f"Readiness         : {readiness['status']} (Pronto: {readiness['ready']})")
    print(f"Factory State     : {health['factory_state']}")
    print(f"Instance Role     : {health['instance_role']}")
    print("------------------------------------------------------")
    print(f"Banco SQLite      : {health['database']['path']}")
    print(f"Journal Mode      : {health['database']['journal_mode']}")
    print(f"Storage Writable  : {health['storage']['writable']} (Livre: {health['storage']['free_bytes'] / (1024**3):.2f} GB)")
    print(f"FFmpeg            : {'OK' if health['ffmpeg']['available'] else 'FALHA'}")
    s = health['scheduler']
    print(f"Scheduler         : Enabled={s.get('scheduler_enabled')}, WorkerAlive={s.get('worker_alive')}, AutoPublish={s.get('auto_publish_enabled')}, DryRun={s.get('dry_run')}")
    print("------------------------------------------------------")
    b = health.get("backup", {})
    b_age_str = f"{b['latest_backup_age_seconds'] // 3600}h atrás" if b.get('latest_backup_age_seconds') is not None else "N/A"
    print(f"Backup Status     : {b.get('status')} (Válidos: {b.get('valid_backups_count', 0)}, Último: {b.get('latest_backup_at') or 'Nenhum'} - {b_age_str})")
    print("------------------------------------------------------")
    print("Credenciais (Presença Sanitizada):")
    for cred, c_status in readiness['checks']['credentials'].items():
        print(f"  - {cred:<22}: {c_status}")

    if health.get("degraded_reasons"):
        print("------------------------------------------------------")
        print("Avisos / Motivos de Degradação:")
        for r in health["degraded_reasons"]:
            print(f"  [!] {r}")

    if health.get("unhealthy_reasons"):
        print("------------------------------------------------------")
        print("Problemas Críticos (UNHEALTHY):")
        for r in health["unhealthy_reasons"]:
            print(f"  [X] {r}")

    sys.exit(0 if health["status"] != HEALTH_STATUS_UNHEALTHY else 1)


if __name__ == "__main__":
    main()
