"""End-to-end demo runner.

What this does:
  1. Spins up the fake LLM
  2. For each of the 5 flow definitions, generates a baseline of N executions
     per distinct input class.
  3. Posts every execution to flowprov's /api/ingest endpoint, just like the
     production interceptor would.
  4. Prints a summary at the end.

After this completes, open http://localhost:8000/ to see the dashboard.
Then run `make demo-drift` to see drift detection fire.
"""
from __future__ import annotations

import asyncio
import time

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from examples.flow_simulator.flows import ALL_FLOWS, INPUTS_BY_FLOW
from flowprov.config import get_settings
from flowprov.llm import FakeLLM

console = Console()

# How many executions per (flow, input-class) to build a stable baseline.
RUNS_PER_INPUT = 6


def _build_prompt(template: str, inputs: dict) -> str:
    try:
        return template.format(**inputs)
    except KeyError:
        return template


async def run_one(client: httpx.AsyncClient, llm: FakeLLM, flow, inputs: dict) -> dict:
    prompt = _build_prompt(flow.prompt_template, inputs)
    t0 = time.perf_counter()
    output, usage = await llm.acomplete(prompt, model=flow.model_name, temperature=flow.temperature)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    body = {
        "flow_id": flow.flow_id,
        "flow_name": flow.flow_name,
        "node_id": flow.node_id,
        "prompt_template": flow.prompt_template,
        "model_name": flow.model_name,
        "model_provider": "openai" if flow.model_name.startswith("gpt") else "anthropic",
        "temperature": flow.temperature,
        "input_json": inputs,
        "output_text": output,
        "latency_ms": latency_ms,
        "token_usage_json": usage,
    }
    r = await client.post("/api/ingest", json=body, timeout=60.0)
    r.raise_for_status()
    return r.json()


async def main() -> None:
    s = get_settings()
    base = f"http://localhost:{s.api_port}"

    console.print("[bold cyan]flowprov · demo simulator[/]")
    console.print(f"  api: {base}")
    console.print("  llm: fake (deterministic, offline)")
    console.print(f"  flows: {len(ALL_FLOWS)}, runs/class: {RUNS_PER_INPUT}\n")

    llm = FakeLLM()
    drift_seen = 0
    total = 0
    failures = 0

    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        # Pre-flight check
        try:
            r = await client.get("/health")
            r.raise_for_status()
        except Exception as e:
            console.print(f"[red]API not reachable at {base}: {e}[/]")
            console.print("[yellow]Did you run `make api` in another terminal?[/]")
            return

        steps = sum(len(INPUTS_BY_FLOW[f.flow_id]) * RUNS_PER_INPUT for f in ALL_FLOWS)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("seeding executions...", total=steps)
            for flow in ALL_FLOWS:
                for inputs in INPUTS_BY_FLOW[flow.flow_id]:
                    for _ in range(RUNS_PER_INPUT):
                        try:
                            result = await run_one(client, llm, flow, inputs)
                            total += 1
                            if result.get("drift"):
                                drift_seen += 1
                        except Exception as e:
                            failures += 1
                            console.print(f"[red]✘ ingest failed: {e}[/]")
                        progress.advance(task)

    console.print()
    console.print(f"[green]✔[/] {total} executions ingested")
    console.print(f"  drift signals during baseline: {drift_seen}")
    if failures:
        console.print(f"[red]✘[/] {failures} ingest failures")
    console.print(f"\n[bold]→ open[/] [cyan]{base}/[/] to inspect the dashboard")
    console.print("[bold]→ next:[/] [cyan]make demo-drift[/] to inject a prompt regression and trigger drift")


if __name__ == "__main__":
    asyncio.run(main())
