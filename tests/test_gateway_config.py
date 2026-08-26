"""Structural tests for the gateway stack's config.yaml and docker-compose.yml.

These assert what the checked-in config *declares*, not live routing/caching
behavior (no OpenRouter/network calls) — see gateway-stack-design.md.
"""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config():
    with open(REPO_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def compose():
    with open(REPO_ROOT / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _model_entries(config, model_name):
    return [m for m in config["model_list"] if m["model_name"] == model_name]


# @spec GATE-001
def test_smart_auto_routes_to_openrouter_auto(config):
    entries = _model_entries(config, "smart-auto")
    assert len(entries) == 1
    assert entries[0]["litellm_params"]["model"] == "openrouter/openrouter/auto"


# @spec GATE-002
def test_cheapest_auto_routes_to_floor(config):
    entries = _model_entries(config, "cheapest-auto")
    assert len(entries) == 1
    assert entries[0]["litellm_params"]["model"] == "openrouter/openrouter/auto:floor"


# @spec GATE-003
def test_fast_auto_routes_to_nitro(config):
    entries = _model_entries(config, "fast-auto")
    assert len(entries) == 1
    assert entries[0]["litellm_params"]["model"] == "openrouter/openrouter/auto:nitro"


# @spec GATE-004
def test_resilient_router_is_a_two_model_fallback_chain_in_order(config):
    entries = _model_entries(config, "resilient-router")
    assert [e["litellm_params"]["model"] for e in entries] == [
        "openrouter/nousresearch/hermes-3-llama-3.1-405b",
        "openrouter/nvidia/llama-3.1-nemotron-70b-instruct",
    ]


# @spec GATE-005
def test_wildcard_passthrough_present(config):
    entries = _model_entries(config, "openrouter/*")
    assert len(entries) == 1
    assert entries[0]["litellm_params"]["model"] == "openrouter/*"


# @spec GATE-006
def test_headroom_registered_as_default_on_pre_call_guardrail(config):
    guardrails = config["guardrails"]
    headroom = [g for g in guardrails if g["litellm_params"]["guardrail"] == "headroom"]
    assert len(headroom) == 1
    params = headroom[0]["litellm_params"]
    assert params["mode"] == "pre_call"
    assert params["api_base"] == "http://headroom:8787"
    assert params["default_on"] is True


# @spec GATE-007
def test_redis_cache_enabled_with_seven_day_ttl(config):
    settings = config["litellm_settings"]
    assert settings["cache"] is True
    assert settings["cache_params"]["type"] == "redis"
    assert settings["cache_params"]["ttl"] == 604800


# @spec GATE-008
def test_redis_service_persists_snapshots_to_mounted_volume(compose):
    redis = compose["services"]["redis"]
    assert "./redis-data:/data" in redis["volumes"]
    assert "--save 60 1" in redis["command"]


# @spec GATE-009
def test_redis_service_caps_memory_with_lru_eviction(compose):
    redis = compose["services"]["redis"]
    assert "--maxmemory 1536mb" in redis["command"]
    assert "--maxmemory-policy allkeys-lru" in redis["command"]


# @spec GATE-010
def test_litellm_depends_on_redis_and_headroom(compose):
    depends_on = compose["services"]["litellm"]["depends_on"]
    assert set(depends_on) == {"redis", "headroom"}
