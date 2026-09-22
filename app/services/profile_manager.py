"""
Profile Manager Service (Fase V9-A — Multi-Profile Foundation).

Gerencia perfis de conteúdo e canais de publicação da Video Factory,
garantindo compatibilidade retroativa total com o nó PRIMARY e suporte
a operações de leitura em nós secundários (VIEW ONLY).
"""
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import config
from app.models import const

DEFAULT_PROFILE_ID = "default"
DEFAULT_PROFILE_NAME = "Video Factory Default"
DEFAULT_PROFILE_SLUG = "default"
ALLOWED_PLATFORMS = {"youtube", "tiktok"}
ACTIVE_PROFILE_SETTING_KEY = "active_profile_id"

SECOND_PROFILE_ID = "profile-historias-misterio"
SECOND_PROFILE_NAME = "Dose Diária de Histórias e Mistério"
SECOND_PROFILE_SLUG = "dose-diaria-de-historias-e-misterio"
SECOND_CHANNEL_ID = "channel-historias-misterio-youtube"
SECOND_CHANNEL_DISPLAY = "Dose Diária de Histórias e Mistério (YouTube)"
SECOND_PROFILE_NICHE = "historias_misterio"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho do banco de dados SQLite."""
    if custom_path:
        return custom_path
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, "storage", "video_factory.db")


@contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o banco SQLite com WAL e Foreign Keys ativadas."""
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        with conn:
            yield conn
    finally:
        conn.close()


