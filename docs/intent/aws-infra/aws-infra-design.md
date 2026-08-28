---
parent: high-level-design
prefix: INFRA
---

# AWS Infra

## Context and Design Philosophy

This leaf owns the Terraform config (`infra/main.tf`) that provisions the physical AWS resources the other AWS-side leaves run on: the EC2 instance and Elastic IP `aws-deploy`'s boot/idle scripts run on, and the IAM role, Lambda function, and Function URL that expose `aws-ignition`'s request-handling logic. It owns **provisioning and teardown**, plus the Bitwarden Secrets Manager integration `secrets_mode = "bitwarden"` depends on — both the boot-time fetch and the operator-side vault check/update script, since both sides read the same `BWS_ACCESS_TOKEN`-scoped project. It does not own boot-script behavior (`aws-deploy`) or request-handling logic (`aws-ignition`); it packages `ignition/handler.py` unmodified as the Lambda's deployed source.

Terraform replaces the manual console click-through implied by `docs/gemini/initial-survey.md`'s original setup steps. `terraform destroy` is the primary teardown path back to $0.00; `cloud-nuke` is a documented fallback for when local Terraform state is lost, not code this repo ships or tests.

## File Layout

A single `infra/main.tf`, matching the source guide's one-file approach. `infra/terraform.tfstate*`, `infra/.terraform/`, and the generated `infra/lambda_ignition.zip` are gitignored — state and build artifacts are local, not checked in.

## EC2 + Networking

