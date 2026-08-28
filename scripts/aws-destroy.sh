#!/bin/bash
# Tears down the AWS stack provisioned by scripts/launch.sh --env=aws.
# See docs/intent/aws-infra/aws-infra-design.md.
# @spec INFRA-024
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INFRA_DIR=infra
TOML_FILE=project.toml

if [ ! -f "$TOML_FILE" ]; then
  echo "$TOML_FILE not found — nothing to destroy (run this from the repo root)." >&2
  exit 1
fi

python3 "$SCRIPT_DIR/render_config.py"

terraform -chdir="$INFRA_DIR" destroy