def init_profile_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas content_profiles e publishing_channels no SQLite de forma aditiva e idempotente."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                niche TEXT,
                language TEXT,
                region TEXT,
                default_preset TEXT,
                growth_mode TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS publishing_channels (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                display_name TEXT NOT NULL,
                external_profile_name TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES content_profiles(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_profiles_slug ON content_profiles(slug);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_profiles_active ON content_profiles(is_active);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_channels_profile ON publishing_channels(profile_id);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_profiles (
                task_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_profiles_pid ON task_profiles(profile_id);")


def _validate_growth_mode(mode: str) -> str:
    clean = str(mode or "").strip().lower()
    if clean not in const.GROWTH_MODES:
        raise ValueError(
            f"Growth mode inválido: '{mode}'. Opções válidas: {const.GROWTH_MODES}"
        )
    return clean


def _validate_preset(preset: str) -> str:
    clean = str(preset or "").strip().lower()
    if clean not in const.MONETIZATION_PRESET_CHOICES:
        raise ValueError(
            f"Preset inválido: '{preset}'. Opções válidas: {const.MONETIZATION_PRESET_CHOICES}"
        )
    return clean


def _validate_platform(platform: str) -> str:
    clean = str(platform or "").strip().lower()
    if clean not in ALLOWED_PLATFORMS:
        raise ValueError(
            f"Plataforma inválida: '{platform}'. Permitidas apenas: {sorted(list(ALLOWED_PLATFORMS))}"
        )
    return clean


def generate_slug(name: str, db_path: Optional[str] = None, exclude_id: Optional[str] = None) -> str:
    """Gera slug estável, lowercase, sem espaços e único no banco de dados."""
    init_profile_db(db_path)
    normalized = unicodedata.normalize("NFKD", str(name or ""))
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c)).lower()
    slug_base = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if not slug_base:
        slug_base = "profile"

    candidate = slug_base
    suffix = 1
    with get_connection(db_path) as conn:
        while True:
            if exclude_id:
                row = conn.execute(
                    "SELECT id FROM content_profiles WHERE slug = ? AND id != ?;",
                    (candidate, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM content_profiles WHERE slug = ?;",
                    (candidate,),
                ).fetchone()
            if not row:
                return candidate
            suffix += 1
            candidate = f"{slug_base}-{suffix}"


def ensure_default_profile(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Garante de forma idempotente a existência do DEFAULT PROFILE e de seus canais padrão."""
    init_profile_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM content_profiles WHERE id = ?;",
            (DEFAULT_PROFILE_ID,),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO content_profiles (
                    id, name, slug, niche, language, region,
                    default_preset, growth_mode, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    DEFAULT_PROFILE_ID,
                    DEFAULT_PROFILE_NAME,
                    DEFAULT_PROFILE_SLUG,
                    "curiosidades",
                    "pt-BR",
                    "BR",
                    const.DEFAULT_MONETIZATION_PRESET,
                    const.DEFAULT_GROWTH_MODE,
                    1,
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                "SELECT * FROM content_profiles WHERE id = ?;",
                (DEFAULT_PROFILE_ID,),
            ).fetchone()

        # Garante canais padrão compatíveis com a infra existente de Upload-Post
        upload_post_username = (config.app.get("upload_post_username") or "").strip() or "video-factory"

        # Canal YouTube Default
        yt_row = conn.execute(
            "SELECT id FROM publishing_channels WHERE profile_id = ? AND platform = ?;",
            (DEFAULT_PROFILE_ID, "youtube"),
        ).fetchone()
        if yt_row is None:
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "channel-default-youtube",
                    DEFAULT_PROFILE_ID,
                    "youtube",
                    "YouTube (Default)",
                    upload_post_username,
                    1,
                    now_iso,
                    now_iso,
                ),
            )

        # Canal TikTok Default
        tt_row = conn.execute(
            "SELECT id FROM publishing_channels WHERE profile_id = ? AND platform = ?;",
            (DEFAULT_PROFILE_ID, "tiktok"),
        ).fetchone()
        if tt_row is None:
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "channel-default-tiktok",
                    DEFAULT_PROFILE_ID,
                    "tiktok",
                    "TikTok (Default)",
                    upload_post_username,
                    1,
                    now_iso,
                    now_iso,
                ),
            )

        return dict(row)


def get_default_profile(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna o perfil padrão da Video Factory."""
    init_profile_db(db_path)
    p = get_profile(DEFAULT_PROFILE_ID, db_path=db_path)
    if not p:
        return ensure_default_profile(db_path=db_path)
    return p


def ensure_second_channel_profile(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Cadastra e configura de forma idempotente o perfil e canal do segundo canal.

    Perfil: Dose Diária de Histórias e Mistério
    Nicho: historias_misterio
    Growth Mode: WARMUP ('warmup')
    Canal YouTube: isolado, sem credenciais reais conectadas.
    """
    init_profile_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        p_row = conn.execute(
            "SELECT * FROM content_profiles WHERE id = ? OR slug = ?;",
            (SECOND_PROFILE_ID, SECOND_PROFILE_SLUG),
        ).fetchone()
        if p_row is None:
            conn.execute(
                """
                INSERT INTO content_profiles (
                    id, name, slug, niche, language, region,
                    default_preset, growth_mode, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    SECOND_PROFILE_ID,
                    SECOND_PROFILE_NAME,
                    SECOND_PROFILE_SLUG,
                    SECOND_PROFILE_NICHE,
                    "pt-BR",
                    "BR",
                    const.DEFAULT_MONETIZATION_PRESET,
                    const.GROWTH_MODE_WARMUP,
                    1,
                    now_iso,
                    now_iso,
                ),
            )
            p_row = conn.execute("SELECT * FROM content_profiles WHERE id = ?;", (SECOND_PROFILE_ID,)).fetchone()

        ch_row = conn.execute(
            "SELECT * FROM publishing_channels WHERE id = ? OR (profile_id = ? AND platform = 'youtube');",
            (SECOND_CHANNEL_ID, SECOND_PROFILE_ID),
        ).fetchone()
        if ch_row is None:
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    SECOND_CHANNEL_ID,
                    SECOND_PROFILE_ID,
                    "youtube",
                    SECOND_CHANNEL_DISPLAY,
                    "dose-diaria-misterio",
                    1,
                    now_iso,
                    now_iso,
                ),
            )
            ch_row = conn.execute("SELECT * FROM publishing_channels WHERE id = ?;", (SECOND_CHANNEL_ID,)).fetchone()

    return {
        "profile": dict(p_row) if p_row else {},
        "channel": _normalize_channel_dict(dict(ch_row)) if ch_row else {},
    }


def create_profile(
    name: str,
    niche: Optional[str] = None,
    language: str = "pt-BR",
    region: str = "BR",
    default_preset: str = const.DEFAULT_MONETIZATION_PRESET,
    growth_mode: str = const.DEFAULT_GROWTH_MODE,
    is_active: bool = True,
    profile_id: Optional[str] = None,
    slug: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria um novo perfil de conteúdo no SQLite."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Nome do perfil não pode ser vazio.")

    clean_growth_mode = _validate_growth_mode(growth_mode)
    clean_preset = _validate_preset(default_preset)

    new_id = profile_id or f"profile-{uuid.uuid4().hex[:12]}"
    new_slug = slug or generate_slug(clean_name, db_path=db_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_profiles (
                id, name, slug, niche, language, region,
                default_preset, growth_mode, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                new_id,
                clean_name,
                new_slug,
                niche.strip() if niche else None,
                language.strip() if language else "pt-BR",
                region.strip().upper() if region else "BR",
                clean_preset,
                clean_growth_mode,
                1 if is_active else 0,
                now_iso,
                now_iso,
            ),
        )
        row = conn.execute("SELECT * FROM content_profiles WHERE id = ?;", (new_id,)).fetchone()
        return dict(row)


def update_profile(
    profile_id: str,
    name: Optional[str] = None,
    niche: Optional[str] = None,
    language: Optional[str] = None,
    region: Optional[str] = None,
    default_preset: Optional[str] = None,
    growth_mode: Optional[str] = None,
    is_active: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza atributos de um perfil existente."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_id = str(profile_id or "").strip()
    if clean_id == DEFAULT_PROFILE_ID and is_active is False:
        raise ValueError("O perfil padrão 'default' é a base de segurança do sistema e não pode ser desativado.")

    existing = get_profile(profile_id, db_path=db_path)
    if not existing:
        raise ValueError(f"Perfil com ID '{profile_id}' não encontrado.")

    updates = []
    params = []

    if name is not None:
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Nome do perfil não pode ser vazio.")
        updates.append("name = ?")
        params.append(clean_name)

    if niche is not None:
        updates.append("niche = ?")
        params.append(niche.strip() if niche else None)

    if language is not None:
        updates.append("language = ?")
        params.append(language.strip())

    if region is not None:
        updates.append("region = ?")
        params.append(region.strip().upper())

    if default_preset is not None:
        clean_preset = _validate_preset(default_preset)
        updates.append("default_preset = ?")
        params.append(clean_preset)

    if growth_mode is not None:
        clean_growth_mode = _validate_growth_mode(growth_mode)
        updates.append("growth_mode = ?")
        params.append(clean_growth_mode)

    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)

    now_iso = datetime.now(timezone.utc).isoformat()
    updates.append("updated_at = ?")
    params.append(now_iso)

    params.append(profile_id)

    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE content_profiles SET {', '.join(updates)} WHERE id = ?;",
            tuple(params),
        )
        row = conn.execute("SELECT * FROM content_profiles WHERE id = ?;", (profile_id,)).fetchone()
        return dict(row)


