# llm-proxy-server

A private LiteLLM gateway proxying to OpenRouter, with [Headroom](https://github.com/headroomlabs-ai/headroom) as a pre-call context-compression guardrail and Redis for persistent semantic caching. Reachable only over Tailscale — no public endpoint, domain, or TLS setup. Two deploy targets: Jarvis Labs (pause/resume GPU pods) and AWS EC2 (on-demand, auto-stops after 4h idle, Lambda-triggered start).

See `docs/high-level-design.md` for the full architecture and rationale, and `docs/intent/` for each component's design and requirements.

## Quickstart

Requires [mise](https://mise.jdx.dev/) and [uv](https://docs.astral.sh/uv/) — tool versions are pinned in `.mise.toml`, dependencies in `pyproject.toml`.

```bash
mise install      # installs the pinned Python
uv sync           # creates .venv, installs dev deps
uv run pytest     # runs the test suite
```

## Running the stack

```bash
cp .env.example .env   # then fill in OPENROUTER_API_KEY / LITELLM_MASTER_KEY
docker compose up -d
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-master-key-1234" \
  -H "Content-Type: application/json" \
  -d '{"model": "smart-auto", "messages": [{"role": "user", "content": "Ping."}]}'
```

## Layout

| Path | What |
|---|---|
| `config.yaml`, `docker-compose.yml` | The gateway stack — LiteLLM, Headroom, Redis (deploy-target-agnostic) |
| `scripts/jarvis-startup.sh` | Jarvis Labs pod boot sequence |
| `scripts/aws-start-stack.sh`, `aws-idle-check.sh(+.cron)` | AWS EC2 boot sequence and idle auto-shutdown |
| `ignition/handler.py` | AWS Lambda "ignition switch" that starts/resizes the EC2 host on demand |
| `docs/high-level-design.md`, `docs/intent/` | Design intent (HLD, per-component LLDs, EARS specs) |
| `docs/gemini/` | Original research this project was built from |

For agent-facing conventions (LID workflow, spec IDs, dev commands), see `AGENTS.md`.
