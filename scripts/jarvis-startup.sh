#!/bin/bash
# Jarvis Labs pod startup script — pasted into the pod's "Startup Script"
# field, so it runs on every resume, not just first boot.
# @spec JARVIS-001, JARVIS-002, JARVIS-003, JARVIS-004, JARVIS-005
set -euo pipefail

WORKSPACE=${WORKSPACE:-/home/litellm-stack}
TAILSCALE_STATEDIR=${TAILSCALE_STATEDIR:-"$WORKSPACE/tailscale-state"}
TAILSCALE_AUTHKEY=${TAILSCALE_AUTHKEY:-tskey-auth-YOUR_SECRET_KEY_HERE}
TAILSCALE_HOSTNAME=${TAILSCALE_HOSTNAME:-jarvis-litellm}
GIT_REPO_URL=${GIT_REPO_URL:-https://github.com/yourusername/your-litellm-repo.git}
BOOT_SLEEP_SECS=${BOOT_SLEEP_SECS:-3}
DOCKER_POLL_INTERVAL_SECS=${DOCKER_POLL_INTERVAL_SECS:-2}

echo "Starting Jarvis Labs Boot Sequence..."

# 1. Ensure Tailscale state persists across pauses.
mkdir -p "$TAILSCALE_STATEDIR"
sudo tailscaled --statedir="$TAILSCALE_STATEDIR" &
sleep "$BOOT_SLEEP_SECS"
sudo tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="$TAILSCALE_HOSTNAME" --accept-routes

# 2. Setup/update workspace from GitHub.
if [ ! -d "$WORKSPACE/.git" ]; then
  git clone "$GIT_REPO_URL" "$WORKSPACE"
else
  (cd "$WORKSPACE" && git pull origin main)
fi

# 3. Wait for the Docker daemon.
echo "Waiting for Docker daemon..."
until docker info > /dev/null 2>&1; do
  sleep "$DOCKER_POLL_INTERVAL_SECS"
done

# 4. Inject secrets & launch stack.
cd "$WORKSPACE"
if [ ! -f .env ]; then
  {
    echo "OPENROUTER_API_KEY=your_key_here"
    echo "LITELLM_MASTER_KEY=sk-master-key-1234"
  } > .env
fi

docker compose up -d --build
echo "Jarvis Labs sequence complete. Available at http://$TAILSCALE_HOSTNAME:4000"
