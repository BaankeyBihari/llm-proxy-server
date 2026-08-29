#!/bin/bash
# Pulls secrets from Bitwarden Secrets Manager and writes them into
# project.toml — the shared local-secrets-manager step for all three deploy
# targets. Run it, then scripts/launch.sh --env=local|aws as usual; its
# keep-or-replace prompt shows the just-synced values as current. Same
# command everywhere: on your laptop for local dev, over an SSM session for
# AWS, over SSH for a Jarvis pod.
# Reads BWS_ACCESS_TOKEN from the environment (bws's own env var), same
# convention as scripts/bws-secrets-check.sh.
# See docs/intent/aws-infra/aws-infra-design.md § Bitwarden Sync Script.
# @spec INFRA-031, INFRA-032, INFRA-033
set -euo pipefail

TOML_FILE=project.toml
TOML_EXAMPLE_FILE=project.toml.example

if [ ! -f "$TOML_FILE" ]; then
  cp "$TOML_EXAMPLE_FILE" "$TOML_FILE"
fi

secrets_env=$(bws secret list --output env)

# sync_one <bitwarden key> <project.toml key>
#
# Overwrites <project.toml key>'s value with Bitwarden's <bitwarden key>
# secret, when present in this vault; leaves the field untouched otherwise
# (e.g. tailscale_auth_key before an operator has added TAILSCALE_AUTH_KEY
# to the vault).
sync_one() {
  local bws_key="$1" toml_key="$2" line value
  line=$(printf '%s\n' "$secrets_env" | grep -m1 "^${bws_key}=" || true)
  [ -z "$line" ] && return
  value=${line#*=}
  value=${value#\"}
  value=${value%\"}
  awk -v k="$toml_key" -v v="$value" '
    $0 ~ "^" k " = " { print k " = \"" v "\""; next }
    { print }
  ' "$TOML_FILE" > "$TOML_FILE.tmp" && mv "$TOML_FILE.tmp" "$TOML_FILE"
  echo "Synced $toml_key from Bitwarden."
}

sync_one OPENROUTER_API_KEY openrouter_api_key
sync_one LITELLM_MASTER_KEY litellm_master_key
sync_one POSTGRES_PASSWORD postgres_password
sync_one TAILSCALE_AUTH_KEY tailscale_auth_key
