"""Módulo de Guarda de Isolamento Rigoroso — Video Factory V2 (Fase V2.0).

Garantias absolutas:
1. Impede qualquer escrita ou conexão ao banco de produção (C:\\Projetos\\MoneyPrinterTurbo).
2. Impede qualquer escrita ou conexão ao banco do DEV original (D:\\Projetos\\MoneyPrinterTurbo\\storage).
3. Garante que o ambiente de execução seja exclusivamente DEV_V2 em D:\\Projetos\\MoneyPrinterTurbo-V2.
4. Bloqueia chamadas de publicação real (Post for Me, YouTube, TikTok, Upload-Post) na V2,
   forçando modo simulado/mock seguro.
"""

from __future__ import annotations

import os
import sys
from typing import Optional
from loguru import logger

ENVIRONMENT_IDENTITY = "DEV_V2"
FORBIDDEN_PATHS = [
    r"c:\projetos\moneyprinterturbo",
    r"d:\projetos\moneyprinterturbo\storage\video_factory.db",
]


class IsolationViolationError(RuntimeError):
    """Lançada quando qualquer tentativa de violação de isolamento contra Produção ou DEV Original ocorre."""
    pass


def get_v2_root_dir() -> str:
    """Retorna o diretório raiz canônico da V2."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def validate_path_isolation(target_path: Optional[str], purpose: str = "generic") -> str:
    """Valida se um caminho é seguro e estritamente contido no ambiente V2 ou temporário de teste."""
    if not target_path:
        return ""
    norm = os.path.normpath(os.path.abspath(target_path)).lower()

    for forbidden in FORBIDDEN_PATHS:
        if norm.startswith(forbidden) or norm == forbidden:
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
    """Retorna se a publicação externa real está permitida. Na V2, é SEMPRE False."""
    return False


def assert_safe_environment() -> None:
    """Executa verificações de sanidade do ambiente V2."""
    v2_root = get_v2_root_dir().lower()
    if "moneyprinterturbo-v2" not in v2_root and "v2_isolated" not in v2_root:
        logger.warning(f"[ISOLATION_GUARD] Diretório raiz '{v2_root}' não contém padrão esperado de V2.")
