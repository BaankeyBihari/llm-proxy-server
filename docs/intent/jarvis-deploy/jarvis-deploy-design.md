---
parent: high-level-design
prefix: JARVIS
---

# Jarvis Deploy

## Context and Design Philosophy

Jarvis Labs pods are paused, not terminated, between sessions — the boot script's job is to make a paused-then-resumed pod indistinguishable from a continuously-running one: same Tailscale identity, same code, same running stack. It consumes `gateway-stack`'s `config.yaml`/`docker-compose.yml` unmodified; everything here is boot orchestration, not routing or caching logic.

## Boot Sequence

The startup script (pasted into Jarvis Labs' instance "Startup Script" field, so it runs on every resume) performs, in order:

1. **Tailscale up with a pinned state directory.** `tailscaled --statedir=/home/litellm-stack/tailscale-state`, then `tailscale up --authkey=... --hostname=jarvis-litellm --accept-routes`. Pinning `--statedir` under `/home/` (Jarvis's persistent volume) is the fix for the "ghost node" failure mode: a pod pause resets `/var/lib/`, and an unpinned Tailscale would re-register as a new machine (`jarvis-litellm-1`, `-2`, ...) on every resume.
2. **Workspace sync.** If `$WORKSPACE/.git` doesn't exist, clone the repo; otherwise `git pull origin main`. This makes the script idempotent across both first-boot and every subsequent resume.
3. **Docker daemon wait.** Poll `docker info` in a loop until it succeeds — cloud startup scripts run early enough in boot that the Docker daemon is often not yet ready, and `docker compose up` against a not-yet-ready daemon fails silently.
4. **`.env` bootstrap.** If `.env` doesn't exist, write placeholder `OPENROUTER_API_KEY` / `LITELLM_MASTER_KEY` lines so the compose stack has something to read on true first boot; a real deployment overwrites these before first genuine use.
5. **Bring up the stack.** `docker compose up -d --build`.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Tailscale state location | `/home/litellm-stack/tailscale-state` | Default `/var/lib/tailscale` | Only `/home/` survives a Jarvis Labs pause; `/var/lib/` is reset. |
| Repo sync strategy | Clone-if-absent, else pull | Always re-clone | Re-cloning discards any host-local `.env` and `redis-data/`; pull preserves them. |
| Docker readiness check | Polling loop on `docker info` | Fixed `sleep N` | A fixed sleep is either too short (race) or wastes boot time on faster resumes; polling adapts to actual readiness. |

## Open Questions & Future Decisions

### Deferred

1. Whether to systemd-manage this script instead of relying solely on the Jarvis Labs "Startup Script" hook is left for later — the platform-native hook is sufficient at current scale.

## References

- `docs/high-level-design.md`
- `docs/gemini/MasterGuide-LiteLLM-Stack.md` § 4 (Phase 2: Production on Jarvis Labs)
- `docs/gemini/RisAnalysis.md` § 1 (Tailscale Ghost Node), § 2 (Docker Daemon Boot Race)
