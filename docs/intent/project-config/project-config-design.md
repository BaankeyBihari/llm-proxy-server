---
parent: high-level-design
prefix: CONF
---

# Project Config

## Context and Design Philosophy

Secrets and config were scattered across three checked-in templates in three formats — `.env.example` (dotenv, for Compose), `infra/terraform.tfvars.example` (HCL, for Terraform), and `jarvis-startup.sh`'s inline placeholder writes — each populated by its own script (`local-launch.sh`, `aws-launch.sh`, `jarvis-startup.sh`) with no shared source of truth. This leaf replaces all three with one canonical `project.toml`, and owns the schema plus the generator that renders it into whatever native format each consumer actually reads. It does not own *when* a script prompts for a value or brings a stack up — that stays with `local-launch`, `aws-infra` (`aws-launch.sh`), and `jarvis-deploy`, which now target `project.toml` instead of their old per-format files.

**Per-machine, not cross-machine.** `project.toml` is the single source of truth *per checkout*, not synced across deploy targets — the laptop's clone (feeding `aws-launch.sh`/Terraform) and the EC2 host's clone (feeding `local-launch.sh`/Compose, reached over SSM) are separate files with the same schema, exactly as `.env` and `terraform.tfvars` were already separate files today. Unifying the format doesn't unify the machines.

## Schema

Two sections, not six single-purpose tables — `[config]` for non-secret settings, `[secrets]` for everything sensitive:

```toml
[config]
secrets_mode = "project_toml"       # or "bitwarden" — AWS-only, opt in via aws-launch.sh
embedding_similarity_threshold = 0.85

[secrets]
openrouter_api_key = "your_openrouter_key_here"
litellm_master_key = "sk-master-key-1234"
postgres_password = "changeme"
tailscale_auth_key = "tskey-auth-REPLACE_ME"
bws_access_token = ""
```

Checked in as `project.toml.example`; `project.toml` itself is gitignored, same as `.env`/`terraform.tfvars` were.

`[config]` and `[secrets]` are both always read straight from `project.toml`, unconditionally — **`render_config.py` never branches on `secrets_mode` and never calls `bws`.** `secrets_mode` is a Terraform-only concept (see below); `project-config` renders it through for Terraform to read, but doesn't act on it itself.

## `secrets_mode`: Terraform-Only, Not a Render-Time Toggle

`secrets_mode` (`"bitwarden"` or `"project_toml"`) still lives in `[config]` and still gets rendered into `infra/generated.auto.tfvars.json` for Terraform — that part is unchanged from `aws-infra`'s original `bitwarden`/`env_file` variable, just relocated into `project.toml` alongside everything else and renamed to describe reality (`env_file` stopped being accurate once `.env` became generated, not hand-edited).

What it does **not** do: change how `render_config.py` resolves `.env`. An earlier draft of this doc had `render_config.py` itself branch on `secrets_mode` and shell out to `bws secret list` when in Bitwarden mode — rejected. That would mean `bws_access_token` has to live in the EC2 host's own `project.toml` (not just Terraform state) and the `bws` CLI becomes a live, repeatedly-callable dependency from inside the running instance, not the one-shot boot-time fetch it is today. Deliberately not doing that — Bitwarden stays a **pre-clone, `user_data`-only bootstrap**, exactly as it already was:

- `user_data` fetches `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY`/`POSTGRES_PASSWORD` from `bws` directly to `/home/ubuntu/.env`, once, before the repo (and `project.toml`) even exist on the host.
- `render_config.py` and `local-launch.sh` never know or care that this happened. If an operator later runs `local-launch.sh` on that host, it prompts through `project.toml` and renders `.env` from it normally — same as any other target — which **will overwrite** the Bitwarden-fetched values with whatever's in `project.toml` at that point. This is accepted, not fixed: the documented Bitwarden workflow (`README.md`) never tells an operator to run `local-launch.sh` on a Bitwarden-provisioned host in the first place (`cp ~/.env` is the documented step); an operator who deviates from that is knowingly taking over manual management from that point on.

## Table-to-File Mapping

| Key(s) | Rendered into | Consumed by |
|---|---|---|
| `[config]` (all), `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password` | `.env` | `docker-compose.yml` (`gateway-stack`, `key-management`) |
| `[secrets].tailscale_auth_key`/`bws_access_token`, `[config].secrets_mode` | `infra/generated.auto.tfvars.json` | Terraform (`aws-infra`) |

