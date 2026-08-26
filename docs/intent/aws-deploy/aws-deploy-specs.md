# AWS Deploy — EARS Specs

## Host Constraint

The single-EIP / no-load-balancer / no-NAT-gateway constraint (see design doc) is AWS account/console configuration, not code this repo ships — it has no EARS spec here for the same reason as the Tailscale one-time setup below.

## Boot Sequence

Note: pinning Tailscale's `--statedir` to `/home/ubuntu/tailscale-state` is a one-time, manual host-provisioning step (run once over SSH when the instance is first created), not part of the recurring `start_stack.sh` — see design doc's Boot Sequence section. It has no EARS spec here because it is not code this repo ships or tests.

- [x] **AWS-003**: The start script shall poll `docker info` in a loop until the Docker daemon is ready before starting containers.
- [x] **AWS-004**: The start script shall run `git pull origin main` and bring up the Docker Compose stack on each invocation.

## Idle Shutdown

- [x] **AWS-005**: While host uptime is under 14400 seconds (4 hours), the idle-check script shall exit without checking request activity.
- [x] **AWS-006**: While host uptime is at least 14400 seconds, if the trailing-4-hour `litellm-proxy` log contains zero `POST /` lines, then the idle-check script shall power off the host.
- [x] **AWS-007**: The repository shall provide a crontab fragment that schedules the idle-check script to run once per hour.
