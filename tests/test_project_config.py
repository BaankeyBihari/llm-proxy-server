"""Tests for project.toml.example, scripts/render_config.py, and the shared
scripts/lib/project-toml.sh prompt loop. See project-config-design.md.
"""
import os
import subprocess
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_config.py"
PROMPT_LIB = REPO_ROOT / "scripts" / "lib" / "project-toml.sh"
EXAMPLE = REPO_ROOT / "project.toml.example"

_STDLIB_ALLOWLIST = {"tomllib", "json", "sys", "os", "pathlib", "subprocess", "argparse"}


def _write_project_toml(path):
    path.write_text(
        "[secrets]\n"
        'openrouter_api_key = "or-real"\n'
        'litellm_master_key = "sk-real"\n'
        'postgres_password = "pg-real"\n'
        'tailscale_auth_key = "tskey-real"\n'
    )


def _run_render(tmp_path, extra_path=None):
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{extra_path}:{env['PATH']}"
    return subprocess.run(
        ["python3", str(RENDER_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


# @spec CONF-001
def test_example_has_secrets_table_with_expected_keys():
    data = tomllib.loads(EXAMPLE.read_text())
    assert "config" not in data
    for key in (
        "openrouter_api_key",
        "litellm_master_key",
        "postgres_password",
        "tailscale_auth_key",
    ):
        assert key in data["secrets"]


# @spec CONF-002
def test_render_script_only_imports_stdlib_modules():
    text = RENDER_SCRIPT.read_text()
    imports = [
        line.split()[1].split(".")[0]
        for line in text.splitlines()
        if line.startswith("import ")
    ]
    assert imports, "expected at least one top-level import"
    assert set(imports) <= _STDLIB_ALLOWLIST


# @spec CONF-003
def test_render_writes_env_with_expected_keys(tmp_path):
    _write_project_toml(tmp_path / "project.toml")

    result = _run_render(tmp_path)

    assert result.returncode == 0, result.stderr
    env_text = (tmp_path / ".env").read_text()
    assert "OPENROUTER_API_KEY=or-real" in env_text
    assert "LITELLM_MASTER_KEY=sk-real" in env_text
    assert "POSTGRES_PASSWORD=pg-real" in env_text


# @spec CONF-004
def test_render_writes_tfvars_json_with_expected_keys(tmp_path):
    _write_project_toml(tmp_path / "project.toml")

    result = _run_render(tmp_path)

    assert result.returncode == 0, result.stderr
    import json

    tfvars = json.loads((tmp_path / "infra" / "generated.auto.tfvars.json").read_text())
    assert tfvars["tailscale_auth_key"] == "tskey-real"
    assert set(tfvars) == {"tailscale_auth_key"}


# @spec CONF-005
def test_render_never_invokes_bws(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("bws", f'echo "bws $*" >> {call_log}\nexit 1')
    _write_project_toml(tmp_path / "project.toml")

    result = _run_render(tmp_path, extra_path=bin_dir)

    assert result.returncode == 0, result.stderr
    assert not call_log.exists() or call_log.read_text() == ""


# @spec CONF-007
def test_render_errors_on_unrecognized_table(tmp_path):
    (tmp_path / "project.toml").write_text('[nonsense]\nfoo = "bar"\n')

    result = _run_render(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()


# @spec CONF-008
def test_gitignore_covers_project_toml_and_generated_files():
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "project.toml" in gitignore
    assert ".env" in gitignore
    assert "infra/generated.auto.tfvars.json" in gitignore


# @spec CONF-011
def test_old_per_target_templates_are_retired():
    assert not (REPO_ROOT / ".env.example").exists()
    assert not (REPO_ROOT / "infra" / "terraform.tfvars.example").exists()
    assert EXAMPLE.exists()


# --- shared prompt loop (scripts/lib/project-toml.sh) ----------------------


def _run_prompt_loop(tmp_path, toml_path, keys, stdin_text):
    script = tmp_path / "invoke.sh"
    script.write_text(
        f'#!/bin/bash\nsource "{PROMPT_LIB}"\n'
        f'project_toml_prompt_keys "{toml_path}" {" ".join(keys)}\n'
    )
    return subprocess.run(
        ["bash", str(script)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


# @spec CONF-009
def test_prompt_loop_replaces_owned_key_and_leaves_others_untouched(tmp_path):
    toml_path = tmp_path / "project.toml"
    _write_project_toml(toml_path)

    result = _run_prompt_loop(tmp_path, toml_path, ["openrouter_api_key"], "or-new\n")

    assert result.returncode == 0, result.stderr
    data = tomllib.loads(toml_path.read_text())
    assert data["secrets"]["openrouter_api_key"] == "or-new"
    assert data["secrets"]["litellm_master_key"] == "sk-real"  # untouched, not owned


# @spec CONF-009
def test_prompt_loop_keeps_current_value_on_empty_response(tmp_path):
    toml_path = tmp_path / "project.toml"
    _write_project_toml(toml_path)

    result = _run_prompt_loop(tmp_path, toml_path, ["openrouter_api_key"], "\n")

    assert result.returncode == 0, result.stderr
    data = tomllib.loads(toml_path.read_text())
    assert data["secrets"]["openrouter_api_key"] == "or-real"


# @spec CONF-009
def test_prompt_loop_preserves_table_headers_and_comments(tmp_path):
    toml_path = tmp_path / "project.toml"
    toml_path.write_text(
        '# a comment\n[other]\nfoo = "bar"\n\n[secrets]\n'
        'openrouter_api_key = "or-real"\n'
    )

    result = _run_prompt_loop(tmp_path, toml_path, ["openrouter_api_key"], "\n")

    assert result.returncode == 0, result.stderr
    text = toml_path.read_text()
    assert "# a comment" in text
    assert "[other]" in text
    assert "[secrets]" in text
