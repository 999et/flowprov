"""Drift injection — the killer demo.

We take an existing flow (HackerOne triage), make a deliberate prompt
regression (someone "improved" the prompt and accidentally introduced a
behavior change), and replay one of the original inputs against the broken
prompt. flowprov should:

  1. Recognise this as a new flow_version
  2. Flag the output as drifted (hard or soft) for the same input class
  3. Make the cause visible in the dashboard

Run AFTER `make demo`.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import httpx
from rich.console import Console

from examples.flow_simulator.flows import HACKERONE_TRIAGE, INPUTS_BY_FLOW
from flowprov.config import get_settings
from flowprov.llm import FakeLLM

console = Console()

# This is the "regression": the new prompt asks for a totally different
# output format. A real-world example would be a teammate "cleaning up"
# the prompt without realising downstream consumers depended on the
# original answer shape.
REGRESSED_PROMPT = (
    "Quickly summarize this HackerOne ticket in one short sentence; "
    "do not provide severity or component or owner.\n\n"
    "Title: {title}\n"
    "Body: {body}\n"
    "Asset: {asset}"
)


def _fmt(template: str, inputs: dict) -> str:
    try:
        return template.format(**inputs)
    except KeyError:
        return template


async def main() -> None:
    s = get_settings()
    base = f"http://localhost:{s.api_port}"

    # Build the regressed version of the flow (same flow_id, new prompt).
    regressed = replace(HACKERONE_TRIAGE, prompt_template=REGRESSED_PROMPT)

    inputs_to_replay = INPUTS_BY_FLOW[HACKERONE_TRIAGE.flow_id]
    console.print("[bold magenta]flowprov · drift injection[/]")
    console.print(f"  flow: {regressed.flow_id}")
    console.print("  regression: prompt rewritten to suppress severity/component/owner")
    console.print(f"  will replay {len(inputs_to_replay)} input classes against the new prompt\n")

    llm = FakeLLM()
    fail = 0
    warn = 0

    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        for inputs in inputs_to_replay:
            prompt = _fmt(regressed.prompt_template, inputs)
            t0 = time.perf_counter()
            output, usage = await llm.acomplete(
                prompt, model=regressed.model_name, temperature=regressed.temperature
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            body = {
                "flow_id": regressed.flow_id,
                "flow_name": regressed.flow_name,
                "node_id": regressed.node_id,
                "prompt_template": regressed.prompt_template,  # ← the new (broken) version
                "model_name": regressed.model_name,
                "model_provider": "openai",
                "temperature": regressed.temperature,
                "input_json": inputs,
                "output_text": output,
                "latency_ms": latency_ms,
                "token_usage_json": usage,
            }
            r = await client.post("/api/ingest", json=body, timeout=60.0)
            r.raise_for_status()
            result = r.json()
            drift = result.get("drift")
            tag = "—"
            if drift:
                sev = drift["severity"]
                tag = f"[red]{sev.upper()}[/] (dist={drift['distance']:.3f})"
                if sev == "fail":
                    fail += 1
                else:
                    warn += 1
            console.print(
                f"  → ingested execution {result['execution_id']:>5}  "
                f"v{result['flow_version']}  {tag}"
            )

    console.print()
    console.print(f"[bold]drift signals fired:[/] {fail} fail · {warn} warn")
    console.print(f"\n[bold]→ open[/] [cyan]{base}/flows/{regressed.flow_id}[/]")
    console.print("  inspect the new version and the drift events.")
    console.print(
        "[bold]→ then click 'replay'[/] on a drifted execution to see it re-run "
        "against the original (good) version and confirm root cause."
    )


if __name__ == "__main__":
    asyncio.run(main())
