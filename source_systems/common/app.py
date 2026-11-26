"""Montagem comum das APIs: health check, tratamento de cursor inválido e rotas de webhook."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from source_systems.common.guard import ApiGuard
from source_systems.common.pagination import InvalidCursorError
from source_systems.common.webhooks import WebhookDispatcher

logger = logging.getLogger(__name__)


class PageOut[T](BaseModel):
    data: list[T]
    next_cursor: str | None


class UpsertResult(BaseModel):
    received: int
    applied: int
    ignored_duplicates: int = 0
    enqueued: int = 0


async def _delivery_loop(dispatcher: WebhookDispatcher, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # httpx síncrono + SQLite: roda fora do event loop
            await asyncio.to_thread(dispatcher.deliver_due)
        except Exception:
            logger.exception("Falha no loop de entrega de webhooks")


def create_base_app(
    *,
    title: str,
    description: str,
    guard: ApiGuard,
    dispatcher: WebhookDispatcher | None = None,
    delivery_interval_seconds: float = 5.0,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = None
        if dispatcher is not None and dispatcher.url:
            task = asyncio.create_task(_delivery_loop(dispatcher, delivery_interval_seconds))
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title=title, description=description, version="1.0.0", lifespan=lifespan)

    @app.get("/health", tags=["operação"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(InvalidCursorError)
    async def invalid_cursor(_: Request, error: InvalidCursorError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    if dispatcher is not None:
        router = APIRouter(
            prefix="/admin/webhooks", tags=["admin"], dependencies=[Depends(guard.admin)]
        )

        @router.post("/deliver")
        def deliver_now() -> dict[str, int]:
            """Entrega agora os eventos pendentes (sem esperar o loop de fundo)."""
            return dispatcher.deliver_due().as_dict()

        @router.get("/stats")
        def outbox_stats() -> dict[str, int]:
            return dispatcher.stats()

        app.include_router(router)
    return app
