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

- [x] **GATE-007**: The system shall enable Redis-backed response caching with a TTL of 604800 seconds (7 days).
- [x] **GATE-008**: The Redis service shall persist snapshots to a host-mounted volume (`./redis-data:/data`) with `--save 60 1`, so cache state survives container restart.
- [x] **GATE-009**: The Redis service shall cap memory at 1536mb and evict under the `allkeys-lru` policy when the cap is reached.

## Service Composition

- [x] **GATE-010**: The `litellm` service shall declare `depends_on` on both `redis` and `headroom`.
