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

`0.85` is biased toward precision over recall: a false cache **hit** serves a wrong answer (silent, hard to notice); a false cache **miss** just costs one extra OpenRouter call (visible in spend, self-correcting). Tunable via `EMBEDDING_SIMILARITY_THRESHOLD` if false hits show up in practice (e.g. two prompts differing only in an ID or a negation embedding close enough to collide).

**Cache-key ordering assumption**: the cache key is computed from the incoming request as the client sent it, before the Headroom guardrail transforms what's forwarded upstream. Two similar-enough client requests hit the cache on the second call regardless of any compression Headroom applies — compression affects upstream token spend, not cache-hit rate. This is LiteLLM's default pre-call-guardrail-vs-cache ordering; it is not overridden here.

## Embedding Sidecar

`redis-semantic` needs an embedding model to score prompt similarity; OpenRouter doesn't reliably serve embeddings, so this is self-hosted in-stack per the HLD's "self-host over external vendor for capability gaps" tenet, rather than a second external API/key.

- Image: `michaelfeil/infinity` — off-the-shelf, OpenAI-embeddings-API-compatible, no custom Dockerfile.
- Model: `BAAI/bge-small-en-v1.5` — small enough for fast CPU inference, sufficient for prompt-similarity scoring (not full-corpus retrieval).
- Weights cache: `./embedding-cache:/data`, `HF_HOME=/data` — same bind-mount-under-the-repo pattern as `redis-data`, so a pause/resume or stop/start reloads cached weights instead of re-downloading them.
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
| Embedding sidecar image | `michaelfeil/infinity` | Custom Dockerfile around `sentence-transformers` | Off-the-shelf OpenAI-embeddings-API-compatible server needs no build step, matches "boring over clever." |
| Embedding model | `BAAI/bge-small-en-v1.5` | A larger/higher-accuracy embedding model | Small enough for fast CPU inference on the same constrained instance tiers the rest of the stack runs on; prompt-similarity scoring doesn't need retrieval-grade accuracy. |
| Similarity threshold default | `0.85` | LiteLLM's own default (`0.8`) | Biased toward precision (fewer false cache hits serving a wrong answer) over recall (a false miss only costs one extra OpenRouter call). |
| Embedding sidecar failure mode | Fail open — treat as cache miss, request still completes | Error the request | Availability over cache-hit-rate; a missed semantic lookup costs money, an errored request breaks a tool call mid-flow. |

## Open Questions & Future Decisions

### Deferred

1. Whether additional named routes (e.g., a coding-specific model) are added is left to future demand — no current spec constrains the `model_list` to exactly these four plus wildcard.

## References

- `docs/high-level-design.md`
- `docs/gemini/initial-survey.md` § 2 (Core Configuration Files)
