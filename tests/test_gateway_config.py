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
def test_redis_semantic_cache_enabled_with_seven_day_ttl(config):
    settings = config["litellm_settings"]
    assert settings["cache"] is True
    assert settings["cache_params"]["type"] == "redis-semantic"
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


# @spec GATE-011
def test_similarity_threshold_defaults_to_0_85_overridable_via_env(config, compose):
    assert config["litellm_settings"]["cache_params"]["similarity_threshold"] == (
        "os.environ/EMBEDDING_SIMILARITY_THRESHOLD"
    )
    litellm_env = compose["services"]["litellm"]["environment"]
    assert "EMBEDDING_SIMILARITY_THRESHOLD=${EMBEDDING_SIMILARITY_THRESHOLD:-0.85}" in litellm_env


# @spec GATE-012
def test_embedding_service_uses_infinity_image_serving_bge_small_no_host_port(compose):
    embedding = compose["services"]["embedding"]
    assert embedding["image"] == "michaelfeil/infinity"
    assert "BAAI/bge-small-en-v1.5" in " ".join(embedding.get("command", []))
    assert "ports" not in embedding


# @spec GATE-013
def test_embedding_service_persists_weights_cache(compose):
    embedding = compose["services"]["embedding"]
    assert "./embedding-cache:/data" in embedding["volumes"]
    assert "HF_HOME=/data" in embedding["environment"]


# @spec GATE-010
def test_litellm_depends_on_redis_headroom_and_embedding(compose):
    # Subset, not exact-equality: key-management-specs.md's KEYS-004 independently
    # asserts "postgres" is also present in the same depends_on list.
    depends_on = set(compose["services"]["litellm"]["depends_on"])
    assert {"redis", "headroom", "embedding"} <= depends_on
