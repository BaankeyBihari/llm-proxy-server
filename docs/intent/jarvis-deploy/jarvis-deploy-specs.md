# Jarvis Deploy — EARS Specs

- [x] **JARVIS-001**: The startup script shall store Tailscale state under the persistent `/home/litellm-stack/tailscale-state` directory rather than the default ephemeral state path.
- [x] **JARVIS-002**: When the workspace directory does not contain a `.git` folder, the startup script shall clone the repository; otherwise it shall run `git pull origin main`.
- [x] **JARVIS-003**: The startup script shall poll `docker info` in a loop until the Docker daemon is ready before starting any containers.
- [x] **JARVIS-004**: If no `project.toml` file exists in the workspace, then the startup script shall copy `project.toml.example` to `project.toml` and run `scripts/render_config.py` to produce a placeholder `.env` before starting the stack.
- [x] **JARVIS-005**: The startup script shall bring up the Docker Compose stack only after the workspace sync and Docker-daemon wait steps complete.

## Rendering the Startup Script

- [x] **JARVIS-006**: `scripts/launch.sh --env=jarvis` shall use the shared prompt loop (`CONF-009`) scoped to `[secrets].tailscale_auth_key` in `project.toml` (seeded from `project.toml.example` if missing).
- [x] **JARVIS-007**: The script shall render `scripts/jarvis-startup.sh` from `scripts/jarvis-startup.sh.example`, substituting `TAILSCALE_AUTHKEY`'s default with `project.toml`'s `tailscale_auth_key` and `GIT_REPO_URL`'s default with the output of `git remote get-url origin`, leaving all other lines unchanged.
- [x] **JARVIS-008**: `scripts/jarvis-startup.sh` (the rendered output) shall be excluded from version control; only `scripts/jarvis-startup.sh.example` shall be checked in.
