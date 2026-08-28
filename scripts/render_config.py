#!/usr/bin/env python3
"""Reads project.toml and renders .env (for docker compose) and
infra/generated.auto.tfvars.json (for Terraform) — project-config's
table-to-file mapping. Unconditional: never shells out to bws itself —
scripts/bws-sync.sh is the only thing that talks to Bitwarden, and it writes
into project.toml, not around this generator. Stdlib-only, runs under any
system python3 >=3.11 without needing `uv sync` first (matters for
jarvis-startup.sh's boot).
@spec CONF-002, CONF-003, CONF-004, CONF-005, CONF-007
"""
import json
import sys
import tomllib
from pathlib import Path

SCHEMA = {
    "config": {"embedding_similarity_threshold"},
    "secrets": {
        "openrouter_api_key",
        "litellm_master_key",
        "postgres_password",
        "tailscale_auth_key",
    },
}


def main():
    with Path("project.toml").open("rb") as f:
        data = tomllib.load(f)

    for table, keys in data.items():
        if table not in SCHEMA:
            sys.exit(f"render_config.py: unrecognized table [{table}] in project.toml")
        for key in keys:
            if key not in SCHEMA[table]:
                sys.exit(f"render_config.py: unrecognized key {table}.{key} in project.toml")

    config = data.get("config", {})
    secrets = data.get("secrets", {})

    env_lines = [
        f"OPENROUTER_API_KEY={secrets['openrouter_api_key']}",
        f"LITELLM_MASTER_KEY={secrets['litellm_master_key']}",
        f"POSTGRES_PASSWORD={secrets['postgres_password']}",
        f"EMBEDDING_SIMILARITY_THRESHOLD={config['embedding_similarity_threshold']}",
    ]
    Path(".env").write_text("\n".join(env_lines) + "\n")

    tfvars = {
        "tailscale_auth_key": secrets["tailscale_auth_key"],
    }
    infra_dir = Path("infra")
    infra_dir.mkdir(exist_ok=True)
    (infra_dir / "generated.auto.tfvars.json").write_text(json.dumps(tfvars, indent=2) + "\n")


if __name__ == "__main__":
    main()
