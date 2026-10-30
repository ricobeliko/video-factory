"""Operational endpoints for Web UI V2."""

import os
from typing import List, Optional, Dict, Any
from loguru import logger

from fastapi import Depends, Query, Request
from pydantic import BaseModel, Field

from app.models import const

from app.controllers import base
from app.controllers.v2.base import new_router
from app.models.exception import HttpException
from app.services import autonomous_production, operator_console, profile_manager, scheduler
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


@router.get(
    "/system/status",
    summary="Get consolidated system status",
)
def get_system_status(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
):
    status = operator_console.get_system_status(profile_id=profile_id)
    return utils.get_response(200, status)


@router.post(
    "/factory/pause",
    summary="Pause factory operations non-destructively",
)
def pause_factory(request: Request):
    request_id = base.get_task_id(request)
    try:
        operator_console.pause_factory()
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change factory operational state",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error pausing factory",
        )

    state = operator_console.get_factory_state()
    return utils.get_response(
        200,
        {
            "factory_state": state,
            "is_paused": operator_console.is_factory_paused(),
        },
        message="Factory paused successfully",
    )


@router.post(
    "/factory/resume",
    summary="Resume factory operations",
)
def resume_factory(request: Request):
    request_id = base.get_task_id(request)
    try:
        operator_console.resume_factory()
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change factory operational state",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error resuming factory",
        )

    state = operator_console.get_factory_state()
    return utils.get_response(
        200,
        {
            "factory_state": state,
            "is_paused": operator_console.is_factory_paused(),
        },
        message="Factory resumed successfully",
    )


class RunCycleRequest(BaseModel):
    profile_id: Optional[str] = None
    channel_id: Optional[str] = None
    force: bool = True
    one_shot: bool = True


@router.post(
    "/factory/run-cycle",
    summary="Trigger a supervised factory autonomous run cycle",
)
def run_factory_cycle(
    request: Request,
    body: Optional[RunCycleRequest] = None,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
):
    request_id = base.get_task_id(request)
    target_profile_id = (body.profile_id if body and body.profile_id else None) or profile_id
    target_channel_id = body.channel_id if body and body.channel_id else None
    force = body.force if body is not None else True
    one_shot = body.one_shot if body is not None else True

    try:
        result = operator_console.run_autonomous_cycle_op(
            force=force,
            one_shot=one_shot,
            profile_id=target_profile_id,
            channel_id=target_channel_id,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can trigger a factory run cycle",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error running factory cycle",
        )

    if not isinstance(result, dict):
        result = {"status": "completed", "result": result}

    if result.get("status") == "busy" or result.get("reason") in ("cycle_in_progress", "active_tasks_generating"):
        busy_msg = result.get("message") or "Operation blocked: a production cycle is already in progress"
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message=busy_msg,
            data=result,
        )

    if result.get("reason") == "factory_paused":
        raise HttpException(
            task_id=request_id,
            status_code=409,
            message="Operation blocked: factory is paused",
            data=result,
        )

    if result.get("reason") == "secondary_view_only":
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can trigger a factory run cycle",
            data=result,
        )

    return utils.get_response(
        200,
        result,
        message="Autonomous production cycle executed successfully",
    )


@router.get(
    "/profiles",
    summary="List operational profiles overview",
)
def list_profiles(request: Request):
    profiles = operator_console.get_profile_operations_overview()
    return utils.get_response(200, {"profiles": profiles, "total": len(profiles)})


@router.get(
    "/channels",
    summary="Get channels overview for Web UI V2",
)
def get_channels_overview(request: Request):
    profile_overviews = operator_console.get_profile_operations_overview()
    channels_data = []
    for p in profile_overviews:
        pid = p.get("profile_id", "")
        settings = profile_manager.get_profile_settings(pid)
        channels = profile_manager.list_channels(profile_id=pid)
        yt_channel = next((c for c in channels if c.get("platform") == "youtube"), None)
        is_auto = autonomous_production.is_profile_autonomous_mode_enabled(pid)
        target_stock = autonomous_production.get_target_ready_stock(pid)

        channels_data.append({
            "channel_id": pid,
            "profile_id": pid,
            "format": p.get("format") or "traditional",
            "is_quiz": profile_manager.is_quiz_profile(pid),
            "name": p.get("name"),
            "slug": p.get("slug"),
            "niche": p.get("niche") or "—",
            "language": p.get("language") or "pt-BR",
            "region": p.get("region") or "BR",
            "growth_mode": p.get("growth_mode") or "WARMUP",
            "is_active": p.get("is_active", True),
            "is_active_profile": p.get("is_active_profile", False),
            "autonomous_enabled": is_auto,
            "target_stock": target_stock,
            "ready_stock": p.get("ready_stock"),
            "channel_status": p.get("channel_status"),
            "channel_status_label": p.get("channel_status_label"),
            "channel_reason_code": p.get("channel_reason_code"),
            "channel_reason": p.get("channel_reason"),
            "pending_processing": p.get("pending_processing", 0),
            "scheduled": p.get("scheduled", 0),
            "failed": p.get("failed", 0),
            "channels_count": p.get("channels_count", len(channels)),
            "channels_enabled": p.get("channels_enabled", 0),
            "channels": channels,
            "youtube_channel": yt_channel,
            "settings": settings.model_dump(),
        })

    return utils.get_response(200, {"channels": channels_data, "total": len(channels_data)})

class CreateChannelRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Nome do canal")
    niche: str = Field(..., min_length=1, max_length=100, description="Nicho do canal")
    video_format: Optional[str] = Field("traditional", description="traditional, quiz_dilemma, quiz_paper")
    topic_brief: Optional[str] = Field(None, max_length=1000, description="Briefing editorial / tema")
    language: Optional[str] = Field("pt-BR", description="Idioma do canal")
    slug: Optional[str] = Field(None, max_length=100, description="Slug customizado opcional")
    voice_name: Optional[str] = Field(None, description="Voz homologada opcional")

    model_config = {"extra": "forbid"}


