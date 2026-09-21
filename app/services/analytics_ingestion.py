"""
Analytics Ingestion Service.
V10-A — Automatic Analytics Provider Foundation.

Responsável por resolver publicações anteriores, obter métricas dos providers
automáticos (YouTube, TikTok), normalizar dados e persistir snapshots de forma
compatível com o sistema existente de analytics, sem duplicar scoring e sem
alterar o estado das tarefas de vídeo em caso de falha.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import sqlite3

from loguru import logger

from app.services import analytics
from app.services.analytics_providers import (
    AnalyticsProviderError,
    ERR_AUTH,
    ERR_NOT_FOUND,
    ERR_PRIVACY_BLOCKED,
    get_provider,
)


@dataclass
class PublishedContentReference:
    """Referência imutável de conteúdo publicado para coleta de métricas."""

    task_id: str
    profile_id: str
    channel_id: Optional[str]
    platform: str
    external_post_id: Optional[str]
    external_url: Optional[str]
    publication_event_id: Optional[int] = None
    published_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_published_content_reference(
    task_id: str,
    platform: str,
    channel_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> PublishedContentReference:
    """
    Resolve os metadados de publicação histórica para uma tarefa e plataforma.
    Garante isolamento estrito de profile e channel sem depender do active_profile.
    """
    clean_tid = str(task_id or "").strip()
    clean_platform = str(platform or "").strip().lower()

    if not clean_tid:
        raise ValueError("task_id must be provided")
    if not clean_platform:
        raise ValueError("platform must be provided")

    # Garante que as tabelas necessárias estejam inicializadas
    from app.services import scheduler
    scheduler.init_db(db_path)

    with scheduler.get_connection(db_path) as conn:
        query = """
            SELECT id, task_id, platform, published_at, status, external_id,
                   provider_request_id, profile_id, channel_id, external_url
            FROM publication_events
            WHERE task_id = ? AND platform = ? AND status = 'success'
        """
        params = [clean_tid, clean_platform]
        if channel_id:
            query += " AND channel_id = ?"
            params.append(channel_id)
        query += " ORDER BY id DESC LIMIT 1;"

        row = conn.execute(query, tuple(params)).fetchone()

    if not row:
        raise AnalyticsProviderError(
            f"Nenhuma publicação com status 'success' encontrada para task '{clean_tid}' na plataforma '{clean_platform}'.",
            code=ERR_NOT_FOUND,
        )

    ext_id = row["external_id"]
    ext_url = row["external_url"] if "external_url" in row.keys() else None
    resolved_channel = row["channel_id"] or channel_id
    resolved_profile = row["profile_id"]

    # Se o publication_events antigo não tinha profile_id persistido, resolve via task_profiles
    if not resolved_profile:
        try:
            from app.services.profile_manager import get_task_profile_id
            resolved_profile = get_task_profile_id(clean_tid, db_path=db_path)
        except Exception:
            resolved_profile = "default"

    # Derivação de URL padrão caso external_url ainda não esteja explícito
    if not ext_url and ext_id:
        if clean_platform == "youtube":
            ext_url = f"https://www.youtube.com/watch?v={ext_id}"
        elif clean_platform == "tiktok":
            ext_url = f"https://www.tiktok.com/video/{ext_id}"

    return PublishedContentReference(
        task_id=clean_tid,
        profile_id=str(resolved_profile),
        channel_id=str(resolved_channel) if resolved_channel else None,
        platform=clean_platform,
        external_post_id=str(ext_id) if ext_id else None,
        external_url=str(ext_url) if ext_url else None,
        publication_event_id=int(row["id"]) if row["id"] else None,
        published_at=str(row["published_at"]) if row["published_at"] else None,
    )


def ingest_analytics_for_publication(
    task_id: str,
    platform: str,
    channel_id: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
    collected_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Executa a ingestão controlada de métricas para uma publicação específica:
    1. Resolve a publicação histórica (task, profile, channel, external_post_id, external_url)
    2. Resolve o provider oficial registrado
    3. Coleta os dados brutos (respeitando dry_run e credenciais)
    4. Normaliza para o modelo padronizado NormalizedAnalytics
    5. Verifica idempotência (mesmo external_post_id + provider + collected_at)
    6. Persiste via pipeline existente (analytics.save_snapshot), reutilizando scoring original
    7. Retorna o snapshot gerado sem alterar o status da task em caso de falha
    """
    # 1. Resolver publicação
    ref = get_published_content_reference(
        task_id=task_id,
        platform=platform,
        channel_id=channel_id,
        db_path=db_path,
    )

    if not ref.external_post_id:
        raise AnalyticsProviderError(
            f"Publicação da task '{ref.task_id}' na plataforma '{ref.platform}' não possui external_post_id para consulta.",
            code=ERR_NOT_FOUND,
        )

    # 2. Resolver provider
    provider = get_provider(ref.platform)

    # 3. Coletar métricas brutas
    raw_data = provider.fetch_metrics(
        external_post_id=ref.external_post_id,
        dry_run=dry_run,
    )

    # 4. Normalizar dados
    normalized = provider.normalize_metrics(
        raw_data,
        external_post_id=ref.external_post_id,
        external_url=ref.external_url,
    )

    if collected_at:
        normalized.collected_at = analytics._parse_iso_dt(collected_at).isoformat()

    # 5. Verificação de Idempotência
    analytics.init_analytics_db(db_path)
    with analytics.get_connection(db_path) as conn:
        existing_row = conn.execute(
            """
            SELECT * FROM content_analytics
            WHERE external_id = ? AND source = ? AND collected_at = ?
            LIMIT 1;
            """,
            (normalized.external_post_id, provider.provider_name, normalized.collected_at),
        ).fetchone()

        if existing_row:
            logger.info(
                f"[ANALYTICS] Snapshot idêntico já registrado para post {normalized.external_post_id} "
                f"via {provider.provider_name} em {normalized.collected_at}. Retornando registro existente."
            )
            d = dict(existing_row)
            if not d.get("source"):
                d["source"] = provider.provider_name
            return d

    # 6. Persistir snapshot via pipeline existente (analytics.save_snapshot)
    snapshot = analytics.save_snapshot(
        task_id=ref.task_id,
        platform=ref.platform,
        views=normalized.views,
        likes=normalized.likes,
        comments=normalized.comments,
        shares=normalized.shares,
        favorites=normalized.favorites,
        average_view_duration=normalized.average_view_duration_seconds,
        average_percentage_viewed=normalized.average_view_percentage,
        completion_rate=normalized.retention_rate,
        subscribers_gained=normalized.followers_gained,
        external_id=normalized.external_post_id,
        external_url=normalized.external_url,
        publication_event_id=ref.publication_event_id,
        published_at=ref.published_at,
        collected_at=normalized.collected_at,
        source=provider.provider_name,
        profile_id=ref.profile_id,
        channel_id=ref.channel_id,
        metadata_json=normalized.raw_metadata,
        db_path=db_path,
    )

    logger.info(
        f"[ANALYTICS] Ingestão concluída com sucesso para task '{ref.task_id}' "
        f"({ref.platform}, provider={provider.provider_name}, score={snapshot.get('performance_score')})"
    )
    return snapshot


