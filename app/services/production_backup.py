"""
Serviço de Backup Seguro e Retenção do Banco de Dados SQLite (Fase V12-C).

Implementa cópias transacionais consistentes do banco SQLite em execução (modo WAL)
utilizando a API oficial sqlite3.Connection.backup(), validação prévia de integridade,
nomenclatura determinística (UTC), manifesto JSON sidecar e política de retenção controlada.

PRINCÍPIOS:
- Nunca copiar arquivos .db/.db-wal/.db-shm diretamente com o processo ativo.
- Criação atômica via arquivo temporário (.tmp) seguido de os.replace().
- PRAGMA integrity_check obrigatório antes de oficializar o backup.
- Não muta o banco original, não altera estado da fábrica e não registra segredos.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services import scheduler
from app.utils import utils

SCHEMA_VERSION = 1
APP_VERSION = "1.3.7"
DEFAULT_RETENTION_COUNT = 24
DEFAULT_BACKUP_SUBDIR = os.path.join("storage", "backups", "database")

BACKUP_FILENAME_REGEX = re.compile(r"^video_factory_(\d{8})_(\d{6})\.db$")
MANIFEST_FILENAME_REGEX = re.compile(r"^video_factory_(\d{8})_(\d{6})\.json$")


def get_backup_dir(custom_dir: Optional[str] = None, create: bool = False) -> str:
    """Retorna o caminho do diretório padrão de backups de banco de dados.

    Cria o diretório em disco somente se create=True (operações de escrita).
    Operações somente leitura/passivas utilizam create=False.
    """
    if custom_dir:
        target_dir = os.path.abspath(custom_dir)
    else:
        target_dir = os.path.join(utils.root_dir(), DEFAULT_BACKUP_SUBDIR)
    if create:
        os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _calculate_sha256(filepath: str) -> str:
    """Calcula o hash SHA-256 de um arquivo em disco em blocos de 64KB."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def verify_database_backup(backup_file_path: str) -> Dict[str, Any]:
    """Valida um arquivo de backup quanto à existência, hash SHA-256 (se houver manifesto) e PRAGMA integrity_check.

    Retorna dicionário com o resultado da auditoria passiva.
    """
    if not os.path.isfile(backup_file_path):
        return {
            "valid": False,
            "error": f"Arquivo de backup não encontrado: {backup_file_path}",
            "sha256": None,
            "size_bytes": 0,
            "integrity": "missing",
            "manifest_matched": False,
            "manifest": None,
        }

    size_bytes = os.path.getsize(backup_file_path)
    current_sha256 = _calculate_sha256(backup_file_path)

    # Verifica manifesto sidecar (.json)
    base_no_ext = os.path.splitext(backup_file_path)[0]
    manifest_path = f"{base_no_ext}.json"
    manifest_data: Optional[Dict[str, Any]] = None
    manifest_matched = True

    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            expected_sha = manifest_data.get("sha256")
            if expected_sha and expected_sha.lower() != current_sha256.lower():
                return {
                    "valid": False,
                    "error": f"SHA-256 mismatch (esperado: {expected_sha}, calculado: {current_sha256})",
                    "sha256": current_sha256,
                    "size_bytes": size_bytes,
                    "integrity": "sha_mismatch",
                    "manifest_matched": False,
                    "manifest": manifest_data,
                }
        except Exception as exc:
            return {
                "valid": False,
                "error": f"Erro ao ler manifesto sidecar: {exc}",
                "sha256": current_sha256,
                "size_bytes": size_bytes,
                "integrity": "manifest_error",
                "manifest_matched": False,
                "manifest": None,
            }

    # Executa PRAGMA integrity_check no arquivo de backup em modo estritamente somente leitura
    try:
        abs_path = os.path.abspath(backup_file_path)
        uri = f"file:{abs_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            cur = conn.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
            if not rows or rows[0][0].lower() != "ok":
                return {
                    "valid": False,
                    "error": f"PRAGMA integrity_check falhou: {rows}",
                    "sha256": current_sha256,
                    "size_bytes": size_bytes,
                    "integrity": str(rows),
                    "manifest_matched": manifest_matched,
                    "manifest": manifest_data,
                }
        finally:
            conn.close()
    except Exception as exc:
        return {
            "valid": False,
            "error": f"Erro ao conectar ou executar integrity_check no backup: {exc}",
            "sha256": current_sha256,
            "size_bytes": size_bytes,
            "integrity": "connection_error",
            "manifest_matched": manifest_matched,
            "manifest": manifest_data,
        }

    return {
        "valid": True,
        "error": None,
        "sha256": current_sha256,
        "size_bytes": size_bytes,
        "integrity": "ok",
        "manifest_matched": manifest_matched,
        "manifest": manifest_data,
    }


