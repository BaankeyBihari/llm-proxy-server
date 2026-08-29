---
parent: high-level-design
prefix: GATE
---

# Gateway Stack

## Context and Design Philosophy

The gateway stack is the deploy-target-agnostic core: `config.yaml`, `docker-compose.yml`, and `.env.example`. It is the single source of truth both deploy targets (`jarvis-deploy`, `aws-deploy`) run unmodified — target-specific concerns (Tailscale, boot sequencing, idle shutdown) live in those leaves, not here. Its job is routing, guardrailing, and caching; it owns no deployment orchestration.

## Model Routing

LiteLLM's `model_list` exposes four named routes plus a wildcard, each mapped to a specific OpenRouter behavior:

| `model_name` | Upstream model | Purpose |
|---|---|---|
| `smart-auto` | `openrouter/openrouter/auto` | Best overall model, OpenRouter's own routing |
| `cheapest-auto` | `openrouter/openrouter/auto:floor` | Lowest-cost auto-router |
| `fast-auto` | `openrouter/openrouter/auto:nitro` | High-speed auto-router |
| `resilient-router` | `nousresearch/hermes-3-llama-3.1-405b`, then `nvidia/llama-3.1-nemotron-70b-instruct` | LiteLLM's built-in fallback chain — two `litellm_params` entries under the same `model_name` |
| `openrouter/*` | `openrouter/*` | Wildcard passthrough for any OpenRouter model not covered above |

All entries share `api_key: os.environ/OPENROUTER_API_KEY`.

## Guardrail Wiring

Headroom is registered as a `pre_call` guardrail (`guardrail: headroom`, `api_base: http://headroom:8787`, `default_on: true`) so every request is compressed before it reaches OpenRouter, with no per-request opt-in required.

## Caching

`litellm_settings.cache` is backed by Redis (`cache_params.type: redis-semantic`, host from `REDIS_HOST`, `ttl: 604800` — 7 days, `similarity_threshold: 0.85`). The TTL is chosen to survive a full work week of pause/resume cycles while still bounding the `.rdb` file's growth (see HLD Tenets: cost ceiling over convenience). `redis-semantic` (not plain `redis`) makes near-duplicate prompts — not just byte-identical ones — hit the cache; a rephrased question with the same intent no longer pays for a fresh OpenRouter call.

`0.85` is biased toward precision over recall: a false cache **hit** serves a wrong answer (silent, hard to notice); a false cache **miss** just costs one extra OpenRouter call (visible in spend, self-correcting). It's a literal float in `config.yaml`, not env-var-driven — LiteLLM's `os.environ/` substitution always returns a string, and the redis-semantic backend does unguarded arithmetic on this value at boot (`1 - similarity_threshold`), so a string crashes it every time. Tuning it (e.g. if two prompts differing only in an ID or a negation embed close enough to collide) means editing `config.yaml` directly.

**Cache-key ordering assumption**: the cache key is computed from the incoming request as the client sent it, before the Headroom guardrail transforms what's forwarded upstream. Two similar-enough client requests hit the cache on the second call regardless of any compression Headroom applies — compression affects upstream token spend, not cache-hit rate. This is LiteLLM's default pre-call-guardrail-vs-cache ordering; it is not overridden here.

## Embedding Sidecar

`redis-semantic` needs an embedding model to score prompt similarity; OpenRouter doesn't reliably serve embeddings, so this is self-hosted in-stack per the HLD's "self-host over external vendor for capability gaps" tenet, rather than a second external API/key.

