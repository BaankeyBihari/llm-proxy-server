# High-Level Design: llm-proxy-server

## Problem

Personal AI-assisted development (IDE agents, CLI tools) needs a single, private endpoint for OpenRouter model access from a laptop, without exposing that endpoint to the public internet, managing a domain or TLS certificates, or paying for idle GPU/compute time. Repeated identical calls (common in agentic tool loops) also waste money without a cache. A weekend-cadence engineer additionally needs the compute to be cheap to leave off and fast to bring back.

## Approach

A single Docker Compose stack — LiteLLM (router), Headroom (pre-call context-compression guardrail), Redis (persistent semantic cache) — deployed identically behind a Tailscale mesh network, with two interchangeable deploy targets:

- **Jarvis Labs**: a GPU-cloud pod, paused (not terminated) between sessions; state that must survive a pause lives on the pod's persistent home directory.
- **AWS EC2**: an on-demand instance, fully stopped between sessions and restarted on demand via a Lambda "ignition switch," with an in-instance cron job that self-stops after 4 hours of inbound-request silence.

Both targets run the same `config.yaml` / `docker-compose.yml` pair unmodified; only the boot/deploy scripts differ per target.

## Target Users

A single engineer (or small personal team) running AI coding tools from their own laptop(s), who wants one OpenRouter-backed endpoint reachable only over their own Tailscale network — no public exposure, no per-seat SaaS cost, and a cache that survives their pause/resume usage pattern.

## Goals

- One OpenAI-compatible endpoint (`/v1/chat/completions`) fronting OpenRouter, reachable only via Tailscale.
- Repeated identical requests hit cache in well under 1s, and cache survives container restarts and host pause/resume.
- Long-context / tool-output payloads are compressed before they leave the host, cutting upstream token spend.
- AWS deploy target never exceeds ~$3.65/month in public-IP cost and self-stops after sustained idle.
- Both deploy targets boot unattended from a cold pause/stop with no manual intervention beyond the initial trigger (pod resume click, or Lambda ignition URL hit).

## Non-Goals

- No public HTTPS endpoint, domain, or TLS certificate — Tailscale is the only network boundary.
- No multi-tenant auth model — a single shared LiteLLM master key is sufficient for this project's user base.
- No self-hosted model inference — all completions are proxied to OpenRouter; this project owns no model weights.
- No load balancer, NAT gateway, or secondary IPs on the AWS target — the single-EIP constraint is deliberate, not a gap to fill later.

## Tenets

- **Boring over clever.** Prefer LiteLLM's and Headroom's built-in config-driven mechanisms over custom proxy code; a future maintainer should not have to reverse-engineer a bespoke router.
- **Network isolation over app-layer security.** Tailscale is the sole trust boundary; do not compensate for a network-layer gap by adding application-layer auth complexity.
- **Persistent state survives ephemeral compute.** Anything that must not reset on pause/stop (Tailscale identity, Redis snapshots) lives on the host's persistent volume, never in default ephemeral paths.
- **Cost ceiling over convenience.** Where a cost constraint (single EIP, `t3`/`t4g` small-medium whitelist, 4h idle stop) trades off against operational convenience, the cost constraint wins.

## System Design

```
[ Your Laptops (Mac/Windows with Tailscale) ]
                 |
   (Encrypted WireGuard Tunnel via MagicDNS/IP)
                 |
[ Jarvis Labs Pod  -OR-  AWS EC2 Instance (Tailscale Installed) ]
                 |
    [ LiteLLM Gateway :4000 ]
      /                    \
(Pre-Call Guardrail)   (Semantic Cache + Persistence)
    v                        v
[ Headroom :8787 ]     [ Redis :6379 (Volume Mounted) ]
    \                      /
     v                    v
  [ OpenRouter API (Upstream) ]
```

- **LiteLLM** — central router: OpenAI-compatible endpoint translation, model list (including an OpenRouter wildcard passthrough), guardrail invocation, Redis-backed response caching.
- **Headroom** — sidecar invoked by LiteLLM as a `pre_call` guardrail; compresses long context / tool output before the request reaches OpenRouter.
- **Redis** — response cache with a 7-day TTL (bounds staleness) and `allkeys-lru` eviction under a 1.5GB memory cap (bounds runaway growth); volume-mounted so pause/resume and container restarts don't lose cache state.
- **Tailscale** — installed on the host (not containerized); provides the only reachable network path to port 4000. Its machine-identity state directory is pinned onto the host's persistent volume so pause/resume doesn't re-register the host as a new node.
- **Deploy-target boot scripts** — target-specific (Jarvis startup script vs. AWS `start_stack.sh` + `idle_check.sh` + Lambda ignition); everything above the boot script is shared.

## Key Design Decisions

| Decision | Alternatives considered | Rationale |
|---|---|---|
| Config (`config.yaml`, `docker-compose.yml`) is identical across both deploy targets | Per-target config forks | A single source of truth avoids drift between environments; only boot orchestration differs, and that's inherently target-specific. |
| Tailscale runs on the host, not as a container | Containerized Tailscale sidecar | Host-level install lets `--statedir` pin to a path that survives pause/resume without extra volume plumbing per container. |
| Redis persistence via `--save 60 1` + mounted volume, not a managed cache service | Managed Redis (ElastiCache, Upstash) | Avoids recurring cloud spend and keeps the whole stack inside the pause/stop cost model of the compute host itself. |
| AWS idle-shutdown detected via `docker logs --since 4h | grep -c "POST /"` | CloudWatch-based request metrics | No AWS-side metering cost or IAM surface; the check runs entirely on-host via cron. |
| EC2 instance type whitelist enforced in the Lambda ignition function, not just documented | Trust the caller / no server-side check | AWS silently fails cross-architecture (`t3` ↔ `t4g`) resizes; validating server-side turns a silent failure into a clear 400. |
| Test tooling: pytest as the sole runner, for both the Python Lambda and the shell boot/idle scripts (via subprocess + PATH-shimmed fake `docker`/`git`/`tailscale` binaries) | A second shell-specific framework (e.g. bats) for the scripts | One runner across the whole repo avoids a second test framework for a handful of shell scripts whose logic is thin orchestration; PATH-shimming is sufficient to assert call sequence without real infra. |
| Dev tooling: mise pins the Python version (`.mise.toml`), uv manages dependencies (`pyproject.toml` + `uv.lock`) | pyenv + pip/venv, Poetry | mise+uv gives a single pinned, reproducible toolchain across contributors/CI without a second version manager; uv's lockfile makes dependency resolution deterministic. `python-preference = "only-system"` in `pyproject.toml` keeps uv from fetching its own interpreter and silently diverging from mise's pin. |

## Success Metrics

- Second identical request to `/v1/chat/completions` returns in well under 1s (cache hit), verified via LiteLLM logs showing a cache hit on the second call.
- `docker logs litellm-proxy` shows zero unauthenticated/public-origin requests — all traffic originates from a Tailscale peer IP.
- An EC2 instance left idle (zero `POST /` in `docker logs --since 4h`) transitions to `stopped` within one cron interval after the 4-hour mark.
- A Lambda ignition call with an invalid `size` query param returns HTTP 400 and does not start the instance.
- A Jarvis Labs pod resumed after a pause reconnects to Tailscale under its original hostname (no `-1`/`-2` suffix ghost node) and serves a cache hit for a pre-pause request.

## References

- `docs/gemini/initial-survey.md` — full stack spec, both deploy targets, Lambda ignition code.
