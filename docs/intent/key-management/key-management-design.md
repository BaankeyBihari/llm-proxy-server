---
parent: high-level-design
prefix: KEYS
---

# Key Management

## Context and Design Philosophy

The gateway stack ships with one shared `LITELLM_MASTER_KEY` — fine for a single laptop, not for an operator running several devices (or a small personal team) against the same gateway who wants per-device spend visibility and a cap that doesn't require trusting every device with the one key that can do anything. This leaf adds LiteLLM's own DB-backed virtual-key management (`/key/generate`, `/ui`, per-key budgets and spend logs) on top of `gateway-stack`'s `config.yaml`/`docker-compose.yml`, which it extends rather than forks. It owns the Postgres service and the key/budget policy; it does not own routing, guardrailing, or caching (`gateway-stack`'s territory).

The HLD's Non-Goal still holds: this is not an external user-account system. Keys are operator-provisioned (via `/key/generate`, authenticated with the master key), not self-service signup — same single-operator trust model as before, just with per-device budget isolation instead of one shared key for everything.

## Postgres Service

`postgres:16-alpine`, `./postgres-data:/var/lib/postgresql/data` — same bind-mount-under-the-repo persistence pattern as `redis-data` and the embedding sidecar's weights cache, so a pause/resume or stop/start doesn't lose issued keys, budgets, or spend history. `POSTGRES_PASSWORD` comes from `project-config`'s `project.toml` (`[secrets].postgres_password`, see `project-config-design.md`); `POSTGRES_DB=litellm`.

No host port published — internal-only, same convention as every other backing service in this stack.

## LiteLLM Wiring

`DATABASE_URL=postgresql://litellm:${POSTGRES_PASSWORD}@postgres:5432/litellm` on the `litellm` service. LiteLLM's own image runs its Prisma migration automatically at startup when `DATABASE_URL` is present — no manual migration step in any boot script, matching the "boring over clever" tenet.

`litellm` declares `depends_on: [redis, headroom, embedding, postgres]`. Same convention as the other three sidecars: this governs container *start order* only, not readiness. A Postgres hiccup at boot doesn't hard-fail the whole gateway — LiteLLM's own retry covers the gap, and plain chat completions (which don't touch keys/budgets) keep working even while key-management is mid-restart.

## `/key/generate` and `/ui`

Operator mints a key per device against `/key/generate` (authenticated with `LITELLM_MASTER_KEY`), setting `max_budget` (USD) and `budget_duration` (e.g. `30d`) explicitly per call — **no blanket default budget applied automatically**. A silent default risks capping a device that legitimately needs more, or under-capping one that doesn't; the operator already knows the intended budget at mint time.

`/ui` (LiteLLM's built-in Admin UI) is reachable at `http://<tailscale-host>:4000/ui`, over the same Tailscale-only network path as everything else. Login reuses `LITELLM_MASTER_KEY` — no new secret to manage, no `UI_USERNAME`/`UI_PASSWORD` pair, consistent with the single-operator trust model.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Key management backend | Postgres in-stack, LiteLLM's built-in `/key/generate` + `/ui` | Per-device OpenRouter-native keys, no LiteLLM DB | Real per-key budgets and a unified spend view across devices are worth one more self-hosted stateful service on the same cost model as Redis (no managed DB, no recurring cloud spend). |
| DB engine | Postgres 16-alpine | MySQL (also LiteLLM-supported) | Postgres is LiteLLM's primary-documented/tested DB target; matches its Prisma schema's default. |
| Migration | Automatic, via LiteLLM's own startup when `DATABASE_URL` is set | A manual `prisma migrate deploy` step added to every boot script | Built-in mechanism — no new boot-script logic duplicated across `local-launch`, `aws-deploy`, `jarvis-deploy`. |
| `/ui` auth | Reuse `LITELLM_MASTER_KEY` | Separate `UI_USERNAME`/`UI_PASSWORD` | No new secret to provision or store; matches the single-operator trust model already established. |
| Default per-key budget | None — operator sets `max_budget`/`budget_duration` explicitly per `/key/generate` call | A blanket default budget applied to every generated key | Different devices need different caps; a silent default risks surprising a legitimate high-usage device or under-capping a low-usage one. |
| Postgres readiness | `depends_on` + LiteLLM's own retry, same convention as Redis/Headroom/embedding | Hard-fail the gateway if Postgres is unreachable at boot | Chat completions don't depend on key-management; a DB hiccup shouldn't take down the whole gateway. |

## Open Questions & Future Decisions

### Deferred

1. Budget-exceeded behavior (hard block vs. soft-warn) is left to LiteLLM's own default (`max_budget` blocks further requests once exceeded) — no override specced here.
2. Per-key model restrictions (limiting a device to a subset of `model_list` entries) are available via `/key/generate`'s `models` param but not currently exercised by any spec — left to future demand.

## References

- `docs/high-level-design.md`
- `docs/intent/gateway-stack/gateway-stack-design.md` — the `config.yaml`/`docker-compose.yml` this leaf extends
- `docs/intent/project-config/project-config-design.md` — supplies `POSTGRES_PASSWORD` via `project.toml`
