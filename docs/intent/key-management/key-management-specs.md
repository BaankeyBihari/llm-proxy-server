# Key Management — EARS Specs

## Postgres Service

- [x] **KEYS-001**: The `docker-compose.yml` shall declare exactly one `postgres` service using the `postgres:16-alpine` image, with `./postgres-data:/var/lib/postgresql/data` mounted and `POSTGRES_DB=litellm`.
- [x] **KEYS-002**: The `postgres` service shall not publish any host port.
- [x] **KEYS-003**: The `litellm` service shall set `DATABASE_URL` to a `postgresql://` connection string using `POSTGRES_PASSWORD` from the environment.
- [x] **KEYS-004**: The `litellm` service's `depends_on` shall include `postgres`.

(Readiness-insensitivity — `litellm` not requiring `postgres` to be ready before its own retry logic handles the gap — is design-doc rationale, not a separate spec; same precedent as `GATE-010`, which only tests `depends_on` membership, not readiness semantics.)
- [x] **KEYS-007**: No boot script (`local-launch.sh`, `aws-start-stack.sh`, `jarvis-startup.sh`) shall invoke a database migration command; schema migration shall be handled automatically by LiteLLM's own startup when `DATABASE_URL` is set.

## Virtual Keys and Budgets

- [x] **KEYS-005**: The system shall not configure any default `max_budget` applied automatically to keys generated via `/key/generate`; budget parameters shall be supplied explicitly per call.
- [x] **KEYS-006**: The system shall not configure separate `UI_USERNAME`/`UI_PASSWORD` variables; `/ui` login shall authenticate with `LITELLM_MASTER_KEY`.

## References

- `docs/high-level-design.md`
- `docs/intent/key-management/key-management-design.md`
- `docs/intent/gateway-stack/gateway-stack-specs.md` — `GATE-010`'s `depends_on` list, extended by `KEYS-004`
