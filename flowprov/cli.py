"""flowprov CLI — convenience commands for ops and demos."""
from __future__ import annotations

import asyncio
import json

import httpx
import typer
from rich.console import Console
from rich.table import Table

from flowprov.config import get_settings
from flowprov.db import session_scope
from flowprov.service import ProvenanceService

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def health() -> None:
    """Check API liveness."""
    s = get_settings()
    r = httpx.get(f"http://{s.api_host if s.api_host != '0.0.0.0' else 'localhost'}:{s.api_port}/health", timeout=5.0)
    r.raise_for_status()
    console.print(f"[green]✔[/] api ok — {r.json()}")


@app.command()
def flows() -> None:
    """List all tracked flows."""
    async def _run() -> None:
        async with session_scope() as session:
            data = await ProvenanceService.list_flows(session)

        table = Table(title="flowprov · tracked flows", show_lines=False)
        table.add_column("flow id", style="cyan")
        table.add_column("name")
        table.add_column("versions", justify="right")
        table.add_column("executions", justify="right")
        table.add_column("drift", justify="right", style="yellow")
        for f in data:
            table.add_row(
                f["id"],
                f["name"],
                str(f["version_count"]),
                str(f["execution_count"]),
                str(f["drift_count"]),
            )
        console.print(table)

    asyncio.run(_run())


@app.command()
def ingest(payload_file: str) -> None:
    """Ingest a single execution payload from a JSON file (for testing)."""
    s = get_settings()
    with open(payload_file) as f:
        body = json.load(f)
    r = httpx.post(
        f"http://localhost:{s.api_port}/api/ingest", json=body, timeout=30.0
    )
    r.raise_for_status()
    console.print_json(data=r.json())


if __name__ == "__main__":
    app()