`[config].secrets_mode` is rendered into `infra/generated.auto.tfvars.json` only — it's Terraform's `user_data` that acts on it, nothing on the `.env`/Compose side reads it.

## Generator

`scripts/render_config.py` — stdlib-only (`tomllib`, `json`), no new dependency, runs under any system `python3` ≥3.11 without needing `uv sync` first. That matters for `jarvis-startup.sh`, which can't assume the repo's `uv`-managed venv exists yet at first boot.

Reads `project.toml`, writes `.env` and `infra/generated.auto.tfvars.json` per the mapping above — a straight, unconditional read-and-split, no branching on any value inside `project.toml`. Both outputs are **always fully regenerated, gitignored, never hand-edited** — `project.toml` is the only file an operator or script touches directly; drift between a generated file and its source is structurally impossible if nothing ever hand-edits the generated side.

An unrecognized table/key in `project.toml` (e.g. a typo'd table name) is a hard error, not a silently-dropped value — a dropped key means a service boots with a missing secret, which is a worse failure to debug than a fast, loud one at render time.

Terraform loading: `infra/generated.auto.tfvars.json` matches Terraform's native `*.auto.tfvars.json` auto-load convention, so `aws-launch.sh`/`aws-destroy.sh` drop their `-var-file=terraform.tfvars` flag entirely — one less thing to keep in sync.

## Editing `project.toml`: Shared Prompt Loop

`local-launch.sh` and `aws-launch.sh` both need the same keep-or-replace-per-key prompt UX, now against the *same file and same syntax* (previously `.env`'s `KEY=value` vs `.tfvars`'s `key = "value"` justified two separate ~15-line loops — see `aws-infra-design.md`'s now-superseded decision row). That justification no longer holds once both scripts edit the same `project.toml`, so the loop moves to a shared `scripts/lib/project-toml.sh`, sourced by both.

The loop itself doesn't change shape: line-by-line scan, `[table]` header lines pass through unchanged (tracked only for display context, e.g. `secrets.openrouter_api_key`), `key = "value"` lines get the existing show-current/prompt-for-replacement/keep-on-empty treatment, blank lines and `#`-comments pass through unchanged. No TOML-writing library needed — this is the same line-based rewrite technique already proven twice in this repo (`.env`, `.tfvars`), just extended to recognize one more line shape (`[table]`). Python's `tomllib` is read-only by design (stdlib has no TOML writer); the generator (above) only ever *reads* `project.toml`, so that limitation never actually bites.

With only two tables now (`[config]`, `[secrets]`), scripts scope by **key**, not by table: `local-launch.sh` prompts `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`; `aws-launch.sh` prompts `[config].secrets_mode` and `[secrets].tailscale_auth_key`/`bws_access_token`. No mode-awareness in the loop itself — every owned key is always prompted, unconditionally, regardless of `secrets_mode`.

**Interface**: `project_toml_prompt_keys <file> <key> [<key> ...]` — scans `<file>` line by line; for any `key = "value"` line whose bare key name (unique across both tables in this schema, no disambiguation needed) is in the given list, shows the current value and prompts for a replacement, same keep-or-replace semantics as before. All other lines (including owned-table keys not passed in the list, unrecognized keys, blanks, comments, `[table]` headers) pass through unchanged. Callers: `local-launch.sh` → `project_toml_prompt_keys project.toml embedding_similarity_threshold openrouter_api_key litellm_master_key postgres_password`; `aws-launch.sh` → `project_toml_prompt_keys project.toml secrets_mode tailscale_auth_key bws_access_token`.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Generator implementation | Stdlib-only Python (`tomllib`, `json`) | A bash TOML parser (`yq`/`dasel`, new dependency) | No new dependency; runs under any system `python3` without `uv sync`, which matters for `jarvis-startup.sh`'s zero-setup boot. |
| Table-to-file mapping | Fixed table-level routing | Per-key metadata/target annotations inside `project.toml` | Each key has exactly one consumer already; fixed routing needs no extra schema and stays plain, readable TOML. |
| Generated file lifecycle | Always regenerated, gitignored, never hand-edited | Generate once, allow manual edits to drift | Matches `project.toml` as sole source of truth; hand-edits to a generated file would silently desync from it. |
| Terraform var loading | Native `*.auto.tfvars.json` auto-load | Keep `-var-file=terraform.tfvars` | Terraform's built-in mechanism does this for free — one less flag to keep in sync. |
| `project.toml` write path | Line-based rewrite in bash, shared between `local-launch.sh`/`aws-launch.sh` | A TOML-writing library (e.g. `tomlkit`) invoked from Python | Reuses the exact technique already proven for `.env` and `.tfvars` in this repo; avoids a new dependency for round-trip TOML writing that stdlib doesn't provide. |
| Prompt-loop code ownership | Shared `scripts/lib/project-toml.sh`, sourced by both launch scripts | Two separate copies (as `.env`/`.tfvars` had) | Same file, same syntax now — the divergence that justified two copies (`aws-infra-design.md`'s prior decision) no longer exists. |
| Unrecognized key/table in `project.toml` | Hard error at render time | Silently ignore/drop it | A dropped key means a service boots with a missing secret — a loud, fast failure at render time is cheaper to debug. |
| Retiring `.env.example` / `terraform.tfvars.example` | Replaced by one `project.toml.example` | Keep all three templates alongside the new file | Multiple templates for the same secrets invites drift; one canonical example matches "single source of truth." |
| Schema shape | Two sections, `[config]`/`[secrets]` | Six single-purpose tables (`[openrouter]`, `[litellm]`, `[postgres]`, `[embedding]`, `[tailscale]`, `[aws]`) (this doc's original draft) | Per-service tables looked tidy but didn't map to how the file is actually edited or reasoned about — the real distinction that matters is secret-vs-not (for prompting/masking) and mode-toggled-vs-not (for sourcing), not which container consumes a value. |
| `secrets_mode` scope | Lives in `project.toml`'s `[config]` (relocated, renamed `bitwarden`/`project_toml`), but stays a **Terraform-only** behavioral toggle — `render_config.py` never branches on it | Make `render_config.py` itself `secrets_mode`-aware, fetching from `bws` at render time when in Bitwarden mode | Would require `bws_access_token` to live in the EC2 host's own `project.toml` (not just Terraform state/`user_data`) and make `bws` a live, repeatedly-callable dependency from inside the running instance instead of a one-shot boot-time fetch — rejected on exposure grounds; `bws` stays boot-time-only, same as before this leaf existed. |
| `project.toml.example`'s shipped `secrets_mode` default | `"project_toml"` | `"bitwarden"` (AWS's historical default, back when the field only lived in `terraform.tfvars.example`) | One `project.toml.example` now serves local dev, Jarvis, and AWS — the first two have no `bws` CLI installed, so a Bitwarden default would break them out of the box. `aws-launch.sh` still lets an AWS operator opt into `"bitwarden"` explicitly. |
| `local-launch.sh` run against a Bitwarden-provisioned host | Accepted as-is: it overwrites `.env` with `project.toml`'s values, same as any other target | Detect the pre-existing Bitwarden-sourced `.env` and guard/refuse | No signal to detect against without writing `secrets_mode`/`bws_access_token` into the host's own `project.toml` — which is the exposure this decision set out to avoid. The documented workflow (`README.md`) never routes a Bitwarden-mode operator through `local-launch.sh` in the first place (`cp ~/.env` is the documented step); deviating from that is an explicit, informed choice, not a silent trap. |

## Open Questions & Future Decisions

### Deferred

1. `scripts/bws-secrets-check.sh` still reads `BWS_ACCESS_TOKEN` from its own environment variable, separate from `project.toml`'s `[aws].bws_access_token` — unifying those is left open; it's an independent vault-maintenance script, not a boot-time consumer of `project.toml` (see `aws-infra-design.md`'s existing note on the two-places-for-one-token trade-off).
2. Non-interactive/CI rendering (e.g. a `--yes`/env-var-driven mode that skips the prompt loop entirely) is left open — no current need beyond local-dev and single-operator deploy convenience.

## References

- `docs/high-level-design.md`
- `docs/intent/local-launch/local-launch-design.md` — consumes `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`
- `docs/intent/aws-infra/aws-infra-design.md` — consumes `[config].secrets_mode` and `[secrets].tailscale_auth_key`/`bws_access_token` via `aws-launch.sh`; owns the Bitwarden pre-clone bootstrap this leaf deliberately doesn't integrate with
- `docs/intent/jarvis-deploy/jarvis-deploy-design.md` — seeds a placeholder `project.toml` on first unattended boot
- `docs/intent/key-management/key-management-design.md` — consumes `[secrets].postgres_password`
