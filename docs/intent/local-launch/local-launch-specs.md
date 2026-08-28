# Local Launch — EARS Specs

## Pre-flight

- [x] **LOCAL-007**: If any container from this Compose project is already running, then the script shall exit non-zero without modifying `project.toml` or calling `docker compose up`.

## `project.toml` Population

- [x] **LOCAL-001**: If `project.toml` does not exist, then the script shall copy `project.toml.example` to `project.toml` before proceeding.
- [x] **LOCAL-002**: While `project.toml` already exists, the script shall leave it unmodified at the copy step and proceed directly to prompting.
- [x] **LOCAL-003**: The script shall use the shared prompt loop (`CONF-009`) scoped to `[config].embedding_similarity_threshold` and `[secrets].openrouter_api_key`/`litellm_master_key`/`postgres_password`.
- [x] **LOCAL-004**: For each owned key, in file order, the script shall display the current value and prompt for a replacement, unconditionally.
- [x] **LOCAL-005**: When the user enters a non-empty replacement for a key, the script shall write that value; when the user submits an empty response, the script shall retain the current value.
- [x] **LOCAL-006**: The script shall write the result back to `project.toml`, preserving the original line order and any comment/blank/table lines unchanged.

## Launch

- [x] **LOCAL-012**: After `project.toml` is populated, the script shall run `scripts/render_config.py` to produce `.env` before calling `docker compose up -d`.
- [x] **LOCAL-008**: After `.env` is rendered, the script shall run `docker compose up -d`.
- [x] **LOCAL-009**: After bringing the stack up, the script shall print a `curl` example against `/v1/chat/completions` with the `Authorization` header populated using the real `LITELLM_MASTER_KEY` value from `.env`.

## Stop

- [x] **LOCAL-010**: If no container from this Compose project is running, then `local-stop.sh` shall print a warning and exit zero without calling `docker compose down`.
- [x] **LOCAL-011**: While any container from this Compose project is running, `local-stop.sh` shall run `docker compose down`.
