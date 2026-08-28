---
parent: high-level-design
prefix: INFRA
---

# AWS Infra

## Context and Design Philosophy

This leaf owns the Terraform config (`infra/main.tf`) that provisions the physical AWS resources the other AWS-side leaves run on: the EC2 instance and Elastic IP `aws-deploy`'s boot/idle scripts run on, and the IAM role, Lambda function, and Function URL that expose `aws-ignition`'s request-handling logic. It owns **provisioning and teardown**, plus the Bitwarden Secrets Manager integration's two operator-side scripts — `scripts/bws-sync.sh` (pull secrets into `project.toml`) and `scripts/bws-secrets-check.sh` (review/update the vault) — since both read the same `BWS_ACCESS_TOKEN`-scoped project. It does not own boot-script behavior (`aws-deploy`) or request-handling logic (`aws-ignition`); it packages `ignition/handler.py` unmodified as the Lambda's deployed source.

Terraform replaces the manual console click-through implied by `docs/gemini/initial-survey.md`'s original setup steps. `terraform destroy` is the primary teardown path back to $0.00; `cloud-nuke` is a documented fallback for when local Terraform state is lost, not code this repo ships or tests.

## File Layout

A single `infra/main.tf`, matching the source guide's one-file approach. `infra/terraform.tfstate*`, `infra/.terraform/`, the generated `infra/lambda_ignition.zip`, and the generated `infra/generated.auto.tfvars.json` (`project-config`'s output — see below) are gitignored — state and build artifacts are local, not checked in.

## EC2 + Networking