@router.post(
    "/channels",
    status_code=201,
    summary="Create a new channel workspace (UI-006 / M2.7)",
)
def create_channel(request: Request, payload: CreateChannelRequest):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()

    # 1. Fail-closed: only PRIMARY instance can create channels
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can create channels",
        )

    # 2. Input validation
    clean_name = str(payload.name or "").strip()
    if not clean_name:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message="Nome do canal não pode ser vazio.",
        )

    clean_niche = str(payload.niche or "").strip()
    if not clean_niche:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message="Nicho do canal não pode ser vazio.",
        )

    clean_format = str(payload.video_format or "traditional").strip().lower()
    valid_formats = {"traditional", "quiz_dilemma", "quiz_paper"}
    if clean_format not in valid_formats:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"Formato de vídeo '{clean_format}' inválido. Opções válidas: traditional, quiz_dilemma, quiz_paper.",
        )

    clean_topic = str(payload.topic_brief or "").strip() if payload.topic_brief else ""
    clean_lang = str(payload.language or "pt-BR").strip() or "pt-BR"

    # 3. Check duplicate name / slug
    with profile_manager.get_connection(db_path) as conn:
        dup_name = conn.execute(
            "SELECT id, name FROM content_profiles WHERE LOWER(TRIM(name)) = LOWER(TRIM(?));",
            (clean_name,),
        ).fetchone()
        if dup_name:
            raise HttpException(
                task_id=request_id,
                status_code=409,
                message=f"Já existe um canal cadastrado com o nome '{clean_name}'. Escolha um nome diferente.",
            )

        if payload.slug and str(payload.slug).strip():
            clean_slug = str(payload.slug).strip().lower()
            dup_slug = conn.execute(
                "SELECT id, slug FROM content_profiles WHERE LOWER(TRIM(slug)) = LOWER(TRIM(?));",
                (clean_slug,),
            ).fetchone()
            if dup_slug:
                raise HttpException(
                    task_id=request_id,
                    status_code=409,
                    message=f"Já existe um canal cadastrado com o slug '{clean_slug}'. Escolha um slug diferente.",
                )
        else:
            clean_slug = None

    # 4. Voice validation & canonical precedence:
    # Precedência: Canal > Global UI > Padrão App > Fallback Brian
    # O canal NÃO pode nascer herdando voz inválida:
    # - Se voice_name foi fornecido, valida se pertence à allowlist homologada
    # - Se omitido (None), deixa sem sobrescrita (voice_name = None) seguindo a precedência canônica
    #   desde que o valor herdado seja válido pt-BR; se porventura a herança for inválida, força fallback seguro homologado.
    if payload.voice_name and str(payload.voice_name).strip():
        req_voice = str(payload.voice_name).strip()
        allowed_list = [v.get("id") for v in profile_manager.get_allowed_voices()]
        from app.services import autonomous_production, voice
        is_allowed = (req_voice in allowed_list) or autonomous_production.is_valid_pt_br_voice(req_voice)
        if not is_allowed:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"Voz '{req_voice}' inválida ou não homologada para pt-BR. Use uma das vozes de /voices/allowed.",
            )
        canon_req = voice.canonicalize_voice_name(req_voice)
        if canon_req.endswith(("-Male", "-Female")):
            canon_req = voice.parse_voice_name(canon_req)
        channel_voice = canon_req
        voice_declaration = "override"
    else:
        from app.config import config
        from app.services import autonomous_production, voice
        candidate = (
            config.ui.get("voice_name")
            or config.app.get("voice_name")
            or "en-US-BrianMultilingualNeural"
        )
        canon_candidate = voice.canonicalize_voice_name(candidate)
        if canon_candidate.endswith(("-Male", "-Female")):
            canon_candidate = voice.parse_voice_name(canon_candidate)

        if autonomous_production.is_valid_pt_br_voice(canon_candidate):
            channel_voice = None  # Sem sobrescrita, herdando via precedência canônica
            voice_declaration = "inherited"
        else:
            channel_voice = "en-US-BrianMultilingualNeural"
            voice_declaration = "fallback_protected"

    # 5. Build ChannelWorkspaceSettings with safe defaults
    settings_obj = profile_manager.ChannelWorkspaceSettings()
    settings_obj.editorial.topic_brief = clean_topic
    settings_obj.editorial.video_format = clean_format
    settings_obj.editorial.content_style = clean_format
    if clean_format == "quiz_paper":
        settings_obj.editorial.closing_type = "comments"
        settings_obj.editorial.num_questions = 5
    elif clean_format == "quiz_dilemma":
        settings_obj.editorial.closing_type = "auto"
        settings_obj.editorial.num_questions = 8
    else:
        settings_obj.editorial.closing_type = None
        settings_obj.editorial.num_questions = None

    settings_obj.voice.voice_name = channel_voice
    # voice_rate e voice_volume herdam (None por padrao no ChannelWorkspaceSettings, igual a V1)

    settings_obj.visual.visual_director_enabled = True
    settings_obj.visual.flow_enabled = True
    settings_obj.visual.flow_scene_count = profile_manager.DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT
    settings_obj.visual.stock_fallback_enabled = True

    # Defaults seguros da V1: modo autônomo DESLIGADO, meta de estoque 3
    settings_obj.automation.autonomous_enabled = False
    settings_obj.automation.target_ready_stock = 3

    settings_obj.music.enabled = False
    settings_obj.music.mode = "auto"
    settings_obj.music.volume = 0.20
    settings_obj.music.default_mood = "neutral"

    # 6. Reutiliza profile_manager.onboard_channel_workspace
    try:
        res = profile_manager.onboard_channel_workspace(
            name=clean_name,
            niche=clean_niche,
            topic_brief=clean_topic,
            language=clean_lang,
            region="BR",
            settings=settings_obj,
            autonomous_enabled=False,
            require_destination=False,
            destinations=[],
            video_format=clean_format,
            closing_type=settings_obj.editorial.closing_type,
            num_questions=settings_obj.editorial.num_questions,
            slug=clean_slug,
            db_path=db_path,
        )
    except ValueError as ve:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(ve),
        )
    except Exception as exc:
        logger.error(f"Erro ao criar canal: {exc}")
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Erro interno ao cadastrar canal.",
        )

    new_pid = res.get("profile_id")
    prof_row = res.get("profile") or {}
    slug_created = prof_row.get("slug")

    # 7. Audit log in operational_events (CHANNEL_CREATED, sem dados sensíveis)
    operator_console.log_operational_event(
        component="channels",
        severity=operator_console.SEVERITY_INFO,
        event_type="CHANNEL_CREATED",
        message=f"Novo canal '{clean_name}' cadastrado com sucesso (profile_id={new_pid}, slug={slug_created})",
        metadata={
            "profile_id": new_pid,
            "channel_name": clean_name,
            "niche": clean_niche,
            "video_format": clean_format,
            "slug": slug_created,
            "autonomous_enabled": False,
            "growth_mode": const.GROWTH_MODE_WARMUP,
            "target_ready_stock": 3,
            "voice_declaration": voice_declaration,
            "voice_override": channel_voice,
        },
        db_path=db_path,
    )

    # Resolve effective voice for verification
    effective_voice_info = profile_manager.get_effective_voice_settings(new_pid, db_path=db_path)

    response_payload = {
        "profile_id": new_pid,
        "name": clean_name,
        "slug": slug_created,
        "niche": clean_niche,
        "video_format": clean_format,
        "growth_mode": const.GROWTH_MODE_WARMUP,
        "autonomous_enabled": False,
        "target_ready_stock": 3,
        "profile": prof_row,
        "channel": res.get("channel") or {},
        "channel_ids": res.get("channel_ids") or [],
        "voice_declaration": voice_declaration,
        "voice_name": channel_voice,
        "effective_voice": effective_voice_info,
        "settings": settings_obj.model_dump(),
    }

    return utils.get_response(
        201,
        response_payload,
        message=f"Canal '{clean_name}' cadastrado com sucesso",
    )