- Image: `ollama/ollama:latest` — off-the-shelf, multi-arch (amd64 + arm64), no custom Dockerfile.
- Model: `nomic-embed-text` — small enough for fast CPU inference, sufficient for prompt-similarity scoring (not full-corpus retrieval); served over Ollama's OpenAI-compatible `/v1/embeddings` endpoint.
- `OLLAMA_HOST=0.0.0.0` — Ollama binds `127.0.0.1` by default; without this the `litellm` container can't reach it over the compose network.
- Boot sequence: entrypoint runs `ollama serve` in the background, then `ollama pull nomic-embed-text` before handing off to `wait`. The pull is a no-op after the first boot — the model is cached on the mounted volume, so pause/resume or restart doesn't re-download it. A failed pull (e.g. no network on first boot) leaves the sidecar without the model loaded; covered by the existing fail-open behavior below, not a new failure mode.
- Weights cache: `./embedding-cache:/root/.ollama` — same bind-mount-under-the-repo pattern as `redis-data`, so a pause/resume or stop/start reloads cached weights instead of re-downloading them.
- No host port published — internal-only, same convention as Headroom and Redis.
- **Sidecar unreachable mid-request**: fails open. LiteLLM treats it as a cache miss and the request still completes via OpenRouter — availability over cache-hit-rate; a missed semantic-cache lookup is a spend cost, an errored request is a broken tool call.

## Redis Persistence and Bounds

The `redis` service mounts `./redis-data:/data` and enables snapshotting via `--save 60 1` (save if ≥1 key changed in the last 60s), so the cache survives container restarts and host pause/resume. Memory is capped at `1536mb` with `allkeys-lru` eviction, bounding worst-case growth independent of the TTL.

## Service Startup Order

`litellm` declares `depends_on: [redis, headroom, embedding]` — Compose starts the other three first, though this governs container *start order* only, not readiness; LiteLLM's own retry/connection handling covers the gap between "container started" and "service accepting connections."

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Cache backend | Redis, self-hosted in-stack | Managed cache (ElastiCache, Upstash) | Keeps the whole stack inside the host's own pause/stop cost model; no recurring managed-service spend. |
| Redis eviction bound | `maxmemory 1536mb` + `allkeys-lru`, alongside the 7-day TTL | TTL alone | TTL bounds staleness, not size — a burst of unique requests within the TTL window could otherwise grow `.rdb` unbounded. |
| Guardrail invocation point | `pre_call` | `post_call` or dual pre/post | Compression must happen before the request leaves the host to reduce upstream token spend; a post-call guardrail would compress a response already paid for. |
| Model routing | Named routes (`smart-auto`, `cheapest-auto`, `fast-auto`, `resilient-router`) plus a wildcard | Wildcard-only passthrough | Named routes give predictable, memorable entry points for common cases while the wildcard still covers the long tail. |
| Embedding sidecar image | `ollama/ollama:latest` | `michaelf34/infinity`; custom Dockerfile around `sentence-transformers` | `michaelf34/infinity` publishes amd64-only manifests (verified: no arm64 variant on `latest` or `-cpu` tags) — breaks the `t4g.*` EC2 whitelist and Apple Silicon dev parity. Ollama is multi-arch and still off-the-shelf, matching "boring over clever." |
| Embedding model | `nomic-embed-text` | `BAAI/bge-small-en-v1.5`; a larger/higher-accuracy embedding model | Ollama's standard small embedding model, matches the sidecar-image swap; small enough for fast CPU inference on the same constrained instance tiers the rest of the stack runs on — prompt-similarity scoring doesn't need retrieval-grade accuracy. |
| Similarity threshold default | `0.85`, literal in `config.yaml` | LiteLLM's own default (`0.8`); `os.environ/EMBEDDING_SIMILARITY_THRESHOLD` for runtime overridability | Biased toward precision (fewer false cache hits serving a wrong answer) over recall (a false miss only costs one extra OpenRouter call). The env-var form was tried first and crashes on boot — LiteLLM's `os.environ/` substitution is string-only and the redis-semantic backend does unguarded float arithmetic on it. |
| Embedding sidecar failure mode | Fail open — treat as cache miss, request still completes | Error the request | Availability over cache-hit-rate; a missed semantic lookup costs money, an errored request breaks a tool call mid-flow. |

## Open Questions & Future Decisions

### Deferred

1. Whether additional named routes (e.g., a coding-specific model) are added is left to future demand — no current spec constrains the `model_list` to exactly these four plus wildcard.

## References

- `docs/high-level-design.md`
- `docs/gemini/initial-survey.md` § 2 (Core Configuration Files)