def fetch_real_metrics_for_publication(
    task_id: str,
    platform: str,
    channel_id: Optional[str] = None,
    persist: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executa a coleta REAL, manual e controlada de UMA publicação por vez.
    Garante todas as validações de segurança antes de disparar requisição HTTP.

    REQUISITOS (Fase V10-B):
    - chamada manual e controlada
    - UMA publicação por vez
    - requer external_post_id válido
    - sem loop / sem batch / sem cron / sem background worker
    - persist=False: obtém métricas reais, normaliza e retorna SEM gravar no SQLite.
    - persist=True: exige PRIMARY role (VIEW ONLY é bloqueado), normaliza e persiste snapshot.
    """
    clean_tid = str(task_id or "").strip()
    clean_platform = str(platform or "").strip().lower()

    if not clean_tid:
        raise ValueError("task_id must be provided")
    if not clean_platform:
        raise ValueError("platform must be provided")

    # 1. Resolver provedor e validar plataforma
    provider = get_provider(clean_platform)

    # 2. Validar configuração do provedor antes de qualquer chamada
    config_validation = provider.validate_configuration(db_path=db_path)
    if not config_validation.get("configured"):
        missing = config_validation.get("missing_fields", [])
        raise AnalyticsProviderError(
            f"Provedor '{clean_platform}' não está configurado. Campo(s) ausente(s): {missing}.",
            code=ERR_AUTH,
        )

    # 3. Resolver publicação histórica
    ref = get_published_content_reference(
        task_id=clean_tid,
        platform=clean_platform,
        channel_id=channel_id,
        db_path=db_path,
    )

    if not ref.external_post_id:
        raise AnalyticsProviderError(
            f"Publicação da task '{ref.task_id}' na plataforma '{ref.platform}' não possui external_post_id.",
            code=ERR_NOT_FOUND,
        )

    # 3.5. Privacidade do YouTube fail-closed (V12-F.1C): a coleta manual respeita
    # exatamente o mesmo contrato do Analytics automático. PUBLIC precisa estar
    # comprovado (publication_events.privacy_status ou fallback legado task.json)
    # ANTES de qualquer requisição HTTP real, para persist=False e persist=True.
    if clean_platform == "youtube":
        from app.services import analytics_scheduler

        privacy_status = analytics_scheduler.get_known_publication_privacy_status(
            ref.task_id, clean_platform, db_path=db_path
        )
        if privacy_status != analytics_scheduler.PRIVACY_PUBLIC:
            raise AnalyticsProviderError(
                f"Coleta manual bloqueada: privacidade do YouTube não confirmada como PUBLIC "
                f"para a task '{ref.task_id}' (status={privacy_status}).",
                code=ERR_PRIVACY_BLOCKED,
            )

    # 4. Validar formato do external_post_id
    clean_post_id = provider.validate_external_id(ref.external_post_id)

    # 5. Guarda de Single-Instance: se persist=True, exige PRIMARY
    if persist:
        from app.services import operator_console
        operator_console.require_primary_instance(db_path=db_path)

    # 6. Executar coleta real através da API oficial (dry_run=False)
    raw_data = provider.fetch_metrics(
        external_post_id=clean_post_id,
        dry_run=False,
    )

    # 7. Normalizar dados brutos para modelo padronizado
    normalized = provider.normalize_metrics(
        raw_data,
        external_post_id=clean_post_id,
        external_url=ref.external_url,
    )

    # 8. Fluxo SEM persistência (persist=False)
    if not persist:
        logger.info(
            f"[ANALYTICS][REAL_FETCH] Coleta real concluída (sem persistência) para task '{ref.task_id}' "
            f"({ref.platform}, views={normalized.views}, likes={normalized.likes})"
        )
        return {
            "success": True,
            "persisted": False,
            "platform": ref.platform,
            "task_id": ref.task_id,
            "profile_id": ref.profile_id,
            "channel_id": ref.channel_id,
            "external_post_id": clean_post_id,
            "external_url": ref.external_url,
            "metrics": normalized.to_dict(),
        }

    # 9. Fluxo COM persistência (persist=True)
    snapshot = analytics.save_snapshot(
        task_id=ref.task_id,
        platform=ref.platform,
        views=normalized.views,
        likes=normalized.likes,
        comments=normalized.comments,
        shares=normalized.shares,
        favorites=normalized.favorites,
        average_view_duration=normalized.average_view_duration_seconds,
        average_percentage_viewed=normalized.average_view_percentage,
        completion_rate=normalized.retention_rate,
        subscribers_gained=normalized.followers_gained,
        external_id=clean_post_id,
        external_url=ref.external_url,
        publication_event_id=ref.publication_event_id,
        published_at=ref.published_at,
        collected_at=normalized.collected_at,
        source=provider.provider_name,
        profile_id=ref.profile_id,
        channel_id=ref.channel_id,
        metadata_json=normalized.raw_metadata,
        db_path=db_path,
    )

    logger.info(
        f"[ANALYTICS][REAL_FETCH] Coleta real persistida com sucesso para task '{ref.task_id}' "
        f"({ref.platform}, score={snapshot.get('performance_score')})"
    )
    return {
        "success": True,
        "persisted": True,
        "platform": ref.platform,
        "task_id": ref.task_id,
        "profile_id": ref.profile_id,
        "channel_id": ref.channel_id,
        "external_post_id": clean_post_id,
        "external_url": ref.external_url,
        "snapshot": snapshot,
    }
