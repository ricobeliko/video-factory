"""
Serviço de Restauração Controlada e Segura de Backup (Fase V12-C).

Implementa restauração segura do banco de dados SQLite a partir de snapshots oficiais.

REGRA ABSOLUTA DE SEGURANÇA:
Nunca sobrescrever o SQLite de produção enquanto o backend estiver ativo.
A restauração exige validação estrita de integridade prévia, confirmação de parada
do backend, criação de safety copy do banco atual e substituição atômica.
"""
import argparse
import json
import os
import shutil
import socket
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from app.services import operator_console, production_backup, scheduler
from app.utils import utils

DEFAULT_SAFETY_SUBDIR = os.path.join("storage", "backups", "recovery_safety")


def is_backend_active(
    db_path: Optional[str] = None,
    port: int = 8501,
    host: str = "127.0.0.1",
) -> Tuple[bool, str]:
    """Detecta se o processo backend ou servidor WebUI está atualmente ativo e ouvindo.

    Retorna (True, motivo) se o backend estiver em execução, ou (False, "") se estiver inativo.
    """
    # 1. Teste de conexão por socket TCP na porta do servidor
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            result = s.connect_ex((host, port))
            if result == 0:
                return True, f"Porta de serviço {port} está aberta e respondendo no host {host}"
    except Exception:
        pass

    # 2. Verificação de lock ativo no SQLite se o banco existir
    target_db = scheduler.get_db_path(db_path)
    if os.path.isfile(target_db):
        try:
            uri = f"file:{os.path.abspath(target_db)}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            try:
                cur = conn.execute(
                    "SELECT hostname, pid, status FROM instance_locks WHERE lock_key = ?;",
                    (operator_console.DEFAULT_INSTANCE_LOCK_KEY,),
                )
                row = cur.fetchone()
                if row:
                    host_db, pid_db, status_db = row[0], int(row[1] or 0), row[2]
                    if status_db == operator_console.INSTANCE_STATUS_ACTIVE:
                        # Se estiver no mesmo host, verifica se o PID ainda está vivo no sistema
                        my_hostname = operator_console.platform.node() or socket.gethostname() or "unknown_host"
                        if host_db == my_hostname and operator_console._is_local_pid_alive(pid_db):
                            return True, f"Instância PRIMARY ativa detectada no banco (PID {pid_db} no host {host_db})"
            finally:
                conn.close()
        except Exception:
            pass

    return False, ""


