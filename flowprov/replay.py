"""Replay service.

Given a historical execution, re-run it against a chosen flow version (or
its own version) and diff the outputs. This is the "what changed?" tool
used to confirm that a prompt or model change caused observed drift.
"""
from __future__ import annotations

import difflib
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from flowprov.embeddings import cosine_distance, embed
from flowprov.llm import get_llm
from flowprov.models import Execution, FlowVersion
from flowprov.schemas import ReplayResponse

log = logging.getLogger(__name__)


def _build_prompt(template: str, input_json: dict) -> str:
    """A flow-version's prompt_template may include {input.key} placeholders.

    For demo simplicity we do .format(input=...) — production code would use
    a sandboxed templating engine (Jinja in strict mode, or Pebble).
    """
    try:
        return template.format(input=_DotDict(input_json), **input_json)
    except (KeyError, IndexError):
        # Fall back to plain concat if the template doesn't reference inputs.
        return f"{template}\n\nINPUT: {input_json}"


class _DotDict(dict):
    """Allows {input.field} in prompt templates."""

    def __getattr__(self, item):
        v = self.get(item)
        if isinstance(v, dict):
            return _DotDict(v)
        return v


class ReplayService:
    @staticmethod
    async def replay(
        session: AsyncSession,
        *,
        execution_id: int,
        target_flow_version_id: int | None = None,
    ) -> ReplayResponse:
        original = await session.get(Execution, execution_id)
        if original is None:
            raise ValueError(f"Execution {execution_id} not found")

        original_fv = await session.get(FlowVersion, original.flow_version_id)
        if original_fv is None:
            raise ValueError("Original flow version not found")

        if target_flow_version_id is None:
            target_fv = original_fv
        else:
            target_fv = await session.get(FlowVersion, target_flow_version_id)
            if target_fv is None:
                raise ValueError(f"Flow version {target_flow_version_id} not found")

        prompt = _build_prompt(target_fv.prompt_template, original.input_json)

        llm = get_llm()
        replay_text, _usage = await llm.acomplete(
            prompt,
            model=target_fv.model_name,
            temperature=target_fv.temperature,
        )

        replay_emb = embed(replay_text)
        # original.output_embedding is a list when round-tripped through pgvector.
        orig_emb = list(original.output_embedding) if original.output_embedding is not None else embed(
            original.output_text
        )
        distance = cosine_distance(orig_emb, replay_emb)

        diff_summary = _make_diff_summary(original.output_text, replay_text)

        return ReplayResponse(
            original_execution_id=execution_id,
            original_output=original.output_text,
            original_version=original_fv.version,
            replay_output=replay_text,
            replay_version=target_fv.version,
            cosine_distance=distance,
            diff_summary=diff_summary,
        )


def _make_diff_summary(original: str, replay: str, max_lines: int = 20) -> str:
    """Compact unified diff for display."""
    diff = list(
        difflib.unified_diff(
            original.splitlines(),
            replay.splitlines(),
            fromfile="original",
            tofile="replay",
            n=1,
            lineterm="",
        )
    )
    if not diff:
        return "(no textual difference)"
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... ({len(diff) - max_lines} more lines)"]
    return "\n".join(diff)
