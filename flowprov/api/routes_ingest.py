"""Ingest + replay JSON endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowprov.db import get_db
from flowprov.models import DriftEvent, Execution, FlowVersion
from flowprov.replay import ReplayService
from flowprov.schemas import (
    DriftEventResponse,
    ExecutionIngestRequest,
    ExecutionIngestResponse,
    ExecutionResponse,
    ReplayRequest,
    ReplayResponse,
)
from flowprov.service import ProvenanceService

router = APIRouter()


@router.post("/ingest", response_model=ExecutionIngestResponse)
async def ingest(
    req: ExecutionIngestRequest, session: AsyncSession = Depends(get_db)
) -> ExecutionIngestResponse:
    """Record an execution and run drift detection. Called by interceptors."""
    return await ProvenanceService.ingest(session, req)


@router.post("/replay", response_model=ReplayResponse)
async def replay(
    req: ReplayRequest, session: AsyncSession = Depends(get_db)
) -> ReplayResponse:
    """Re-run a historical execution against its own or another flow version."""
    try:
        return await ReplayService.replay(
            session,
            execution_id=req.execution_id,
            target_flow_version_id=req.target_flow_version_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/flows/{flow_id}/executions", response_model=list[ExecutionResponse])
async def list_executions(
    flow_id: str,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[ExecutionResponse]:
    q = (
        select(Execution)
        .where(Execution.flow_id == flow_id)
        .order_by(desc(Execution.ts))
        .limit(limit)
    )
    rows = (await session.execute(q)).scalars().all()
    return [
        ExecutionResponse(
            id=e.id,
            flow_id=e.flow_id,
            flow_version_id=e.flow_version_id,
            node_id=e.node_id,
            input_hash=e.input_hash,
            input_json=e.input_json,
            output_text=e.output_text,
            latency_ms=e.latency_ms,
            ts=e.ts,
        )
        for e in rows
    ]


@router.get("/flows/{flow_id}/versions")
async def list_versions(
    flow_id: str, session: AsyncSession = Depends(get_db)
) -> list[dict]:
    q = (
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.version)
    )
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": v.id,
            "version": v.version,
            "model_name": v.model_name,
            "model_provider": v.model_provider,
            "temperature": v.temperature,
            "prompt_template": v.prompt_template,
            "created_at": v.created_at.isoformat(),
        }
        for v in rows
    ]


@router.get("/drift", response_model=list[DriftEventResponse])
async def list_drift(
    flow_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[DriftEventResponse]:
    q = select(DriftEvent).order_by(desc(DriftEvent.ts)).limit(limit)
    if flow_id:
        q = q.where(DriftEvent.flow_id == flow_id)
    if severity:
        q = q.where(DriftEvent.severity == severity)
    rows = (await session.execute(q)).scalars().all()
    return [
        DriftEventResponse(
            id=d.id,
            execution_id=d.execution_id,
            flow_id=d.flow_id,
            severity=d.severity,
            distance=d.distance,
            baseline_mean=d.baseline_mean,
            baseline_std=d.baseline_std,
            baseline_n=d.baseline_n,
            explanation=d.explanation,
            acknowledged=d.acknowledged,
            ts=d.ts,
        )
        for d in rows
    ]


@router.post("/drift/{drift_id}/ack")
async def ack_drift(drift_id: int, session: AsyncSession = Depends(get_db)) -> dict:
    drift = await session.get(DriftEvent, drift_id)
    if drift is None:
        raise HTTPException(status_code=404, detail="Drift event not found")
    drift.acknowledged = True
    return {"id": drift.id, "acknowledged": True}
