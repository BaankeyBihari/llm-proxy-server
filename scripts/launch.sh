#!/bin/bash
# Interactive project.toml setup and launch, dispatched by deploy target.
# --env=local: local dev (docker compose up -d). --env=aws: AWS infra
# (terraform init/apply). See docs/intent/local-launch/local-launch-design.md
# and docs/intent/aws-infra/aws-infra-design.md.
# @spec LOCAL-001, LOCAL-002, LOCAL-003, LOCAL-004, LOCAL-005, LOCAL-006, LOCAL-007, LOCAL-008, LOCAL-009, LOCAL-012
# @spec INFRA-022, INFRA-023, INFRA-029
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/project-toml.sh"

TOML_FILE=project.toml
TOML_EXAMPLE_FILE=project.toml.example

usage() {
  echo "Usage: $0 --env=local|aws" >&2
  exit 1
}

if [ $# -ne 1 ]; then
  usage
fi

case "$1" in
  --env=local) TARGET_ENV=local ;;
  --env=aws) TARGET_ENV=aws ;;
  *) usage ;;
esac

# @spec LOCAL-001, LOCAL-002, LOCAL-003, LOCAL-004, LOCAL-005, LOCAL-006, LOCAL-007, LOCAL-008, LOCAL-009, LOCAL-012
local_launch() {
  # Abort before touching project.toml if the stack is already up — a live
  # container won't see project.toml edits until restarted, so proceeding
  # would be misleading.
  if [ -n "$(docker compose ps --status running -q)" ]; then
    echo "Stack is already running (docker compose ps shows running containers)." >&2
    echo "Aborting — restart the stack yourself if you want it to pick up new project.toml values." >&2
    exit 1
  fi

  if [ ! -f "$TOML_FILE" ]; then
    cp "$TOML_EXAMPLE_FILE" "$TOML_FILE"
  fi

  project_toml_prompt_keys "$TOML_FILE" \
    embedding_similarity_threshold \
    openrouter_api_key \
    litellm_master_key \
    postgres_password

  python3 "$SCRIPT_DIR/render_config.py"

  docker compose up -d

  master_key=$(grep '^LITELLM_MASTER_KEY=' .env | head -1 | cut -d= -f2- || true)
  cat <<EOF

Stack is up. Try:

curl http://localhost:4000/v1/chat/completions \\
  -H "Authorization: Bearer $master_key" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "smart-auto", "messages": [{"role": "user", "content": "Ping."}]}'
EOF
}

# @spec INFRA-022, INFRA-023, INFRA-029
aws_launch() {
  local infra_dir=infra

  if [ ! -f "$TOML_FILE" ]; then
    cp "$TOML_EXAMPLE_FILE" "$TOML_FILE"
  fi

  project_toml_prompt_keys "$TOML_FILE" \
    secrets_mode \
    tailscale_auth_key \
    bws_access_token

  python3 "$SCRIPT_DIR/render_config.py"

  terraform -chdir="$infra_dir" init
  terraform -chdir="$infra_dir" apply
}

case "$TARGET_ENV" in
  local) local_launch ;;
  aws) aws_launch ;;
esac
