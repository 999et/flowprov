"""Provenance service.

The single entry point for "an execution happened, record it and decide if
it drifted." Used by:
  - the /ingest API endpoint
  - the n8n interceptor
  - the flow simulator
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowprov.drift import DriftEngine
from flowprov.embeddings import canonical_input_hash, embed
from flowprov.models import DriftEvent, Execution, Flow, FlowVersion
from flowprov.notify import maybe_send_slack
from flowprov.schemas import DriftSummary, ExecutionIngestRequest, ExecutionIngestResponse

log = logging.getLogger(__name__)
_drift = DriftEngine()


class ProvenanceService:
    @staticmethod
    async def ingest(
        session: AsyncSession, req: ExecutionIngestRequest
    ) -> ExecutionIngestResponse:
        """Record an execution. Create flow/version rows on demand. Detect drift."""

        # 1) Upsert flow
        flow = await session.get(Flow, req.flow_id)
        if flow is None:
            flow = Flow(id=req.flow_id, name=req.flow_name)
            session.add(flow)
            await session.flush()

        # 2) Upsert flow_version
        #
        # Identity rule: a (flow_id, prompt_template, model_name, temperature)
        # tuple is one version. Any change to those creates a new version row.
        version_q = select(FlowVersion).where(
            FlowVersion.flow_id == req.flow_id,
            FlowVersion.prompt_template == req.prompt_template,
            FlowVersion.model_name == req.model_name,
            FlowVersion.model_provider == req.model_provider,
            FlowVersion.temperature == req.temperature,
        )
        fv = (await session.execute(version_q)).scalar_one_or_none()
        if fv is None:
            # Determine the next version number for this flow.
            max_q = select(FlowVersion.version).where(FlowVersion.flow_id == req.flow_id)
            existing = [v for v in (await session.execute(max_q)).scalars()]
            next_version = (max(existing) + 1) if existing else 1
            fv = FlowVersion(
                flow_id=req.flow_id,
                version=next_version,
                prompt_template=req.prompt_template,
                model_name=req.model_name,
                model_provider=req.model_provider,
                temperature=req.temperature,
            )
            session.add(fv)
            await session.flush()
            log.info("New flow version: %s v%d", req.flow_id, next_version)

        # 3) Embed output and compute input hash
        embedding = embed(req.output_text)
        input_hash = canonical_input_hash(req.input_json)

        # 4) Persist execution
        execution = Execution(
            flow_id=req.flow_id,
            flow_version_id=fv.id,
            node_id=req.node_id,
            input_hash=input_hash,
            input_json=req.input_json,
            output_text=req.output_text,
            output_embedding=embedding,
            latency_ms=req.latency_ms,
            token_usage_json=req.token_usage_json,
        )
        session.add(execution)
        await session.flush()  # populate execution.id

        # 5) Drift check (excludes the just-inserted row)
        decision = await _drift.evaluate(
            session,
            flow_id=req.flow_id,
            node_id=req.node_id,
            input_hash=input_hash,
            new_embedding=embedding,
            exclude_execution_id=execution.id,
        )

        drift_summary: DriftSummary | None = None
        if decision.severity:
            drift = DriftEvent(
                execution_id=execution.id,
                flow_id=req.flow_id,
                severity=decision.severity,
                distance=decision.distance,
                baseline_mean=decision.baseline_mean,
                baseline_std=decision.baseline_std,
                baseline_n=decision.baseline_n,
                explanation=decision.explanation,
            )
            session.add(drift)
            await session.flush()

            drift_summary = DriftSummary(
                severity=decision.severity,
                distance=decision.distance,
                baseline_mean=decision.baseline_mean,
                baseline_std=decision.baseline_std,
                baseline_n=decision.baseline_n,
                explanation=decision.explanation,
            )

            # Fire and forget notification (no failure should poison ingest).
            try:
                await maybe_send_slack(
                    flow_id=req.flow_id,
                    node_id=req.node_id,
                    severity=decision.severity,
                    explanation=decision.explanation or "",
                    execution_id=execution.id,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Slack notify failed: %s", e)

            log.warning(
                "DRIFT %s on flow=%s node=%s exec=%d: %s",
                decision.severity.upper(),
                req.flow_id,
                req.node_id,
                execution.id,
                decision.explanation,
            )

        return ExecutionIngestResponse(
            execution_id=execution.id,
            flow_version_id=fv.id,
            flow_version=fv.version,
            drift=drift_summary,
        )

    @staticmethod
    async def list_flows(session: AsyncSession) -> list[dict[str, Any]]:
        """Return flows with counts for the dashboard."""
        from sqlalchemy import func

        flow_q = (
            select(
                Flow.id,
                Flow.name,
                Flow.description,
                Flow.created_at,
                func.count(FlowVersion.id.distinct()).label("version_count"),
            )
            .outerjoin(FlowVersion, FlowVersion.flow_id == Flow.id)
            .group_by(Flow.id)
            .order_by(Flow.created_at.desc())
        )
        rows = (await session.execute(flow_q)).all()

        out: list[dict[str, Any]] = []
        for r in rows:
            exec_count = (
                await session.execute(
                    select(func.count(Execution.id)).where(Execution.flow_id == r.id)
                )
            ).scalar_one()
            drift_count = (
                await session.execute(
                    select(func.count(DriftEvent.id)).where(DriftEvent.flow_id == r.id)
                )
            ).scalar_one()
            out.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "created_at": r.created_at,
                    "version_count": int(r.version_count),
                    "execution_count": int(exec_count),
                    "drift_count": int(drift_count),
                }
            )
        return out