def create_database_backup(
    db_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
    retention_count: int = DEFAULT_RETENTION_COUNT,
) -> Dict[str, Any]:
    """Executa backup transacional e seguro do banco SQLite de produção.

    Garante integridade contra WAL ativo usando sqlite3.Connection.backup(),
    valida integridade no arquivo temporário, renomeia atomicamente,
    grava manifesto JSON sidecar e aplica política de retenção.
    """
    target_db = scheduler.get_db_path(db_path)
    if not os.path.isfile(target_db):
        raise FileNotFoundError(f"Banco de dados SQLite fonte não encontrado em: {target_db}")

    dest_dir = get_backup_dir(backup_dir, create=True)

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y%m%d_%H%M%S")
    final_db_name = f"video_factory_{ts_str}.db"
    final_db_path = os.path.join(dest_dir, final_db_name)
    final_manifest_name = f"video_factory_{ts_str}.json"
    final_manifest_path = os.path.join(dest_dir, final_manifest_name)

    # Arquivo temporário no mesmo diretório para garantir rename atômico no mesmo filesystem
    temp_db_name = f"{final_db_name}.tmp_{uuid.uuid4().hex[:8]}"
    temp_db_path = os.path.join(dest_dir, temp_db_name)

    try:
        # 1. Realiza o backup online com a API do SQLite
        # Conecta no source em modo somente leitura (para não bloquear leituras concorrentes)
        src_uri = f"file:{os.path.abspath(target_db)}?mode=ro"
        src_conn = sqlite3.connect(src_uri, uri=True, timeout=30.0)
        try:
            dest_conn = sqlite3.connect(temp_db_path, timeout=30.0)
            try:
                src_conn.backup(dest_conn)
                dest_conn.execute("PRAGMA journal_mode=DELETE;")
                dest_conn.commit()
            finally:
                dest_conn.close()
        finally:
            src_conn.close()

        # Limpa eventuais resíduos temporários de WAL e SHM do arquivo temporário
        for comp in [f"{temp_db_path}-wal", f"{temp_db_path}-shm"]:
            if os.path.exists(comp):
                try:
                    os.remove(comp)
                except OSError:
                    pass

        # 2. Executa PRAGMA integrity_check no arquivo temporário
        temp_verify = verify_database_backup(temp_db_path)
        if not temp_verify.get("valid"):
            raise RuntimeError(
                f"Integridade do arquivo temporário de backup falhou: {temp_verify.get('error')}"
            )

        sha256_hash = temp_verify["sha256"]
        size_bytes = temp_verify["size_bytes"]

        # 3. Rename atômico para o nome definitivo
        os.replace(temp_db_path, final_db_path)

        # 4. Geração e gravação do manifesto JSON sidecar
        manifest_data = {
            "schema_version": SCHEMA_VERSION,
            "created_at": now_utc.isoformat(),
            "database_file": final_db_name,
            "size_bytes": size_bytes,
            "sha256": sha256_hash,
            "integrity_check": "ok",
            "source_database": os.path.basename(target_db),
            "app_version": APP_VERSION,
        }
        with open(final_manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        # 5. Aplica política de retenção
        pruned_files = prune_database_backups(dest_dir, retention_count=retention_count)

        logger.info(
            f"[BACKUP] Backup SQLite criado com sucesso: {final_db_name} "
            f"({size_bytes} bytes, sha256={sha256_hash[:10]}...). Podas realizadas: {len(pruned_files)}"
        )

        return {
            "success": True,
            "database_file": final_db_name,
            "database_path": final_db_path,
            "manifest_file": final_manifest_name,
            "manifest_path": final_manifest_path,
            "size_bytes": size_bytes,
            "sha256": sha256_hash,
            "integrity_check": "ok",
            "created_at": now_utc.isoformat(),
            "pruned_files": pruned_files,
        }

    except Exception as exc:
        for f in [temp_db_path, f"{temp_db_path}-wal", f"{temp_db_path}-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        logger.error(f"[BACKUP] Falha crítica ao gerar backup do banco SQLite: {exc}")
        raise


def list_database_backups(backup_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista todos os backups oficiais de banco existentes, ordenados do mais recente ao mais antigo."""
    dest_dir = get_backup_dir(backup_dir, create=False)
    if not os.path.isdir(dest_dir):
        return []

    backups: List[Dict[str, Any]] = []

    for fname in os.listdir(dest_dir):
        m = BACKUP_FILENAME_REGEX.match(fname)
        if not m:
            continue

        db_path = os.path.join(dest_dir, fname)
        if not os.path.isfile(db_path):
            continue

        size_bytes = os.path.getsize(db_path)
        base_name = os.path.splitext(fname)[0]
        manifest_path = os.path.join(dest_dir, f"{base_name}.json")

        manifest_data: Optional[Dict[str, Any]] = None
        created_at_iso = None
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                created_at_iso = manifest_data.get("created_at")
            except Exception:
                pass

        if not created_at_iso:
            # Reconstrói a partir do timestamp no nome YYYYMMDD_HHMMSS
            date_part, time_part = m.group(1), m.group(2)
            try:
                dt = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S").replace(
                    tzinfo=timezone.utc
                )
                created_at_iso = dt.isoformat()
            except ValueError:
                created_at_iso = datetime.fromtimestamp(
                    os.path.getmtime(db_path), tzinfo=timezone.utc
                ).isoformat()

        backups.append({
            "filename": fname,
            "path": db_path,
            "manifest_path": manifest_path if os.path.isfile(manifest_path) else None,
            "size_bytes": size_bytes,
            "created_at": created_at_iso,
            "manifest": manifest_data,
        })

    # Ordena pelo timestamp decrescente (mais recente primeiro)
    backups.sort(key=lambda b: b.get("created_at") or "", reverse=True)
    return backups


def prune_database_backups(
    backup_dir: Optional[str] = None,
    retention_count: int = DEFAULT_RETENTION_COUNT,
) -> List[str]:
    """Aplica a política de retenção mantendo apenas os N backups mais recentes.

    Nunca apaga arquivos fora do diretório oficial ou arquivos não reconhecidos
    pelo padrão determinístico video_factory_YYYYMMDD_HHMMSS.db.
    """
    if retention_count <= 0:
        return []

    dest_dir = get_backup_dir(backup_dir, create=False)
    all_backups = list_database_backups(dest_dir)

    if len(all_backups) <= retention_count:
        return []

    to_prune = all_backups[retention_count:]
    pruned_files: List[str] = []

    for item in to_prune:
        db_f = item["path"]
        if os.path.isfile(db_f):
            try:
                os.remove(db_f)
                pruned_files.append(db_f)
            except OSError as exc:
                logger.warning(f"[BACKUP] Não foi possível remover backup antigo '{db_f}': {exc}")

        manifest_f = item.get("manifest_path")
        if manifest_f and os.path.isfile(manifest_f):
            try:
                os.remove(manifest_f)
                pruned_files.append(manifest_f)
            except OSError as exc:
                logger.warning(f"[BACKUP] Não foi possível remover manifesto antigo '{manifest_f}': {exc}")

    return pruned_files


def get_latest_backup_info(backup_dir: Optional[str] = None) -> Dict[str, Any]:
    """Retorna sumário passivo do estado do último backup para integração com health check.

    Não cria arquivos, não muta o banco e não executa prune.
    """
    dest_dir = get_backup_dir(backup_dir, create=False)
    now_utc = datetime.now(timezone.utc)

    if not os.path.isdir(dest_dir):
        return {
            "status": "NONE",
            "error": None,
            "latest_backup_at": None,
            "latest_backup_age_seconds": None,
            "valid_backups_count": 0,
            "latest_integrity": None,
            "path": None,
            "backup_dir": dest_dir,
        }

    backups = list_database_backups(dest_dir)
    if not backups:
        return {
            "status": "NONE",
            "error": None,
            "latest_backup_at": None,
            "latest_backup_age_seconds": None,
            "valid_backups_count": 0,
            "latest_integrity": None,
            "path": None,
            "backup_dir": dest_dir,
        }

    latest = backups[0]
    verify_res = verify_database_backup(latest["path"])

    age_seconds: Optional[int] = None
    created_at = latest.get("created_at")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at)
            age_seconds = max(0, int((now_utc - dt).total_seconds()))
        except Exception:
            pass

    return {
        "status": "HEALTHY" if verify_res.get("valid") else "CORRUPT",
        "error": verify_res.get("error"),
        "latest_backup_at": created_at,
        "latest_backup_age_seconds": age_seconds,
        "valid_backups_count": len(backups),
        "latest_integrity": verify_res.get("integrity"),
        "path": latest["path"],
        "backup_dir": dest_dir,
    }


def main():
    """Ponto de entrada CLI para execução de backup manual ou via Task Scheduler."""
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo - Production SQLite Backup")
    parser.add_argument("--db-path", type=str, default=None, help="Caminho do banco SQLite fonte")
    parser.add_argument("--backup-dir", type=str, default=None, help="Diretório de destino dos backups")
    parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION_COUNT, help="Quantidade de backups a reter")
    parser.add_argument("--json", action="store_true", help="Formatar saída estritamente em JSON")
    args = parser.parse_args()

    try:
        res = create_database_backup(
            db_path=args.db_path,
            backup_dir=args.backup_dir,
            retention_count=args.retention,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print("======================================================")
            print(" MoneyPrinterTurbo - Backup de Produção Concluído")
            print("======================================================")
            print(f"Arquivo     : {res['database_file']}")
            print(f"Destino     : {res['database_path']}")
            print(f"Tamanho     : {res['size_bytes']} bytes")
            print(f"SHA-256     : {res['sha256']}")
            print(f"Integridade : {res['integrity_check']}")
            print(f"Timestamp   : {res['created_at']}")
            print(f"Podados     : {len(res['pruned_files'])} arquivos antigos")
            print("Status      : SUCESSO (exit 0)")
        sys.exit(0)
    except Exception as exc:
        err_dict = {"success": False, "error": str(exc)}
        if args.json:
            print(json.dumps(err_dict, indent=2))
        else:
            print(f"ERRO CRÍTICO NO BACKUP: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
