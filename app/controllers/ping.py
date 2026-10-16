import os
from fastapi import APIRouter, Request

from app.config import config
from app.utils import utils

router = APIRouter()


@router.get(
    "/ping",
    tags=["Health Check"],
    description="检查服务可用性",
    response_description="pong",
)
def ping(request: Request) -> str:
    return "pong"


@router.get(
    "/health",
    tags=["Health Check"],
    description="Application and Web UI V2 health check",
)
def health(request: Request):
    webui_dist = utils.webui_v2_dist_dir()
    webui_built = os.path.isdir(webui_dist) and os.path.isfile(
        os.path.join(webui_dist, "index.html")
    )
    return {
        "status": "healthy",
        "app": config.project_name,
        "version": config.project_version,
        "webui_v2_available": webui_built,
        "same_origin": True,
    }

