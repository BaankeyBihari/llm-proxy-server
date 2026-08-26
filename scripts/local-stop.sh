#!/bin/bash
# Stops the local stack gracefully, if it's running. Warns (doesn't error)
# if it's already down — see docs/intent/local-launch/local-launch-design.md.
# @spec LOCAL-010, LOCAL-011
set -euo pipefail

if [ -z "$(docker compose ps --status running -q)" ]; then
  echo "Stack is not running — nothing to stop." >&2
  exit 0
fi

docker compose down
