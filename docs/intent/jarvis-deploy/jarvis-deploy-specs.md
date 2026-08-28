# Jarvis Deploy — EARS Specs

- [x] **JARVIS-001**: The startup script shall store Tailscale state under the persistent `/home/litellm-stack/tailscale-state` directory rather than the default ephemeral state path.
- [x] **JARVIS-002**: When the workspace directory does not contain a `.git` folder, the startup script shall clone the repository; otherwise it shall run `git pull origin main`.
- [x] **JARVIS-003**: The startup script shall poll `docker info` in a loop until the Docker daemon is ready before starting any containers.
- [x] **JARVIS-004**: If no `project.toml` file exists in the workspace, then the startup script shall copy `project.toml.example` to `project.toml` and run `scripts/render_config.py` to produce a placeholder `.env` before starting the stack.
- [x] **JARVIS-005**: The startup script shall bring up the Docker Compose stack only after the workspace sync and Docker-daemon wait steps complete.
