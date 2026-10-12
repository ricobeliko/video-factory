from fastapi import APIRouter


def new_router(dependencies=None):
    router = APIRouter()
    router.tags = ["V2"]
    router.prefix = "/api/v2"
    if dependencies:
        router.dependencies = dependencies
    return router
