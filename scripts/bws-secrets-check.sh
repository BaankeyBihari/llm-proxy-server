#!/bin/bash
# Reviews and updates this project's Bitwarden Secrets Manager vault: lists
# each secret via `bws`, shows its current value, and prompts to keep or
# replace it. Reads BWS_ACCESS_TOKEN from the environment (bws's own env
# var) — no project ID is passed, the machine account token is assumed
# scoped to one project (docs/gemini/bitwarden.md's setup). Editing a
# secret here does not reach an already-booted EC2 host.
# See docs/intent/aws-infra/aws-infra-design.md § Bitwarden Vault Check Script.
# @spec INFRA-025, INFRA-026, INFRA-027, INFRA-028
set -euo pipefail

secrets_json=$(bws secret list --output json)

# Read secrets on fd 3, keeping fd 0 (stdin) free for the interactive
# prompts below (same technique as scripts/launch.sh).
while IFS= read -r secret <&3; do
  id=$(echo "$secret" | jq -r '.id')
  key=$(echo "$secret" | jq -r '.key')
  value=$(echo "$secret" | jq -r '.value')

  printf '%s [%s]: ' "$key" "$value"
  read -r new_value
  if [ -n "$new_value" ]; then
    bws secret edit --value "$new_value" "$id"
  fi
done 3<<< "$(echo "$secrets_json" | jq -c '.[]')"
