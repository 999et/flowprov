# n8n Integration

flowprov ingests executions via a single HTTP POST to `/api/ingest`. The
recommended pattern: in each n8n flow, add an **HTTP Request** node
immediately after every LLM node. The HTTP node sends the prompt template,
model name, input payload, and the LLM output to flowprov.

## One-time setup

1. Bring up the optional n8n container (Postgres must already be running):

   ```bash
   make n8n-up
   # → http://localhost:5678
   ```

2. Create an n8n account on first open.

3. Import the workflows in this folder:
   - `01_triage.json` — a sample HackerOne triage flow with a flowprov sidecar.

4. In each workflow, the **flowprov-ingest** HTTP node is preconfigured to
   POST to `http://host.docker.internal:8000/api/ingest`. If you are NOT
   running flowprov on the docker host, change the URL.

## How it works

```
[Webhook] → [LLM Node] ──┬─► [downstream business logic]
                          │
                          └─► [HTTP Request: flowprov-ingest]
```

The interceptor node is fire-and-forget on the happy path; it does NOT block
the main flow. If flowprov is down, n8n's HTTP Request node retries are configured to be best-effort.

## Manual wiring

If you prefer to wire your own flow, here's the exact body the ingest endpoint
expects:

```json
{
  "flow_id": "<your stable id>",
  "flow_name": "<human-readable>",
  "node_id": "<the LLM node id, e.g. llm.triage>",
  "prompt_template": "<the template, NOT the rendered prompt>",
  "model_name": "gpt-4o-mini",
  "model_provider": "openai",
  "temperature": 0.0,
  "input_json": { "...": "..." },
  "output_text": "<the LLM's response>",
  "latency_ms": 1234,
  "token_usage_json": {"prompt_tokens": 80, "completion_tokens": 40}
}
```

The response includes `drift` if the execution was flagged.
