"""Behavioral tests for scripts/launch.sh's shared --env dispatch — the part
that belongs to neither the local-launch nor aws-infra leaf specifically.
Same PATH-shimmed fake-bin technique as test_local_launch.py.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "launch.sh"


def _run(tmp_path, bin_dir, args):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp_path,
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_errors_with_usage_when_env_flag_missing(tmp_path, fake_bin):
    bin_dir, _ = fake_bin

    result = _run(tmp_path, bin_dir, [])

    assert result.returncode != 0
    assert "Usage" in result.stderr
    assert not (tmp_path / "project.toml").exists()


def test_errors_with_usage_when_env_value_invalid(tmp_path, fake_bin):
    bin_dir, _ = fake_bin

    result = _run(tmp_path, bin_dir, ["--env=staging"])

    assert result.returncode != 0
    assert "Usage" in result.stderr
    assert not (tmp_path / "project.toml").exists()
