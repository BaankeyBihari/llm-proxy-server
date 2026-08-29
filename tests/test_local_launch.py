"""Behavioral tests for scripts/launch.sh --env=local.

Runs the real script against a tmp_path cwd, feeding prompt responses over
stdin and a PATH-shimmed fake `docker` (same technique as the deploy-script
tests — see conftest.py). See local-launch-design.md and
project-config-design.md (project.toml, render_config.py).
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "launch.sh"

EXAMPLE_TOML = (
    "[secrets]\n"
    'openrouter_api_key = "your_openrouter_key_here"\n'
    'litellm_master_key = "sk-master-key-1234"\n'
    'postgres_password = "changeme"\n'
    'tailscale_auth_key = "tskey-auth-REPLACE_ME"\n'
)


def _fake_docker(add, call_log, running=False):
    ps_output = 'echo "fake-container-id"' if running else ":"
    add(
        "docker",
        f'echo "docker $*" >> {call_log}\n'
        f'if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then\n'
        f"  {ps_output}\n"
        f"  exit 0\n"
        f"fi\n"
        f'if [ "$1" = "compose" ] && [ "$2" = "up" ]; then\n'
        f"  exit 0\n"
        f"fi\n"
        f"exit 0\n",
    )


def _run(tmp_path, bin_dir, stdin_text):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), "--env=local"],
        cwd=tmp_path,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


# @spec LOCAL-001
def test_copies_project_toml_example_when_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "\n\n\n")  # keep all three owned keys

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "project.toml").read_text() == EXAMPLE_TOML


# @spec LOCAL-002
def test_does_not_reset_existing_project_toml_to_example_values(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    real = EXAMPLE_TOML.replace("your_openrouter_key_here", "or-real-value")
    (tmp_path / "project.toml").write_text(real)

    result = _run(tmp_path, bin_dir, "\n\n\n")  # keep current

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "project.toml").read_text() == real


# @spec LOCAL-003
def test_only_prompts_owned_keys_not_tailscale(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    assert "tailscale_auth_key" not in result.stdout


# @spec LOCAL-004
def test_prompt_shows_current_value(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    assert "openrouter_api_key" in result.stdout
    assert "your_openrouter_key_here" in result.stdout


# @spec LOCAL-005
def test_replaces_value_when_new_value_given_keeps_others(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    # order prompted: openrouter_api_key, litellm_master_key, postgres_password
    result = _run(tmp_path, bin_dir, "or-new\n\n\n")

    assert result.returncode == 0, result.stderr
    text = (tmp_path / "project.toml").read_text()
    assert 'openrouter_api_key = "or-new"' in text
    assert 'litellm_master_key = "sk-master-key-1234"' in text  # unchanged


# @spec LOCAL-006
def test_preserves_table_headers_and_comments(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    example = "# top comment\n" + EXAMPLE_TOML
    (tmp_path / "project.toml.example").write_text(example)

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    text = (tmp_path / "project.toml").read_text()
    assert "# top comment" in text
    assert "[secrets]" in text


# @spec LOCAL-007
def test_aborts_when_stack_already_running(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log, running=True)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "")

    assert result.returncode != 0
    assert not (tmp_path / "project.toml").exists()
    assert "compose up" not in call_log.read_text()


# @spec LOCAL-012
def test_renders_env_from_project_toml_before_bringing_stack_up(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    env_text = (tmp_path / ".env").read_text()
    assert "OPENROUTER_API_KEY=your_openrouter_key_here" in env_text
    assert "compose up -d" in call_log.read_text()


# @spec LOCAL-008
def test_brings_up_stack_after_populating_project_toml(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text().splitlines()
    ps_line = next(i for i, l in enumerate(calls) if "compose ps" in l)
    up_line = next(i for i, l in enumerate(calls) if "compose up -d" in l)
    assert ps_line < up_line


# @spec LOCAL-009
def test_prints_curl_example_with_real_master_key(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    real = EXAMPLE_TOML.replace("sk-master-key-1234", "sk-real-secret")
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    (tmp_path / "project.toml").write_text(real)

    result = _run(tmp_path, bin_dir, "\n\n\n")  # keep all

    assert result.returncode == 0, result.stderr
    assert "curl" in result.stdout
    assert "/v1/chat/completions" in result.stdout
    assert "Bearer sk-real-secret" in result.stdout
