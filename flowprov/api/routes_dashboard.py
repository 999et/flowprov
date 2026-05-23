"""HTMX-driven HTML dashboard routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowprov.db import get_db
from flowprov.models import DriftEvent, Execution, FlowVersion
from flowprov.replay import ReplayService
from flowprov.service import ProvenanceService

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_db)) -> HTMLResponse:
    flows = await ProvenanceService.list_flows(session)
    recent_drift = (
        (
            await session.execute(
                select(DriftEvent).order_by(desc(DriftEvent.ts)).limit(10)
            )
        )
        .scalars()
        .all()
    )
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "index.html",
        {"flows": flows, "recent_drift": recent_drift},
    )


@router.get("/flows/{flow_id}", response_class=HTMLResponse)
async def flow_detail(
    request: Request, flow_id: str, session: AsyncSession = Depends(get_db)
) -> HTMLResponse:
    versions = (
        (
            await session.execute(
                select(FlowVersion)
                .where(FlowVersion.flow_id == flow_id)
                .order_by(FlowVersion.version)
            )
        )
        .scalars()
        .all()
    )
    executions = (
        (
            await session.execute(
                select(Execution)
                .where(Execution.flow_id == flow_id)
                .order_by(desc(Execution.ts))
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    drift = (
        (
            await session.execute(
                select(DriftEvent)
                .where(DriftEvent.flow_id == flow_id)
                .order_by(desc(DriftEvent.ts))
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    if not versions and not executions:
        raise HTTPException(status_code=404, detail=f"Flow {flow_id} has no data")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "flow_detail.html",
        {
            "flow_id": flow_id,
            "versions": versions,
            "executions": executions,
            "drift": drift,
        },
    )


@router.get("/executions/{execution_id}/replay", response_class=HTMLResponse)
async def replay_view(
    request: Request,
    execution_id: int,
    target_version_id: int | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        result = await ReplayService.replay(
            session,
            execution_id=execution_id,
            target_flow_version_id=target_version_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    original = await session.get(Execution, execution_id)
    versions = (
        (
            await session.execute(
                select(FlowVersion)
                .where(FlowVersion.flow_id == original.flow_id)
                .order_by(FlowVersion.version)
            )
        )
        .scalars()
        .all()
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "replay.html",
        {
            "result": result,
            "execution": original,
            "versions": versions,
        },
    )
