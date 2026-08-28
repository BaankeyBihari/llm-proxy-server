#!/bin/bash
# Interactive project.toml setup for the AWS target: copies project.toml.example
# to project.toml if missing, walks through this script's owned keys prompting
# to keep or replace each current value, renders infra/generated.auto.tfvars.json
# via render_config.py, then provisions the AWS stack.
# See docs/intent/aws-infra/aws-infra-design.md and
# docs/intent/project-config/project-config-design.md.
# @spec INFRA-022, INFRA-023, INFRA-029
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/project-toml.sh"

INFRA_DIR=infra
TOML_FILE=project.toml
TOML_EXAMPLE_FILE=project.toml.example

if [ ! -f "$TOML_FILE" ]; then
  cp "$TOML_EXAMPLE_FILE" "$TOML_FILE"
fi

project_toml_prompt_keys "$TOML_FILE" \
  secrets_mode \
  tailscale_auth_key \
  bws_access_token

python3 "$SCRIPT_DIR/render_config.py"

terraform -chdir="$INFRA_DIR" init
terraform -chdir="$INFRA_DIR" apply
