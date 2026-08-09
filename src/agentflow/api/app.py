"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.responses import Response

from agentflow import __version__
from agentflow.api.routes import api_router, operations_router
from agentflow.config import Settings, get_settings
from agentflow.container import Container, build_container
from agentflow.errors import AgentFlowError
from agentflow.logging import configure_logging
from agentflow.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(level=runtime_settings.log_level, json_logs=runtime_settings.json_logs)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime_container = container or await build_container(runtime_settings)
        application.state.container = runtime_container
        worker_task: asyncio.Task[None] | None = None
        if runtime_settings.embedded_worker:
            worker_task = asyncio.create_task(
                runtime_container.worker.run_forever(),
                name="agentflow-embedded-worker",
            )
        try:
            yield
        finally:
            if worker_task is not None:
                await runtime_container.worker.stop()
                try:
                    await asyncio.wait_for(
                        worker_task,
                        timeout=runtime_settings.shutdown_grace_seconds,
                    )
                except TimeoutError:
                    worker_task.cancel()
                    await asyncio.gather(worker_task, return_exceptions=True)
            await runtime_container.close()
            application.state.container = None

    application = FastAPI(
        title="AgentFlow API",
        version=__version__,
        description="Evidence-first document workflows with inspectable citations.",
        lifespan=lifespan,
    )
    application.state.container = None
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @application.middleware("http")
    async def observability_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(
            method=request.method,
            route=route_path,
            status=str(response.status_code),
        ).inc()
        HTTP_DURATION.labels(method=request.method, route=route_path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http_request_completed",
            method=request.method,
            route=route_path,
            status=response.status_code,
            duration_ms=elapsed * 1000,
        )
        return response

    @application.exception_handler(AgentFlowError)
    async def handle_agentflow_error(request: Request, exc: AgentFlowError) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
        )

    @application.exception_handler(PydanticValidationError)
    async def handle_internal_validation_error(
        request: Request,
        exc: PydanticValidationError,
    ) -> JSONResponse:
        logger.exception("internal_schema_validation_failed")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_schema_error",
                    "message": "An internal response failed validation.",
                    "details": {},
                    "request_id": request.headers.get("X-Request-ID"),
                }
            },
        )

    application.include_router(operations_router)
    application.include_router(api_router)
    return application


app = create_app()
