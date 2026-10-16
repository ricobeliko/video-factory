# -*- coding: utf-8 -*-
"""
app/controllers/v2/review.py
============================
Endpoints da Central de Revisão Humana de Vídeos (QG-V2.2 Complemento).

Permite aos operadores autorizados:
- Listar a fila de revisão (pendentes, aprovados, descartados, todos).
- Assistir ao vídeo final (.mp4) de forma segura contra path-traversal.
- Aprovar vídeos elegíveis ou com override editorial (score < 70) para o Ready Stock.
- Descartar vídeos permanentemente sem exclusão de arquivos de mídia.
- Operar em conformidade com o modelo PRIMARY / SECONDARY_VIEW_ONLY através de ponte segura.
"""

import os
import re
from typing import Optional

from fastapi import Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v2.base import new_router
from app.models.exception import HttpException
from app.services import quality_recovery
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])

SAFE_TASK_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class ApproveReviewRequest(BaseModel):
    operator_id: Optional[str] = Field(default="operator", description="Identificação do operador editorial")
    note: Optional[str] = Field(default=None, description="Nota ou justificativa editorial opcional")
    confirm: str = Field(default="APPROVE_FOR_STOCK", description="Confirmação explícita obrigatória")


class DiscardReviewRequest(BaseModel):
    operator_id: Optional[str] = Field(default="operator", description="Identificação do operador")
    note: Optional[str] = Field(default=None, description="Motivo ou nota do descarte opcional")
    confirm: str = Field(default="DISCARD_HELD_VIDEO", description="Confirmação explícita obrigatória")


@router.get(
    "/review/tasks",
    summary="Get human video review queue tasks and summary counts",
)
def get_review_tasks(
    request: Request,
    filter: str = Query(default="pending", description="Filtro de visualização: pending, approved, discarded, all"),
    profile_id: Optional[str] = Query(default=None, description="Filtro opcional por perfil operacional"),
):
    try:
        queue_data = quality_recovery.get_review_queue(
            filter=filter,
            profile_id=profile_id,
        )
    except Exception as exc:
        raise HttpException(
            task_id=base.get_task_id(request),
            status_code=500,
            message=f"Erro ao carregar fila de revisão: {exc}",
        )

    return utils.get_response(200, queue_data)


@router.get(
    "/review/tasks/{task_id}/video",
    summary="Safely stream task video for human inspection player",
)
def stream_review_video(task_id: str, request: Request):
    clean_tid = str(task_id or "").strip()
    req_id = base.get_task_id(request)

    # 1. Validação estrita do task_id contra Path Traversal
    if not clean_tid or not SAFE_TASK_ID_REGEX.match(clean_tid):
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message="Identificador task_id inválido ou malformado.",
        )

    base_dir = os.path.realpath(utils.task_dir())
    task_dir = os.path.realpath(os.path.join(base_dir, clean_tid))
    video_path = os.path.realpath(os.path.join(task_dir, "final-1.mp4"))

    # 2. Defesa rigorosa contra Path Traversal
    if not video_path.startswith(base_dir + os.sep) and video_path != base_dir:
        raise HttpException(
            task_id=req_id,
            status_code=403,
            message="Acesso negado: tentativa de path traversal detectada.",
        )

    # 3. Validação de existência física e integridade do arquivo
    if not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        raise HttpException(
            task_id=req_id,
            status_code=404,
            message=f"Arquivo de vídeo final-1.mp4 inexistente ou vazio para a tarefa '{clean_tid}'.",
        )

    return FileResponse(
        video_path,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{clean_tid}-final.mp4"',
        },
    )


@router.post(
    "/review/tasks/{task_id}/approve",
    summary="Approve held task for ready stock (human editorial decision)",
)
def approve_review_task(
    task_id: str,
    request: Request,
    body: Optional[ApproveReviewRequest] = None,
):
    clean_tid = str(task_id or "").strip()
    req_id = base.get_task_id(request)

    if not clean_tid or not SAFE_TASK_ID_REGEX.match(clean_tid):
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message="Identificador task_id inválido.",
        )

    payload = body or ApproveReviewRequest()
    if payload.confirm != quality_recovery.CONFIRM_APPROVE_FOR_STOCK:
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message=f"Confirmação '{quality_recovery.CONFIRM_APPROVE_FOR_STOCK}' é obrigatória.",
        )

    try:
        res = quality_recovery.submit_or_apply_review_decision(
            task_id=clean_tid,
            action=quality_recovery.DECISION_APPROVED,
            operator_id=payload.operator_id,
            note=payload.note,
            confirm=payload.confirm,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=req_id,
            status_code=403,
            message=str(exc),
        )
    except ValueError as exc:
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=req_id,
            status_code=500,
            message=f"Erro interno ao aprovar tarefa: {exc}",
        )

    status_code = 200 if res.get("status") in ("success", "approved") else 202
    msg = res.get("message") or "Decisão de aprovação processada com sucesso."
    return utils.get_response(status_code, res, message=msg)


@router.post(
    "/review/tasks/{task_id}/discard",
    summary="Discard held task from human review queue",
)
def discard_review_task(
    task_id: str,
    request: Request,
    body: Optional[DiscardReviewRequest] = None,
):
    clean_tid = str(task_id or "").strip()
    req_id = base.get_task_id(request)

    if not clean_tid or not SAFE_TASK_ID_REGEX.match(clean_tid):
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message="Identificador task_id inválido.",
        )

    payload = body or DiscardReviewRequest()
    if payload.confirm != quality_recovery.CONFIRM_DISCARD_HELD_VIDEO:
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message=f"Confirmação '{quality_recovery.CONFIRM_DISCARD_HELD_VIDEO}' é obrigatória.",
        )

    try:
        res = quality_recovery.submit_or_apply_review_decision(
            task_id=clean_tid,
            action=quality_recovery.DECISION_DISCARDED,
            operator_id=payload.operator_id,
            note=payload.note,
            confirm=payload.confirm,
        )
    except PermissionError as exc:
        raise HttpException(
            task_id=req_id,
            status_code=403,
            message=str(exc),
        )
    except ValueError as exc:
        raise HttpException(
            task_id=req_id,
            status_code=400,
            message=str(exc),
        )
    except Exception as exc:
        raise HttpException(
            task_id=req_id,
            status_code=500,
            message=f"Erro interno ao descartar tarefa: {exc}",
        )

    status_code = 200 if res.get("status") in ("success", "discarded") else 202
    msg = res.get("message") or "Decisão de descarte processada com sucesso."
    return utils.get_response(status_code, res, message=msg)
