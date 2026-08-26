"""Behavioral tests for scripts/local-stop.sh — same fake-docker technique
as test_local_launch.py. See local-launch-design.md § local-stop.sh."""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "local-stop.sh"


def _fake_docker(add, call_log, running=False):
    ps_output = 'echo "fake-container-id"' if running else ":"
    add(
        "docker",
        f'echo "docker $*" >> {call_log}\n'
        f'if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then\n'
        f"  {ps_output}\n"
        f"  exit 0\n"
        f"fi\n"
        f'if [ "$1" = "compose" ] && [ "$2" = "down" ]; then\n'
        f"  exit 0\n"
        f"fi\n"
        f"exit 0\n",
    )


def _run(tmp_path, bin_dir):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10
    )


# @spec LOCAL-010
def test_warns_and_exits_zero_when_not_running(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log, running=False)

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "not running" in result.stderr.lower()
    assert "compose down" not in call_log.read_text()


# @spec LOCAL-011
def test_brings_down_gracefully_when_running(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log, running=True)

    result = _run(tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "docker compose down" in call_log.read_text()