@router.get(
    "/profiles/{profile_id}/status",
    summary="Get status snapshot for a single profile",
)
def get_profile_status(request: Request, profile_id: str):
    request_id = base.get_task_id(request)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    pid = profile.get("id", profile_id)
    auto_status = autonomous_production.get_autonomous_status(profile_id=pid)
    ready_stock = operator_console.get_canonical_ready_stock(profile_id=pid)
    channels = profile_manager.list_channels(profile_id=pid)
    youtube_channel_id = autonomous_production.resolve_autonomous_youtube_channel(pid)

    data = {
        "profile": profile,
        "growth_mode": profile.get("growth_mode", "WARMUP"),
        "is_active": profile.get("is_active", True),
        "autonomous_status": auto_status,
        "canonical_status": auto_status.get("canonical_status"),
        "ready_stock": ready_stock,
        "youtube_channel_id": youtube_channel_id,
        "channels": channels,
    }
    return utils.get_response(200, data)


class UpdateGrowthModeRequest(BaseModel):
    growth_mode: str


class UpdateAutonomousRequest(BaseModel):
    enabled: bool


class UpdateQuotasRequest(BaseModel):
    target_ready_stock: Optional[int] = Field(None, description="Meta de estoque pronto (3 a 10)")
    max_generations_24h: Optional[int] = Field(None, ge=1, le=15, description="Teto de gerações diárias aprovadas")
    max_attempts_24h: Optional[int] = Field(None, ge=1, le=30, description="Teto de tentativas totais de geração em 24h")
    posts_per_day: Optional[int] = Field(None, ge=1, le=10, description="Publicações diárias desejadas")


class UpdateScheduleRequest(BaseModel):
    publish_start_hour: Optional[int] = Field(None, ge=0, le=23, description="Horário inicial da janela de publicação (0-23)")
    publish_end_hour: Optional[int] = Field(None, ge=0, le=23, description="Horário final da janela de publicação (0-23)")
    timezone: Optional[str] = Field(None, description="Fuso horário (ex: America/Sao_Paulo)")
    min_interval_hours: Optional[int] = Field(None, ge=1, le=24, description="Intervalo mínimo entre posts em horas")


class UpdateVoiceSettingsRequest(BaseModel):
    voice_name: Optional[str] = Field(None, description="Identificador da voz TTS homologada pt-BR")
    voice_rate: Optional[float] = Field(None, description="Velocidade da voz (0.5 a 2.0)")
    voice_volume: Optional[float] = Field(None, description="Volume da voz (0.0 a 1.0)")
    tts_server: Optional[str] = Field(None, description="Provedor de TTS (ex: azure-tts-v1, elevenlabs)")


