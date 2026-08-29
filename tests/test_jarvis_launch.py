"""Behavioral tests for scripts/launch.sh --env=jarvis — renders
jarvis-startup.sh.example into a real jarvis-startup.sh with
TAILSCALE_AUTHKEY (from project.toml) and GIT_REPO_URL (from `git remote
get-url origin`) substituted. See jarvis-deploy-design.md.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "launch.sh"
TEMPLATE = REPO_ROOT / "scripts" / "jarvis-startup.sh.example"

EXAMPLE_TOML = (
    "[secrets]\n"
    'openrouter_api_key = "your_openrouter_key_here"\n'
    'litellm_master_key = "sk-master-key-1234"\n'
    'postgres_password = "changeme"\n'
    'tailscale_auth_key = "tskey-auth-REPLACE_ME"\n'
)


@pytest.fixture
def repo(tmp_path):
    """A tmp_path checkout: project.toml.example + a real scripts/ dir (so
    launch.sh can source lib/project-toml.sh and find the template), with
    its own git remote so `git remote get-url origin` resolves."""
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "launch.sh").write_bytes(SCRIPT.read_bytes())
    (scripts_dir / "jarvis-startup.sh.example").write_bytes(TEMPLATE.read_bytes())
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir()
    (lib_dir / "project-toml.sh").write_bytes(
        (REPO_ROOT / "scripts" / "lib" / "project-toml.sh").read_bytes()
    )
    (scripts_dir / "render_config.py").write_bytes(
        (REPO_ROOT / "scripts" / "render_config.py").read_bytes()
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/repo.git"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _run(repo, stdin_text):
    env = dict(os.environ)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "launch.sh"), "--env=jarvis"],
        cwd=repo,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


# @spec JARVIS-008
def test_rendered_script_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "scripts/jarvis-startup.sh" in gitignore


# @spec JARVIS-006
def test_prompts_tailscale_auth_key(repo):
    result = _run(repo, "\n")

    assert result.returncode == 0, result.stderr
    assert "tailscale_auth_key" in result.stdout


# @spec JARVIS-007
def test_renders_tailscale_authkey_and_git_repo_url(repo):
    result = _run(repo, "tskey-real-value\n")

    assert result.returncode == 0, result.stderr
    rendered = (repo / "scripts" / "jarvis-startup.sh").read_text()
    assert "TAILSCALE_AUTHKEY=${TAILSCALE_AUTHKEY:-tskey-real-value}" in rendered
    assert (
        "GIT_REPO_URL=${GIT_REPO_URL:-https://github.com/example/repo.git}" in rendered
    )


# @spec JARVIS-007
def test_rendered_script_keeps_other_lines_unchanged(repo):
    result = _run(repo, "\n")

    assert result.returncode == 0, result.stderr
    rendered = (repo / "scripts" / "jarvis-startup.sh").read_text()
    template_text = TEMPLATE.read_text()
    for line in template_text.splitlines():
        if not line.startswith(("TAILSCALE_AUTHKEY=", "GIT_REPO_URL=")):
            assert line in rendered
