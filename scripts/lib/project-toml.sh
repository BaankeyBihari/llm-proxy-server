#!/bin/bash
# Shared per-key keep-or-replace prompt loop over project.toml, sourced by
# scripts/launch.sh's local and aws paths — replaces what used to be two
# separate copies (one per .env/.tfvars syntax) now that both paths edit the
# same file. See docs/intent/project-config/project-config-design.md.
# @spec CONF-009

# project_toml_prompt_keys <file> <key> [<key> ...]
#
# Scans <file> line by line. For any `key = value` line whose bare key name
# is in the given list, shows the current value and prompts for a
# replacement (empty response keeps the current value). All other lines —
# [table] headers, comments, blanks, and keys not in the list — pass through
# unchanged. Preserves whether a value was quoted (a TOML string) or bare
# (a TOML number/bool), so round-tripping an unedited value doesn't change
# its type.
project_toml_prompt_keys() {
  local toml_file="$1"
  shift
  local owned_keys=("$@")
  local tmp_file
  tmp_file=$(mktemp)

  local line key value_part is_quoted current_value new_value chosen_value owned k
  while IFS= read -r line <&3 || [ -n "$line" ]; do
    if [ -z "$line" ] || [[ "$line" == \#* ]] || [[ "$line" == \[*\]* ]]; then
      echo "$line" >> "$tmp_file"
      continue
    fi

    key=$(echo "${line%%=*}" | xargs)

    owned=false
    for k in "${owned_keys[@]}"; do
      [ "$k" = "$key" ] && owned=true && break
    done
    if [ "$owned" != true ]; then
      echo "$line" >> "$tmp_file"
      continue
    fi

    # Trim whitespace only — xargs would also strip quote characters, which
    # matters here since we need to tell a quoted string from a bare number.
    value_part="${line#*=}"
    value_part="${value_part#"${value_part%%[![:space:]]*}"}"
    value_part="${value_part%"${value_part##*[![:space:]]}"}"
    if [[ "$value_part" == \"*\" ]]; then
      is_quoted=true
      current_value=${value_part%\"}
      current_value=${current_value#\"}
    else
      is_quoted=false
      current_value=$value_part
    fi

    printf '%s [%s]: ' "$key" "$current_value"
    read -r new_value
    if [ -n "$new_value" ]; then
      chosen_value=$new_value
    else
      chosen_value=$current_value
    fi

    if [ "$is_quoted" = true ]; then
      echo "$key = \"$chosen_value\"" >> "$tmp_file"
    else
      echo "$key = $chosen_value" >> "$tmp_file"
    fi
  done 3< "$toml_file"

  mv "$tmp_file" "$toml_file"
}
