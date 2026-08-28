"""Structural tests for key-management's docker-compose.yml additions.

Same style as test_gateway_config.py: assert what's declared, not live
Postgres/LiteLLM behavior. See key-management-design.md.
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def compose():
    with open(REPO_ROOT / "docker-compose.yml") as f:
        return yaml.safe_load(f)


# @spec KEYS-001
def test_postgres_service_declared_with_persistent_volume(compose):
    postgres = compose["services"]["postgres"]
    assert postgres["image"] == "postgres:16-alpine"
    assert "./postgres-data:/var/lib/postgresql/data" in postgres["volumes"]
    assert "POSTGRES_DB=litellm" in postgres["environment"]


# @spec KEYS-002
def test_postgres_service_publishes_no_host_port(compose):
    assert "ports" not in compose["services"]["postgres"]


# @spec KEYS-003
def test_litellm_database_url_uses_postgres_password(compose):
    litellm_env = compose["services"]["litellm"]["environment"]
    assert (
        "DATABASE_URL=postgresql://litellm:${POSTGRES_PASSWORD}@postgres:5432/litellm"
        in litellm_env
    )


# @spec KEYS-004
def test_litellm_depends_on_postgres(compose):
    assert "postgres" in compose["services"]["litellm"]["depends_on"]


# @spec KEYS-005
def test_no_default_max_budget_configured():
    with open(REPO_ROOT / "config.yaml") as f:
        config = yaml.safe_load(f)
    assert "max_budget" not in config.get("litellm_settings", {})
    assert "general_settings" not in config or "max_budget" not in config["general_settings"]


# @spec KEYS-006
def test_no_separate_ui_credentials_configured(compose):
    litellm_env = compose["services"]["litellm"]["environment"]
    joined = " ".join(litellm_env)
    assert "UI_USERNAME" not in joined
    assert "UI_PASSWORD" not in joined


# @spec KEYS-007
def test_no_boot_script_invokes_a_migration_command():
    scripts_dir = REPO_ROOT / "scripts"
    for name in ("launch.sh", "aws-start-stack.sh", "jarvis-startup.sh.example"):
        text = (scripts_dir / name).read_text()
        assert "migrate" not in text.lower()
