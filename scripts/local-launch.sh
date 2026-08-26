#!/bin/bash
# Interactive .env setup: copies .env.example to .env if missing, walks
# through each key prompting to keep or replace its current value, then
# brings the stack up and prints a ready-to-run curl example.
# See docs/intent/local-launch/local-launch-design.md.
# @spec LOCAL-001, LOCAL-002, LOCAL-003, LOCAL-004, LOCAL-005, LOCAL-006, LOCAL-007, LOCAL-008, LOCAL-009
set -euo pipefail

ENV_FILE=.env
ENV_EXAMPLE_FILE=.env.example

# Abort before touching .env if the stack is already up — a live container
# won't see .env edits until restarted, so proceeding would be misleading.
if [ -n "$(docker compose ps --status running -q)" ]; then
  echo "Stack is already running (docker compose ps shows running containers)." >&2
  echo "Aborting — restart the stack yourself if you want it to pick up new .env values." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
fi

tmp_file=$(mktemp)

# Read .env on fd 3, keeping fd 0 (stdin) free for the interactive prompts.
while IFS= read -r line <&3 || [ -n "$line" ]; do
  # Pass comments and blank lines through unchanged.
  if [ -z "$line" ] || [[ "$line" == \#* ]]; then
    echo "$line" >> "$tmp_file"
    continue
  fi

  key=${line%%=*}
  current_value=${line#*=}

  # printf + plain `read`, not `read -p`: some bash builds (e.g. macOS's
  # bash 3.2) silently drop -p's prompt when stdin isn't a tty.
  printf '%s [%s]: ' "$key" "$current_value"
  read -r new_value
  if [ -n "$new_value" ]; then
    echo "$key=$new_value" >> "$tmp_file"
  else
    echo "$key=$current_value" >> "$tmp_file"
  fi
done 3< "$ENV_FILE"

mv "$tmp_file" "$ENV_FILE"

docker compose up -d

master_key=$(grep '^LITELLM_MASTER_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)
cat <<EOF

Stack is up. Try:

curl http://localhost:4000/v1/chat/completions \\
  -H "Authorization: Bearer $master_key" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "smart-auto", "messages": [{"role": "user", "content": "Ping."}]}'
EOF
