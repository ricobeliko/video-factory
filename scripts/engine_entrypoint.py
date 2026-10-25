"""
Engine Entrypoint — V2 Unified Engine Server (Motor sem Streamlit).

Hospeda o servidor FastAPI/Uvicorn (app.asgi:app) juntamente com o
SchedulerExecutionWorker e o Watchdog no MESMO processo de produção,
substituindo o Streamlit legado.

Ordem de Inicialização (Fail-Closed):
1. Logging e inicialização de ambiente;
2. operator_console.ensure_instance_initialized(): se não for PRIMARY, aborta
   (exit code != 0) sem abrir porta de rede;
3. task.recover_interrupted_cross_posts(): recupera/finaliza uploads interrompidos;
4. operator_console.reconcile_orphaned_tasks(): reconcilia tarefas órfãs pós-restart/queda;
5. scheduler.start_scheduler_worker(interval_seconds=30) e confirmação de
   is_worker_alive() (salvo se --no-worker);
6. Watchdog em thread daemon a cada 30s conferindo se o worker está vivo e reiniciando
   se estiver inativo (salvo se --no-worker);
7. uvicorn.run(app.asgi:app) em --host (default 0.0.0.0) e --port (default 8080).

Encerramento Limpo:
- Parada do watchdog;
- Parada do worker (scheduler.stop_scheduler_worker());
- Liberação do lock de instância (operator_console.release_instance_lock());
- Idempotente via atexit e bloco finally.
"""
from __future__ import annotations

import argparse
import atexit
import sys
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger  # noqa: E402

