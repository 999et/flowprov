"""LLM client abstraction.

Two backends:
  - "fake": deterministic, fully offline. Used by the simulator and tests.
  - "openai": real OpenAI API (set OPENAI_API_KEY).

Both are exposed through `LLMClient.acomplete(prompt, model, temperature)`.
"""
from __future__ import annotations

import hashlib
import logging
import random
from typing import Any, Protocol

from tenacity import retry, stop_after_attempt, wait_exponential

from flowprov.config import get_settings

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    async def acomplete(
        self, prompt: str, *, model: str, temperature: float = 0.0
    ) -> tuple[str, dict[str, Any]]:
        """Return (output_text, token_usage_dict)."""
        ...


# ─── Fake (deterministic offline) ──────────────────────────────────────────

class FakeLLM:
    """Deterministic offline LLM.

    For demo realism we generate plausible-looking outputs based on the
    prompt's content fingerprint, with controlled randomness driven by a
    seed derived from the prompt — that way:

      - Re-running the same prompt deterministically yields the same answer
        (mimicking a temperature-0 deployment).
      - A small perturbation in the prompt yields a noticeably different
        answer (which is exactly the "drift" we want flowprov to catch).
    """

    # Pools of "answer fragments" by detected intent.
    INTENT_TEMPLATES: dict[str, list[str]] = {
        "triage": [
            "Severity: {sev}. Likely component: {comp}. Recommended owner: {owner}.",
            "Initial triage suggests {sev} impact on the {comp} subsystem. Page {owner}.",
            "Categorized as {sev}-priority {comp} incident. Assigning to {owner}.",
        ],
        "classify": [
            "Category: {cat}. Confidence: {conf}%. Reasoning: {reason}.",
            "Classified as {cat} ({conf}% confidence). {reason}",
            "{cat} | confidence={conf}% | {reason}",
        ],
        "route": [
            "Route to team: {team}. Priority: {prio}. ETA bucket: {eta}.",
            "Routing decision -> {team} ({prio}); expected handling window: {eta}.",
            "Forward to {team} with {prio} priority, ETA {eta}.",
        ],
        "summarize": [
            "Summary: {topic}. Key points: {kp1}, {kp2}. Action: {action}.",
            "TL;DR — {topic}. Notably: {kp1} and {kp2}. Next: {action}.",
            "{topic}. Highlights: {kp1}; {kp2}. Recommended action: {action}.",
        ],
        "decide": [
            "Decision: {decision}. Justification: {just}.",
            "Recommended action: {decision}. Reason: {just}.",
            "{decision} — because {just}.",
        ],
        "generic": [
            "Acknowledged. Processing complete. Result: {result}.",
            "Processed input successfully. Output: {result}.",
            "Done. {result}.",
        ],
    }

    def _detect_intent(self, prompt: str) -> str:
        p = prompt.lower()
        if any(w in p for w in ("triage", "incident", "severity", "vulnerability", "hackerone")):
            return "triage"
        if any(w in p for w in ("classify", "category", "label", "tag")):
            return "classify"
        if any(w in p for w in ("route", "forward", "assign")):
            return "route"
        if any(w in p for w in ("summari", "tl;dr", "synopsis")):
            return "summarize"
        if any(w in p for w in ("decide", "should we", "recommend")):
            return "decide"
        return "generic"

    def _seed_for(self, prompt: str, model: str, temperature: float) -> int:
        h = hashlib.blake2b(
            f"{model}|{temperature}|{prompt}".encode(), digest_size=8
        ).digest()
        return int.from_bytes(h, "big")

    async def acomplete(
        self, prompt: str, *, model: str, temperature: float = 0.0
    ) -> tuple[str, dict[str, Any]]:
        intent = self._detect_intent(prompt)
        rng = random.Random(self._seed_for(prompt, model, temperature))
        template = rng.choice(self.INTENT_TEMPLATES[intent])

        # Stable per-prompt fillers (deterministic at T=0).
        fillers = {
            "sev": rng.choice(["P0", "P1", "P2", "P3"]),
            "comp": rng.choice(["auth", "payments", "trading-engine", "kyc", "ledger"]),
            "owner": rng.choice(["@team-platform", "@team-trading", "@team-security"]),
            "cat": rng.choice(["fraud", "support", "feature_request", "bug_report"]),
            "conf": rng.randint(72, 98),
            "reason": rng.choice(
                [
                    "matches known patterns in training set",
                    "high textual similarity with category centroid",
                    "explicit keywords present",
                ]
            ),
            "team": rng.choice(["trading-ops", "compliance", "platform", "finance-ops"]),
            "prio": rng.choice(["high", "medium", "low"]),
            "eta": rng.choice(["<1h", "1-4h", "same-day", "next-business-day"]),
            "topic": rng.choice(
                ["deposit issue", "withdrawal review", "trade-execution anomaly", "KYC update"]
            ),
            "kp1": rng.choice(
                ["amount within limits", "user is verified", "consistent with history"]
            ),
            "kp2": rng.choice(
                ["no policy violation detected", "second-factor confirmed", "rail latency normal"]
            ),
            "action": rng.choice(["approve", "hold for review", "auto-reconcile", "escalate"]),
            "decision": rng.choice(["APPROVE", "HOLD", "REJECT", "ESCALATE"]),
            "just": rng.choice(
                [
                    "all checks pass within tolerance",
                    "one check is in the soft-warn band",
                    "manual review reduces residual risk",
                ]
            ),
            "result": rng.choice(["OK", "needs_review", "queued", "auto-resolved"]),
        }
        text = template.format(**fillers)

        token_usage = {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": len(text.split()),
            "total_tokens": len(prompt.split()) + len(text.split()),
        }
        return text, token_usage


# ─── Real OpenAI ───────────────────────────────────────────────────────────

class OpenAILLM:
    def __init__(self) -> None:
        from openai import AsyncOpenAI

        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set but LLM_PROVIDER=openai")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def acomplete(
        self, prompt: str, *, model: str, temperature: float = 0.0
    ) -> tuple[str, dict[str, Any]]:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else None,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else None,
            "total_tokens": resp.usage.total_tokens if resp.usage else None,
        }
        return text, usage


# ─── Factory ───────────────────────────────────────────────────────────────

def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "openai":
        return OpenAILLM()
    return FakeLLM()
