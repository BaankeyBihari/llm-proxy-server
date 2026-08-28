# Project Config — EARS Specs

## Schema

- [x] **CONF-001**: The repository shall provide `project.toml.example` with a `[config]` table (`embedding_similarity_threshold` defaulting to `0.85`) and a `[secrets]` table (`openrouter_api_key`, `litellm_master_key`, `postgres_password`, `tailscale_auth_key`).

## Generator

- [x] **CONF-002**: `scripts/render_config.py` shall read `project.toml` using the stdlib `tomllib` module and shall not require any third-party dependency.
- [x] **CONF-003**: `render_config.py` shall write `.env` containing `OPENROUTER_API_KEY`, `LITELLM_MASTER_KEY`, `POSTGRES_PASSWORD`, and `EMBEDDING_SIMILARITY_THRESHOLD`.
- [x] **CONF-004**: `render_config.py` shall write `infra/generated.auto.tfvars.json` containing `tailscale_auth_key`, read directly from `project.toml` with no branching logic.
- [x] **CONF-005**: `render_config.py` shall read `openrouter_api_key`, `litellm_master_key`, and `postgres_password` directly from `project.toml`'s `[secrets]` table, unconditionally — it shall not invoke the `bws` CLI or any external process.
- [x] **CONF-007**: If `project.toml` contains a table or key not defined in the schema, `render_config.py` shall exit non-zero with an error rather than silently ignoring it.
- [x] **CONF-008**: `project.toml`, `.env`, and `infra/generated.auto.tfvars.json` shall be listed in `.gitignore`.
- [x] **CONF-011**: The repository shall not check in `.env.example` or `infra/terraform.tfvars.example`; `project.toml.example` shall be the sole checked-in template.

## Shared Prompt Loop

- [x] **CONF-009**: `scripts/lib/project-toml.sh` shall provide a per-key prompt loop over `project.toml` that passes `[table]` header lines, blank lines, and `#`-comment lines through unchanged, and for each `key = "value"` line shows the current value and prompts for a replacement (empty response keeps current, non-empty response replaces), unconditionally.

## References

- `docs/high-level-design.md`
- `docs/intent/project-config/project-config-design.md`
- `docs/intent/local-launch/local-launch-specs.md` — consumes `CONF-009` for `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`
- `docs/intent/aws-infra/aws-infra-specs.md` — consumes `CONF-004`/`CONF-009` for `[secrets].tailscale_auth_key`; owns `scripts/bws-sync.sh`, the Bitwarden-to-`project.toml` sync this leaf deliberately doesn't integrate with
- `docs/intent/jarvis-deploy/jarvis-deploy-specs.md` — consumes `CONF-009` for `[secrets].tailscale_auth_key` (reusing `aws-infra`'s field) via `launch.sh --env=jarvis`
