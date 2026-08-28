"""Behavioral tests for scripts/bws-sync.sh — pulls secrets from Bitwarden
into project.toml. Same PATH-shimmed fake-bin technique as the other
launch-script tests. See aws-infra-design.md § Bitwarden Sync Script.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bws-sync.sh"

EXAMPLE_TOML = (
    "[config]\n"
    "embedding_similarity_threshold = 0.85\n"
    "\n"
    "[secrets]\n"
    'openrouter_api_key = "your_openrouter_key_here"\n'
    'litellm_master_key = "sk-master-key-1234"\n'
    'postgres_password = "changeme"\n'
    'tailscale_auth_key = "tskey-auth-REPLACE_ME"\n'
)


def _run(tmp_path, bin_dir, bws_access_token="test-token"):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["BWS_ACCESS_TOKEN"] = bws_access_token
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _fake_bws(add, call_log, output):
    add(
        "bws",
        f'echo "bws $*" >> {call_log}\n'
        f'if [ "$1" = "secret" ] && [ "$2" = "list" ]; then\n'
        f'  printf %s "{output}"\n'
        f"fi\n",
    )


# @spec INFRA-031
def test_seeds_project_toml_from_example_when_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    _fake_bws(add, call_log, "OPENROUTER_API_KEY=or-real\n")

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "project.toml").exists()


# @spec INFRA-031
def test_calls_bws_secret_list_with_output_env(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    _fake_bws(add, call_log, "OPENROUTER_API_KEY=or-real\n")

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "bws secret list --output env" in call_log.read_text()


# @spec INFRA-032
def test_syncs_matching_keys_overwriting_existing_values(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    (tmp_path / "project.toml").write_text(EXAMPLE_TOML)
    vault_output = (
        "OPENROUTER_API_KEY=or-synced\n"
        "LITELLM_MASTER_KEY=sk-synced\n"
        "POSTGRES_PASSWORD=pg-synced\n"
        "TAILSCALE_AUTH_KEY=tskey-synced\n"
    )
    _fake_bws(add, call_log, vault_output)

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    text = (tmp_path / "project.toml").read_text()
    assert 'openrouter_api_key = "or-synced"' in text
    assert 'litellm_master_key = "sk-synced"' in text
    assert 'postgres_password = "pg-synced"' in text
    assert 'tailscale_auth_key = "tskey-synced"' in text


# @spec INFRA-032
def test_leaves_field_untouched_when_key_absent_from_vault(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    (tmp_path / "project.toml").write_text(EXAMPLE_TOML)
    _fake_bws(add, call_log, "OPENROUTER_API_KEY=or-synced\n")  # no TAILSCALE_AUTH_KEY

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    text = (tmp_path / "project.toml").read_text()
    assert 'openrouter_api_key = "or-synced"' in text
    assert 'tailscale_auth_key = "tskey-auth-REPLACE_ME"' in text  # unchanged


# @spec INFRA-033
def test_propagates_bws_failure(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    add("bws", f'echo "bws $*" >> {call_log}\nexit 1')

    result = _run(tmp_path, bin_dir)

    assert result.returncode != 0