class UpdateSchedulerSettingsRequest(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    auto_publish_enabled: Optional[bool] = Field(None, description="Habilita ou desabilita a publicação automática")
    scheduler_enabled: Optional[bool] = Field(None, description="Habilita ou desabilita o agendamento de posts")
    dry_run: Optional[bool] = Field(None, description="Habilita ou desabilita o modo de simulação (dry run)")


class UpdateProviderSettingsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    llm_provider: Optional[str] = Field(None, description="Provedor LLM ativo (ex: gemini, openai, moonshot)")
    llm_api_key: Optional[str] = Field(None, description="Chave de API para o provedor LLM ativo")
    llm_model_name: Optional[str] = Field(None, description="Nome do modelo para o provedor LLM ativo")
    llm_base_url: Optional[str] = Field(None, description="Base URL para o provedor LLM ativo")

    upload_post_enabled: Optional[bool] = Field(None, description="Habilita ou desabilita Upload-Post")
    upload_post_auto_upload: Optional[bool] = Field(None, description="Habilita auto-upload no Upload-Post")
    upload_post_api_key: Optional[str] = Field(None, description="Chave de API do Upload-Post")
    upload_post_username: Optional[str] = Field(None, description="Username/perfil do Upload-Post")
    upload_post_platforms: Optional[List[str]] = Field(None, description="Plataformas ativas (youtube, tiktok, instagram)")
    upload_post_youtube_privacy_status: Optional[str] = Field(None, description="Privacidade YouTube (public, private, unlisted)")
    upload_post_youtube_made_for_kids: Optional[bool] = Field(None, description="Made for Kids (true, false)")


@router.patch(
    "/channels/{profile_id}/growth-mode",
    summary="Update channel Growth Mode (WARMUP / SCALE)",
)
def update_profile_growth_mode(
    request: Request,
    profile_id: str,
    body: UpdateGrowthModeRequest,
):
    request_id = base.get_task_id(request)
    profile = profile_manager.get_profile(profile_id)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    try:
        updated = profile_manager.update_profile(
            profile_id=profile_id,
            growth_mode=body.growth_mode,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change growth mode",
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error updating growth mode",
        )

    clean_mode = updated.get("growth_mode", body.growth_mode)
    return utils.get_response(
        200,
        {
            "profile_id": profile_id,
            "growth_mode": clean_mode,
        },
        message=f"Growth mode for profile '{profile_id}' updated to {clean_mode.upper()}",
    )


@router.patch(
    "/channels/{profile_id}/autonomous",
    summary="Enable or pause autonomous production for a channel",
)
def update_profile_autonomous_mode(
    request: Request,
    profile_id: str,
    body: UpdateAutonomousRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()

    # Fail-closed: only PRIMARY instance can change autonomous mode
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change autonomous mode",
        )

    clean_p = str(profile_id or "").strip()
    if clean_p != profile_manager.DEFAULT_PROFILE_ID and clean_p != "default":
        profile = profile_manager.get_profile(clean_p, db_path=db_path)
        if not profile:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"Profile '{profile_id}' not found",
            )

    # Fail-closed guard: cannot enable autonomous mode if channel has no publish destinations enabled
    if body.enabled:
        active_plats = autonomous_production.get_channel_active_platforms(clean_p, db_path=db_path)
        if not active_plats:
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message="Canal sem destino de publicação habilitado",
            )

    try:
        operator_console.set_autonomous_mode_enabled_op(
            enabled=body.enabled,
            profile_id=clean_p,
            db_path=db_path,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change autonomous mode",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Internal error updating autonomous mode",
        )

    is_auto = autonomous_production.is_profile_autonomous_mode_enabled(clean_p, db_path=db_path)
    return utils.get_response(
        200,
        {
            "profile_id": clean_p,
            "autonomous_enabled": is_auto,
        },
        message=f"Autonomous mode for profile '{clean_p}' {'enabled' if is_auto else 'disabled'}",
    )


@router.get(
    "/channels/{profile_id}/settings",
    summary="Get comprehensive per-profile settings including quotas and schedule (R7 Phase 2)",
)
def get_channel_settings(request: Request, profile_id: str):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    profile = profile_manager.get_profile(profile_id, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )
    clean_p = profile.get("id", profile_id)
    quotas = profile_manager.get_profile_quotas(clean_p, db_path=db_path)
    schedule_model = profile_manager.get_profile_schedule(clean_p, db_path=db_path)
    is_auto = autonomous_production.is_profile_autonomous_mode_enabled(clean_p, db_path=db_path)
    ws_settings = profile_manager.get_profile_settings(clean_p, db_path=db_path)
    effective_v = profile_manager.get_effective_voice_settings(clean_p, db_path=db_path)

    data = {
        "profile_id": clean_p,
        "profile_name": profile.get("name"),
        "growth_mode": profile.get("growth_mode", "WARMUP"),
        "autonomous_enabled": is_auto,
        "quotas": quotas,
        "schedule": schedule_model.model_dump(),
        "workspace_settings": ws_settings.model_dump(),
        "effective_voice": effective_v,
        "is_quiz": profile_manager.is_quiz_profile(clean_p, db_path=db_path),
    }
    return utils.get_response(200, data)


@router.patch(
    "/channels/{profile_id}/quotas",
    summary="Update quotas and generation limits for a channel/profile (R7 Phase 2)",
)
def update_channel_quotas(
    request: Request,
    profile_id: str,
    payload: UpdateQuotasRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    profile = profile_manager.get_profile(profile_id, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )
    clean_p = profile.get("id", profile_id)

    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile quotas ({exc})",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile quotas ({exc})",
        )

    try:
        q_dict = payload.model_dump(exclude_unset=True)
        old_quotas = profile_manager.get_profile_quotas(clean_p, db_path=db_path)
        res = profile_manager.update_profile_quotas(clean_p, q_dict, db_path=db_path)
        for k, v in q_dict.items():
            old_v = old_quotas.get(k)
            if old_v != v:
                operator_console.log_operational_event(
                    component="profile_manager",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="PROFILE_QUOTAS_UPDATED",
                    message=f"Quota '{k}' updated for profile '{clean_p}': {old_v} -> {v}",
                    metadata={
                        "profile_id": clean_p,
                        "field": k,
                        "old_value": old_v,
                        "new_value": v,
                    },
                    db_path=db_path,
                )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error updating profile quotas: {exc}",
        )

    return utils.get_response(200, res, message="Profile quotas updated successfully")