def get_profile(profile_id_or_slug: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Busca um perfil por ID ou por slug (permitido em VIEW ONLY)."""
    init_profile_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM content_profiles WHERE id = ? OR slug = ?;",
            (profile_id_or_slug, profile_id_or_slug),
        ).fetchone()
        return dict(row) if row else None


def list_profiles(active_only: bool = False, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista perfis de conteúdo cadastrados (permitido em VIEW ONLY)."""
    init_profile_db(db_path)
    with get_connection(db_path) as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM content_profiles WHERE is_active = 1 ORDER BY created_at ASC;"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM content_profiles ORDER BY created_at ASC;"
            ).fetchall()
        return [dict(r) for r in rows]


def set_profile_active(profile_id: str, is_active: bool, db_path: Optional[str] = None) -> bool:
    """Ativa ou desativa um perfil."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    clean_id = str(profile_id or "").strip()
    if clean_id == DEFAULT_PROFILE_ID and not is_active:
        raise ValueError("O perfil padrão 'default' é a base de segurança do sistema e não pode ser desativado.")

    init_profile_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE content_profiles SET is_active = ?, updated_at = ? WHERE id = ?;",
            (1 if is_active else 0, now_iso, clean_id),
        )
        return cur.rowcount > 0


def _normalize_channel_dict(row_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row_dict:
        return None
    d = dict(row_dict)
    if "channel_id" not in d:
        d["channel_id"] = d.get("id")
    if "channel_name" not in d:
        d["channel_name"] = d.get("display_name")
    return d


def create_channel(
    profile_id: str,
    platform: str,
    display_name: Optional[str] = None,
    external_profile_name: Optional[str] = None,
    is_enabled: bool = True,
    channel_id: Optional[str] = None,
    db_path: Optional[str] = None,
    channel_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria um canal de publicação associado a um perfil."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_platform = _validate_platform(platform)
    clean_display = str(display_name or channel_name or "").strip()
    if not clean_display:
        raise ValueError("Display name do canal não pode ser vazio.")

    # Valida que o perfil existe no SQLite
    profile = get_profile(profile_id, db_path=db_path)
    if not profile:
        raise ValueError(f"Perfil com ID '{profile_id}' não encontrado.")

    cid = channel_id or f"channel-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publishing_channels (
                id, profile_id, platform, display_name, external_profile_name,
                is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                cid,
                profile_id,
                clean_platform,
                clean_display,
                external_profile_name.strip() if external_profile_name else None,
                1 if is_enabled else 0,
                now_iso,
                now_iso,
            ),
        )
        row = conn.execute("SELECT * FROM publishing_channels WHERE id = ?;", (cid,)).fetchone()
        return _normalize_channel_dict(dict(row))


def update_channel(
    channel_id: str,
    display_name: Optional[str] = None,
    external_profile_name: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza atributos de um canal de publicação."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    existing = get_channel(channel_id, db_path=db_path)
    if not existing:
        raise ValueError(f"Canal com ID '{channel_id}' não encontrado.")

    updates = []
    params = []

    if display_name is not None:
        clean_name = str(display_name).strip()
        if not clean_name:
            raise ValueError("Display name não pode ser vazio.")
        updates.append("display_name = ?")
        params.append(clean_name)

    if external_profile_name is not None:
        updates.append("external_profile_name = ?")
        params.append(external_profile_name.strip() if external_profile_name else None)

    if is_enabled is not None:
        updates.append("is_enabled = ?")
        params.append(1 if is_enabled else 0)

    now_iso = datetime.now(timezone.utc).isoformat()
    updates.append("updated_at = ?")
    params.append(now_iso)

    params.append(channel_id)

    with get_connection(db_path) as conn:
        conn.execute(
            f"UPDATE publishing_channels SET {', '.join(updates)} WHERE id = ?;",
            tuple(params),
        )
        row = conn.execute("SELECT * FROM publishing_channels WHERE id = ?;", (channel_id,)).fetchone()
        return _normalize_channel_dict(dict(row))


def get_channel(channel_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Busca canal por ID (permitido em VIEW ONLY)."""
    init_profile_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM publishing_channels WHERE id = ?;", (channel_id,)).fetchone()
        return _normalize_channel_dict(dict(row)) if row else None


