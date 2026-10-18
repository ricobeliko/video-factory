r"""Módulo de Guarda de Isolamento Rigoroso — Video Factory V2 (Fase V2.0 / V2.14).

Garantias absolutas:
1. Em DEV_V2 (padrão): Impede qualquer escrita ou conexão ao banco de produção (C:\Projetos\MoneyPrinterTurbo).
2. Em DEV_V2 (padrão): Impede qualquer escrita ou conexão ao banco do DEV original (D:\Projetos\MoneyPrinterTurbo\storage).
3. Em DEV_V2 (padrão): Bloqueia chamadas de publicação real (Post for Me, YouTube, TikTok, Upload-Post).
4. Em Produção (MPT_ENVIRONMENT=PRODUCTION no PC Forte): Permite operação legítima no diretório de produção sem bloqueios de DEV.
"""

from __future__ import annotations

import os
import sys
from typing import Optional
from loguru import logger

ENVIRONMENT_IDENTITY = os.getenv("MPT_ENVIRONMENT", "DEV_V2")

DEFAULT_FORBIDDEN_PATHS = [
    r"c:\projetos\moneyprinterturbo",
    r"d:\projetos\moneyprinterturbo\storageideo_factory.db",
]


class IsolationViolationError(RuntimeError):
    """Lançada quando qualquer tentativa de violação de isolamento contra Produção ou DEV Original ocorre."""
    pass


def get_v2_root_dir() -> str:
    """Retorna o diretório raiz canônico da V2."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_forbidden_paths() -> list[str]:
    """Retorna a lista de caminhos proibidos com base no ambiente operacional."""
    current_env = os.getenv("MPT_ENVIRONMENT", ENVIRONMENT_IDENTITY).upper()
    if current_env == "PRODUCTION":
        return []
    return DEFAULT_FORBIDDEN_PATHS


def validate_path_isolation(target_path: Optional[str], purpose: str = "generic") -> str:
    """Valida se um caminho é seguro e estritamente contido no ambiente V2 ou temporário de teste."""
    if not target_path:
        return ""
    norm = os.path.normpath(os.path.abspath(target_path)).lower()

    for forbidden in get_forbidden_paths():
        forbidden_norm = os.path.normpath(forbidden).lower()
        if norm == forbidden_norm or norm.startswith(forbidden_norm + os.sep):
            msg = (
                f"[ISOLATION_GUARD_CRITICAL] Tentativa de acesso bloqueada para {purpose}: '{target_path}'. "
                f"O caminho viola a regra de isolamento da Video Factory V2 contra Produção/DEV Original."
            )
            logger.critical(msg)
            raise IsolationViolationError(msg)

    return target_path


def get_v2_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho seguro e isolado do banco SQLite para a V2."""
    if custom_path:
        validate_path_isolation(custom_path, purpose="sqlite_custom_db")
        return custom_path

    v2_root = get_v2_root_dir()
    db_path = os.path.join(v2_root, "storage", "video_factory_v2.db")
    validate_path_isolation(db_path, purpose="sqlite_default_db")
    return db_path


def is_external_publication_allowed() -> bool:
    """Retorna se a publicação externa real está permitida. Na V2 em DEV, é SEMPRE False."""
    current_env = os.getenv("MPT_ENVIRONMENT", ENVIRONMENT_IDENTITY).upper()
    if current_env == "PRODUCTION":
        # Em produção, a publicação é controlada pelas configurações operacionais canônicas do Scheduler
        return True
    return False


def assert_safe_environment() -> None:
    """Executa verificações de sanidade do ambiente V2."""
    current_env = os.getenv("MPT_ENVIRONMENT", ENVIRONMENT_IDENTITY).upper()
    if current_env == "PRODUCTION":
        return
    v2_root = get_v2_root_dir().lower()
    if "moneyprinterturbo-v2" not in v2_root and "v2_isolated" not in v2_root:
        logger.warning(f"[ISOLATION_GUARD] Diretório raiz '{v2_root}' não contém padrão esperado de V2.")
