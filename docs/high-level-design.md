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
- Semantic cache hits near-duplicate prompts (not just byte-identical), cutting cache misses from harmless rephrasing.
- Long-context / tool-output payloads are compressed before they leave the host, cutting upstream token spend.
- Per-device virtual keys with individual budgets and spend visibility, no external user-account system.
- AWS deploy target never exceeds ~$3.65/month in public-IP cost and self-stops after sustained idle.
- Both deploy targets boot unattended from a cold pause/stop with no manual intervention beyond the initial trigger (pod resume click, or Lambda ignition URL hit).

## Non-Goals

- No public HTTPS endpoint, domain, or TLS certificate — Tailscale is the only network boundary.
- No external user-account system — virtual keys are operator-provisioned (via LiteLLM's `/key/generate`), not self-service signup; still a single-operator trust model, just with per-device budget isolation.
- No self-hosted **completion** inference — all chat completions are proxied to OpenRouter; this project owns no completion-model weights. Embeddings (semantic-cache similarity only) are the one exception, self-hosted in-stack per the self-host tenet below.
- No load balancer, NAT gateway, or secondary IPs on the AWS target — the single-EIP constraint is deliberate, not a gap to fill later.

## Tenets

- **Boring over clever.** Prefer LiteLLM's and Headroom's built-in config-driven mechanisms over custom proxy code; a future maintainer should not have to reverse-engineer a bespoke router.
- **Network isolation over app-layer security.** Tailscale is the sole trust boundary; do not compensate for a network-layer gap by adding application-layer auth complexity.
- **Persistent state survives ephemeral compute.** Anything that must not reset on pause/stop (Tailscale identity, Redis snapshots) lives on the host's persistent volume, never in default ephemeral paths.
- **Cost ceiling over convenience.** Where a cost constraint (single EIP, `t3`/`t4g` small-medium whitelist, 4h idle stop) trades off against operational convenience, the cost constraint wins.
- **Self-host over external vendor for capability gaps.** When OpenRouter lacks a capability this project needs (embeddings today), prefer a small in-stack sidecar with the same volume-mount persistence pattern as Redis/Tailscale over adding a new external API vendor and key.

## System Design

```
[ Your Laptops (Mac/Windows with Tailscale) ]
                 |
   (Encrypted WireGuard Tunnel via MagicDNS/IP)
                 |
[ Jarvis Labs Pod  -OR-  AWS EC2 Instance (Tailscale Installed) ]
                 |
             [ LiteLLM Gateway :4000 ]
      /            |             |            \
(Pre-Call    (Semantic Cache  (Virtual Keys  (Response
 Guardrail)   + Persistence)   + Budgets)     Cache)
    v              v               v              v
[Headroom]   [Embedding      [Postgres      [Redis :6379
  :8787]      Sidecar        (Volume         (Volume
  |            (Volume        Mounted)]       Mounted)]
  |            Mounted)]
  |               |
   \             /
    v           v
  [ OpenRouter API (Upstream) ]
```

- **LiteLLM** — central router: OpenAI-compatible endpoint translation, model list (including an OpenRouter wildcard passthrough), guardrail invocation, Redis-backed response caching, virtual-key issuance and budget enforcement.
- **Headroom** — sidecar invoked by LiteLLM as a `pre_call` guardrail; compresses long context / tool output before the request reaches OpenRouter.
- **Redis** — response cache with a 7-day TTL (bounds staleness) and `allkeys-lru` eviction under a 1.5GB memory cap (bounds runaway growth); volume-mounted so pause/resume and container restarts don't lose cache state.
- **Embedding sidecar** — self-hosted OpenAI-embeddings-API-compatible service, invoked by LiteLLM's semantic-cache backend to score prompt similarity; model weights volume-mounted so pause/resume doesn't force a re-download, only a reload.
- **Postgres** — backs LiteLLM's virtual-key management (`/key/generate`, `/ui`, per-key budgets and spend logs); volume-mounted for the same persistence reason as Redis.
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
| AWS resources (EC2, EIP, IAM, Lambda) provisioned via Terraform, not manual console clicks or CloudFormation/CDK | Manual console setup, CloudFormation/CDK, bash+aws-cli scripts | A declarative state file gives a reliable `terraform destroy` teardown path matching the cost-ceiling tenet; avoids a second toolchain (CDK) in a Python/shell repo; `cloud-nuke` is the documented fallback only if local state is lost. |
| Local, AWS, and Jarvis interactive setup share one script (`scripts/launch.sh --env=local|aws|jarvis`) that populates `project.toml` per-key and then does the target's own trailing action (`docker compose up -d` for local, `terraform apply` for AWS, rendering `jarvis-startup.sh` for Jarvis), not a one-shot `cp .env.example .env`, separate per-target scripts, or hand-editing a checked-in placeholder script | Leave `cp .env.example .env` as the only documented step; keep separate `local-launch.sh`/`aws-launch.sh`/hand-edited-`jarvis-startup.sh`, one mechanism per target | A silent copy leaves placeholder secrets in place with no prompt to replace them; per-key confirmation surfaces that at setup time instead of at a failed OpenRouter auth call. All three targets share `project-toml.sh`'s prompt loop; only the trailing action and owned-key list differ, so one dispatched entrypoint is one fewer filename to remember without merging the `local-launch`/`aws-infra`/`jarvis-deploy` leaves themselves. The running-container guard stays local-only — AWS's `terraform apply` has its own idempotency, and Jarvis's render step has no state to guard. |
| Bitwarden Secrets Manager is a local secrets source, not a cloud-side bootstrap: `scripts/bws-sync.sh` pulls secrets into `project.toml`, run by the operator wherever they currently are (laptop, an SSM session on EC2, SSH on a Jarvis pod) — the same script and command for all three deploy targets | A Terraform `secrets_mode` switch that made the EC2 host self-fetch from Bitwarden at boot (this project's original approach) | The boot-time switch only ever covered AWS, needed its own Terraform variable/validation/branch, and put a Bitwarden access token in `user_data`/`terraform.tfstate`. A local sync script gives every target the same capability with no cloud-side token exposure and no target-specific code. |
| Bitwarden vault content is reviewed/updated via a standalone operator script (`scripts/bws-secrets-check.sh`), not folded into `scripts/launch.sh --env=aws` | Extend `scripts/launch.sh --env=aws` to also touch the bws vault during `terraform apply` | Vault maintenance happens whenever an operator wants to check/rotate a value, not only at deploy time; keeping it a separate script leaves the AWS launch path scoped to provisioning. |
| Semantic-cache embedding provider is a self-hosted sidecar, not an external API | External embedding API (e.g. OpenAI) | Self-host tenet; a second external vendor/key for a narrow capability gap isn't worth it, and a volume-mounted weights cache reuses the same pause/resume persistence pattern already established for Redis and Tailscale state. |
| Virtual-key management is Postgres in-stack, using LiteLLM's built-in `/key/generate` + `/ui` | Per-device OpenRouter-native keys, no LiteLLM DB | Real per-key budgets and a unified spend view across devices are worth one more self-hosted stateful service on the same cost model as Redis (no managed DB, no recurring cloud spend); the added RAM pressure on `t3.small`/`t4g.small` is an accepted trade-off, sized if/when it actually OOMs rather than upfront. |
| Canonical secrets/config source is `project.toml`, generated into `.env` (Compose) and `.auto.tfvars.json` (Terraform) by a small script | Every consumer script (`scripts/launch.sh`, `jarvis-startup.sh`, `bws-secrets-check.sh`) live-parses TOML at runtime | Native format per consumer (Compose's dotenv, Terraform's auto-loaded tfvars.json) avoids a parsing shim duplicated across scripts; matches "boring over clever." |

## Success Metrics

- Second identical request to `/v1/chat/completions` returns in well under 1s (cache hit), verified via LiteLLM logs showing a cache hit on the second call.
- `docker logs litellm-proxy` shows zero unauthenticated/public-origin requests — all traffic originates from a Tailscale peer IP.
- An EC2 instance left idle (zero `POST /` in `docker logs --since 4h`) transitions to `stopped` within one cron interval after the 4-hour mark.
- A Lambda ignition call with an invalid `size` query param returns HTTP 400 and does not start the instance.
- A Jarvis Labs pod resumed after a pause reconnects to Tailscale under its original hostname (no `-1`/`-2` suffix ghost node) and serves a cache hit for a pre-pause request.

## References

- `docs/gemini/initial-survey.md` — full stack spec, both deploy targets, Lambda ignition code.
- `docs/gemini/terraform-and-nuke-guide.md` — Terraform config for AWS provisioning + teardown (native `terraform destroy` and `cloud-nuke` fallback).