def list_channels(
    profile_id: Optional[str] = None,
    enabled_only: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista canais de publicação, opcionalmente filtrados por perfil e status (permitido em VIEW ONLY)."""
    init_profile_db(db_path)
    conditions = []
    params = []

    if profile_id:
        conditions.append("profile_id = ?")
        params.append(profile_id)

    if enabled_only:
        conditions.append("is_enabled = 1")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM publishing_channels {where_clause} ORDER BY created_at ASC;"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        return [_normalize_channel_dict(dict(r)) for r in rows]


def set_channel_enabled(channel_id: str, is_enabled: bool, db_path: Optional[str] = None) -> bool:
    """Habilita ou desabilita um canal de publicação."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE publishing_channels SET is_enabled = ?, updated_at = ? WHERE id = ?;",
            (1 if is_enabled else 0, now_iso, channel_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Active Profile & Contexto de Geração (Fase V9-B)
# ---------------------------------------------------------------------------


def get_active_profile_id(db_path: Optional[str] = None) -> str:
    """Retorna o ID do perfil operacional ativo (permitido em VIEW ONLY)."""
    init_profile_db(db_path)
    try:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autopilot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            row = conn.execute(
                "SELECT value FROM autopilot_settings WHERE key = ?;",
                (ACTIVE_PROFILE_SETTING_KEY,),
            ).fetchone()
            if row and row["value"]:
                active_id = str(row["value"]).strip()
                p = get_profile(active_id, db_path=db_path)
                if p and p.get("is_active"):
                    return active_id
    except Exception:
        pass
    return DEFAULT_PROFILE_ID


def get_active_profile(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna os dados completos do perfil ativo com fallback seguro para DEFAULT PROFILE."""
    init_profile_db(db_path)
    active_id = get_active_profile_id(db_path=db_path)
    p = get_profile(active_id, db_path=db_path)
    if not p or not p.get("is_active"):
        return get_default_profile(db_path=db_path)
    return p


def set_active_profile(profile_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Define o perfil operacional ativo no SQLite (somente PRIMARY)."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_id = str(profile_id or "").strip()
    p = get_profile(clean_id, db_path=db_path)
    if not p:
        raise ValueError(f"Perfil com ID '{profile_id}' não encontrado.")
    if not p.get("is_active"):
        raise ValueError(f"Perfil '{p.get('name')}' está inativo e não pode ser definido como ativo.")

    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS autopilot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO autopilot_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (ACTIVE_PROFILE_SETTING_KEY, clean_id),
        )
    return p


set_active_profile_id = set_active_profile


def get_generation_profile_context(
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retorna o contexto operacional de geração para um perfil especificado ou para o perfil ativo."""
    init_profile_db(db_path)
    if profile_id:
        profile = get_profile(profile_id, db_path=db_path)
        if not profile or not profile.get("is_active"):
            profile = get_active_profile(db_path=db_path)
    else:
        profile = get_active_profile(db_path=db_path)

    # Fallbacks da aplicação / config.toml
    fallback_niche = config.app.get("default_niche") or "curiosidades"
    fallback_language = config.app.get("video_language") or "pt-BR"
    fallback_region = config.app.get("default_region") or "BR"
    fallback_preset = const.DEFAULT_MONETIZATION_PRESET
    fallback_growth = const.DEFAULT_GROWTH_MODE

    return {
        "profile_id": profile.get("id") or DEFAULT_PROFILE_ID,
        "profile_name": profile.get("name") or DEFAULT_PROFILE_NAME,
        "profile_slug": profile.get("slug") or DEFAULT_PROFILE_SLUG,
        "niche": profile.get("niche") or fallback_niche,
        "language": profile.get("language") or fallback_language,
        "region": profile.get("region") or fallback_region,
        "default_preset": profile.get("default_preset") or fallback_preset,
        "growth_mode": profile.get("growth_mode") or fallback_growth,
    }


def save_task_profile(task_id: str, profile_id: str, db_path: Optional[str] = None) -> None:
    """Associa imutavelmente uma tarefa ao seu perfil de origem no SQLite."""
    init_profile_db(db_path)
    clean_tid = str(task_id or "").strip()
    clean_pid = str(profile_id or "").strip() or DEFAULT_PROFILE_ID
    if not clean_tid:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO task_profiles (task_id, profile_id, created_at)
            VALUES (?, ?, ?);
            """,
            (clean_tid, clean_pid, now_iso),
        )


set_task_profile_id = save_task_profile


def get_task_profile_id(task_id: str, db_path: Optional[str] = None) -> str:
    """Recupera o profile_id de uma tarefa (fallback seguro para 'default' se não associada)."""
    init_profile_db(db_path)
    clean_tid = str(task_id or "").strip()
    if not clean_tid:
        return DEFAULT_PROFILE_ID
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT profile_id FROM task_profiles WHERE task_id = ?;",
                (clean_tid,),
            ).fetchone()
            if row and row["profile_id"]:
                return str(row["profile_id"])
    except Exception:
        pass
    return DEFAULT_PROFILE_ID


def resolve_task_channels(
    task_id: str,
    platforms: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Resolve os canais de publicação habilitados vinculados ao perfil imutável da task.

    Fluxo:
    1. Descobre o profile_id da task (imutável)
    2. Fallback para 'default' se task antiga
    3. Verifica se o perfil está ativo (se inativo, retorna vazio)
    4. Lista publishing_channels desse profile
    5. Opcionalmente filtra pelas platforms solicitadas
    6. Retorna apenas canais habilitados (is_enabled == 1)
    """
    init_profile_db(db_path)
    profile_id = get_task_profile_id(task_id, db_path=db_path)
    prof = get_profile(profile_id, db_path=db_path)
    if prof and not prof.get("is_active"):
        return []

    channels = list_channels(profile_id=profile_id, db_path=db_path)
    enabled_channels = [c for c in channels if c.get("is_enabled")]

    if platforms:
        norm_platforms = {p.lower().strip() for p in platforms if p and p.strip()}
        enabled_channels = [
            c for c in enabled_channels
            if c.get("platform", "").lower().strip() in norm_platforms
        ]

    return enabled_channels