@router.patch(
    "/channels/{profile_id}/schedule",
    summary="Update schedule and publishing window for a channel/profile (R7 Phase 2)",
)
def update_channel_schedule(
    request: Request,
    profile_id: str,
    payload: UpdateScheduleRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    profile = profile_manager.get_profile(profile_id, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )
    clean_p = profile.get("id", profile_id)

    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile schedule ({exc})",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile schedule ({exc})",
        )

    try:
        s_dict = payload.model_dump(exclude_unset=True)
        old_schedule = profile_manager.get_profile_schedule(clean_p, db_path=db_path).model_dump()
        cur_sched = dict(old_schedule)
        cur_sched.update(s_dict)
        res = profile_manager.update_profile_schedule(clean_p, cur_sched, db_path=db_path)
        for k, v in s_dict.items():
            old_v = old_schedule.get(k)
            if old_v != v:
                operator_console.log_operational_event(
                    component="profile_manager",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="PROFILE_SCHEDULE_UPDATED",
                    message=f"Schedule '{k}' updated for profile '{clean_p}': {old_v} -> {v}",
                    metadata={
                        "profile_id": clean_p,
                        "field": k,
                        "old_value": old_v,
                        "new_value": v,
                    },
                    db_path=db_path,
                )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error updating profile schedule: {exc}",
        )

    return utils.get_response(200, res.model_dump(), message="Profile schedule updated successfully")


@router.patch(
    "/channels/{profile_id}/voice",
    summary="Update voice settings for a channel/profile (M6a)",
)
def update_channel_voice(
    request: Request,
    profile_id: str,
    payload: UpdateVoiceSettingsRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    profile = profile_manager.get_profile(profile_id, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )
    clean_p = profile.get("id", profile_id)

    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile voice ({exc})",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"Operation blocked: only primary instance can update profile voice ({exc})",
        )

    try:
        v_dict = payload.model_dump(exclude_unset=True)
        old_settings = profile_manager.get_profile_settings(clean_p, db_path=db_path)
        old_voice_dict = {
            "voice_name": old_settings.voice.voice_name,
            "voice_rate": old_settings.voice.voice_rate,
            "voice_volume": old_settings.voice.voice_volume,
            "tts_server": getattr(old_settings.voice, "tts_server", None),
        }
        res = profile_manager.update_profile_voice_settings(clean_p, v_dict, db_path=db_path)
        new_settings = profile_manager.get_profile_settings(clean_p, db_path=db_path)
        new_voice_dict = {
            "voice_name": new_settings.voice.voice_name,
            "voice_rate": new_settings.voice.voice_rate,
            "voice_volume": new_settings.voice.voice_volume,
            "tts_server": getattr(new_settings.voice, "tts_server", None),
        }
        for k in v_dict.keys():
            old_v = old_voice_dict.get(k)
            new_v = new_voice_dict.get(k)
            if old_v != new_v:
                operator_console.log_operational_event(
                    component="profile_manager",
                    severity=operator_console.SEVERITY_INFO,
                    event_type="PROFILE_VOICE_UPDATED",
                    message=f"Voice setting '{k}' updated for profile '{clean_p}': {old_v} -> {new_v}",
                    metadata={
                        "profile_id": clean_p,
                        "field": k,
                        "old_value": old_v,
                        "new_value": new_v,
                    },
                    db_path=db_path,
                )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error updating profile voice: {exc}",
        )

    return utils.get_response(200, res, message="Profile voice updated successfully")


@router.get(
    "/scheduler/posts",
    summary="Get scheduler queue summary",
)
def get_scheduler_posts(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Optional profile ID filter"
    ),
    limit: int = Query(
        default=50, ge=1, le=100, description="Max upcoming posts to inspect"
    ),
):
    summary = operator_console.get_scheduler_queue_summary(limit=limit)
    if profile_id:
        summary["upcoming_posts"] = [
            p for p in summary.get("upcoming_posts", [])
            if p.get("profile_id") == profile_id
        ]
    return utils.get_response(200, summary)


@router.patch(
    "/scheduler/settings",
    summary="Update global scheduler settings (auto_publish_enabled, scheduler_enabled, dry_run)",
)
def update_scheduler_settings(
    request: Request,
    payload: UpdateSchedulerSettingsRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can change scheduler settings",
        )

    update_dict = payload.model_dump(exclude_unset=True)
    if not update_dict:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message="No valid scheduler settings provided to update",
        )

    old_settings = scheduler.get_all_settings(db_path=db_path)

    for k, v in update_dict.items():
        old_v = old_settings.get(k)
        scheduler.set_setting(k, v, db_path=db_path)
        if old_v != v:
            operator_console.log_operational_event(
                component="scheduler",
                severity=operator_console.SEVERITY_INFO,
                event_type="SCHEDULER_SETTINGS_UPDATED",
                message=f"Scheduler setting '{k}' updated: {old_v} -> {v}",
                metadata={
                    "field": k,
                    "old_value": old_v,
                    "new_value": v,
                },
                db_path=db_path,
            )

    current = scheduler.get_all_settings(db_path=db_path)
    return utils.get_response(
        200,
        {
            "scheduler_enabled": current["scheduler_enabled"],
            "auto_publish_enabled": current["auto_publish_enabled"],
            "dry_run": current["dry_run"],
        },
        message="Scheduler settings updated successfully",
    )


