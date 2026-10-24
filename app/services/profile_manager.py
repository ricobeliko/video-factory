"""
Profile Manager Service (Fase V9-A — Multi-Profile Foundation).

Gerencia perfis de conteúdo e canais de publicação da Video Factory,
garantindo compatibilidade retroativa total com o nó PRIMARY e suporte
a operações de leitura em nós secundários (VIEW ONLY).
"""
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, model_validator

from app.config import config
from app.models import const
from app.services.post_for_me import CHANNEL_DEFAULT_DISPLAY

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
SECOND_CHANNEL_HANDLE = "@DoseDiáriadeHistóriasemistério"
SECOND_PROFILE_NICHE = "historias_misterio"

DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT = 6


# ---------------------------------------------------------------------------
# Modelos Pydantic de Configuração Tipada (Fase V1.5E-B / V1.5E-B.1)
# ---------------------------------------------------------------------------

class EditorialSettings(BaseModel):
    topic_brief: Optional[str] = None
    content_style: Optional[str] = None
    video_format: Optional[str] = None
    narrative_structure: Optional[str] = None
    closing_type: Optional[str] = None
    num_questions: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def reconcile_editorial(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("content_style") and not data.get("narrative_structure"):
            data["narrative_structure"] = data["content_style"]
        if str(data.get("closing_type") or "").strip().lower() == "comments":
            data["closing_type"] = "score_challenge"
        return data


class VoiceSettings(BaseModel):
    voice_name: Optional[str] = None
    voice_rate: Optional[float] = None
    voice_volume: Optional[float] = None


class VisualSettings(BaseModel):
    visual_director_enabled: Optional[bool] = None
    flow_enabled: Optional[bool] = None
    flow_scene_count: Optional[int] = None
    stock_fallback_enabled: Optional[bool] = None
    visual_style_brief: Optional[str] = None


class SubtitleSettings(BaseModel):
    position: Optional[str] = None
    font_size: Optional[int] = None


class AutomationSettings(BaseModel):
    autonomous_enabled: Optional[bool] = None
    target_ready_stock: Optional[int] = None
    posts_per_day: Optional[int] = None
    max_generations_24h: Optional[int] = None
    max_attempts_24h: Optional[int] = None


class ScheduleSettings(BaseModel):
    publish_start_hour: int = 10
    publish_end_hour: int = 22
    timezone: str = "America/Sao_Paulo"
    min_interval_hours: int = 2
    posts_per_day: int = 1


class MusicSettings(BaseModel):
    enabled: bool = False
    mode: str = "auto"
    volume: float = 0.20
    default_mood: str = "neutral"


class ChannelWorkspaceSettings(BaseModel):
    schema_version: int = 1
    editorial: EditorialSettings = Field(default_factory=EditorialSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    visual: VisualSettings = Field(default_factory=VisualSettings)
    subtitle: SubtitleSettings = Field(default_factory=SubtitleSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    music: MusicSettings = Field(default_factory=MusicSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: Optional[Union[str, Dict[str, Any]]]) -> "ChannelWorkspaceSettings":
        if not raw:
            return cls()
        if isinstance(raw, dict):
            return cls.model_validate(raw)
        if isinstance(raw, str):
            clean = raw.strip()
            if not clean or clean == "{}":
                return cls()
            try:
                return cls.model_validate_json(clean)
            except Exception:
                return cls()
        return cls()


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
                settings_json TEXT NOT NULL DEFAULT '{}',
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
                external_account_id TEXT,
                project_id TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES content_profiles(id) ON DELETE CASCADE
            );
            """
        )

        # Migrations aditivas e idempotentes para bancos pré-existentes
        p_cols = {row["name"] for row in conn.execute("PRAGMA table_info(content_profiles);").fetchall()}
        if "settings_json" not in p_cols:
            conn.execute("ALTER TABLE content_profiles ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}';")

        ch_cols = {row["name"] for row in conn.execute("PRAGMA table_info(publishing_channels);").fetchall()}
        if "external_account_id" not in ch_cols:
            conn.execute("ALTER TABLE publishing_channels ADD COLUMN external_account_id TEXT;")
        if "project_id" not in ch_cols:
            conn.execute("ALTER TABLE publishing_channels ADD COLUMN project_id TEXT;")

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

        # Migração legada idempotente: atualizar 'YouTube (Default)' para o nome canônico
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE publishing_channels
            SET display_name = ?, updated_at = ?
            WHERE id = ? AND display_name = ?;
            """,
            (
                CHANNEL_DEFAULT_DISPLAY,
                now_iso,
                "channel-default-youtube",
                "YouTube (Default)",
            ),
        )


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
                    CHANNEL_DEFAULT_DISPLAY,
                    upload_post_username,
                    1,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            # Migração legada idempotente: atualizar 'YouTube (Default)' para o nome canônico
            conn.execute(
                """
                UPDATE publishing_channels
                SET display_name = ?, updated_at = ?
                WHERE id = ? AND display_name = ?;
                """,
                (
                    CHANNEL_DEFAULT_DISPLAY,
                    now_iso,
                    "channel-default-youtube",
                    "YouTube (Default)",
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

    ch_dict = _normalize_channel_dict(dict(ch_row)) if ch_row else {}
    if ch_dict:
        ch_dict["channel_handle"] = SECOND_CHANNEL_HANDLE

    return {
        "profile": dict(p_row) if p_row else {},
        "channel": ch_dict,
        "channel_handle": SECOND_CHANNEL_HANDLE,
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
    external_account_id: Optional[str] = None,
    is_enabled: bool = True,
    channel_id: Optional[str] = None,
    db_path: Optional[str] = None,
    channel_name: Optional[str] = None,
    project_id: Optional[str] = None,
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
    clean_ext_account = str(external_account_id).strip() if external_account_id else None
    clean_project_id = str(project_id).strip() if project_id else None

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO publishing_channels (
                id, profile_id, platform, display_name, external_profile_name,
                external_account_id, project_id, is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                cid,
                profile_id,
                clean_platform,
                clean_display,
                external_profile_name.strip() if external_profile_name else None,
                clean_ext_account,
                clean_project_id,
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
    external_account_id: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    project_id: Optional[str] = None,
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

    if external_account_id is not None:
        updates.append("external_account_id = ?")
        params.append(external_account_id.strip() if external_account_id else None)

    if project_id is not None:
        updates.append("project_id = ?")
        params.append(project_id.strip() if project_id else None)

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


def get_profile_settings(profile_id: str, db_path: Optional[str] = None) -> ChannelWorkspaceSettings:
    """Recupera as configurações tipadas de um perfil. Se inexistente ou vazio, retorna defaults seguros."""
    init_profile_db(db_path)
    clean_id = str(profile_id or "").strip()
    if not clean_id:
        return ChannelWorkspaceSettings()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT settings_json FROM content_profiles WHERE id = ?;",
            (clean_id,),
        ).fetchone()
        if not row:
            return ChannelWorkspaceSettings()
        raw = row["settings_json"] if "settings_json" in row.keys() else None
        return ChannelWorkspaceSettings.from_json(raw)


def update_profile_settings(
    profile_id: str,
    settings: Union[ChannelWorkspaceSettings, Dict[str, Any]],
    db_path: Optional[str] = None,
) -> ChannelWorkspaceSettings:
    """Atualiza as configurações tipadas de um perfil e sincroniza o modo autônomo associado."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_id = str(profile_id or "").strip()
    if not clean_id:
        raise ValueError("Profile ID não pode ser vazio.")

    existing = get_profile(clean_id, db_path=db_path)
    if not existing:
        raise ValueError(f"Perfil com ID '{clean_id}' não encontrado.")

    if isinstance(settings, dict):
        settings_model = ChannelWorkspaceSettings.model_validate(settings)
    elif isinstance(settings, ChannelWorkspaceSettings):
        settings_model = settings
    else:
        raise ValueError("Settings deve ser um ChannelWorkspaceSettings ou dicionário compatível.")

    now_iso = datetime.now(timezone.utc).isoformat()
    json_str = settings_model.to_json()

    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE content_profiles SET settings_json = ?, updated_at = ? WHERE id = ?;",
            (json_str, now_iso, clean_id),
        )
        if settings_model.automation.target_ready_stock is not None:
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
                (f"autonomous_target_ready_stock:{clean_id}", str(settings_model.automation.target_ready_stock)),
            )

    return settings_model


def get_profile_schedule(profile_id: str, db_path: Optional[str] = None) -> ScheduleSettings:
    """Recupera as configurações de agendamento e janela de publicação do perfil."""
    settings = get_profile_settings(profile_id, db_path=db_path)
    return getattr(settings, "schedule", ScheduleSettings())


def update_profile_schedule(
    profile_id: str,
    schedule_data: Union[ScheduleSettings, Dict[str, Any]],
    db_path: Optional[str] = None,
) -> ScheduleSettings:
    """Atualiza as configurações de agendamento e janela de publicação do perfil."""
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    clean_id = str(profile_id or "").strip()
    existing = get_profile(clean_id, db_path=db_path)
    if not existing:
        raise ValueError(f"Perfil com ID '{clean_id}' não encontrado.")

    if isinstance(schedule_data, ScheduleSettings):
        model = schedule_data
    elif isinstance(schedule_data, dict):
        model = ScheduleSettings.model_validate(schedule_data)
    else:
        raise ValueError("Dados de agendamento inválidos.")

    if not (0 <= model.publish_start_hour <= 23):
        raise ValueError("publish_start_hour deve estar entre 0 e 23.")
    if not (0 <= model.publish_end_hour <= 23):
        raise ValueError("publish_end_hour deve estar entre 0 e 23.")
    if model.publish_end_hour < model.publish_start_hour:
        raise ValueError("publish_end_hour não pode ser menor que publish_start_hour.")
    if model.min_interval_hours < 1:
        raise ValueError("min_interval_hours deve ser pelo menos 1.")
    if model.posts_per_day < 1:
        raise ValueError("posts_per_day deve ser pelo menos 1.")

    current_settings = get_profile_settings(clean_id, db_path=db_path)
    current_settings.schedule = model
    if model.posts_per_day:
        current_settings.automation.posts_per_day = model.posts_per_day

    update_profile_settings(clean_id, current_settings, db_path=db_path)
    return model


def get_profile_quotas(profile_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retorna as quotas e limites operacionais canônicos do perfil."""
    from app.services import autonomous_production
    clean_id = str(profile_id or "").strip()
    prof = get_profile(clean_id, db_path=db_path)
    if not prof:
        raise ValueError(f"Perfil com ID '{clean_id}' não encontrado.")

    settings = get_profile_settings(clean_id, db_path=db_path)
    growth_mode = prof.get("growth_mode") or const.DEFAULT_GROWTH_MODE
    target_stock = autonomous_production.get_target_ready_stock(clean_id, db_path=db_path)
    max_gen = autonomous_production.get_max_generations_24h(clean_id, db_path=db_path)
    max_att = autonomous_production.get_max_attempts_24h(clean_id, db_path=db_path)
    posts_day = (
        settings.automation.posts_per_day
        or (settings.schedule.posts_per_day if hasattr(settings, "schedule") else None)
        or 1
    )

    return {
        "profile_id": clean_id,
        "growth_mode": growth_mode,
        "target_ready_stock": target_stock,
        "max_generations_24h": max_gen,
        "max_attempts_24h": max_att,
        "posts_per_day": posts_day,
    }


def update_profile_quotas(
    profile_id: str,
    quotas: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Atualiza as quotas e limites operacionais do perfil com validação e clamping canônico."""
    from app.services import autonomous_production, operator_console
    operator_console.require_primary_instance(db_path=db_path)

    clean_id = str(profile_id or "").strip()
    prof = get_profile(clean_id, db_path=db_path)
    if not prof:
        raise ValueError(f"Perfil com ID '{clean_id}' não encontrado.")

    current_settings = get_profile_settings(clean_id, db_path=db_path)

    if "target_ready_stock" in quotas and quotas["target_ready_stock"] is not None:
        target = int(quotas["target_ready_stock"])
        if target < 1:
            raise ValueError("target_ready_stock deve ser >= 1.")
        autonomous_production.set_target_ready_stock(target, profile_id=clean_id, db_path=db_path)
        current_settings.automation.target_ready_stock = target

    if "max_generations_24h" in quotas and quotas["max_generations_24h"] is not None:
        val = int(quotas["max_generations_24h"])
        if val < 1:
            raise ValueError("max_generations_24h deve ser >= 1.")
        autonomous_production.set_max_generations_24h(val, profile_id=clean_id, db_path=db_path)
        current_settings.automation.max_generations_24h = val

    if "max_attempts_24h" in quotas and quotas["max_attempts_24h"] is not None:
        att = int(quotas["max_attempts_24h"])
        if att < 1:
            raise ValueError("max_attempts_24h deve ser >= 1.")
        autonomous_production.set_autonomous_setting(
            f"{autonomous_production.KEY_AUTONOMOUS_MAX_ATTEMPTS_24H}:{clean_id}",
            str(att),
            db_path=db_path,
        )
        current_settings.automation.max_attempts_24h = att

    if "posts_per_day" in quotas and quotas["posts_per_day"] is not None:
        ppd = int(quotas["posts_per_day"])
        if ppd < 1:
            raise ValueError("posts_per_day deve ser >= 1.")
        current_settings.automation.posts_per_day = ppd
        if hasattr(current_settings, "schedule"):
            current_settings.schedule.posts_per_day = ppd

    update_profile_settings(clean_id, current_settings, db_path=db_path)
    return get_profile_quotas(clean_id, db_path=db_path)


def backfill_legacy_channels_external_ids(db_path: Optional[str] = None) -> Dict[str, str]:
    """Preenche deterministicamente o external_account_id dos canais legados homologados sem chamadas externas."""
    init_profile_db(db_path)
    backfilled: Dict[str, str] = {}
    legacy_map = {
        "channel-default-youtube": "UCss-ng7mkGuB2v-5KKtIN9A",
        "channel-historias-misterio-youtube": "UCGJaC83EuaOwiZ0a3-KqUZA",
    }
    with get_connection(db_path) as conn:
        for cid, ext_id in legacy_map.items():
            row = conn.execute(
                "SELECT id, external_account_id FROM publishing_channels WHERE id = ?;",
                (cid,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE publishing_channels SET external_account_id = ?, updated_at = ? WHERE id = ?;",
                    (ext_id, datetime.now(timezone.utc).isoformat(), cid),
                )
                backfilled[cid] = ext_id
    return backfilled


def onboard_channel_workspace(
    name: str,
    niche: str,
    topic_brief: Optional[str] = None,
    language: str = "pt-BR",
    region: str = "BR",
    external_account_id: Optional[str] = None,
    channel_display_name: Optional[str] = None,
    settings: Optional[Union[ChannelWorkspaceSettings, Dict[str, Any]]] = None,
    autonomous_enabled: bool = False,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    platform: str = "youtube",
    require_destination: bool = True,
    video_format: Optional[str] = None,
    closing_type: Optional[str] = None,
    num_questions: Optional[int] = None,
    destinations: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Onboarding atômico de novo workspace/canal.

    Executa em UMA ÚNICA transação SQLite:
    1. Validações preliminares antes da transação (external_account_id para YouTube quando destino exigido).
    2. INSERT em content_profiles com settings_json tipado.
    3. INSERT em publishing_channels com external_account_id e status de ativação de publicação (suporte a multi-destino YouTube e TikTok).
    4. Inicialização de autopilot_settings (autonomous_mode_enabled=False por padrão seguro).
    5. Se qualquer etapa falhar, ROLLBACK completo é executado sem deixar profile órfão.
    """
    from app.services import operator_console
    operator_console.require_primary_instance(db_path=db_path)

    init_profile_db(db_path)
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Nome do canal/workspace não pode ser vazio.")

    clean_niche = str(niche or "").strip()
    if not clean_niche:
        raise ValueError("Nicho não pode ser vazio.")

    clean_plat = _validate_platform(platform)
    clean_lang = "pt-BR"
    clean_reg = "BR"

    clean_ext_id = None
    ch_is_enabled = 1
    if destinations is None:
        if clean_plat == "youtube":
            if require_destination:
                if not external_account_id or not str(external_account_id).strip().startswith("UC"):
                    raise ValueError(
                        "Onboarding de canal YouTube exige conta conectada com external_account_id válido iniciando com 'UC'."
                    )
                clean_ext_id = str(external_account_id).strip()
                ch_is_enabled = 1
            else:
                if external_account_id and str(external_account_id).strip().startswith("UC"):
                    clean_ext_id = str(external_account_id).strip()
                    ch_is_enabled = 1
                else:
                    clean_ext_id = None
                    ch_is_enabled = 0
        else:
            clean_ext_id = str(external_account_id).strip() if external_account_id else None
            ch_is_enabled = 1 if clean_ext_id else 0

    clean_ch_display = str(channel_display_name or f"{clean_name} ({clean_plat.capitalize()})").strip()

    if settings is None:
        settings_model = ChannelWorkspaceSettings()
        # Novos canais criados pelo onboarding recebem defaults operacionais explícitos
        settings_model.voice.voice_name = config.ui.get("voice_name") or config.app.get("voice_name") or "en-US-BrianMultilingualNeural"
        settings_model.voice.voice_rate = 1.0
        settings_model.voice.voice_volume = 1.0
        settings_model.visual.visual_director_enabled = True
        settings_model.visual.flow_enabled = True
        settings_model.visual.flow_scene_count = DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT
        settings_model.visual.stock_fallback_enabled = True
        settings_model.automation.target_ready_stock = 3
    elif isinstance(settings, dict):
        settings_model = ChannelWorkspaceSettings.model_validate(settings)
    elif isinstance(settings, ChannelWorkspaceSettings):
        settings_model = settings.model_copy(deep=True)
    else:
        raise ValueError("Settings inválido para onboarding.")

    if topic_brief:
        settings_model.editorial.topic_brief = str(topic_brief).strip()

    if video_format:
        settings_model.editorial.video_format = str(video_format).strip()
    if closing_type:
        settings_model.editorial.closing_type = str(closing_type).strip()
    if num_questions is not None:
        settings_model.editorial.num_questions = int(num_questions)

    if settings_model.visual.flow_scene_count is None:
        settings_model.visual.flow_scene_count = DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT

    settings_model.automation.autonomous_enabled = bool(autonomous_enabled)
    settings_json_str = settings_model.to_json()

    new_pid = profile_id or f"profile-{uuid.uuid4().hex[:12]}"
    new_slug = generate_slug(clean_name, db_path=db_path)
    new_cid = channel_id or f"channel-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO content_profiles (
                id, name, slug, niche, language, region,
                default_preset, growth_mode, is_active, settings_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                new_pid,
                clean_name,
                new_slug,
                clean_niche,
                clean_lang,
                clean_reg,
                const.DEFAULT_MONETIZATION_PRESET,
                const.GROWTH_MODE_WARMUP,
                1,
                settings_json_str,
                now_iso,
                now_iso,
            ),
        )

        created_channels = []
        if destinations is not None:
            if not destinations:
                # Nenhum destino ativo (somente estoque)
                fallback_cid = new_cid
                conn.execute(
                    """
                    INSERT INTO publishing_channels (
                        id, profile_id, platform, display_name, external_profile_name,
                        external_account_id, project_id, is_enabled, created_at, updated_at
                    ) VALUES (?, ?, 'youtube', ?, NULL, NULL, NULL, 0, ?, ?);
                    """,
                    (fallback_cid, new_pid, f"{clean_name} (Somente Estoque)", now_iso, now_iso),
                )
                created_channels.append(fallback_cid)
            else:
                for d in destinations:
                    d_plat = _validate_platform(d.get("platform", "youtube"))
                    d_ext_id = str(d.get("external_account_id") or "").strip() or None
                    d_project_id = str(d.get("project_id") or "").strip() or None
                    d_is_en = 1 if d.get("is_enabled", True) and d_ext_id else 0
                    d_cid = d.get("channel_id") or f"channel-{uuid.uuid4().hex[:12]}"
                    d_display = str(d.get("display_name") or f"{clean_name} ({d_plat.capitalize()})").strip()

                    if d_plat == "youtube" and d_ext_id and not d_ext_id.startswith("UC"):
                        raise ValueError(f"ID do YouTube deve iniciar com 'UC' (recebido: '{d_ext_id}')")

                    conn.execute(
                        """
                        INSERT INTO publishing_channels (
                            id, profile_id, platform, display_name, external_profile_name,
                            external_account_id, project_id, is_enabled, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            d_cid,
                            new_pid,
                            d_plat,
                            d_display,
                            None,
                            d_ext_id,
                            d_project_id,
                            d_is_en,
                            now_iso,
                            now_iso,
                        ),
                    )
                    created_channels.append(d_cid)
        else:
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, external_profile_name,
                    external_account_id, project_id, is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?);
                """,
                (
                    new_cid,
                    new_pid,
                    clean_plat,
                    clean_ch_display,
                    None,
                    clean_ext_id,
                    ch_is_enabled,
                    now_iso,
                    now_iso,
                ),
            )
            created_channels.append(new_cid)

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
            (f"autonomous_mode_enabled:{new_pid}", "True" if autonomous_enabled else "False"),
        )
        conn.execute(
            """
            INSERT INTO autopilot_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (f"autonomous_target_ready_stock:{new_pid}", str(settings_model.automation.target_ready_stock or 3)),
        )

        p_row = conn.execute("SELECT * FROM content_profiles WHERE id = ?;", (new_pid,)).fetchone()
        primary_cid = created_channels[0] if created_channels else new_cid
        ch_row = conn.execute("SELECT * FROM publishing_channels WHERE id = ?;", (primary_cid,)).fetchone()

    return {
        "ok": True,
        "profile_id": new_pid,
        "profile": dict(p_row),
        "channel": _normalize_channel_dict(dict(ch_row)) if ch_row else {},
        "channel_ids": created_channels,
        "settings": settings_model,
    }


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

    pid = profile.get("id") or DEFAULT_PROFILE_ID
    settings = get_profile_settings(pid, db_path=db_path)

    # Fallbacks da aplicação / config.toml
    fallback_niche = config.app.get("default_niche") or "curiosidades"
    fallback_language = "pt-BR"
    fallback_region = "BR"
    fallback_preset = const.DEFAULT_MONETIZATION_PRESET
    fallback_growth = const.DEFAULT_GROWTH_MODE

    # 1. Voice - Precedência: Global UI (Voz Global da Fábrica) -> Profile Settings -> Global App -> Safe Default
    # O controle 'Voz Global da Fábrica' na Channel Factory define a voz TTS única utilizada por todos os canais.
    global_voice = (
        str(config.ui.get("voice_name")).strip()
        if (config.ui.get("voice_name") and str(config.ui.get("voice_name")).strip())
        else None
    )
    profile_voice = (
        str(settings.voice.voice_name).strip()
        if (settings and settings.voice and settings.voice.voice_name and str(settings.voice.voice_name).strip())
        else None
    )
    fallback_voice = config.app.get("voice_name") or "en-US-BrianMultilingualNeural"
    raw_voice = global_voice or profile_voice or fallback_voice
    from app.services import voice
    voice_name = voice.canonicalize_voice_name(raw_voice) or "en-US-BrianMultilingualNeural"

    global_rate = config.ui.get("voice_rate") or config.app.get("voice_rate") or 1.0
    try:
        voice_rate = settings.voice.voice_rate if settings.voice.voice_rate is not None else float(global_rate)
    except (ValueError, TypeError):
        voice_rate = 1.0

    global_volume = config.ui.get("voice_volume") or config.app.get("voice_volume") or 1.0
    try:
        voice_volume = settings.voice.voice_volume if settings.voice.voice_volume is not None else float(global_volume)
    except (ValueError, TypeError):
        voice_volume = 1.0

    # 2. Resolução Canônica de Formato e Estrutura Narrativa
    raw_fmt = str(settings.editorial.video_format or "").strip().lower()
    raw_style = str(settings.editorial.narrative_structure or settings.editorial.content_style or "").strip().lower()

    if raw_fmt in ("quiz_dilemma", "quiz", "quiz_escolhas_impossiveis") or raw_style in ("quiz_dilemma", "quiz", "quiz_escolhas_impossiveis"):
        resolved_format = const.VIDEO_FORMAT_QUIZ_DILEMMA
        resolved_narrative = None
    elif raw_fmt in ("quiz_paper", "paper") or raw_style in ("quiz_paper", "paper"):
        resolved_format = const.VIDEO_FORMAT_QUIZ_PAPER
        resolved_narrative = None
    else:
        resolved_format = const.VIDEO_FORMAT_TRADITIONAL
        resolved_narrative = raw_style if raw_style in const.NARRATIVE_STRUCTURES else None

    # Normalização de closing_type e num_questions por formato
    raw_closing = str(settings.editorial.closing_type or "").strip()
    if raw_closing.lower() == "comments":
        raw_closing = "score_challenge"

    if settings.editorial.num_questions is not None:
        try:
            num_questions = int(settings.editorial.num_questions)
        except (ValueError, TypeError):
            num_questions = 5 if resolved_format == const.VIDEO_FORMAT_QUIZ_PAPER else 8
    elif resolved_format == const.VIDEO_FORMAT_QUIZ_PAPER:
        num_questions = 5
    elif resolved_format == const.VIDEO_FORMAT_QUIZ_DILEMMA:
        num_questions = 8
    else:
        num_questions = None

    # 3. Visual / Flow (exclusivo para traditional; quiz desativa Flow/Director estritamente)
    if resolved_format in (const.VIDEO_FORMAT_QUIZ_DILEMMA, const.VIDEO_FORMAT_QUIZ_PAPER):
        flow_enabled = False
        visual_director_enabled = False
    else:
        flow_enabled = bool(settings.visual.flow_enabled) if settings.visual.flow_enabled is not None else False
        visual_director_enabled = bool(settings.visual.visual_director_enabled) if settings.visual.visual_director_enabled is not None else False
    flow_scene_count = int(settings.visual.flow_scene_count) if settings.visual.flow_scene_count is not None else DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT
    stock_fallback_enabled = bool(settings.visual.stock_fallback_enabled) if settings.visual.stock_fallback_enabled is not None else True

    # 4. Subtitles
    subtitle_position = settings.subtitle.position if settings.subtitle.position else (config.ui.get("subtitle_position") or "bottom")
    subtitle_font_size = settings.subtitle.font_size if settings.subtitle.font_size is not None else int(config.ui.get("font_size") or 16)

    # 5. Automation (fonte canônica de status é autopilot_settings)
    from app.services import autonomous_production
    canonical_auto_enabled = autonomous_production.is_profile_autonomous_mode_enabled(pid, db_path=db_path)
    canonical_target_stock = autonomous_production.get_target_ready_stock(pid, db_path=db_path)

    return {
        "profile_id": pid,
        "profile_name": profile.get("name") or DEFAULT_PROFILE_NAME,
        "profile_slug": profile.get("slug") or DEFAULT_PROFILE_SLUG,
        "niche": profile.get("niche") or fallback_niche,
        "language": fallback_language,
        "region": fallback_region,
        "default_preset": profile.get("default_preset") or fallback_preset,
        "growth_mode": profile.get("growth_mode") or fallback_growth,
        "topic_brief": settings.editorial.topic_brief or "",
        "content_style": settings.editorial.content_style or "",
        "video_format": resolved_format,
        "narrative_structure": resolved_narrative,
        "closing_type": raw_closing,
        "num_questions": num_questions,
        "voice_name": voice_name,
        "voice_rate": voice_rate,
        "voice_volume": voice_volume,
        "visual_director_enabled": visual_director_enabled,
        "flow_enabled": flow_enabled,
        "flow_scene_count": flow_scene_count,
        "stock_fallback_enabled": stock_fallback_enabled,
        "visual_style_brief": settings.visual.visual_style_brief or "",
        "subtitle_position": subtitle_position,
        "subtitle_font_size": subtitle_font_size,
        "autonomous_enabled": canonical_auto_enabled,
        "target_ready_stock": canonical_target_stock,
        "posts_per_day": settings.automation.posts_per_day or 1,
        "music": settings.music,
        "music_enabled": bool(settings.music.enabled),
        "music_mode": settings.music.mode,
        "music_volume": settings.music.volume,
        "music_default_mood": settings.music.default_mood,
        "settings": settings.model_dump(),
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


# ---------------------------------------------------------------------------
# Identificação de Canais e Formatos (Missão M — Somente Leitura)
# ---------------------------------------------------------------------------

def get_task_origin_channel_name(task_id: str, db_path: Optional[str] = None) -> str:
    """
    Retorna o nome do canal responsável pela tarefa a partir do vínculo persistido:
    task_profiles.task_id -> task_profiles.profile_id -> content_profiles.name.
    Quando não houver vínculo válido, retorna 'Canal não identificado'.
    """
    clean_tid = str(task_id or "").strip()
    if not clean_tid:
        return "Canal não identificado"
    try:
        init_profile_db(db_path)
        with get_connection(db_path) as conn:
            row = conn.execute(
                """
                SELECT cp.name
                FROM task_profiles tp
                JOIN content_profiles cp ON tp.profile_id = cp.id
                WHERE tp.task_id = ?;
                """,
                (clean_tid,),
            ).fetchone()
            if row and row["name"]:
                name = str(row["name"]).strip()
                if name == DEFAULT_PROFILE_NAME:
                    return CHANNEL_DEFAULT_DISPLAY
                return name
    except Exception:
        pass
    return "Canal não identificado"


def get_tasks_origin_channel_names(task_ids: List[str], db_path: Optional[str] = None) -> Dict[str, str]:
    """
    Carregamento em lote dos nomes dos canais de origem das tarefas:
    task_profiles.task_id -> content_profiles.name.
    Retorna dict {task_id: channel_name}. Tarefas sem vínculo válido retornam 'Canal não identificado'.
    """
    if not task_ids:
        return {}
    clean_ids = [str(tid).strip() for tid in task_ids if str(tid).strip()]
    if not clean_ids:
        return {}
    results = {}
    try:
        init_profile_db(db_path)
        placeholders = ",".join("?" for _ in clean_ids)
        with get_connection(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT tp.task_id, cp.name
                FROM task_profiles tp
                JOIN content_profiles cp ON tp.profile_id = cp.id
                WHERE tp.task_id IN ({placeholders});
                """,
                clean_ids,
            ).fetchall()
            for r in rows:
                tid = str(r["task_id"]).strip()
                name = str(r["name"]).strip() if r["name"] else ""
                if name == DEFAULT_PROFILE_NAME:
                    name = CHANNEL_DEFAULT_DISPLAY
                if name:
                    results[tid] = name
    except Exception:
        pass
    for tid in clean_ids:
        if tid not in results:
            results[tid] = "Canal não identificado"
    return results


def get_task_real_structure(
    task_path: Optional[str] = None,
    task_id: Optional[str] = None,
    safety_info: Optional[Dict[str, Any]] = None,
    task_data: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    Determina a estrutura real e o rótulo de exibição a partir dos dados históricos canônicos da tarefa:
    1. task_data / script.json -> params.narrative_structure ou params.video_format
    2. task_data / script.json -> narrative_structure ou video_format
    3. safety_info -> narrative_structure (monetization_safety)
    
    Retorna tupla: (structure_id, display_label).
    Garante mapeamento:
    - 'quiz_paper' / 'multiple_choice_paper' -> 'Quiz de Papel / Perguntas & Respostas'
    - 'quiz_dilemma' -> 'Quiz / Escolhas Impossíveis'
    - Outros formatos -> seus rótulos existentes (Mistério Investigativo, etc.)
    """
    from app.services import safety_gate
    from app.utils import utils

    script_data = None
    if task_data and isinstance(task_data, dict):
        script_data = task_data
    else:
        resolved_path = task_path
        if not resolved_path and task_id:
            resolved_path = os.path.join(utils.task_dir(), task_id)
        if resolved_path and os.path.isdir(resolved_path):
            script_file = os.path.join(resolved_path, "script.json")
            if os.path.isfile(script_file):
                try:
                    with open(script_file, "r", encoding="utf-8") as f:
                        script_data = json.load(f)
                except Exception:
                    pass

    raw_structure = ""
    raw_format = ""
    if script_data and isinstance(script_data, dict):
        params = script_data.get("params")
        if isinstance(params, dict):
            raw_structure = str(params.get("narrative_structure") or "").strip().lower()
            raw_format = str(params.get("video_format") or "").strip().lower()
        if not raw_structure:
            raw_structure = str(script_data.get("narrative_structure") or "").strip().lower()
        if not raw_format:
            raw_format = str(script_data.get("video_format") or "").strip().lower()

    if not raw_structure and safety_info and isinstance(safety_info, dict):
        raw_structure = str(safety_info.get("narrative_structure") or "").strip().lower()

    if raw_structure in ("quiz_paper", "multiple_choice_paper", const.STRUCTURE_QUIZ_PAPER) or raw_format in ("quiz_paper", const.VIDEO_FORMAT_QUIZ_PAPER):
        return (const.STRUCTURE_QUIZ_PAPER, "Quiz de Papel / Perguntas & Respostas")

    if raw_structure in ("quiz_dilemma", "quiz_dilemmas", const.STRUCTURE_QUIZ_DILEMMA) or raw_format in ("quiz_dilemma", const.VIDEO_FORMAT_QUIZ_DILEMMA):
        return (const.STRUCTURE_QUIZ_DILEMMA, "Quiz / Escolhas Impossíveis")

    struct_key = raw_structure or raw_format
    if struct_key:
        if struct_key in ("mystery", "investigative_mystery", const.STRUCTURE_MYSTERY):
            return (const.STRUCTURE_MYSTERY, "Mistério Investigativo")
        spec = safety_gate.get_structure_spec(struct_key)
        if spec and spec.get("name"):
            return (struct_key, spec["name"])
        return (struct_key, struct_key)

    return ("", "—")


def get_posts_destination_channel_names(posts: List[Dict[str, Any]], db_path: Optional[str] = None) -> Dict[Any, str]:
    """
    Carregamento em lote dos nomes dos canais de destino para uma lista de agendamentos:
    scheduled_posts.channel_id -> publishing_channels.
    Retorna mapeamento {post_id: destination_channel_name}.
    Quando não houver canal válido persistido, mapeia para 'Destino não identificado'.
    """
    if not posts:
        return {}
    clean_cids = list({str(p.get("channel_id") or "").strip() for p in posts if str(p.get("channel_id") or "").strip()})
    
    ch_map = {}
    if clean_cids:
        try:
            init_profile_db(db_path)
            placeholders = ",".join("?" for _ in clean_cids)
            with get_connection(db_path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT pc.id, pc.display_name, pc.profile_id, cp.name as profile_name
                    FROM publishing_channels pc
                    LEFT JOIN content_profiles cp ON pc.profile_id = cp.id
                    WHERE pc.id IN ({placeholders});
                    """,
                    clean_cids,
                ).fetchall()
                for r in rows:
                    cid = str(r["id"]).strip()
                    pname = str(r["profile_name"] or "").strip()
                    dname = str(r["display_name"] or "").strip()
                    if pname:
                        if pname == DEFAULT_PROFILE_NAME:
                            ch_map[cid] = CHANNEL_DEFAULT_DISPLAY
                        else:
                            ch_map[cid] = pname
                    elif dname:
                        d_clean = re.sub(r"\s*\((YouTube|TikTok|Somente Estoque|Default)\)\s*$", "", dname, flags=re.IGNORECASE).strip()
                        if d_clean == DEFAULT_PROFILE_NAME or d_clean.lower() == "tiktok":
                            ch_map[cid] = CHANNEL_DEFAULT_DISPLAY
                        else:
                            ch_map[cid] = d_clean or dname
                    else:
                        ch_map[cid] = "Destino não identificado"
        except Exception:
            pass

    results = {}
    for p in posts:
        pid = p.get("id")
        cid = str(p.get("channel_id") or "").strip()
        if not cid or cid not in ch_map:
            results[pid] = "Destino não identificado"
        else:
            results[pid] = ch_map[cid]
    return results


def get_post_destination_channel_name(post: Dict[str, Any], db_path: Optional[str] = None) -> str:
    """
    Retorna o nome do canal de destino de um agendamento a partir de scheduled_posts.channel_id -> publishing_channels.
    Quando channel_id for nulo, vazio, inconsistente ou ausente em publishing_channels, retorna 'Destino não identificado'.
    Não infere destino a partir do perfil da tarefa nem do canal atualmente selecionado no console.
    """
    if not post or not isinstance(post, dict):
        return "Destino não identificado"
    cid = str(post.get("channel_id") or "").strip()
    if not cid:
        return "Destino não identificado"
    
    names = get_posts_destination_channel_names([post], db_path=db_path)
    return names.get(post.get("id"), "Destino não identificado")


def get_all_channel_filter_options(db_path: Optional[str] = None, upcoming_posts: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """
    Descobre dinamicamente os canais existentes para o filtro de Próximos Posts:
    - Perfis ativos e canais cadastrados no banco
    - Destinos identificados nos posts agendados
    Retorna lista iniciando com 'Todos os canais' seguido dos canais em ordem alfabética.
    """
    options = ["Todos os canais"]
    discovered = set()

    try:
        init_profile_db(db_path)
        with get_connection(db_path) as conn:
            p_rows = conn.execute("SELECT name FROM content_profiles;").fetchall()
            for r in p_rows:
                name = str(r["name"] or "").strip()
                if name:
                    if name == DEFAULT_PROFILE_NAME:
                        discovered.add(CHANNEL_DEFAULT_DISPLAY)
                    else:
                        discovered.add(name)

            c_rows = conn.execute("SELECT display_name, profile_id FROM publishing_channels WHERE is_enabled = 1;").fetchall()
            for r in c_rows:
                dname = str(r["display_name"] or "").strip()
                if dname:
                    d_clean = re.sub(r"\s*\((YouTube|TikTok|Somente Estoque)\)\s*$", "", dname, flags=re.IGNORECASE).strip()
                    if d_clean:
                        if d_clean == DEFAULT_PROFILE_NAME:
                            discovered.add(CHANNEL_DEFAULT_DISPLAY)
                        else:
                            discovered.add(d_clean)
    except Exception:
        pass

    if upcoming_posts:
        dest_names = get_posts_destination_channel_names(upcoming_posts, db_path=db_path)
        for name in dest_names.values():
            if name and name != "Destino não identificado":
                discovered.add(name)

    sorted_discovered = sorted(list(discovered))
    return options + sorted_discovered
