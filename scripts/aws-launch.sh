#!/bin/bash
# Interactive infra/terraform.tfvars setup: copies terraform.tfvars.example to
# terraform.tfvars if missing, walks through each key prompting to keep or
# replace its current value (same UX as scripts/local-launch.sh, adapted for
# Terraform's `key = "value"` syntax), then provisions the AWS stack.
# See docs/intent/aws-infra/aws-infra-design.md.
# @spec INFRA-022, INFRA-023
set -euo pipefail

INFRA_DIR=infra
VARS_FILE="$INFRA_DIR/terraform.tfvars"
VARS_EXAMPLE_FILE="$INFRA_DIR/terraform.tfvars.example"

if [ ! -f "$VARS_FILE" ]; then
  cp "$VARS_EXAMPLE_FILE" "$VARS_FILE"
fi

tmp_file=$(mktemp)

# Read terraform.tfvars on fd 3, keeping fd 0 (stdin) free for prompts.
while IFS= read -r line <&3 || [ -n "$line" ]; do
  # Pass comments and blank lines through unchanged.
  if [ -z "$line" ] || [[ "$line" == \#* ]]; then
    echo "$line" >> "$tmp_file"
    continue
  fi

  key=$(echo "${line%%=*}" | xargs)
  current_value=$(echo "${line#*=}" | xargs)
  current_value=${current_value%\"}
  current_value=${current_value#\"}

  printf '%s [%s]: ' "$key" "$current_value"
  read -r new_value
  if [ -n "$new_value" ]; then
    echo "$key = \"$new_value\"" >> "$tmp_file"
  else
    echo "$key = \"$current_value\"" >> "$tmp_file"
  fi
done 3< "$VARS_FILE"

mv "$tmp_file" "$VARS_FILE"

terraform -chdir="$INFRA_DIR" init
terraform -chdir="$INFRA_DIR" apply -var-file=terraform.tfvars