- `data "aws_ami"` looks up the latest Ubuntu 24.04 ARM64 AMI at apply time rather than hand-pinning an AMI ID that would rot.
- `aws_instance`, type `t4g.small` (the default family/size from `aws-deploy`'s Host-Level Constraint), 20GB gp3 root volume.
- `lifecycle { ignore_changes = [instance_type] }` — the ignition Lambda (`aws-ignition`) resizes the instance at runtime via `modify_instance_attribute`; without this, the next `terraform apply` would silently revert that resize back to the config's default.
- Security group: zero ingress rules, allow-all egress. Matches the HLD's "Tailscale is the sole trust boundary" tenet — no inbound path exists at the AWS network layer at all.
- `user_data` does one-time OS bootstrap: swap file, Docker, Tailscale install *and* authentication. `metadata_options { http_tokens = "required" }` forces IMDSv2 — needed because `user_data` now carries a secret (below), and IMDSv2 closes the plain-unauthenticated-GET path to reading it off the instance metadata service.
- Installing the idle-check crontab remains a manual one-time step, same as documented in `aws-deploy-design.md` — Terraform does not automate it.

## Tailscale Authentication

`tailscale up --authkey=var.tailscale_auth_key --statedir=/home/ubuntu/tailscale-state --hostname=cloud-litellm` runs unattended in `user_data`, using a reusable pre-auth key from the Tailscale Admin Panel supplied as a `sensitive` Terraform variable at `apply` time. `--statedir` is pinned to the persistent EBS root volume for the same reason `aws-deploy-design.md` already gives (consistency with the Jarvis Labs target, even though EC2 stop/start doesn't strictly require it).

This removes what was previously the AWS target's one remaining manual step (`tailscale up` over SSH/console). Cloning the repo remains a manual, one-time step (see Remote Access below); what happens to `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY` after that depends on `secrets_mode`, below.

## Secrets (`secrets_mode`)

A `secrets_mode` variable (`"bitwarden"` default, or `"env_file"`) picks how the host gets `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY`. See `docs/gemini/bitwarden.md` for the Bitwarden Secrets Manager setup this assumes.

- **`bitwarden`**: `user_data` installs the ARM64 `bws` CLI and runs `bws secret list --output env`, authenticated with the `bws_access_token` variable (`sensitive`, empty default), writing the result to `/home/ubuntu/.env`. This runs at first boot, before the repo is cloned — writing to a fixed host path rather than into the (not-yet-cloned) repo directory sidesteps that ordering entirely. The one remaining manual step (repo clone, below) picks the file up with `cp ~/.env ~/litellm-proxy/.env` instead of running `./scripts/local-launch.sh`.
- **`env_file`**: `user_data` does nothing extra. The operator runs `./scripts/local-launch.sh` over the same Session Manager session used for the repo clone, exactly as before this variable existed.

`scripts/aws-launch.sh` (see below) is what actually sets `secrets_mode` and `bws_access_token` at `apply` time — an operator doesn't hand-edit `main.tf` or type `-var` flags per run.

## Bitwarden Vault Check Script

`scripts/bws-secrets-check.sh` runs on the operator's laptop, independent of `terraform apply` — reviewing/updating what's actually stored in the Bitwarden Secrets Manager project is a vault-maintenance task, not a deploy step, so it isn't wired into `aws-launch.sh`.

It reads the machine account token from the `BWS_ACCESS_TOKEN` environment variable — the same variable the `bws` CLI itself reads natively, and the same one `user_data` sets inline at boot (`Secrets (secrets_mode)`, above) — rather than inventing a second place to store it. No project ID is passed to `bws secret list`; like the boot-time fetch, this assumes the token's machine account is scoped to exactly one project (`docs/gemini/bitwarden.md`'s setup), which is what "this project" means in the script's UX.

For each secret returned by `bws secret list --output json` (parsed with `jq`, the only way to recover each secret's ID alongside its key/value — `bws`'s other output formats either drop the ID or aren't structured), the script prints `key [current_value]` and prompts for a replacement — identical keep-or-replace UX to `local-launch.sh`/`aws-launch.sh`, plaintext values (no masking, matching those scripts' existing convention). A non-empty response calls `bws secret edit --value "$new_value" "$secret_id"` against that secret's ID; an empty response leaves it untouched.

`BWS_ACCESS_TOKEN` (this script's env var) and `infra/terraform.tfvars`' `bws_access_token` (what `aws-launch.sh` writes) are the same token value held in two separate places — setting one does not set the other; an operator switching between the two scripts re-supplies it each time.

Editing a secret here only changes what's stored in the Bitwarden project. It does not reach an already-booted EC2 host: `/home/ubuntu/.env` is written once, at first boot (INFRA-020/021), and this script never connects to the instance. An operator who wants a changed secret live on a running host still has to re-run the boot-time fetch (or a fresh `terraform apply`/instance replacement) themselves.

## Local Terraform Wrapper Scripts

`scripts/aws-launch.sh` and `scripts/aws-destroy.sh` run on the operator's laptop, not the EC2 host — they wrap `terraform apply`/`terraform destroy` the way `local-launch.sh` wraps `docker compose up`.

`aws-launch.sh` reuses `local-launch.sh`'s per-key keep-or-replace prompt loop (see `local-launch-design.md`), pointed at `infra/terraform.tfvars` (gitignored, seeded from a checked-in `infra/terraform.tfvars.example`) instead of `.env`, for `tailscale_auth_key`, `secrets_mode`, and `bws_access_token`. It parses/writes Terraform's `key = "value"` syntax rather than `.env`'s `KEY=value`, since a `.tfvars` file has to stay valid HCL — the keep-or-replace UX and per-key prompt are otherwise identical. It then runs `terraform -chdir=infra init` and `terraform -chdir=infra apply -var-file=terraform.tfvars`.

`aws-destroy.sh` runs `terraform -chdir=infra destroy -var-file=terraform.tfvars` against the same file, erroring clearly if it doesn't exist yet.

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
| Where the Bitwarden-fetched `.env` lands | `/home/ubuntu/.env`, a fixed host path, copied into the repo manually as part of the (already-manual) clone step | Have `user_data` also clone the repo, so `.env` could be written straight into it | Automating the clone was out of scope for this change — it stays a manual Session Manager step, same as before `secrets_mode` existed. Writing to a fixed host path avoids that step ordering mattering at all. |
| `secrets_mode` variable validation | `validation` block restricting the variable to `["bitwarden", "env_file"]` | Leave it a free-form string, fail only inside `user_data`'s bash `if` at boot time | A typo'd value should fail fast at `terraform plan`/`apply`, not silently skip both branches on a running instance discovered later. |
| `aws-launch.sh` / `aws-destroy.sh` approval flag | No `-auto-approve` on either; Terraform's own plan-then-confirm stays | `-auto-approve` on both, matching `docs/gemini/terraform-and-nuke-guide.md`'s wrapper scripts | `destroy` is irreversible (EBS volume, EIP release); `apply` is reversible but still costs money per run. Keeping Terraform's native confirmation on both matches this repo's existing pattern of guarding rather than blindly auto-approving (`local-launch.sh`'s running-container guard, `local-stop.sh`'s graceful-only stop). |
| Reusing `local-launch.sh`'s prompt loop for Terraform variables | A near-identical loop in `aws-launch.sh`, adapted for `.tfvars`' `key = "value"` syntax instead of `.env`'s `KEY=value` | Extract a shared shell function/library both scripts source | Two ~15-line loops differing only in line syntax don't justify a shared library in a project with no other shell tooling infrastructure; each script stays copy-pasteable and readable standalone. |
| Where the Bitwarden vault check/update script lives | Folded into `aws-infra` (`scripts/bws-secrets-check.sh`), not a new leaf | A new sibling leaf (e.g. `bws-secrets`) owning its own EARS prefix | This leaf already owns the Bitwarden integration's consuming side (`secrets_mode`, INFRA-018..021); a second leaf for the same project's write side would split one integration across two docs for one script. |
| `bws-secrets-check.sh`'s access-token source | `BWS_ACCESS_TOKEN` env var (the `bws` CLI's own native var) | A new `--access-token` flag, or reading it out of `infra/terraform.tfvars` | Reusing the CLI's own env var needs no new storage or parsing; `terraform.tfvars` only exists once an operator has run `aws-launch.sh`, but the vault check is useful before that too. |
| `bws-secrets-check.sh` project scoping | No project ID passed to `bws secret list` — relies on the machine account token being scoped to one project | Accept a project ID/name argument and pass it through | Matches the existing boot-time fetch (`bws secret list --output env`, INFRA-020), which makes the same assumption; `docs/gemini/bitwarden.md`'s setup only ever creates one project. |
| `bws-secrets-check.sh`'s JSON parsing | `jq`, a new prerequisite for this script | Hand-parse `bws`'s TSV/env output with `cut`/`grep` | `bws`'s `env`/`tsv` formats don't carry the secret ID needed for `bws secret edit <SECRET_ID>`; only `json` does. `jq` is the standard tool for that, and hand-rolled JSON parsing in bash is more code and more fragile than requiring one more common CLI dependency alongside `terraform`/`aws`/`bws` this leaf already assumes. |

## Open Questions & Future Decisions

### Deferred

1. `cloud-nuke` is documented only (see `docs/gemini/terraform-and-nuke-guide.md`), as a fallback for lost local state — not automated or tested, since it's an external tool invocation rather than code this repo authors.
2. Remote Terraform state (e.g. an S3 backend) is out of scope — the target user is a single engineer on a single machine; local, gitignored `terraform.tfstate` is sufficient at this scale.
3. Automating the repo clone itself (so `bitwarden` mode could be fully zero-touch, matching `docs/gemini/terraform-and-nuke-guide.md`'s auto-clone `user_data`) is left open — it would also need the crontab/`@reboot` install (`aws-deploy-design.md`'s own deferred item) automated to actually reach zero-touch, and both are out of scope for this change.

## References

- `docs/high-level-design.md`
- `docs/gemini/terraform-and-nuke-guide.md`
- `docs/gemini/bitwarden.md` — Bitwarden Secrets Manager setup `secrets_mode = "bitwarden"` assumes
- `docs/intent/local-launch/local-launch-design.md` — the per-key prompt/persist UX `aws-launch.sh` adapts for `.tfvars`
- `docs/intent/aws-deploy/aws-deploy-design.md` — the EC2/EIP/instance-type constraints this leaf's Terraform resources implement
- `docs/intent/aws-ignition/aws-ignition-design.md` — the Lambda whose deployment (not request-handling logic) this leaf owns; packages `ignition/handler.py` unmodified