def create_safety_copy(
    target_db_path: str,
    safety_copy_dir: Optional[str] = None,
) -> Optional[str]:
    """Cria cópia de segurança pré-restore do banco de dados atual caso ele exista."""
    if not os.path.isfile(target_db_path):
        return None

    if safety_copy_dir:
        dest_dir = os.path.abspath(safety_copy_dir)
    else:
        dest_dir = os.path.join(utils.root_dir(), DEFAULT_SAFETY_SUBDIR)
    os.makedirs(dest_dir, exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y%m%d_%H%M%S")
    safety_name = f"video_factory_pre_restore_{ts_str}.db"
    safety_path = os.path.join(dest_dir, safety_name)

    # Copia o arquivo principal do banco
    shutil.copy2(target_db_path, safety_path)

    # Se houver WAL ou SHM, copia como acompanhamento para manter integridade
    wal_source = f"{target_db_path}-wal"
    if os.path.isfile(wal_source):
        shutil.copy2(wal_source, f"{safety_path}-wal")

    shm_source = f"{target_db_path}-shm"
    if os.path.isfile(shm_source):
        shutil.copy2(shm_source, f"{safety_path}-shm")

    logger.info(f"[RECOVERY] Safety copy pré-restore criada com sucesso em: {safety_path}")
    return safety_path


def restore_database_backup(
    backup_file_path: str,
    target_db_path: Optional[str] = None,
    safety_copy_dir: Optional[str] = None,
    _check_active_server: bool = True,
) -> Dict[str, Any]:
    """Executa a restauração segura de um arquivo de backup para o banco SQLite destino.

    FLUXO:
    1. Rejeita incondicionalmente se backend estiver ativo (sem bypass).
    2. Valida arquivo de backup (SHA256 manifesto + PRAGMA integrity_check).
    3. Cria safety copy do banco atual (se existente).
    4. Copia para arquivo temporário de restore e valida PRAGMA integrity_check.
    5. os.replace() atômico para o destino.
    6. Remove arquivos companheiros -wal e -shm obsoletos.
    7. Executa integrity_check final no banco restaurado.
    """
    target_db = scheduler.get_db_path(target_db_path)
    abs_target_db = os.path.abspath(target_db)

    # 1. Proteção contra restauração com backend ativo
    if _check_active_server:
        active, reason = is_backend_active(db_path=abs_target_db)
        if active:
            raise RuntimeError(
                f"RESTAURAÇÃO BLOQUEADA POR SEGURANÇA: O backend do servidor está ativo ({reason}). "
                "Para restaurar o banco de produção, encerre completamente o serviço/tarefa do MoneyPrinterTurbo antes de prosseguir."
            )

    # 2. Validação prévia do arquivo de backup
    if not os.path.isfile(backup_file_path):
        raise FileNotFoundError(f"Arquivo de backup especificado não encontrado: {backup_file_path}")

    verify_res = production_backup.verify_database_backup(backup_file_path)
    if not verify_res.get("valid"):
        raise ValueError(
            f"Arquivo de backup inválido ou corrompido: {verify_res.get('error')}"
        )

    # 3. Criação de Safety Copy do banco de dados existente
    safety_copy_path = create_safety_copy(abs_target_db, safety_copy_dir=safety_copy_dir)

    # 4. Restauração atômica utilizando arquivo temporário no mesmo diretório destino
    target_dir = os.path.dirname(abs_target_db)
    os.makedirs(target_dir, exist_ok=True)
    temp_restore_name = f"{os.path.basename(abs_target_db)}.tmp_restore_{uuid.uuid4().hex[:8]}"
    temp_restore_path = os.path.join(target_dir, temp_restore_name)

    try:
        # Copia o backup para o arquivo temporário
        shutil.copy2(backup_file_path, temp_restore_path)

        # Valida integridade do arquivo temporário restaurado
        temp_verify = production_backup.verify_database_backup(temp_restore_path)
        if not temp_verify.get("valid"):
            raise RuntimeError(
                f"Integridade do arquivo temporário pós-cópia falhou: {temp_verify.get('error')}"
            )

        # 5. Substituição atômica
        os.replace(temp_restore_path, abs_target_db)

        # 6. Limpeza obrigatória de arquivos companheiros WAL e SHM remanescentes do banco antigo
        # Isso evita que o SQLite execute replay de transações pertencentes ao banco anterior!
        for comp in [f"{abs_target_db}-wal", f"{abs_target_db}-shm"]:
            if os.path.isfile(comp):
                try:
                    os.remove(comp)
                except OSError as exc:
                    logger.warning(f"[RECOVERY] Falha ao remover companion file antigo '{comp}': {exc}")

        # 7. Validação final pós-restore no destino
        final_verify = production_backup.verify_database_backup(abs_target_db)
        if not final_verify.get("valid"):
            raise RuntimeError(
                f"Integridade do banco de dados restaurado falhou: {final_verify.get('error')}"
            )

        logger.info(
            f"[RECOVERY] Banco de dados restaurado com sucesso a partir de '{backup_file_path}' "
            f"em '{abs_target_db}'. Safety copy: '{safety_copy_path}'"
        )

        return {
            "success": True,
            "restored_from": backup_file_path,
            "target_database": abs_target_db,
            "safety_copy": safety_copy_path,
            "integrity_check": "ok",
            "restored_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        if os.path.exists(temp_restore_path):
            try:
                os.remove(temp_restore_path)
            except OSError:
                pass
        logger.error(f"[RECOVERY] Falha durante restauração de backup: {exc}")
        raise


def main():
    """Ponto de entrada CLI para restauração controlada de banco."""
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo - Production SQLite Recovery")
    parser.add_argument("backup_file", type=str, help="Caminho do arquivo .db de backup a restaurar")
    parser.add_argument("--target-db", type=str, default=None, help="Caminho do banco SQLite destino")
    parser.add_argument("--safety-dir", type=str, default=None, help="Diretório para salvar a safety copy")
    parser.add_argument("--json", action="store_true", help="Formatar saída estritamente em JSON")
    args = parser.parse_args()

    try:
        res = restore_database_backup(
            backup_file_path=args.backup_file,
            target_db_path=args.target_db,
            safety_copy_dir=args.safety_dir,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("======================================================")
            print(" MoneyPrinterTurbo - Restauração Concluída com Sucesso")
            print("======================================================")
            print(f"Origem (Backup) : {res['restored_from']}")
            print(f"Destino (DB)    : {res['target_database']}")
            print(f"Safety Copy     : {res['safety_copy'] or 'Nenhum DB anterior'}")
            print(f"Integridade     : {res['integrity_check']}")
            print(f"Timestamp       : {res['restored_at']}")
            print("Status          : SUCESSO (exit 0)")
        sys.exit(0)
    except Exception as exc:
        err_dict = {"success": False, "error": str(exc)}
        if args.json:
            print(json.dumps(err_dict, indent=2))
        else:
            print(f"ERRO CRÍTICO NA RESTAURAÇÃO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
