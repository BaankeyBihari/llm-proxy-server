#!/bin/bash
# Hourly idle check (see aws-idle-check.cron): powers off the host after 4h
# of continuous uptime with zero litellm-proxy requests in the last 4h.
# @spec AWS-005, AWS-006
set -euo pipefail

UPTIME_THRESHOLD_SECS=${UPTIME_THRESHOLD_SECS:-14400}
CONTAINER_NAME=${CONTAINER_NAME:-litellm-proxy}

# IDLE_TEST_UPTIME_SECONDS / IDLE_TEST_REQUEST_COUNT let tests substitute a
# value for real /proc/uptime and docker log inspection; unset in production.
if [ -n "${IDLE_TEST_UPTIME_SECONDS:-}" ]; then
  UPTIME_SEC=$IDLE_TEST_UPTIME_SECONDS
else
  UPTIME_SEC=$(awk '{print int($1)}' /proc/uptime)
fi

# 1. Check if the server has even been online for 4 hours.
if [ "$UPTIME_SEC" -lt "$UPTIME_THRESHOLD_SECS" ]; then
  exit 0
fi

# 2. Check litellm-proxy logs for any API requests in the last 4 hours.
if [ -n "${IDLE_TEST_REQUEST_COUNT:-}" ]; then
  REQUESTS=$IDLE_TEST_REQUEST_COUNT
else
  REQUESTS=$(docker logs --since 4h "$CONTAINER_NAME" 2>&1 | grep -c "POST /")
fi

# 3. If zero requests, shut down the OS (AWS surfaces this as "Stopped").
if [ "$REQUESTS" -eq 0 ]; then
  sudo poweroff
fi