@router.get(
    "/settings/providers",
    summary="Get active LLM and social publishing provider settings with masked keys",
)
def get_provider_settings(request: Request):
    request_id = base.get_task_id(request)
    from app.services import provider_settings
    try:
        data = provider_settings.get_providers_settings_snapshot()
        return utils.get_response(200, data)
    except Exception as exc:
        logger.error(f"Erro ao obter configuracoes de provedores: {type(exc).__name__}")
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Falha ao ler o arquivo de configuracao no disco (TOML invalido ou inacessivel).",
        )


@router.patch(
    "/settings/providers",
    summary="Update LLM and social publishing provider settings",
)
def update_provider_settings(
    request: Request,
    payload: UpdateProviderSettingsRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can update provider settings",
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message="No valid provider settings provided to update",
        )

    from app.services import provider_settings
    try:
        data, updated_fields = provider_settings.update_providers_settings(
            updates=updates,
            db_path=db_path,
        )
        return utils.get_response(
            200,
            data,
            message=f"Provider settings updated successfully ({len(updated_fields)} fields changed)",
        )
    except ValueError as exc:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        logger.error(f"Erro ao atualizar configuracoes de provedores: {type(exc).__name__}")
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message="Falha ao processar ou gravar configuracao no disco (TOML invalido ou inacessivel).",
        )


@router.post(
    "/scheduler/run-cycle",
    summary="Trigger manual run of publication scheduler cycle",
)
def trigger_scheduler_cycle(request: Request):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can run scheduler cycle",
        )

    try:
        result = scheduler.run_scheduler_cycle(db_path=db_path)
        operator_console.log_operational_event(
            component="scheduler",
            severity=operator_console.SEVERITY_INFO,
            event_type="SCHEDULER_CYCLE_TRIGGERED",
            message=f"Ciclo de publicação disparado manualmente: {result.get('status', 'unknown')}",
            metadata={"result": result},
            db_path=db_path,
        )
        return utils.get_response(200, result, message="Scheduler cycle executed successfully")
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error executing scheduler cycle: {exc}",
        )


@router.post(
    "/scheduler/plan",
    summary="Trigger manual schedule planning for completed unposted videos",
)
def plan_scheduler_schedule(request: Request):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can plan schedule",
        )

    try:
        from app.services import state as sm
        tasks_root = utils.task_dir()
        tasks_map = {}

        # 1. Carrega do state em memória
        try:
            runtime_tasks, _ = sm.state.get_all_tasks(1, 2000)
            for t in runtime_tasks:
                tid = t.get("task_id")
                if tid:
                    tasks_map[tid] = dict(t)
        except Exception as exc:
            logger.warning(f"Failed to fetch runtime tasks from state: {exc}")

        # 2. Varre diretório físico de tasks
        if os.path.exists(tasks_root):
            try:
                with os.scandir(tasks_root) as entries:
                    for entry in entries:
                        if entry.is_dir() and not entry.name.startswith("."):
                            tid = entry.name
                            if tid not in tasks_map:
                                video_file = scheduler.get_task_final_video(tid, task_base_dir=tasks_root)
                                if video_file:
                                    tasks_map[tid] = {
                                        "task_id": tid,
                                        "state": const.TASK_STATE_COMPLETE,
                                        "video_file": video_file,
                                    }
            except Exception as exc:
                logger.warning(f"Failed to scan task files for planning: {exc}")

        all_tasks = list(tasks_map.values())
        new_scheduled = scheduler.plan_schedule(all_tasks, db_path=db_path)
        planned_count = int(new_scheduled) if isinstance(new_scheduled, int) else len(new_scheduled)

        operator_console.log_operational_event(
            component="scheduler",
            severity=operator_console.SEVERITY_INFO,
            event_type="SCHEDULE_PLANNED",
            message=f"Planejamento de agenda executado: {planned_count} posts agendados",
            metadata={
                "planned_count": planned_count,
            },
            db_path=db_path,
        )
        return utils.get_response(
            200,
            {
                "planned_count": planned_count,
            },
            message=f"Schedule planned: {planned_count} new posts scheduled",
        )
    except Exception as exc:
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error planning schedule: {exc}",
        )


@router.get(
    "/publications",
    summary="List recent publication events",
)
def list_publications(
    request: Request,
    profile_id: Optional[str] = Query(
        default=None, description="Filter by profile ID"
    ),
    limit: int = Query(
        default=20, ge=1, le=100, description="Number of events to return"
    ),
):
    items = operator_console.get_recent_publications(limit=limit, profile_id=profile_id)
    return utils.get_response(200, {"publications": items, "total": len(items)})


@router.get(
    "/providers/health",
    summary="Get passive provider health summary",
)
def get_provider_health(request: Request):
    health = operator_console.get_provider_health_summary()
    return utils.get_response(200, health)


@router.get(
    "/executions/live",
    summary="Get live multi-channel execution overview (UI-005)",
)
def get_live_executions(request: Request):
    overview = operator_console.get_live_execution_overview()
    return utils.get_response(200, overview)


@router.get(
    "/executions/{task_id}",
    summary="Get execution trace detail for a specific task (UI-005)",
)
def get_task_execution(request: Request, task_id: str):
    request_id = base.get_task_id(request)
    detail = operator_console.get_execution_detail(task_id)
    if not detail:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Execution for task '{task_id}' not found",
        )
    return utils.get_response(200, detail)


@router.get(
    "/agent-ops",
    summary="Get Agent Ops live observability snapshot (Agent Ops V1.1)",
)
def get_agent_ops(request: Request):
    from app.services import agent_ops
    snapshot = agent_ops.get_agent_ops_snapshot()
    return utils.get_response(200, snapshot)


