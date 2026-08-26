---
parent: high-level-design
prefix: AWS
---

# AWS Deploy

## Context and Design Philosophy

Unlike a Jarvis Labs pod (paused, storage billed continuously), an AWS EC2 target is fully stopped between sessions and restarted on demand (see `aws-ignition`). This leaf owns everything needed to make that stop/start cycle safe and self-managing: the single-IP cost constraint, the boot script that runs on every start, and the idle-detection script that triggers the next stop. It consumes `gateway-stack`'s `config.yaml`/`docker-compose.yml` unmodified.

## Host-Level Constraint: Single IPv4

AWS bills $0.005/hr per public IP. The instance gets **exactly one Elastic IP (EIP)** and nothing else — no load balancer, no NAT gateway, no secondary IP. An EIP stays associated with a *stopped* instance (unlike an auto-assigned public IP, which is released on stop), which is what makes the stop/start cycle preserve the Tailscale-reachable address without re-provisioning networking on every ignition. Instance family is fixed to `t3.*` (x86_64) or `t4g.*` (ARM64) — the two families cannot be crossed on the same EBS volume, which constrains what the ignition Lambda (`aws-ignition`) is allowed to resize into.

## Boot Sequence (`start_stack.sh`)

Runs via `@reboot` cron (or an equivalent systemd unit) so it fires every time the ignition Lambda starts the instance:

1. `cd` into the workspace.
2. Poll `docker info` until the daemon is ready (same rationale as `jarvis-deploy`: cloud boot races the daemon).
3. `git pull origin main`.
4. `docker compose up -d`.

Tailscale itself is brought up separately at initial host setup (`tailscale up --hostname=cloud-litellm --statedir=/home/ubuntu/tailscale-state`) — its state directory is pinned under `/home/ubuntu/` for the same ghost-node reason as `jarvis-deploy`, though EC2's stop/start (rather than pause) means this matters less in practice than for Jarvis; it's pinned anyway for consistency and because `/home` persists across stop/start while ephemeral instance-store paths would not.

## Idle Shutdown (`idle_check.sh`)

1. Read `/proc/uptime`; if the host has been up under 14400s (4 hours), exit immediately — a freshly-booted instance shouldn't be judged idle on its first hour.
2. Otherwise, count `POST /` lines in `docker logs --since 4h litellm-proxy`.
3. If that count is zero, `sudo poweroff` — AWS surfaces this as the instance transitioning to `stopped`.

The hourly cadence is shipped as a versioned crontab fragment (`scripts/aws-idle-check.cron`) rather than a hand-typed `crontab -e` line, so the schedule itself is reviewable and testable rather than trusted to have been typed correctly on the host. Installing it (`crontab scripts/aws-idle-check.cron`) is still a one-time manual step, same as the Tailscale setup below.

The 4-hour uptime floor and the 4-hour log-lookback window are the same value deliberately: once past the floor, "no requests in the last 4h" and "no requests since boot" converge, so the check never has to distinguish "just booted, no requests yet" from "genuinely idle."

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Public IP strategy | One Elastic IP | Auto-assigned public IP, load balancer + target group | Auto-assigned IPs are released on stop (would break the ignition Lambda's assumption of a stable Tailscale-reachable host); a load balancer/NAT adds always-on cost the idle-shutdown model is designed to avoid. |
| Idle detection signal | `docker logs` request count | CloudWatch custom metric | No AWS-side metering cost or extra IAM surface; runs entirely on-host via cron, matching the "host owns its own lifecycle" tenet. |
| Idle check cadence | Hourly cron | Continuous daemon/systemd timer | Hourly is a low-cost proxy for the 4h threshold; a continuously-running checker isn't meaningfully faster to react and adds its own resource use. |

## Open Questions & Future Decisions

### Deferred

1. Whether `idle_check.sh`'s request-count grep (`"POST /"`) should be scoped to exclude LiteLLM's own health-check traffic is left open — not yet observed as a false-idle-negative in practice.

## References

- `docs/high-level-design.md`
- `docs/gemini/MasterGuide-LiteLLM-Stack.md` § 5 (Phase 3: Production on AWS EC2)
- `docs/gemini/RiskAnalysis.md` § 2 (Docker Daemon Boot Race), § 5 (Storage Billing & Footprint Drift)
- `docs/intent/aws-ignition/aws-ignition-design.md` — the Lambda that triggers this leaf's boot sequence and is constrained by this leaf's `t3`/`t4g` family lock
