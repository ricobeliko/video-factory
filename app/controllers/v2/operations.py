"""Operational endpoints for Web UI V2."""

import os
from typing import List, Optional
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
    clean_p = str(profile_id or "").strip()
    if clean_p != profile_manager.DEFAULT_PROFILE_ID and clean_p != "default":
        profile = profile_manager.get_profile(clean_p)
        if not profile:
            raise HttpException(
                task_id=request_id,
                status_code=404,
                message=f"Profile '{profile_id}' not found",
            )

    try:
        operator_console.set_autonomous_mode_enabled_op(
            enabled=body.enabled,
            profile_id=clean_p,
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

    is_auto = autonomous_production.is_profile_autonomous_mode_enabled(clean_p)
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
    from app.services import provider_settings
    data = provider_settings.get_providers_settings_snapshot()
    return utils.get_response(200, data)


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
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"Internal error updating provider settings: {exc}",
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
