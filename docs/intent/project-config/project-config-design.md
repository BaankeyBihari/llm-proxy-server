---
parent: high-level-design
prefix: CONF
---

# Project Config

## Context and Design Philosophy

Secrets and config were scattered across three checked-in templates in three formats — `.env.example` (dotenv, for Compose), `infra/terraform.tfvars.example` (HCL, for Terraform), and `jarvis-startup.sh`'s inline placeholder writes — each populated separately (`scripts/launch.sh`'s `--env=local`/`--env=aws`/`--env=jarvis` paths) with no shared source of truth. This leaf replaces all three with one canonical `project.toml`, and owns the schema plus the generator that renders it into whatever native format each consumer actually reads. It does not own *when* a script prompts for a value or brings a stack up — that stays with `local-launch`, `aws-infra` (`launch.sh --env=aws`), and `jarvis-deploy` (`launch.sh --env=jarvis`), which now target `project.toml` instead of their old per-format files.

**Per-machine, not cross-machine.** `project.toml` is the single source of truth *per checkout*, not synced across deploy targets — the laptop's clone (feeding `launch.sh --env=aws`/Terraform) and the EC2 host's clone (feeding `launch.sh --env=local`/Compose, reached over SSM) are separate files with the same schema, exactly as `.env` and `terraform.tfvars` were already separate files today. Unifying the format doesn't unify the machines.

## Schema

Two sections, not six single-purpose tables — `[config]` for non-secret settings, `[secrets]` for everything sensitive:

```toml
[config]
embedding_similarity_threshold = 0.85

[secrets]
openrouter_api_key = "your_openrouter_key_here"
litellm_master_key = "sk-master-key-1234"
postgres_password = "changeme"
tailscale_auth_key = "tskey-auth-REPLACE_ME"
```

Checked in as `project.toml.example`; `project.toml` itself is gitignored, same as `.env`/`terraform.tfvars` were.

`[config]` and `[secrets]` are both always read straight from `project.toml`, unconditionally, by `render_config.py` — a straight read-and-split, no branching on any value inside `project.toml`.

## Bitwarden as a Local Secrets Source

