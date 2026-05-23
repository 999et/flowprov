"""Tests for the fake LLM — determinism is the contract."""
from __future__ import annotations

import asyncio

from flowprov.llm import FakeLLM


def test_fake_llm_is_deterministic_at_t0() -> None:
    llm = FakeLLM()
    p = "Triage this incident: payments down"
    a, _ = asyncio.run(llm.acomplete(p, model="gpt-4o-mini", temperature=0.0))
    b, _ = asyncio.run(llm.acomplete(p, model="gpt-4o-mini", temperature=0.0))
    assert a == b


def test_fake_llm_differs_for_different_prompts() -> None:
    llm = FakeLLM()
    a, _ = asyncio.run(llm.acomplete("triage incident A", model="gpt-4o-mini"))
    b, _ = asyncio.run(llm.acomplete("classify ticket B", model="gpt-4o-mini"))
    # Different intent → different template pool → essentially never collide
    assert a != b


def test_fake_llm_token_usage_is_populated() -> None:
    llm = FakeLLM()
    _, usage = asyncio.run(llm.acomplete("summarize this", model="gpt-4o-mini"))
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_fake_llm_intent_routing() -> None:
    llm = FakeLLM()
    out_triage, _ = asyncio.run(llm.acomplete("triage this incident", model="gpt-4o-mini"))
    out_class, _ = asyncio.run(llm.acomplete("classify this message", model="gpt-4o-mini"))
    # Outputs should be drawn from different template pools — they should rarely
    # share long substrings. Soft check.
    assert out_triage != out_class