@router.get(
    "/health",
    summary="Get Web UI V2 and API operational readiness",
)
def get_v2_health(request: Request):
    from app.config import config
    import os
    webui_dist = utils.webui_v2_dist_dir()
    webui_built = os.path.isdir(webui_dist) and os.path.isfile(
        os.path.join(webui_dist, "index.html")
    )
    db_path = operator_console.get_db_path()
    is_primary = operator_console.is_primary_instance(db_path=db_path)
    role = (
        operator_console.ROLE_PRIMARY
        if is_primary
        else operator_console.ROLE_SECONDARY_VIEW_ONLY
    )
    return utils.get_response(
        200,
        {
            "status": "healthy",
            "app": config.project_name,
            "version": config.project_version,
            "role": role,
            "is_primary": is_primary,
            "webui_v2_available": webui_built,
            "same_origin": True,
        },
    )


@router.get(
    "/voices/allowed",
    summary="Get list of approved TTS voices for channels (M6b)",
)
def get_allowed_voices(request: Request):
    voices = profile_manager.get_allowed_voices()
    return utils.get_response(200, voices)

class DestinationUpdateRequestItem(BaseModel):
    model_config = {"extra": "forbid"}
    platform: str = Field(..., description="Plataforma do destino (youtube ou tiktok)")
    is_enabled: Optional[bool] = Field(None, description="Habilitar ou desabilitar o destino")
    external_account_id: Optional[str] = Field(None, description="ID da conta externa (UC... para YouTube)")
    project_id: Optional[str] = Field(None, description="ID do projeto no Post for Me / Upload-Post")
    display_name: Optional[str] = Field(None, description="Nome de exibição opcional")
    auto_publish_authorized: Optional[bool] = Field(None, description="Autorizar publicação automática sem revisão")


class UpdateChannelDestinationsRequest(BaseModel):
    model_config = {"extra": "forbid"}
    platform: Optional[str] = Field(None, description="Plataforma do destino (youtube ou tiktok)")
    is_enabled: Optional[bool] = Field(None, description="Habilitar ou desabilitar o destino")
    external_account_id: Optional[str] = Field(None, description="ID da conta externa (UC... para YouTube)")
    project_id: Optional[str] = Field(None, description="ID do projeto no Post for Me / Upload-Post")
    display_name: Optional[str] = Field(None, description="Nome de exibição opcional")
    auto_publish_authorized: Optional[bool] = Field(None, description="Autorizar publicação automática sem revisão")
    destinations: Optional[List[DestinationUpdateRequestItem]] = Field(None, description="Lista para atualização múltipla")


