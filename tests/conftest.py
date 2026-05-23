"""Pytest fixtures.

Integration tests (anything that needs the DB) require Postgres + pgvector
to be running locally per the README:  `make db-up && make migrate`.
"""
from __future__ import annotations

import os

import pytest_asyncio

os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")


# Why a per-test engine with NullPool?
# ------------------------------------
# asyncpg connections are bound to the asyncio event loop they were opened
# under. pytest-asyncio creates a fresh loop per test by default; if we
# share a module-level engine across tests, connections opened during test
# A get reused during test B on a different loop and asyncpg raises
# `Task ... got Future attached to a different loop`. Using NullPool plus a
# fresh engine per test avoids the cross-loop reuse entirely.

@pytest_asyncio.fixture(loop_scope="function")
async def test_engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from flowprov.config import get_settings

    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
        echo=False,
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, SessionLocal
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def db_session(test_engine):
    _engine, SessionLocal = test_engine
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(loop_scope="function")
async def clean_db(test_engine):
    """Wipe app data so each integration test starts from a blank slate."""
    from sqlalchemy import text

    _engine, SessionLocal = test_engine
    async with SessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE drift_events RESTART IDENTITY CASCADE"))
        await session.execute(text("TRUNCATE TABLE executions RESTART IDENTITY CASCADE"))
        await session.execute(text("TRUNCATE TABLE flow_versions RESTART IDENTITY CASCADE"))
        await session.execute(text("TRUNCATE TABLE flows RESTART IDENTITY CASCADE"))
        await session.commit()
    yield
