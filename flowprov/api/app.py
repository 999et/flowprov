"""FastAPI app — combines JSON API and HTML dashboard in one process."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from flowprov.api.routes_dashboard import router as dashboard_router
from flowprov.api.routes_ingest import router as ingest_router
from flowprov.config import get_settings

logging.basicConfig(
    level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("flowprov")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("flowprov starting up")
    yield
    log.info("flowprov shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="flowprov",
        description="Provenance & drift detector for agentic workflows",
        version="0.1.0",
        lifespan=lifespan,
    )

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.templates = templates

    app.include_router(ingest_router, prefix="/api", tags=["api"])
    app.include_router(dashboard_router, tags=["dashboard"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


app = create_app()