@router.get(
    "/channels/{profile_id}/destinations",
    summary="Get configured destinations for a channel",
)
def get_channel_destinations(request: Request, profile_id: str):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()
    clean_p = str(profile_id or "").strip()
    profile = profile_manager.get_profile(clean_p, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    all_channels = profile_manager.list_channels(profile_id=clean_p, db_path=db_path)
    yt_ch = next((c for c in all_channels if c.get("platform") == "youtube"), None)
    tt_ch = next((c for c in all_channels if c.get("platform") == "tiktok"), None)

    destinations = [
        {
            "id": yt_ch.get("id") if yt_ch else None,
            "platform": "youtube",
            "is_enabled": bool(yt_ch.get("is_enabled", 0)) if yt_ch else False,
            "external_account_id": yt_ch.get("external_account_id") if yt_ch else None,
            "project_id": yt_ch.get("project_id") if yt_ch else None,
            "display_name": yt_ch.get("display_name") if yt_ch else None,
            "auto_publish_authorized": bool(yt_ch.get("auto_publish_authorized", 0)) if yt_ch else False,
        },
        {
            "id": tt_ch.get("id") if tt_ch else None,
            "platform": "tiktok",
            "is_enabled": bool(tt_ch.get("is_enabled", 0)) if tt_ch else False,
            "external_account_id": tt_ch.get("external_account_id") if tt_ch else None,
            "project_id": tt_ch.get("project_id") if tt_ch else None,
            "display_name": tt_ch.get("display_name") if tt_ch else None,
            "auto_publish_authorized": bool(tt_ch.get("auto_publish_authorized", 0)) if tt_ch else False,
        },
    ]

    by_platform = {d["platform"]: d for d in destinations}

    return utils.get_response(
        200,
        {
            "profile_id": clean_p,
            "destinations": destinations,
            "by_platform": by_platform,
        },
    )


@router.patch(
    "/channels/{profile_id}/destinations",
    summary="Update or create publishing destinations for a channel",
)
def update_channel_destinations(
    request: Request,
    profile_id: str,
    body: UpdateChannelDestinationsRequest,
):
    request_id = base.get_task_id(request)
    db_path = operator_console.get_db_path()

    # 1. Fail-closed: only PRIMARY instance can modify destinations
    try:
        operator_console.require_primary_instance(db_path=db_path)
    except PermissionError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message="Operation blocked: only primary instance can update channel destinations",
        )

    clean_p = str(profile_id or "").strip()
    profile = profile_manager.get_profile(clean_p, db_path=db_path)
    if not profile:
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"Profile '{profile_id}' not found",
        )

    # 2. Extract destination items to process
    items_to_process: List[DestinationUpdateRequestItem] = []
    if body.destinations:
        items_to_process.extend(body.destinations)
    elif body.platform:
        items_to_process.append(
            DestinationUpdateRequestItem(
                platform=body.platform,
                is_enabled=body.is_enabled,
                external_account_id=body.external_account_id,
                project_id=body.project_id,
                display_name=body.display_name,
                auto_publish_authorized=body.auto_publish_authorized,
            )
        )
    else:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message="Nenhum destino especificado para atualização.",
        )

    # 3. Process each destination
    existing_channels = profile_manager.list_channels(profile_id=clean_p, db_path=db_path)
    for item in items_to_process:
        plat = str(item.platform or "").lower().strip()
        if plat not in ("youtube", "tiktok"):
            raise HttpException(
                task_id=request_id,
                status_code=400,
                message=f"Plataforma '{item.platform}' inválida. Use 'youtube' ou 'tiktok'.",
            )

        clean_ext = str(item.external_account_id).strip() if item.external_account_id is not None else None
        if plat == "youtube" and clean_ext:
            if not clean_ext.startswith("UC"):
                raise HttpException(
                    task_id=request_id,
                    status_code=400,
                    message=f"O YouTube Channel ID deve iniciar com 'UC' (recebido: '{clean_ext}').",
                )

        clean_proj = str(item.project_id).strip() if item.project_id is not None else None

        existing_dest = next((c for c in existing_channels if c.get("platform") == plat), None)

        if existing_dest:
            cid = existing_dest["id"]
            upd_kwargs: Dict[str, Any] = {"db_path": db_path}
            if item.is_enabled is not None:
                upd_kwargs["is_enabled"] = bool(item.is_enabled)
            if item.external_account_id is not None:
                upd_kwargs["external_account_id"] = clean_ext or None
            if item.project_id is not None:
                upd_kwargs["project_id"] = clean_proj or None
            if item.display_name is not None:
                upd_kwargs["display_name"] = str(item.display_name).strip() if item.display_name else None

            profile_manager.update_channel(cid, **upd_kwargs)

            if item.auto_publish_authorized is not None:
                scheduler.set_channel_auto_publish_authorized(
                    cid, bool(item.auto_publish_authorized), db_path=db_path
                )
        else:
            prof_name = profile.get("name") or clean_p
            disp_name = item.display_name or f"{prof_name} ({plat.title()})"
            is_en = bool(item.is_enabled) if item.is_enabled is not None else True
            created = profile_manager.create_channel(
                profile_id=clean_p,
                platform=plat,
                display_name=disp_name,
                external_profile_name=prof_name,
                external_account_id=clean_ext,
                project_id=clean_proj,
                is_enabled=is_en,
                db_path=db_path,
            )
            cid = created["id"]
            if item.auto_publish_authorized is not None:
                scheduler.set_channel_auto_publish_authorized(
                    cid, bool(item.auto_publish_authorized), db_path=db_path
                )
            # Re-fetch for subsequent iterations
            existing_channels = profile_manager.list_channels(profile_id=clean_p, db_path=db_path)

        # Audit event without secrets
        operator_console.log_operational_event(
            component="channels",
            severity=operator_console.SEVERITY_INFO,
            event_type="CHANNEL_DESTINATION_UPDATED",
            message=f"Destino de publicação '{plat}' atualizado para canal '{clean_p}'",
            metadata={
                "profile_id": clean_p,
                "channel_id": cid,
                "platform": plat,
                "is_enabled": item.is_enabled,
                "external_account_id": clean_ext,
                "project_id": clean_proj,
                "auto_publish_authorized": item.auto_publish_authorized,
            },
            db_path=db_path,
        )

    # 4. Return updated destinations
    refetched = profile_manager.list_channels(profile_id=clean_p, db_path=db_path)
    yt_ch = next((c for c in refetched if c.get("platform") == "youtube"), None)
    tt_ch = next((c for c in refetched if c.get("platform") == "tiktok"), None)

    destinations = [
        {
            "id": yt_ch.get("id") if yt_ch else None,
            "platform": "youtube",
            "is_enabled": bool(yt_ch.get("is_enabled", 0)) if yt_ch else False,
            "external_account_id": yt_ch.get("external_account_id") if yt_ch else None,
            "project_id": yt_ch.get("project_id") if yt_ch else None,
            "display_name": yt_ch.get("display_name") if yt_ch else None,
            "auto_publish_authorized": bool(yt_ch.get("auto_publish_authorized", 0)) if yt_ch else False,
        },
        {
            "id": tt_ch.get("id") if tt_ch else None,
            "platform": "tiktok",
            "is_enabled": bool(tt_ch.get("is_enabled", 0)) if tt_ch else False,
            "external_account_id": tt_ch.get("external_account_id") if tt_ch else None,
            "project_id": tt_ch.get("project_id") if tt_ch else None,
            "display_name": tt_ch.get("display_name") if tt_ch else None,
            "auto_publish_authorized": bool(tt_ch.get("auto_publish_authorized", 0)) if tt_ch else False,
        },
    ]

    return utils.get_response(
        200,
        {
            "profile_id": clean_p,
            "destinations": destinations,
            "by_platform": {d["platform"]: d for d in destinations},
        },
        message=f"Destinos de publicação para canal '{clean_p}' atualizados com sucesso.",
    )


@router.get(
    "/publishing/accounts",
    summary="List connected publishing accounts from post_for_me",
)
def list_publishing_accounts(
    request: Request,
    platform: Optional[str] = Query(default=None, description="Optional platform filter (youtube, tiktok)"),
):
    request_id = base.get_task_id(request)
    from app.services import post_for_me
    accounts = []
    clean_platform = str(platform).strip().lower() if platform else None
    if clean_platform and clean_platform not in ("youtube", "tiktok"):
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"Plataforma '{clean_platform}' inválida. Use 'youtube' ou 'tiktok'.",
        )

    platforms_to_query = [clean_platform] if clean_platform else ["youtube", "tiktok"]
    for plat in platforms_to_query:
        try:
            accs = post_for_me.list_connected_publishing_accounts(platform=plat)
            if isinstance(accs, list):
                accounts.extend(accs)
        except Exception as exc:
            logger.warning(f"Falha ao consultar contas conectadas de {plat}: {exc}")

    return utils.get_response(200, {"accounts": accounts, "total": len(accounts)})
