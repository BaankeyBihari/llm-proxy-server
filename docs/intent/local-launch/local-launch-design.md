---
parent: high-level-design
prefix: LOCAL
---

# Local Launch

## Context and Design Philosophy

`.env.example`'s placeholder values (`your_openrouter_key_here`, `sk-master-key-1234`) are easy to leave in place by accident — `docker compose up` starts fine either way, it just silently fails auth against real services. `local-launch.sh` closes that gap and doubles as the single command that takes an operator from a fresh checkout to a running, authenticated stack: populate `.env` interactively, then bring the stack up and hand back a working `curl` example. It defers entirely to `gateway-stack`'s `docker-compose.yml` for what "up" means — it only decides *when* to call `docker compose up -d`, never how the stack itself is composed.

`local-stop.sh` is the matching teardown: bring the stack down gracefully if it's up, warn (not error) if it's already down. Same segment as launch — both are local-dev lifecycle commands over the same Compose project, neither owns anything about the stack's composition.

## Behavior

1. If any container from this Compose project is already running (`docker compose ps --status running`), abort immediately — before touching `.env` — rather than prompting through values that a live container won't pick up without a restart.
2. If `.env` doesn't exist, copy `.env.example` to `.env` first. If `.env` already exists, leave it as-is (the source of current values for the next step) rather than resetting it to the template.
3. Read `.env` line by line, in file order. Blank lines and `#`-comment lines pass through unchanged.
4. For each `KEY=value` line, show the current value and prompt for a replacement.
5. An empty response keeps the current value; a non-empty response replaces it.
6. Write the result back to `.env`, preserving original line order (including untouched comments/blanks).
7. Bring the stack up: `docker compose up -d`.
8. Print a ready-to-run `curl` example against `/v1/chat/completions`, with the `Authorization` header already carrying the real `LITELLM_MASTER_KEY` value just written to `.env`.

### `local-stop.sh`

1. If no container from this Compose project is running, print a warning and exit — there's nothing to stop, and that's not a failure.
2. Otherwise, `docker compose down` — the default graceful stop (SIGTERM, grace period, then removal), no forced `-t 0`.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| How much of `.env` to prompt for | Every key, unconditionally, one at a time | Diff against `.env.example` and only prompt for still-placeholder values | Prompting every key is simpler and lets the operator re-confirm/rotate a real secret too, not just fill in placeholders; a diff-based approach would need to special-case "value equals the example's placeholder," which is fragile if a real secret happens to collide with the example text. |
| Which file's values count as "current" | `.env`'s existing values | Always show `.env.example`'s value as current | Re-running the script on an already-configured `.env` should offer to keep the real values already there, not silently step backward to the placeholders. |
| Whether the script starts the stack | Yes — `docker compose up -d` after `.env` is populated | Leave launching as a separate, manual step | A single command taking the operator from zero to a running, authenticated stack is worth more than the marginal flexibility of a standalone `.env` editor; the running-container guard (below) covers the case where that's undesirable. |
| Guard against re-running while the stack is already up | Abort before touching `.env` if any project container is running | Let `docker compose up -d`'s own idempotency handle it silently | `docker compose up -d` alone is safe to re-run, but *this script* isn't just that — it prompts through `.env` values a live container has already loaded and won't see until restarted; proceeding would silently mislead the operator into thinking an edit took effect. |
| `local-stop.sh`'s behavior when the stack is already down | Print a warning, exit 0 | Exit non-zero (treat as an error) | The desired end state — stack not running — is already true; that's success, not failure, matching `docker compose down`'s own idempotent behavior. |
| `local-stop.sh`'s stop method | Plain `docker compose down` (graceful) | `docker compose down -t 0` / `kill` | "Gracefully" was explicit in the request — the default SIGTERM-then-grace-period is what "graceful" means for Compose; forcing skips it. |

## Open Questions & Future Decisions

### Deferred

1. Non-interactive/CI usage (e.g. a `--yes` flag to skip all prompts) is left open — no current need; this script is a local-dev convenience, not part of any automated deploy path.

## References

- `docs/high-level-design.md`
- `docs/intent/gateway-stack/gateway-stack-design.md` — defines the `.env` keys this script prompts for
- `README.md` § Running the stack
