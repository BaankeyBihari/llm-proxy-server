"""Behavioral tests for scripts/aws-start-stack.sh and scripts/aws-idle-check.sh.

Same PATH-shimmed-fakes technique as test_jarvis_startup.py — see conftest.py.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
START_SCRIPT = REPO_ROOT / "scripts" / "aws-start-stack.sh"
IDLE_SCRIPT = REPO_ROOT / "scripts" / "aws-idle-check.sh"
CRON_FILE = REPO_ROOT / "scripts" / "aws-idle-check.cron"


def _run(script, env_overrides, timeout=10):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, timeout=timeout
    )


# --- start_stack.sh -----------------------------------------------------


def _start_stack_env(tmp_path, bin_dir, workspace):
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "WORKSPACE": str(workspace),
        "DOCKER_POLL_INTERVAL_SECS": "0",
    }


# @spec AWS-003
def test_start_stack_waits_for_docker_before_compose_up(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("git", f'echo "git $*" >> {call_log}')
    counter_file = tmp_path / "attempts"
    add(
        "docker",
        f'echo "docker $*" >> {call_log}\n'
        f'if [ "$1" = "info" ]; then\n'
        f'  n=$(cat {counter_file} 2>/dev/null || echo 0)\n'
        f'  n=$((n + 1))\n'
        f'  echo "$n" > {counter_file}\n'
        f'  [ "$n" -ge 2 ] || exit 1\n'
        f"fi\n",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _run(START_SCRIPT, _start_stack_env(tmp_path, bin_dir, workspace))

    assert result.returncode == 0, result.stderr
    assert counter_file.read_text().strip() == "2"
    calls = call_log.read_text()
    assert calls.index("docker info") < calls.index("docker compose up")


# @spec AWS-004
def test_start_stack_pulls_then_brings_up_compose(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("git", f'echo "git $*" >> {call_log}')
    add("docker", f'echo "docker $*" >> {call_log}\n[ "$1" != "info" ] || exit 0')
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _run(START_SCRIPT, _start_stack_env(tmp_path, bin_dir, workspace))

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "git pull origin main" in calls
    assert "docker compose up -d" in calls
    assert calls.index("git pull") < calls.index("docker compose up")


# --- idle_check.sh -------------------------------------------------------


# @spec AWS-005
def test_idle_check_exits_early_when_uptime_below_threshold(fake_bin, call_log):
    bin_dir, add = fake_bin
    add("docker", f'echo "docker $*" >> {call_log}')
    add("sudo", f'echo "sudo $*" >> {call_log}')

    result = _run(
        IDLE_SCRIPT,
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "IDLE_TEST_UPTIME_SECONDS": "100",
        },
    )

    assert result.returncode == 0, result.stderr
    assert call_log.exists() is False or call_log.read_text() == ""


# @spec AWS-006
def test_idle_check_powers_off_when_idle_past_threshold(fake_bin, call_log):
    bin_dir, add = fake_bin
    add("sudo", f'echo "sudo $*" >> {call_log}')

    result = _run(
        IDLE_SCRIPT,
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "IDLE_TEST_UPTIME_SECONDS": "20000",
            "IDLE_TEST_REQUEST_COUNT": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "sudo poweroff" in call_log.read_text()


# @spec AWS-006
def test_idle_check_does_not_power_off_when_requests_present(fake_bin, call_log):
    bin_dir, add = fake_bin
    add("sudo", f'echo "sudo $*" >> {call_log}')

    result = _run(
        IDLE_SCRIPT,
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "IDLE_TEST_UPTIME_SECONDS": "20000",
            "IDLE_TEST_REQUEST_COUNT": "3",
        },
    )

    assert result.returncode == 0, result.stderr
    assert call_log.exists() is False or "poweroff" not in call_log.read_text()


# --- aws-idle-check.cron ---------------------------------------------------


# @spec AWS-007
def test_cron_fragment_schedules_idle_check_hourly():
    contents = CRON_FILE.read_text()
    assert "0 * * * *" in contents
    assert "aws-idle-check.sh" in contents
