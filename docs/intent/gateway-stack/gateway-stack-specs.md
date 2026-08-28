# Gateway Stack — EARS Specs

## Model Routing

- [x] **GATE-001**: The system shall route requests for model `smart-auto` to `openrouter/openrouter/auto`.
- [x] **GATE-002**: The system shall route requests for model `cheapest-auto` to `openrouter/openrouter/auto:floor`.
- [x] **GATE-003**: The system shall route requests for model `fast-auto` to `openrouter/openrouter/auto:nitro`.
- [x] **GATE-004**: The system shall define `resilient-router` as a fallback chain with `nousresearch/hermes-3-llama-3.1-405b` first and `nvidia/llama-3.1-nemotron-70b-instruct` second.
- [x] **GATE-005**: The system shall accept a wildcard passthrough model name `openrouter/*` and route it to the equivalent OpenRouter model unmodified.

## Guardrail

- [x] **GATE-006**: The system shall register Headroom (`http://headroom:8787`) as a `pre_call` guardrail, enabled by default on every request.

## Caching

- [x] **GATE-007**: The system shall enable Redis-backed semantic response caching (`cache_params.type: redis-semantic`) with a TTL of 604800 seconds (7 days).
- [x] **GATE-008**: The Redis service shall persist snapshots to a host-mounted volume (`./redis-data:/data`) with `--save 60 1`, so cache state survives container restart.
- [x] **GATE-009**: The Redis service shall cap memory at 1536mb and evict under the `allkeys-lru` policy when the cap is reached.
- [x] **GATE-011**: The semantic cache's `similarity_threshold` shall default to `0.85`, overridable via the `EMBEDDING_SIMILARITY_THRESHOLD` environment variable.

## Embedding Sidecar

- [x] **GATE-012**: The `docker-compose.yml` shall declare exactly one `embedding` service using the `michaelfeil/infinity` image, serving the `BAAI/bge-small-en-v1.5` model, with no host port published.
- [x] **GATE-013**: The `embedding` service shall mount `./embedding-cache:/data` and set `HF_HOME=/data`, so downloaded model weights persist across container restart.

Fail-open behavior on a mid-request sidecar outage (design doc's "Embedding Sidecar" section) is deliberately not a spec here — it's LiteLLM's own cache-client behavior, not code this repo writes or a config value it sets; nothing in `config.yaml`/`docker-compose.yml` can assert it. Same class as the unspecced "Cache-key ordering assumption" paragraph already in this doc.

## Service Composition

- [x] **GATE-010**: The `litellm` service shall declare `depends_on` on `redis`, `headroom`, and `embedding`.
