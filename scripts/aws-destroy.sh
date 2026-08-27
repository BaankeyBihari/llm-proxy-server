#!/bin/bash
# Tears down the AWS stack provisioned by scripts/aws-launch.sh.
# See docs/intent/aws-infra/aws-infra-design.md.
# @spec INFRA-024
set -euo pipefail

INFRA_DIR=infra
VARS_FILE="$INFRA_DIR/terraform.tfvars"

if [ ! -f "$VARS_FILE" ]; then
  echo "$VARS_FILE not found — nothing to destroy (run this from the repo root)." >&2
  exit 1
fi

terraform -chdir="$INFRA_DIR" destroy -var-file=terraform.tfvars
