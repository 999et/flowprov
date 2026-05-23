"""Pydantic v2 schemas — API request/response contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ─── Inputs from instrumented flows ─────────────────────────────────────────

class ExecutionIngestRequest(BaseModel):
    """Payload posted by the n8n/BuildShip interceptor for every node execution."""
    flow_id: str = Field(min_length=1, max_length=128)
    flow_name: str = Field(min_length=1, max_length=256)
    node_id: str = Field(min_length=1, max_length=128)
    prompt_template: str
    model_name: str
    model_provider: str = "openai"
    temperature: float = 0.0
    input_json: dict[str, Any]
    output_text: str
    latency_ms: int | None = None
    token_usage_json: dict[str, Any] | None = None


class ExecutionIngestResponse(BaseModel):
    execution_id: int
    flow_version_id: int
    flow_version: int
    drift: DriftSummary | None = None


# ─── Drift reporting ────────────────────────────────────────────────────────

class DriftSummary(BaseModel):
    severity: Literal["warn", "fail"]
    distance: float
    baseline_mean: float | None = None
    baseline_std: float | None = None
    baseline_n: int | None = None
    explanation: str | None = None


class DriftEventResponse(BaseModel):
    id: int
    execution_id: int
    flow_id: str
    severity: str
    distance: float
    baseline_mean: float | None
    baseline_std: float | None
    baseline_n: int | None
    explanation: str | None
    acknowledged: bool
    ts: datetime


# ─── Flow / version surfaces ────────────────────────────────────────────────

class FlowResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    version_count: int = 0
    execution_count: int = 0
    drift_count: int = 0


class FlowVersionResponse(BaseModel):
    id: int
    flow_id: str
    version: int
    prompt_template: str
    model_name: str
    model_provider: str
    temperature: float
    created_at: datetime


class ExecutionResponse(BaseModel):
    id: int
    flow_id: str
    flow_version_id: int
    node_id: str
    input_hash: str
    input_json: dict[str, Any]
    output_text: str
    latency_ms: int | None
    ts: datetime


# ─── Replay ─────────────────────────────────────────────────────────────────

class ReplayRequest(BaseModel):
    """Replay a given execution against either its own version or another version."""
    execution_id: int
    target_flow_version_id: int | None = None  # None = re-run against current/latest


class ReplayResponse(BaseModel):
    original_execution_id: int
    original_output: str
    original_version: int
    replay_output: str
    replay_version: int
    cosine_distance: float
    diff_summary: str
