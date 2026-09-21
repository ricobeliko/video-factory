"""
Production Entrypoint — V12-F.1B (Headless Worker Bootstrap).

Garante que, ao iniciar a Scheduled Task "VideoFactory Production", o PRIMARY
guard e o SchedulerExecutionWorker sejam inicializados no MESMO processo que
hospedará o servidor Streamlit — antes de qualquer sessão de navegador se
conectar. O navegador passa a ser somente UI; nunca é responsável por
inicializar o worker.

Fluxo:
    production_entrypoint.py
    -> operator_console.ensure_instance_initialized()
    -> se PRIMARY: scheduler.start_scheduler_worker(interval_seconds=30)
    -> streamlit.web.bootstrap.run(...) no MESMO processo/interpretador
    -> ao encerrar (sinal, exceção ou saída normal): worker/lock liberados

Fail-closed: qualquer erro crítico ao inicializar PRIMARY/worker aborta o
processo com código de saída != 0 e NÃO inicia o servidor Streamlit.

Não altera regras de Single PRIMARY, Safety Gate, Quality Gate, Growth Mode
ou Analytics. Não inicia um segundo worker nem uma segunda instância.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger  # noqa: E402

DEFAULT_WORKER_INTERVAL_SECONDS = 30
MAIN_SCRIPT_PATH = str(PROJECT_ROOT / "webui" / "Main.py")


def _to_bool(value: Any) -> bool:
    """Converte valores de flag CLI (string/bool) em bool estrito."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Faz o parsing dos mesmos parâmetros operacionais hoje usados pelo start_production.ps1."""
    parser = argparse.ArgumentParser(description="Video Factory production entrypoint")
    parser.add_argument("--server.address", dest="server_address", default="0.0.0.0")
    parser.add_argument("--server.port", dest="server_port", type=int, default=8501)
    parser.add_argument("--server.headless", dest="server_headless", default="true")
    parser.add_argument("--browser.gatherUsageStats", dest="browser_gatherUsageStats", default="false")
    parser.add_argument("--client.toolbarMode", dest="client_toolbarMode", default="minimal")
    parser.add_argument("--logger.hideWelcomeMessage", dest="logger_hideWelcomeMessage", default="true")
    parser.add_argument("--server.showEmailPrompt", dest="server_showEmailPrompt", default="false")
    parser.add_argument("--server.enableCORS", dest="server_enableCORS", default="true")
    return parser.parse_args(list(sys.argv[1:] if argv is None else argv))


def build_flag_options(args: argparse.Namespace) -> Dict[str, Any]:
    """Traduz os argumentos parseados para o dict de flag_options do Streamlit
    (mesma convenção usada por `streamlit run`: chave da config com '.' -> '_')."""
    return {
        "server_address": args.server_address,
        "server_port": args.server_port,
        "server_headless": _to_bool(args.server_headless),
        "browser_gatherUsageStats": _to_bool(args.browser_gatherUsageStats),
        "client_toolbarMode": args.client_toolbarMode,
        "logger_hideWelcomeMessage": _to_bool(args.logger_hideWelcomeMessage),
        "server_showEmailPrompt": _to_bool(args.server_showEmailPrompt),
        "server_enableCORS": _to_bool(args.server_enableCORS),
    }


def bootstrap_primary_and_worker(worker_interval_seconds: int = DEFAULT_WORKER_INTERVAL_SECONDS) -> bool:
    """
    Inicializa o PRIMARY guard e o SchedulerExecutionWorker antes do servidor
    Streamlit subir, reutilizando exatamente o mesmo mecanismo de Single PRIMARY
    já usado pela UI (`operator_console.ensure_instance_initialized`).

    Retorna True se esta instância é PRIMARY (worker iniciado/confirmado vivo).
    Retorna False se é SECONDARY_VIEW_ONLY (worker corretamente NÃO iniciado).
    Levanta RuntimeError se o worker não confirmar atividade após o bootstrap.
    """
    from app.services import operator_console, scheduler

    role, info = operator_console.ensure_instance_initialized()

    if role != operator_console.ROLE_PRIMARY:
        logger.info(
            "[PRODUCTION_ENTRYPOINT] Instância iniciada em modo SECONDARY_VIEW_ONLY "
            f"(PRIMARY ativo: {info.get('node_name')} / pid {info.get('pid')}). "
            "Worker intencionalmente não iniciado."
        )
        return False

    scheduler.start_scheduler_worker(interval_seconds=worker_interval_seconds)
    if not scheduler.is_worker_alive():
        raise RuntimeError(
            "SchedulerExecutionWorker não confirmou atividade após bootstrap PRIMARY."
        )

    logger.info(
        "[PRODUCTION_ENTRYPOINT] PRIMARY confirmado e SchedulerExecutionWorker ativo, "
        "sem depender de navegador ou sessão Streamlit."
    )
    return True


def shutdown_worker_and_lock() -> None:
    """Encerramento limpo: para o worker e libera o lock de instância.

    Idempotente e seguro mesmo se chamado após um shutdown parcial (ex.: via
    atexit) ou em uma instância SECONDARY (nesse caso é um no-op efetivo).
    """
    from app.services import operator_console, scheduler

    try:
        scheduler.stop_scheduler_worker()
    except Exception:
        logger.exception("[PRODUCTION_ENTRYPOINT] Erro ao parar o worker durante o encerramento.")
    try:
        operator_console.release_instance_lock()
    except Exception:
        logger.exception("[PRODUCTION_ENTRYPOINT] Erro ao liberar o instance lock durante o encerramento.")


def run_streamlit_server(flag_options: Dict[str, Any], main_script_path: str = MAIN_SCRIPT_PATH) -> None:
    """Inicia o servidor Streamlit no MESMO processo/interpretador (bloqueante).

    Usa apenas as duas funções públicas do módulo oficial `streamlit.web.bootstrap`
    (as mesmas usadas internamente por `streamlit run`), evitando subprocess e
    evitando depender de APIs privadas menos estáveis (ex.: `cli._main_run`).
    """
    from streamlit.web import bootstrap as st_bootstrap

    st_bootstrap.load_config_options(flag_options=flag_options)
    st_bootstrap.run(main_script_path, False, [], flag_options)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        bootstrap_primary_and_worker()
    except Exception:
        logger.exception(
            "[PRODUCTION_ENTRYPOINT] Falha crítica ao inicializar PRIMARY/worker. "
            "Abortando antes de iniciar o Streamlit (fail-closed)."
        )
        return 1

    flag_options = build_flag_options(args)
    try:
        run_streamlit_server(flag_options)
    finally:
        shutdown_worker_and_lock()
        logger.info("[PRODUCTION_ENTRYPOINT] Streamlit encerrado; worker/lock liberados de forma limpa.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
