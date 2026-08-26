# Local Launch — EARS Specs

## Pre-flight

- [x] **LOCAL-007**: If any container from this Compose project is already running, then the script shall exit non-zero without modifying `.env` or calling `docker compose up`.

## `.env` Population

- [x] **LOCAL-001**: If `.env` does not exist, then the script shall copy `.env.example` to `.env` before proceeding.
- [x] **LOCAL-002**: While `.env` already exists, the script shall leave it unmodified at the copy step and proceed directly to prompting.
- [x] **LOCAL-003**: The script shall read `.env` as `KEY=value` lines, passing blank lines and `#`-comment lines through unchanged.
- [x] **LOCAL-004**: For each key read from `.env`, in file order, the script shall display the current value and prompt for a replacement.
- [x] **LOCAL-005**: When the user enters a non-empty replacement for a key, the script shall write that value; when the user submits an empty response, the script shall retain the current value.
- [x] **LOCAL-006**: The script shall write the result back to `.env`, preserving the original key order and any comment/blank lines unchanged.

## Launch

- [x] **LOCAL-008**: After `.env` is populated, the script shall run `docker compose up -d`.
- [x] **LOCAL-009**: After bringing the stack up, the script shall print a `curl` example against `/v1/chat/completions` with the `Authorization` header populated using the real `LITELLM_MASTER_KEY` value from `.env`.

## Stop

- [x] **LOCAL-010**: If no container from this Compose project is running, then `local-stop.sh` shall print a warning and exit zero without calling `docker compose down`.
- [x] **LOCAL-011**: While any container from this Compose project is running, `local-stop.sh` shall run `docker compose down`.