- `data "aws_ami"` looks up the latest Ubuntu 24.04 ARM64 AMI at apply time rather than hand-pinning an AMI ID that would rot.
- `aws_instance`, type `t4g.small` (the default family/size from `aws-deploy`'s Host-Level Constraint), 20GB gp3 root volume.
- `lifecycle { ignore_changes = [instance_type] }` — the ignition Lambda (`aws-ignition`) resizes the instance at runtime via `modify_instance_attribute`; without this, the next `terraform apply` would silently revert that resize back to the config's default.
- Security group: zero ingress rules, allow-all egress. Matches the HLD's "Tailscale is the sole trust boundary" tenet — no inbound path exists at the AWS network layer at all.
- `user_data` does one-time OS bootstrap: swap file, Docker, Tailscale install *and* authentication. `metadata_options { http_tokens = "required" }` forces IMDSv2 — needed because `user_data` now carries a secret (below), and IMDSv2 closes the plain-unauthenticated-GET path to reading it off the instance metadata service.
- Installing the idle-check crontab remains a manual one-time step, same as documented in `aws-deploy-design.md` — Terraform does not automate it.

## Tailscale Authentication

`tailscale up --authkey=var.tailscale_auth_key --statedir=/home/ubuntu/tailscale-state --hostname=cloud-litellm` runs unattended in `user_data`, using a reusable pre-auth key from the Tailscale Admin Panel supplied as a `sensitive` Terraform variable at `apply` time. `--statedir` is pinned to the persistent EBS root volume for the same reason `aws-deploy-design.md` already gives (consistency with the Jarvis Labs target, even though EC2 stop/start doesn't strictly require it).

This removes what was previously the AWS target's one remaining manual step (`tailscale up` over SSH/console). Cloning the repo remains a manual, one-time step (see Remote Access below); `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY`/`POSTGRES_PASSWORD` reach the host afterward via `scripts/bws-sync.sh`, below.

## Bitwarden Secrets: Local Sync, Not a Cloud-Side Fetch

Earlier revisions of this leaf had `user_data` self-fetch `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY`/`POSTGRES_PASSWORD` from Bitwarden at EC2 boot, gated by a `secrets_mode` Terraform variable, with `bws_access_token` embedded in `user_data` (cleartext in `terraform.tfstate` and the instance's `user_data` attribute, readable by any account principal with `ec2:DescribeInstanceAttribute`). That's retired — see `project-config-design.md`'s "Bitwarden as a local secrets source" section for the replacement: `scripts/bws-sync.sh` runs wherever the operator is (laptop, an SSM session on the EC2 host, an SSH session on a Jarvis pod), pulling secrets into that machine's own `project.toml`. Nothing Bitwarden-related lives in `main.tf` or `user_data` anymore — no `secrets_mode` variable, no `bws_access_token` variable, no `bws` CLI installed on the instance.

The one remaining manual step (repo clone, below) is unchanged; the operator now runs `./scripts/bws-sync.sh` then `./scripts/launch.sh --env=local` over the same Session Manager session, instead of a pre-clone `cp ~/.env` step.

## Bitwarden Vault Check Script

`scripts/bws-secrets-check.sh` runs on the operator's laptop, independent of `terraform apply` — reviewing/updating what's actually stored in the Bitwarden Secrets Manager project is a vault-maintenance task, not a deploy step, so it isn't wired into `scripts/bws-sync.sh`.

It reads the machine account token from the `BWS_ACCESS_TOKEN` environment variable — the same variable the `bws` CLI itself reads natively, and the same one `scripts/bws-sync.sh` reads — rather than inventing a second place to store it. No project ID is passed to `bws secret list`; like the sync script, this assumes the token's machine account is scoped to exactly one project (`docs/gemini/bitwarden.md`'s setup), which is what "this project" means in the script's UX.

For each secret returned by `bws secret list --output json` (parsed with `jq`, the only way to recover each secret's ID alongside its key/value — `bws`'s other output formats either drop the ID or aren't structured), the script prints `key [current_value]` and prompts for a replacement — identical keep-or-replace UX to `launch.sh --env=local`/`launch.sh --env=aws`, plaintext values (no masking, matching those scripts' existing convention). A non-empty response calls `bws secret edit --value "$new_value" "$secret_id"` against that secret's ID; an empty response leaves it untouched.

## Bitwarden Sync Script

`scripts/bws-sync.sh` is the mechanism `project-config-design.md`'s "Bitwarden as a local secrets source" section refers to — it owns the pull side (Bitwarden → `project.toml`); this section owns the operational detail of running it against an EC2 host. Same script, same `BWS_ACCESS_TOKEN` env var convention as `bws-secrets-check.sh`, run over the same Session Manager session as the repo clone — no new remote-access mechanism.

Editing a secret here only changes what's stored in the Bitwarden project; this script never connects to any host. An operator who wants a changed secret live on an already-booted EC2 host still has to re-run `scripts/bws-sync.sh` (INFRA-031) over an SSM session themselves — nothing pushes the change automatically.

## Local Terraform Wrapper Scripts

`scripts/launch.sh --env=aws` and `scripts/aws-destroy.sh` run on the operator's laptop, not the EC2 host — they wrap `terraform apply`/`terraform destroy` the way `launch.sh --env=local` wraps `docker compose up`. `launch.sh` is a single entrypoint shared with the `local-launch` leaf, dispatched by `--env`; this leaf owns the `--env=aws` path — see `local-launch-design.md` for the local path and `high-level-design.md`'s decision table for why the two share one script.

The `--env=aws` path uses `project-config`'s shared prompt loop (`scripts/lib/project-toml.sh`), pointed at `project.toml`'s `[secrets].tailscale_auth_key` instead of its own copy of the loop against `infra/terraform.tfvars` — see `project-config-design.md` for why the two paths share one implementation instead of two. It then calls `scripts/render_config.py` to produce `infra/generated.auto.tfvars.json`, and runs `terraform -chdir=infra init` and `terraform -chdir=infra apply` — no `-var-file` flag; Terraform auto-loads `*.auto.tfvars.json` natively.

`aws-destroy.sh` runs `terraform -chdir=infra destroy` against the same auto-loaded file, erroring clearly if `project.toml` (or its rendered `infra/generated.auto.tfvars.json`) doesn't exist yet.

`infra/terraform.tfvars` / `infra/terraform.tfvars.example` are retired — superseded by `project.toml.example` (`project-config`'s territory).

Neither script passes `-auto-approve` — Terraform's own plan-then-confirm prompt stays in the loop for both. This is a deliberate deviation from `docs/gemini/terraform-and-nuke-guide.md`'s wrapper scripts, which auto-approve both `apply` and `destroy`.

## Remote Access Without Open Ports

The security group above has **zero ingress rules**, including port 22, so the remaining manual step (git clone + secrets) can't go over SSH. The instance carries an IAM instance profile granting `AmazonSSMManagedInstanceCore`, and `user_data` enables the SSM agent, so that step goes over **AWS Systems Manager Session Manager** (outbound-initiated, no inbound port needed) instead. This keeps the "zero ingress, Tailscale is the only path in" tenet intact while still making the host reachable for that one step.

## Elastic IP

`aws_eip` attached to the instance — the single EIP `aws-deploy` requires, no load balancer, no NAT gateway.

## Lambda Packaging

`data "archive_file"` zips the repository's own `ignition/handler.py` (the tested source — see `aws-ignition-specs.md`), not an inline copy of the Python. Deploying the same file the test suite covers means there is exactly one copy of the request-handling logic, never a drifted duplicate baked into HCL.

## IAM

An execution role assumable only by `lambda.amazonaws.com`, with an inline policy granting exactly `ec2:StartInstances` and `ec2:ModifyInstanceAttribute`, scoped to the single provisioned instance's ARN — never `"*"`.

## Function URL

`authorization_type = "NONE"`. The ignition switch's entire purpose is to be reachable while the host is stopped and no Tailscale path exists yet — an `AWS_IAM`-authenticated URL would require distributing AWS credentials to whatever's waking the host, defeating the "hit a URL to boot it" model. The least-privilege IAM role above (single instance, two actions) is the actual safety boundary, not endpoint auth.

## Region and the Lambda's `AWS_REGION`

`var.aws_region` (default `us-east-1`) configures the `provider "aws"` block only. It is **not** passed into the Lambda's `environment.variables` — `AWS_REGION` is an AWS-reserved Lambda environment key; setting it explicitly fails deployment. `ignition/handler.py` already reads `os.environ.get("AWS_REGION", "us-east-1")`, which Lambda's runtime populates automatically.

## Outputs

EC2 public IP (from the EIP) and the ignition switch's Function URL, printed after `terraform apply`.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Where Terraform config lives | `infra/main.tf`, in-repo, version-controlled | A standalone folder outside the repo (the source guide's suggestion) | This repo already tracks all its deploy tooling (`scripts/`, `ignition/`) in git; a config that provisions the same infra those pieces run on belongs alongside them, not in an untracked folder. |
| Lambda deployment source | `archive_file` packaging the existing `ignition/handler.py` | Inline Python string embedded in the HCL (the source guide's approach) | The guide's inline copy is also a functional regression — it only allows `small`/`medium`, not the full `t3`/`t4g` whitelist `IGNITE-001` already implements and tests cover. Packaging the real file guarantees the deployed Lambda matches what `tests/test_ignition_handler.py` verifies. |
| `AWS_REGION` handling | Rely on Lambda's own reserved env var, already read by `ignition/handler.py` | Interpolate a Terraform variable into the Lambda's inline Python (the source guide's `${var.aws_region_placeholder}`) | That variable is never declared anywhere in the guide's own file — it would fail `terraform plan` as-is. `AWS_REGION` is Lambda-reserved and auto-populated; no plumbing is needed. |
| Function URL auth | `NONE` | `AWS_IAM` | The switch must be callable with no prior network path to the host (that's its job). IAM auth would require distributing AWS credentials to the caller; the scoped IAM role on the Lambda's execution role is the actual safety boundary instead. |
| AMI selection | `data "aws_ami"` lookup, most-recent Ubuntu 24.04 ARM64 | Hand-pinned AMI ID | Avoids a stale/deprecated AMI ID rotting in checked-in config. |
| Terraform correctness testing | Scoped regex/substring assertions directly against `main.tf`'s text | `python-hcl2` parsing into a dict (as `test_gateway_config.py` does for YAML); shelling out to `terraform validate` | Tried `python-hcl2` first — it leaves quoted resource labels un-stripped in its output keys (version-dependent) and represents `jsonencode(...)` policy bodies as opaque `${...}` expression strings, so the IAM policy assertions that matter most (INFRA-009, INFRA-010) would need string matching anyway. With exactly one resource of each type in a single-file config, whole-file scoped regex is simpler and dependency-free; `terraform validate` needs the CLI installed/pinned and a provider plugin fetch just to check syntax. |
| Remote access for the remaining manual step (git clone + secrets) | IAM instance profile (`AmazonSSMManagedInstanceCore`) + SSM agent enabled in `user_data`; access via Session Manager | Open port 22 in the security group for SSH | The security group has zero ingress rules by design (Tailscale is the sole trust boundary); Session Manager is outbound-initiated and needs no inbound port, so the remaining manual step doesn't require punching a hole in the "no public ports" tenet. |
| Tailscale authentication | Automated: reusable authkey passed as a `sensitive` Terraform variable, baked into `user_data`, run unattended at first boot | Manual `tailscale up` over Session Manager (this leaf's previous approach) | Removes the last manual step standing between `terraform apply` and a Tailscale-reachable host. Trade-off: the authkey ends up in cleartext in local `terraform.tfstate` and in the instance's `user_data` attribute (readable by any principal in this AWS account with `ec2:DescribeInstanceAttribute`) — accepted given the single-operator target user and the local-state model this project already uses for `.env` secrets; `metadata_options.http_tokens = "required"` closes the unauthenticated-IMDS read path as a mitigation. |
| Bitwarden secrets delivery mechanism | Local sync script (`scripts/bws-sync.sh`), run by the operator wherever they currently are (laptop, an SSM session, an SSH session on a Jarvis pod), writing `project.toml` | Cloud-side self-fetch via `user_data` at EC2 boot (`secrets_mode`, this leaf's prior approach) | Retires the cloud-side fetch entirely — one mechanism for all three deploy targets instead of an AWS-only one; no token or secret ever embedded in Terraform state or `user_data`; Jarvis and local dev get the same capability AWS-only `secrets_mode` never gave them. |
| `tailscale_auth_key` in scope for `bws-sync.sh` | Yes — synced by the same script alongside the three app secrets | Keep it prompt-only at `launch.sh --env=aws`, out of the sync | One vault, one sync step, one place to rotate any of the four secrets — matches the "Bitwarden as local secrets manager" intent rather than carving out an exception. |
| `launch.sh --env=aws` / `aws-destroy.sh` approval flag | No `-auto-approve` on either; Terraform's own plan-then-confirm stays | `-auto-approve` on both, matching `docs/gemini/terraform-and-nuke-guide.md`'s wrapper scripts | `destroy` is irreversible (EBS volume, EIP release); `apply` is reversible but still costs money per run. Keeping Terraform's native confirmation on both matches this repo's existing pattern of guarding rather than blindly auto-approving (`launch.sh --env=local`'s running-container guard, `local-stop.sh`'s graceful-only stop). |
| Terraform variable prompting | `launch.sh --env=aws` sources `project-config`'s shared `scripts/lib/project-toml.sh` loop, scoped to `project.toml`'s `[secrets].tailscale_auth_key` | A separate copy of the loop adapted for `.tfvars`' `key = "value"` syntax (this leaf's prior approach, when `.env` and `.tfvars` were different formats) | Superseded: once both env paths edit the same file in the same syntax (`project.toml`), the format-divergence that justified two copies no longer exists — see `project-config-design.md`. |
| Where the Bitwarden vault check/update and sync scripts live | Folded into `aws-infra` (`scripts/bws-secrets-check.sh`, `scripts/bws-sync.sh`), not a new leaf | A new sibling leaf (e.g. `bws-secrets`) owning its own EARS prefix | This leaf already owns the Bitwarden integration's consuming side (INFRA-031..034); a second leaf for the same project's read/write sides would split one integration across two docs for two scripts. |
| `bws-secrets-check.sh`'s access-token source | `BWS_ACCESS_TOKEN` env var (the `bws` CLI's own native var) | A new `--access-token` flag, or reading it out of `infra/terraform.tfvars` | Reusing the CLI's own env var needs no new storage or parsing; `terraform.tfvars` only exists once an operator has run `launch.sh --env=aws`, but the vault check is useful before that too. |
| `bws-secrets-check.sh` project scoping | No project ID passed to `bws secret list` — relies on the machine account token being scoped to one project | Accept a project ID/name argument and pass it through | Matches `bws-sync.sh`'s own `bws secret list --output env` call (INFRA-031), which makes the same assumption; `docs/gemini/bitwarden.md`'s setup only ever creates one project. |
| `bws-secrets-check.sh`'s JSON parsing | `jq`, a new prerequisite for this script | Hand-parse `bws`'s TSV/env output with `cut`/`grep` | `bws`'s `env`/`tsv` formats don't carry the secret ID needed for `bws secret edit <SECRET_ID>`; only `json` does. `jq` is the standard tool for that, and hand-rolled JSON parsing in bash is more code and more fragile than requiring one more common CLI dependency alongside `terraform`/`aws`/`bws` this leaf already assumes. |
| `bws-sync.sh` overwrite behavior | Always overwrites the matching `project.toml` field when Bitwarden has a value for it (sync = source of truth) | Placeholder-only, like the retired `bws_access_token` pre-fill | A sync's whole point is refreshing `project.toml` from the vault; placeholder-only would silently stop working after the first successful sync (the field's no longer a placeholder). The subsequent `launch.sh` keep-or-replace prompt is the point where an operator can still override a synced value for one run. |
| `bws-sync.sh`'s Bitwarden→`project.toml` key mapping | Hard-coded to the four known fields (`OPENROUTER_API_KEY`, `LITELLM_MASTER_KEY`, `POSTGRES_PASSWORD`, `TAILSCALE_AUTH_KEY`) | Generic: sync any vault key whose name matches a `project.toml` field, no fixed list | `project.toml`'s schema is small and fixed (`project-config-design.md`); a generic mapper is speculative flexibility for a four-key file. Missing-from-vault keys are just left untouched, not an error — an operator hasn't necessarily added `TAILSCALE_AUTH_KEY` to the vault yet. |
| `bws-sync.sh` line rewrite | `awk`, same tool `aws-idle-check.sh` already uses | `sed` (not yet a dependency); a TOML-writing library | `awk` avoids a new dependency; `sed -i` also has GNU/BSD flag incompatibility this repo has otherwise avoided (`project-toml.sh` uses pure bash for the same reason). |

## Open Questions & Future Decisions

### Deferred

1. `cloud-nuke` is documented only (see `docs/gemini/terraform-and-nuke-guide.md`), as a fallback for lost local state — not automated or tested, since it's an external tool invocation rather than code this repo authors.
2. Remote Terraform state (e.g. an S3 backend) is out of scope — the target user is a single engineer on a single machine; local, gitignored `terraform.tfstate` is sufficient at this scale.
3. Automating the repo clone itself (so `bitwarden` mode could be fully zero-touch, matching `docs/gemini/terraform-and-nuke-guide.md`'s auto-clone `user_data`) is left open — it would also need the crontab/`@reboot` install (`aws-deploy-design.md`'s own deferred item) automated to actually reach zero-touch, and both are out of scope for this change.
4. `bws-sync.sh` overwriting a field an operator just hand-edited (they ran `bws-sync.sh` again without realizing it re-pulls everything) is left as a known sharp edge — no "dirty" tracking to warn before overwriting. The subsequent `launch.sh` prompt still shows the (now-synced) value before it's actually used, so nothing ships silently.

## References

- `docs/high-level-design.md`
- `docs/gemini/terraform-and-nuke-guide.md`
- `docs/gemini/bitwarden.md` — Bitwarden Secrets Manager setup `secrets_mode = "bitwarden"` assumes
- `docs/intent/project-config/project-config-design.md` — `project.toml` schema, shared prompt loop, and the generator `launch.sh --env=aws` calls for `infra/generated.auto.tfvars.json`
- `docs/intent/aws-deploy/aws-deploy-design.md` — the EC2/EIP/instance-type constraints this leaf's Terraform resources implement
- `docs/intent/aws-ignition/aws-ignition-design.md` — the Lambda whose deployment (not request-handling logic) this leaf owns; packages `ignition/handler.py` unmodified
