#!/bin/bash
# Runs on every EC2 boot (via @reboot cron / systemd), i.e. every time the
# aws-ignition Lambda starts the instance.
# @spec AWS-003, AWS-004
set -euo pipefail

WORKSPACE=${WORKSPACE:-/home/ubuntu/litellm-proxy}
DOCKER_POLL_INTERVAL_SECS=${DOCKER_POLL_INTERVAL_SECS:-2}

cd "$WORKSPACE"

# Wait for Docker to be ready.
until docker info > /dev/null 2>&1; do
  sleep "$DOCKER_POLL_INTERVAL_SECS"
done

# Pull latest changes and start.
git pull origin main
docker compose up -d