`scripts/bws-sync.sh` (owned by `aws-infra` — see its design doc's "Bitwarden Sync Script" section) is an optional upstream step that pulls `openrouter_api_key`/`litellm_master_key`/`postgres_password`/`tailscale_auth_key` from Bitwarden Secrets Manager and writes them into `project.toml`, before the usual `launch.sh --env=local`/`--env=aws` prompt runs. `project-config` doesn't own that script or know it exists at render time — `render_config.py` only ever reads `project.toml`, regardless of whether its values were typed by hand or synced from Bitwarden first. This replaces an earlier design (`secrets_mode`, a Terraform variable that made the EC2 host self-fetch from Bitwarden at boot) — retired because it only covered AWS, embedded a token into `user_data`/`terraform.tfstate`, and needed its own variable + validation + boot-time branch for what's now a plain, three-line-per-secret local script reusable by all three deploy targets.

## Table-to-File Mapping

| Key(s) | Rendered into | Consumed by |
|---|---|---|
| `[config]` (all), `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password` | `.env` | `docker-compose.yml` (`gateway-stack`, `key-management`) |
| `[secrets].tailscale_auth_key` | `infra/generated.auto.tfvars.json` | Terraform (`aws-infra`) |

## Generator

`scripts/render_config.py` — stdlib-only (`tomllib`, `json`), no new dependency, runs under any system `python3` ≥3.11 without needing `uv sync` first. That matters for `jarvis-startup.sh`, which can't assume the repo's `uv`-managed venv exists yet at first boot.

Reads `project.toml`, writes `.env` and `infra/generated.auto.tfvars.json` per the mapping above — a straight, unconditional read-and-split, no branching on any value inside `project.toml`. Both outputs are **always fully regenerated, gitignored, never hand-edited** — `project.toml` is the only file an operator or script touches directly; drift between a generated file and its source is structurally impossible if nothing ever hand-edits the generated side.

An unrecognized table/key in `project.toml` (e.g. a typo'd table name) is a hard error, not a silently-dropped value — a dropped key means a service boots with a missing secret, which is a worse failure to debug than a fast, loud one at render time.

Terraform loading: `infra/generated.auto.tfvars.json` matches Terraform's native `*.auto.tfvars.json` auto-load convention, so `launch.sh --env=aws`/`aws-destroy.sh` drop their `-var-file=terraform.tfvars` flag entirely — one less thing to keep in sync.

## Editing `project.toml`: Shared Prompt Loop

`launch.sh`'s `--env=local` and `--env=aws` paths both need the same keep-or-replace-per-key prompt UX, now against the *same file and same syntax* (previously `.env`'s `KEY=value` vs `.tfvars`'s `key = "value"` justified two separate ~15-line loops — see `aws-infra-design.md`'s now-superseded decision row). That justification no longer holds once both paths edit the same `project.toml`, so the loop moves to a shared `scripts/lib/project-toml.sh`, sourced by both.

The loop itself doesn't change shape: line-by-line scan, `[table]` header lines pass through unchanged (tracked only for display context, e.g. `secrets.openrouter_api_key`), `key = "value"` lines get the existing show-current/prompt-for-replacement/keep-on-empty treatment, blank lines and `#`-comments pass through unchanged. No TOML-writing library needed — this is the same line-based rewrite technique already proven twice in this repo (`.env`, `.tfvars`), just extended to recognize one more line shape (`[table]`). Python's `tomllib` is read-only by design (stdlib has no TOML writer); the generator (above) only ever *reads* `project.toml`, so that limitation never actually bites.

With only two tables now (`[config]`, `[secrets]`), scripts scope by **key**, not by table: `launch.sh --env=local` prompts `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`; `launch.sh --env=aws` prompts `[secrets].tailscale_auth_key`. No mode-awareness in the loop itself — every owned key is always prompted, unconditionally.

**Interface**: `project_toml_prompt_keys <file> <key> [<key> ...]` — scans `<file>` line by line; for any `key = "value"` line whose bare key name (unique across both tables in this schema, no disambiguation needed) is in the given list, shows the current value and prompts for a replacement, same keep-or-replace semantics as before. All other lines (including owned-table keys not passed in the list, unrecognized keys, blanks, comments, `[table]` headers) pass through unchanged. Callers: `launch.sh --env=local` → `project_toml_prompt_keys project.toml embedding_similarity_threshold openrouter_api_key litellm_master_key postgres_password`; `launch.sh --env=aws` → `project_toml_prompt_keys project.toml tailscale_auth_key`.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Generator implementation | Stdlib-only Python (`tomllib`, `json`) | A bash TOML parser (`yq`/`dasel`, new dependency) | No new dependency; runs under any system `python3` without `uv sync`, which matters for `jarvis-startup.sh`'s zero-setup boot. |
| Table-to-file mapping | Fixed table-level routing | Per-key metadata/target annotations inside `project.toml` | Each key has exactly one consumer already; fixed routing needs no extra schema and stays plain, readable TOML. |
| Generated file lifecycle | Always regenerated, gitignored, never hand-edited | Generate once, allow manual edits to drift | Matches `project.toml` as sole source of truth; hand-edits to a generated file would silently desync from it. |
| Terraform var loading | Native `*.auto.tfvars.json` auto-load | Keep `-var-file=terraform.tfvars` | Terraform's built-in mechanism does this for free — one less flag to keep in sync. |
| `project.toml` write path | Line-based rewrite in bash, shared between `launch.sh --env=local`/`launch.sh --env=aws` | A TOML-writing library (e.g. `tomlkit`) invoked from Python | Reuses the exact technique already proven for `.env` and `.tfvars` in this repo; avoids a new dependency for round-trip TOML writing that stdlib doesn't provide. |
| Prompt-loop code ownership | Shared `scripts/lib/project-toml.sh`, sourced by both of `launch.sh`'s env paths | Two separate copies (as `.env`/`.tfvars` had) | Same file, same syntax now — the divergence that justified two copies (`aws-infra-design.md`'s prior decision) no longer exists. |
| Unrecognized key/table in `project.toml` | Hard error at render time | Silently ignore/drop it | A dropped key means a service boots with a missing secret — a loud, fast failure at render time is cheaper to debug. |
| Retiring `.env.example` / `terraform.tfvars.example` | Replaced by one `project.toml.example` | Keep all three templates alongside the new file | Multiple templates for the same secrets invites drift; one canonical example matches "single source of truth." |
| Schema shape | Two sections, `[config]`/`[secrets]` | Six single-purpose tables (`[openrouter]`, `[litellm]`, `[postgres]`, `[embedding]`, `[tailscale]`, `[aws]`) (this doc's original draft) | Per-service tables looked tidy but didn't map to how the file is actually edited or reasoned about — the real distinction that matters is secret-vs-not (for prompting/masking), not which container consumes a value. |
| Bitwarden integration point | A separate upstream script (`bws-sync.sh`, owned by `aws-infra`) that writes `project.toml` before the usual prompt runs; `render_config.py` stays unaware Bitwarden exists | A `secrets_mode` toggle inside `project.toml`/`render_config.py` itself (this leaf's original design) | Retired: `secrets_mode` only ever covered the AWS target (Terraform-only), needed its own variable/validation/boot-time branch, and embedded a token in `user_data`/`terraform.tfstate`. A plain script that writes the same file every other consumer already reads works for all three targets and adds nothing to this leaf's own schema or generator. |

## Open Questions & Future Decisions

### Deferred

1. Non-interactive/CI rendering (e.g. a `--yes`/env-var-driven mode that skips the prompt loop entirely) is left open — no current need beyond local-dev and single-operator deploy convenience.

## References

- `docs/high-level-design.md`
- `docs/intent/local-launch/local-launch-design.md` — consumes `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`
- `docs/intent/aws-infra/aws-infra-design.md` — consumes `[secrets].tailscale_auth_key` via `launch.sh --env=aws`; owns `scripts/bws-sync.sh`, the optional Bitwarden-to-`project.toml` sync step; owns the Bitwarden pre-clone bootstrap this leaf deliberately doesn't integrate with
- `docs/intent/jarvis-deploy/jarvis-deploy-design.md` — seeds a placeholder `project.toml` on first unattended boot
- `docs/intent/key-management/key-management-design.md` — consumes `[secrets].postgres_password`
