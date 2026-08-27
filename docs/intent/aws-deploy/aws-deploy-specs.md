# AWS Deploy — EARS Specs

## Host Constraint

The single-EIP / no-load-balancer / no-NAT-gateway constraint (see design doc) is codified in Terraform and specced under `aws-infra`, not here — this leaf's scripts consume the provisioned instance, they don't provision it.

## Boot Sequence

Note: Tailscale authentication (with `--statedir` pinned to `/home/ubuntu/tailscale-state`) is not part of the recurring `start_stack.sh` — it runs once, automatically, from `aws-infra`'s Terraform `user_data` at first boot. It has its EARS spec there (`INFRA-015`), not here — this leaf's scripts consume an already-Tailscale-connected host, they don't establish that connection.

- [x] **AWS-003**: The start script shall poll `docker info` in a loop until the Docker daemon is ready before starting containers.
- [x] **AWS-004**: The start script shall run `git pull origin main` and bring up the Docker Compose stack on each invocation.

## Idle Shutdown

- [x] **AWS-005**: While host uptime is under 14400 seconds (4 hours), the idle-check script shall exit without checking request activity.
- [x] **AWS-006**: While host uptime is at least 14400 seconds, if the trailing-4-hour `litellm-proxy` log contains zero `POST /` lines, then the idle-check script shall power off the host.
- [x] **AWS-007**: The repository shall provide a crontab fragment that schedules the idle-check script to run once per hour.
