"""Integration tests against the real DB.

Skip if Postgres isn't reachable.
"""
from __future__ import annotations

import pytest

from flowprov.schemas import ExecutionIngestRequest
from flowprov.service import ProvenanceService


@pytest.fixture
def base_request() -> ExecutionIngestRequest:
    return ExecutionIngestRequest(
        flow_id="test.flow.a",
        flow_name="Test Flow A",
        node_id="llm.test",
        prompt_template="Classify: {x}",
        model_name="gpt-4o-mini",
        model_provider="openai",
        temperature=0.0,
        input_json={"x": "hello"},
        output_text="Category: greeting. Confidence: 95%.",
    )


async def test_ingest_creates_flow_and_version(clean_db, db_session, base_request) -> None:
    resp = await ProvenanceService.ingest(db_session, base_request)
    await db_session.commit()
    assert resp.execution_id > 0
    assert resp.flow_version == 1


async def test_same_prompt_reuses_version(clean_db, db_session, base_request) -> None:
    r1 = await ProvenanceService.ingest(db_session, base_request)
    await db_session.commit()
    r2 = await ProvenanceService.ingest(db_session, base_request)
    await db_session.commit()
    assert r1.flow_version_id == r2.flow_version_id


async def test_prompt_change_creates_new_version(clean_db, db_session, base_request) -> None:
    r1 = await ProvenanceService.ingest(db_session, base_request)
    await db_session.commit()

    changed = base_request.model_copy(update={"prompt_template": "Categorise this: {x}"})
    r2 = await ProvenanceService.ingest(db_session, changed)
    await db_session.commit()

    assert r1.flow_version == 1
    assert r2.flow_version == 2


async def test_drift_fires_on_radically_different_output(clean_db, db_session, base_request) -> None:
    # Build a baseline of identical outputs.
    for _ in range(8):
        await ProvenanceService.ingest(db_session, base_request)
        await db_session.commit()

    # Now ingest a totally different output for the SAME input -> should flag.
    drifted = base_request.model_copy(
        update={"output_text": "🚨🚨🚨 something completely unrelated to greetings 🚨🚨🚨"}
    )
    resp = await ProvenanceService.ingest(db_session, drifted)
    await db_session.commit()
    assert resp.drift is not None
    assert resp.drift.severity in {"warn", "fail"}
