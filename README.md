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
cp .env.example .env   # then fill in OPENROUTER_API_KEY / LITELLM_MASTER_KEY
docker compose up -d
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-master-key-1234" \
  -H "Content-Type: application/json" \
  -d '{"model": "smart-auto", "messages": [{"role": "user", "content": "Ping."}]}'
```

## Deploying to Jarvis Labs

Jarvis Labs pods are paused (not terminated) between sessions, so the whole boot sequence lives in one script pasted into the pod's dashboard — see `docs/intent/jarvis-deploy/jarvis-deploy-design.md`.

1. Provision a pod with a persistent `/home` volume.
2. Open `scripts/jarvis-startup.sh` and, at the top, set real values for `TAILSCALE_AUTHKEY`, `GIT_REPO_URL`, and (if you don't want the defaults) `WORKSPACE` / `TAILSCALE_HOSTNAME` — either edit the `:-default` values directly or export them above the script body.
3. Paste the resulting script into the pod's **Startup Script** field. It runs on every resume, not just first boot.
4. First resume: it pins Tailscale's state under `$WORKSPACE/tailscale-state` (survives pause — this is what stops the pod from re-registering as a new node every time), clones the repo, waits for Docker, and writes a placeholder `.env`.
5. SSH in once and replace the placeholder `.env` with real `OPENROUTER_API_KEY` / `LITELLM_MASTER_KEY` values, then `docker compose up -d --build` to pick them up.
6. From your laptop (Tailscale connected): `http://<TAILSCALE_HOSTNAME>:4000`.

## Deploying to AWS EC2

Fully manual, SSH-driven setup — no CloudFormation/Terraform in this repo. See `docs/intent/aws-deploy/aws-deploy-design.md` and `docs/intent/aws-ignition/aws-ignition-design.md` for the rationale (single-EIP cost constraint, `t3`/`t4g` family lock).

**1. Launch the instance**
- Ubuntu 24.04 LTS, either `t4g.*` (ARM64) or `t3.*` (x86_64) — pick one family, you can't cross it later. Start with `t4g.small`.
- Allocate **exactly one Elastic IP** and associate it. No load balancer, NAT gateway, or secondary IP — that's a deliberate cost cap, not a gap.

**2. One-time host setup (SSH in)**
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
sudo apt update && sudo apt install docker.io docker-compose-v2
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=cloud-litellm --statedir=/home/ubuntu/tailscale-state
```
Generate a GitHub deploy key (`ssh-keygen`), add the public half to the repo, then clone to `/home/ubuntu/litellm-proxy`.

**3. Configure secrets and scheduled jobs**
```bash
cd /home/ubuntu/litellm-proxy
cp .env.example .env   # fill in OPENROUTER_API_KEY / LITELLM_MASTER_KEY
crontab scripts/aws-idle-check.cron   # hourly idle check → poweroff after 4h silence
crontab -l | { cat; echo "@reboot /home/ubuntu/litellm-proxy/scripts/aws-start-stack.sh"; } | crontab -
```
The `@reboot` line is what runs `scripts/aws-start-stack.sh` (docker-wait, `git pull`, `docker compose up -d`) every time the ignition Lambda starts the instance.

**4. Deploy the ignition Lambda**
- Create a Python 3.12 Lambda from `ignition/handler.py`.
- IAM role: `ec2:StartInstances`, `ec2:ModifyInstanceAttribute` on the instance.
- Environment variables: `INSTANCE_ID` (required), `AWS_REGION` (defaults to `us-east-1` if unset).
- Enable a **Function URL**.

**5. Use it**
```bash
curl "https://<lambda-function-url>/"                    # boot at current/default size
curl "https://<lambda-function-url>/?size=t4g.medium"     # resize then boot
```
Allowed sizes: `t4g.small`, `t4g.medium`, `t3.small`, `t3.medium` — anything else returns HTTP 400 without touching the instance.

## Layout

| Path | What |
|---|---|
| `config.yaml`, `docker-compose.yml` | The gateway stack — LiteLLM, Headroom, Redis (deploy-target-agnostic) |
| `scripts/jarvis-startup.sh` | Jarvis Labs pod boot sequence |
| `scripts/aws-start-stack.sh`, `aws-idle-check.sh(+.cron)` | AWS EC2 boot sequence and idle auto-shutdown |
| `ignition/handler.py` | AWS Lambda "ignition switch" that starts/resizes the EC2 host on demand |
| `docs/high-level-design.md`, `docs/intent/` | Design intent (HLD, per-component LLDs, EARS specs) |
| `docs/gemini/` | Original research this project was built from |

For agent-facing conventions (LID workflow, spec IDs, dev commands), see `AGENTS.md`.
