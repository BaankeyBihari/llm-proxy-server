# llm-proxy-server

A private LiteLLM gateway proxying to OpenRouter, with [Headroom](https://github.com/headroomlabs-ai/headroom) as a pre-call context-compression guardrail and Redis for persistent semantic caching. Reachable only over Tailscale — no public endpoint, domain, or TLS setup. Two deploy targets: Jarvis Labs (pause/resume GPU pods) and AWS EC2 (on-demand, auto-stops after 4h idle, Lambda-triggered start).

See `docs/high-level-design.md` for the full architecture and rationale, and `docs/intent/` for each component's design and requirements.

## Quickstart

Requires [mise](https://mise.jdx.dev/) and [uv](https://docs.astral.sh/uv/) — tool versions are pinned in `.mise.toml`, dependencies in `pyproject.toml`.

```bash
mise install      # installs the pinned Python
uv sync           # creates .venv, installs dev deps
uv run pytest     # runs the test suite
```

## Running the stack

```bash
./scripts/local-launch.sh
```

Copies `.env.example` → `.env` if missing, prompts per key to keep or replace it, then runs `docker compose up -d` and prints a ready-to-run `curl` example with your real `LITELLM_MASTER_KEY` already substituted in. Aborts instead of prompting if the stack's already running — run `./scripts/local-stop.sh` first if you want a `.env` edit to take effect.

To stop: `./scripts/local-stop.sh` — brings the stack down gracefully, or warns (doesn't error) if it's already down.

## Deploying to Jarvis Labs

Jarvis Labs pods are paused (not terminated) between sessions, so the whole boot sequence lives in one script pasted into the pod's dashboard — see `docs/intent/jarvis-deploy/jarvis-deploy-design.md`.

1. Provision a pod with a persistent `/home` volume.
2. Open `scripts/jarvis-startup.sh` and, at the top, set real values for `TAILSCALE_AUTHKEY`, `GIT_REPO_URL`, and (if you don't want the defaults) `WORKSPACE` / `TAILSCALE_HOSTNAME` — either edit the `:-default` values directly or export them above the script body.
3. Paste the resulting script into the pod's **Startup Script** field. It runs on every resume, not just first boot.
4. First resume: it pins Tailscale's state under `$WORKSPACE/tailscale-state` (survives pause — this is what stops the pod from re-registering as a new node every time), clones the repo, waits for Docker, and writes a placeholder `.env`.
5. SSH in once. The stack is already running on placeholder secrets (step 4 started it) — `local-launch.sh` aborts rather than edit `.env` under a live container, so stop it first: `./scripts/local-stop.sh`, then `./scripts/local-launch.sh` to set the real `OPENROUTER_API_KEY` / `LITELLM_MASTER_KEY` values and bring it back up.
6. From your laptop (Tailscale connected): `http://<TAILSCALE_HOSTNAME>:4000`.

## Deploying to AWS EC2

The EC2 instance, Elastic IP, IAM roles, and ignition Lambda are provisioned via Terraform (`infra/main.tf`) — no manual console click-through. See `docs/intent/aws-infra/aws-infra-design.md` for what it provisions and why, and `docs/intent/aws-deploy/aws-deploy-design.md` / `docs/intent/aws-ignition/aws-ignition-design.md` for the rationale behind the constraints it encodes (single-EIP cost constraint, `t3`/`t4g` family lock).

**1. Provision the infra**
```bash
./scripts/aws-launch.sh
```
Copies `infra/terraform.tfvars.example` → `infra/terraform.tfvars` if missing, prompts per key to keep or replace it (same UX as `local-launch.sh`), then runs `terraform init`/`terraform apply` — prints `ec2_public_ip` and `ignition_switch_url`. Prompted keys: `tailscale_auth_key` (a reusable key from the Tailscale Admin Panel), `secrets_mode` (`bitwarden` default, or `env_file` — see below), and `bws_access_token` (Bitwarden Secrets Manager machine token, required in `bitwarden` mode — see `docs/gemini/bitwarden.md`). The instance connects to Tailscale automatically on first boot — no manual `tailscale up` needed.

To tear everything down (back to $0.00): `./scripts/aws-destroy.sh`. Both scripts keep Terraform's own plan-then-confirm prompt (no `-auto-approve`). If local Terraform state is lost, `cloud-nuke` is a documented fallback — see `docs/gemini/terraform-and-nuke-guide.md`.

To review or update what's actually stored in the Bitwarden vault (independent of `terraform apply`): `BWS_ACCESS_TOKEN=<token> ./scripts/bws-secrets-check.sh`. Lists each secret with its current value and prompts to keep or replace it, same UX as above. Requires `bws` and `jq`. Doesn't touch an already-booted host — see `docs/intent/aws-infra/aws-infra-design.md`.

**2. One-time host setup (Session Manager, not SSH — the security group has no ingress rules)**
```bash
aws ssm start-session --target <instance-id>
```
Generate a GitHub deploy key (`ssh-keygen`), add the public half to the repo, then clone to `/home/ubuntu/litellm-proxy`. (Docker, Tailscale, and the SSM agent itself are already installed and configured by Terraform's `user_data`.)

**3. Configure secrets and scheduled jobs**
```bash
cd /home/ubuntu/litellm-proxy
```
- `secrets_mode = "bitwarden"` (default): `user_data` already fetched `OPENROUTER_API_KEY`/`LITELLM_MASTER_KEY` to `/home/ubuntu/.env` — just `cp ~/.env .env`.
- `secrets_mode = "env_file"`: run `./scripts/local-launch.sh` to fill in `OPENROUTER_API_KEY` / `LITELLM_MASTER_KEY` instead.

```bash
crontab scripts/aws-idle-check.cron   # hourly idle check → poweroff after 4h silence
crontab -l | { cat; echo "@reboot /home/ubuntu/litellm-proxy/scripts/aws-start-stack.sh"; } | crontab -
```
The `@reboot` line is what runs `scripts/aws-start-stack.sh` (docker-wait, `git pull`, `docker compose up -d`) every time the ignition Lambda starts the instance.

**4. Use it**
```bash
curl "https://<lambda-function-url>/"                    # boot at current/default size
curl "https://<lambda-function-url>/?size=t4g.medium"     # resize then boot
```
Allowed sizes: `t4g.small`, `t4g.medium`, `t3.small`, `t3.medium` — anything else returns HTTP 400 without touching the instance.

## Layout

| Path | What |
|---|---|
| `config.yaml`, `docker-compose.yml` | The gateway stack — LiteLLM, Headroom, Redis (deploy-target-agnostic) |
| `scripts/local-launch.sh`, `local-stop.sh` | Interactive `.env` setup + launch, and graceful teardown, for local dev |
| `scripts/jarvis-startup.sh` | Jarvis Labs pod boot sequence |
| `scripts/aws-start-stack.sh`, `aws-idle-check.sh(+.cron)` | AWS EC2 boot sequence and idle auto-shutdown |
| `ignition/handler.py` | AWS Lambda "ignition switch" that starts/resizes the EC2 host on demand |
| `infra/main.tf` | Terraform: provisions the EC2 instance, EIP, IAM roles, and ignition Lambda |
| `scripts/aws-launch.sh`, `aws-destroy.sh` | Interactive `terraform.tfvars` setup + `terraform apply`, and `terraform destroy` |
| `scripts/bws-secrets-check.sh` | Reviews/updates secrets in the Bitwarden vault directly, independent of Terraform |
| `docs/high-level-design.md`, `docs/intent/` | Design intent (HLD, per-component LLDs, EARS specs) |
| `docs/gemini/` | Original research this project was built from |

For agent-facing conventions (LID workflow, spec IDs, dev commands), see `AGENTS.md`.
