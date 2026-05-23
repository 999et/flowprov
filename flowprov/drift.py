"""Drift detection engine.

Given an embedding for a newly-executed (flow_id, node_id, input_hash, output),
decide whether the output has drifted compared to its history.

Two-tier policy:

  1. HARD FAIL: if the cosine distance from EVERY historical execution of the
     same (flow_id, node_id, input_hash) is greater than `drift_hard_threshold`,
     the output is anomalous regardless of class history. This catches
     catastrophic regressions (e.g. someone replaced the prompt with garbage).

  2. SOFT WARN: per (flow_id, node_id, input_hash) class with >= `drift_min_history`
     samples, compute mean and std of pairwise distances among historical
     in-class outputs. The new output's nearest-neighbor distance is
     statistically tested against this baseline. If it lies beyond
     `mean + soft_std_multiplier * std`, warn.

Both tiers are tunable from .env. The "k-nearest historical neighbors"
search uses pgvector's `<=>` (cosine distance) operator — IVFFlat index
gives sub-millisecond lookups at the scale flowprov targets.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from flowprov.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class DriftDecision:
    severity: str | None  # None | "warn" | "fail"
    distance: float
    baseline_mean: float | None
    baseline_std: float | None
    baseline_n: int
    nearest_execution_id: int | None
    explanation: str


class DriftEngine:
    def __init__(self) -> None:
        s = get_settings()
        self.hard_threshold = s.drift_hard_threshold
        self.soft_mult = s.drift_soft_std_multiplier
        self.min_history = s.drift_min_history
        self.knn = s.drift_knn

    async def evaluate(
        self,
        session: AsyncSession,
        *,
        flow_id: str,
        node_id: str,
        input_hash: str,
        new_embedding: list[float],
        exclude_execution_id: int | None = None,
    ) -> DriftDecision:
        """Score a new execution against its in-class history.

        We compare against historical executions with the SAME (flow_id,
        node_id, input_hash) — i.e. the same logical request.
        """
        # k-NN query against in-class history.
        # The `::vector` cast is required for pgvector to interpret the
        # bound parameter as a vector literal.
        #
        # The `::bigint` cast on :exclude_id is required because asyncpg
        # cannot infer the type of a bound NULL parameter when it appears
        # only inside `... IS NULL OR ...`; without the cast it raises
        # AmbiguousParameterError.
        knn_sql = text(
            """
            SELECT id, (output_embedding <=> CAST(:vec AS vector)) AS dist
            FROM executions
            WHERE flow_id = :flow_id
              AND node_id = :node_id
              AND input_hash = :input_hash
              AND output_embedding IS NOT NULL
              AND (CAST(:exclude_id AS bigint) IS NULL OR id <> CAST(:exclude_id AS bigint))
            ORDER BY output_embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        )
        result = await session.execute(
            knn_sql,
            {
                "vec": self._fmt_vec(new_embedding),
                "flow_id": flow_id,
                "node_id": node_id,
                "input_hash": input_hash,
                "exclude_id": exclude_execution_id,
                "k": self.knn,
            },
        )
        neighbors = result.fetchall()

        if not neighbors:
            return DriftDecision(
                severity=None,
                distance=0.0,
                baseline_mean=None,
                baseline_std=None,
                baseline_n=0,
                nearest_execution_id=None,
                explanation="No historical executions for this input class yet; treating as baseline.",
            )

        nearest_id = int(neighbors[0][0])
        nearest_dist = float(neighbors[0][1])
        distances = [float(r[1]) for r in neighbors]

        # ─── Hard-fail tier ────────────────────────────────────────────
        # Even the closest historical neighbor is far away.
        if nearest_dist > self.hard_threshold:
            return DriftDecision(
                severity="fail",
                distance=nearest_dist,
                baseline_mean=float(np.mean(distances)) if distances else None,
                baseline_std=float(np.std(distances)) if len(distances) > 1 else None,
                baseline_n=len(distances),
                nearest_execution_id=nearest_id,
                explanation=(
                    f"Nearest in-class neighbor is {nearest_dist:.3f} away "
                    f"(>{self.hard_threshold:.2f} hard threshold). "
                    "Output is unlike anything we've seen for this input."
                ),
            )

        # ─── Soft-warn tier ────────────────────────────────────────────
        if len(distances) < self.min_history:
            return DriftDecision(
                severity=None,
                distance=nearest_dist,
                baseline_mean=float(np.mean(distances)) if distances else None,
                baseline_std=None,
                baseline_n=len(distances),
                nearest_execution_id=nearest_id,
                explanation=(
                    f"Only {len(distances)} historical sample(s); need "
                    f"{self.min_history} before soft-warn becomes active."
                ),
            )

        mean = float(np.mean(distances))
        std = float(np.std(distances))
        # Guard against zero-std (all identical) — use a tiny floor so we
        # don't divide by zero when computing z-score.
        std_floor = max(std, 1e-4)
        z = (nearest_dist - mean) / std_floor

        if nearest_dist > mean + self.soft_mult * std_floor:
            return DriftDecision(
                severity="warn",
                distance=nearest_dist,
                baseline_mean=mean,
                baseline_std=std,
                baseline_n=len(distances),
                nearest_execution_id=nearest_id,
                explanation=(
                    f"Nearest-neighbor distance {nearest_dist:.3f} is "
                    f"{z:.2f}σ above class baseline (μ={mean:.3f}, σ={std:.3f}, "
                    f"n={len(distances)})."
                ),
            )

        return DriftDecision(
            severity=None,
            distance=nearest_dist,
            baseline_mean=mean,
            baseline_std=std,
            baseline_n=len(distances),
            nearest_execution_id=nearest_id,
            explanation=(
                f"Within normal range (distance {nearest_dist:.3f}, "
                f"z={z:.2f}σ, baseline μ={mean:.3f})."
            ),
        )

    @staticmethod
    def _fmt_vec(vec: list[float]) -> str:
        """pgvector accepts a string literal '[v1,v2,...]' via a CAST."""
        return "[" + ",".join(f"{float(x):.7f}" if math.isfinite(x) else "0" for x in vec) + "]"