from scripts.production_entrypoint import (  # noqa: E402
    DEFAULT_WORKER_INTERVAL_SECONDS,
    bootstrap_primary_and_worker,
    shutdown_worker_and_lock,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_WATCHDOG_INTERVAL_SECONDS = 30

_shutdown_lock = threading.Lock()
_shutdown_completed = False


class SchedulerWatchdog(threading.Thread):
    """Thread daemon que monitora o SchedulerExecutionWorker a cada 30 segundos.

    Substitui a rede de segurança que o Streamlit realizava em Main.py. Se o worker
    estiver inativo, reinicia o worker automaticamente e emite log de aviso.
    """

    def __init__(self, interval_seconds: int = DEFAULT_WATCHDOG_INTERVAL_SECONDS):
        super().__init__(name="SchedulerWatchdog", daemon=True)
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Sinaliza para a thread de watchdog parar imediatamente."""
        self._stop_event.set()

    def run(self) -> None:
        logger.info(
            f"[ENGINE_WATCHDOG] Watchdog do scheduler ativo (intervalo: {self.interval_seconds}s, daemon=True)."
        )
        while not self._stop_event.wait(self.interval_seconds):
            try:
                from app.services import scheduler

                if not scheduler.is_worker_alive():
                    logger.warning(
                        "[ENGINE_WATCHDOG] SchedulerExecutionWorker detectado inativo! "
                        "Reiniciando worker..."
                    )
                    scheduler.start_scheduler_worker(interval_seconds=self.interval_seconds)
            except Exception as exc:
                logger.warning(f"[ENGINE_WATCHDOG] Erro ao monitorar ou reiniciar worker: {exc}")
        logger.info("[ENGINE_WATCHDOG] Watchdog do scheduler finalizado.")


def bootstrap_engine(
    worker_interval_seconds: int = DEFAULT_WORKER_INTERVAL_SECONDS,
    enable_worker: bool = True,
    node_name: str = "ProductionEngine",
) -> Tuple[bool, Optional[SchedulerWatchdog]]:
    """Executa a sequência de boot determinística e fail-closed do Motor V2.

    Ordem de Boot:
    1) operator_console.ensure_instance_initialized(): Adquire lock PRIMARY exclusivo;
    2) task.recover_interrupted_cross_posts(): Desbloqueia tarefas de publicação interrompidas;
    3) operator_console.reconcile_orphaned_tasks(): Resgata tarefas órfãs de crashes/quedas;
    4) scheduler.start_scheduler_worker(): Inicia worker e valida is_worker_alive() (se enable_worker);
    5) Inicialização da thread daemon de watchdog (se enable_worker).

    Retorna (True, watchdog) se PRIMARY.
    Retorna (False, None) se SECONDARY (sem iniciar worker nem abrir porta).
    Levanta RuntimeError se o worker falhar em confirmar atividade.
    """
    from app.services import operator_console, scheduler, task

    logger.info("[ENGINE_BOOT] 1/5: Verificando papel de instância (Single PRIMARY Guard)...")
    role, info = operator_console.ensure_instance_initialized(node_name=node_name)

    if role != operator_console.ROLE_PRIMARY:
        logger.error(
            f"[ENGINE_BOOT] Instância operando como SECONDARY_VIEW_ONLY "
            f"(PRIMARY ativo: {info.get('node_name')} / pid {info.get('pid')}). "
            "Abortando inicialização do motor (fail-closed, porta de rede não será aberta)."
        )
        return False, None

    logger.info("[ENGINE_BOOT] Papel PRIMARY confirmado com sucesso.")

    logger.info("[ENGINE_BOOT] 2/5: Recuperando publicações interrompidas (cross posts)...")
    try:
        task.recover_interrupted_cross_posts()
    except Exception as exc:
        logger.warning(f"[ENGINE_BOOT] Erro na recuperação de cross-posts: {exc}")

    logger.info("[ENGINE_BOOT] 3/5: Reconciliando tarefas órfãs pós-restart...")
    try:
        operator_console.reconcile_orphaned_tasks()
    except Exception as exc:
        logger.warning(f"[ENGINE_BOOT] Erro na reconciliação pós-restart: {exc}")

    watchdog = None
    if enable_worker:
        logger.info(
            f"[ENGINE_BOOT] 4/5: Inicializando SchedulerExecutionWorker (intervalo: {worker_interval_seconds}s)..."
        )
        scheduler.start_scheduler_worker(interval_seconds=worker_interval_seconds)
        if not scheduler.is_worker_alive():
            logger.error("[ENGINE_BOOT] SchedulerExecutionWorker não confirmou atividade após inicialização.")
            raise RuntimeError(
                "SchedulerExecutionWorker não confirmou atividade após bootstrap PRIMARY."
            )
        logger.info("[ENGINE_BOOT] SchedulerExecutionWorker ativo e confirmado vivo.")

        logger.info(
            f"[ENGINE_BOOT] 5/5: Iniciando thread daemon de Watchdog (intervalo: {worker_interval_seconds}s)..."
        )
        watchdog = SchedulerWatchdog(interval_seconds=worker_interval_seconds)
        watchdog.start()
    else:
        logger.info(
            "[ENGINE_BOOT] 4/5 & 5/5: Flag --no-worker ativa. SchedulerExecutionWorker e Watchdog NÃO serão iniciados."
        )

    return True, watchdog


def clean_shutdown(watchdog: Optional[SchedulerWatchdog] = None) -> None:
    """Encerramento limpo e idempotente do motor.

    Para o watchdog, encerra o worker do scheduler e libera o lock de instância.
    Seguro para múltiplas chamadas (ex.: via finally e via atexit).
    """
    global _shutdown_completed
    with _shutdown_lock:
        if _shutdown_completed:
            return
        _shutdown_completed = True

        logger.info("[ENGINE_SHUTDOWN] Executando encerramento limpo do motor...")

        if watchdog is not None:
            try:
                watchdog.stop()
            except Exception as exc:
                logger.warning(f"[ENGINE_SHUTDOWN] Erro ao parar watchdog: {exc}")

        try:
            shutdown_worker_and_lock()
        except Exception as exc:
            logger.exception(f"[ENGINE_SHUTDOWN] Erro durante shutdown_worker_and_lock: {exc}")

        logger.info("[ENGINE_SHUTDOWN] Encerramento limpo concluído com sucesso.")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Faz o parsing dos parâmetros de linha de comando do Motor V2."""
    parser = argparse.ArgumentParser(description="Video Factory V2 Unified Engine Server")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Endereço de bind do servidor HTTP (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Porta TCP de escuta do servidor HTTP (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-worker",
        action="store_true",
        dest="no_worker",
        default=False,
        help="Inicia apenas o servidor web FastAPI/Uvicorn, sem worker do scheduler e sem watchdog",
    )

    # Suporte a argumentos legados se passados por scripts externos
    parser.add_argument("--server.address", dest="legacy_address", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--server.port", dest="legacy_port", type=int, default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.legacy_address:
        args.host = args.legacy_address
    if args.legacy_port:
        args.port = args.legacy_port
    return args


def run_engine_server(host: str, port: int, asgi_app: Any = None) -> None:
    """Executa o servidor Uvicorn hospedando o ASGI app."""
    import uvicorn

    if asgi_app is None:
        from app.asgi import app as asgi_app

    logger.info(f"[ENGINE_ENTRYPOINT] Iniciando servidor Uvicorn em http://{host}:{port}...")
    uvicorn.run(asgi_app, host=host, port=port, log_level="info")


def main(argv: Optional[List[str]] = None) -> int:
    """Ponto de entrada principal do processo Motor V2."""
    global _shutdown_completed
    _shutdown_completed = False

    args = parse_args(argv)
    watchdog: Optional[SchedulerWatchdog] = None

    try:
        is_primary, watchdog = bootstrap_engine(
            worker_interval_seconds=DEFAULT_WORKER_INTERVAL_SECONDS,
            enable_worker=not args.no_worker,
        )
        if not is_primary:
            return 1

        # Registra callback de saída limpa idempotente
        atexit.register(clean_shutdown, watchdog)

        run_engine_server(host=args.host, port=args.port)
    except Exception as exc:
        logger.exception(f"[ENGINE_ENTRYPOINT] Falha crítica durante execução do motor: {exc}")
        return 1
    finally:
        clean_shutdown(watchdog)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
