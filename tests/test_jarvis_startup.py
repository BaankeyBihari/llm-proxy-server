"""Behavioral tests for scripts/jarvis-startup.sh via PATH-shimmed fakes.

The script is parameterized via env vars (WORKSPACE, TAILSCALE_STATEDIR,
BOOT_SLEEP_SECS, DOCKER_POLL_INTERVAL_SECS) precisely so it's testable this
way without real Tailscale/Docker/Git — see jarvis-deploy-design.md.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "jarvis-startup.sh"


def _run(tmp_path, fake_bin, workspace, env_overrides=None):
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WORKSPACE"] = str(workspace)
    env["BOOT_SLEEP_SECS"] = "0"
    env["DOCKER_POLL_INTERVAL_SECS"] = "0"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10
    )


def _basic_fakes(add, call_log):
    add("sudo", f'echo "sudo $*" >> {call_log}\nexec "$@"')
    add("tailscaled", f'echo "tailscaled $*" >> {call_log}')
    add("tailscale", f'echo "tailscale $*" >> {call_log}')
    add("git", f'echo "git $*" >> {call_log}\nif [ "$1" = "clone" ]; then mkdir -p "$3/.git"; fi')
    add("docker", f'echo "docker $*" >> {call_log}\nif [ "$1" = "info" ]; then exit 0; fi')


# @spec JARVIS-001
def test_pins_tailscale_statedir_under_workspace(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert f"--statedir={workspace}/tailscale-state" in calls


# @spec JARVIS-002
def test_clones_when_workspace_has_no_git_dir(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"  # not created — no .git present

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "git clone" in calls
    assert "git pull" not in calls


# @spec JARVIS-002
def test_pulls_when_workspace_already_has_git_dir(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "git pull origin main" in calls
    assert "git clone" not in calls


# @spec JARVIS-003
def test_waits_for_docker_daemon_before_compose_up(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("sudo", f'echo "sudo $*" >> {call_log}\nexec "$@"')
    add("tailscaled", f'echo "tailscaled $*" >> {call_log}')
    add("tailscale", f'echo "tailscale $*" >> {call_log}')
    add("git", f'echo "git $*" >> {call_log}\nif [ "$1" = "clone" ]; then mkdir -p "$3/.git"; fi')
    # docker info fails twice, then succeeds — proves the script actually polls.
    counter_file = tmp_path / "docker-info-attempts"
    add(
        "docker",
        f'echo "docker $*" >> {call_log}\n'
        f'if [ "$1" = "info" ]; then\n'
        f'  n=$(cat {counter_file} 2>/dev/null || echo 0)\n'
        f'  n=$((n + 1))\n'
        f'  echo "$n" > {counter_file}\n'
        f'  [ "$n" -ge 3 ] || exit 1\n'
        f"fi\n",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    assert counter_file.read_text().strip() == "3"
    calls = call_log.read_text()
    compose_idx = calls.index("docker compose up")
    last_info_idx = calls.rindex("docker info")
    assert last_info_idx < compose_idx


# @spec JARVIS-004
def test_bootstraps_env_file_when_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    env_file = workspace / ".env"
    assert env_file.exists()
    contents = env_file.read_text()
    assert "OPENROUTER_API_KEY" in contents
    assert "LITELLM_MASTER_KEY" in contents


# @spec JARVIS-004
def test_does_not_overwrite_existing_env_file(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / ".env").write_text("OPENROUTER_API_KEY=real-key\n")

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    assert (workspace / ".env").read_text() == "OPENROUTER_API_KEY=real-key\n"


# @spec JARVIS-005
def test_compose_up_runs_after_sync_and_docker_wait(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _basic_fakes(add, call_log)
    workspace = tmp_path / "workspace"  # triggers clone path

    result = _run(tmp_path, bin_dir, workspace)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text().splitlines()
    compose_line = next(i for i, l in enumerate(calls) if "docker compose up" in l)
    clone_line = next(i for i, l in enumerate(calls) if "git clone" in l)
    info_line = next(i for i, l in enumerate(calls) if l.strip() == "docker info")
    assert clone_line < compose_line
    assert info_line < compose_line
