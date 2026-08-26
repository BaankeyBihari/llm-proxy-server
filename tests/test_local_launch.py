"""Behavioral tests for scripts/local-launch.sh.

Runs the real script against a tmp_path cwd, feeding prompt responses over
stdin and a PATH-shimmed fake `docker` (same technique as the deploy-script
tests — see conftest.py). See local-launch-design.md.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "local-launch.sh"


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
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


# @spec LOCAL-001
def test_copies_env_example_when_env_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=bar\nBAZ=qux\n")

    result = _run(tmp_path, bin_dir, "\n\n")  # keep both

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text() == "FOO=bar\nBAZ=qux\n"


# @spec LOCAL-002
def test_does_not_reset_existing_env_to_example_values(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=placeholder\n")
    (tmp_path / ".env").write_text("FOO=real-value\n")

    result = _run(tmp_path, bin_dir, "\n")  # keep current

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text() == "FOO=real-value\n"


# @spec LOCAL-003
def test_preserves_comments_and_blank_lines(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=bar\n")
    (tmp_path / ".env").write_text("# a comment\nFOO=bar\n\nBAZ=qux\n")

    result = _run(tmp_path, bin_dir, "\n\n")  # keep both real keys

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text() == "# a comment\nFOO=bar\n\nBAZ=qux\n"


# @spec LOCAL-004
def test_prompt_shows_current_value(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=bar\n")
    (tmp_path / ".env").write_text("FOO=bar\n")

    result = _run(tmp_path, bin_dir, "\n")

    assert result.returncode == 0, result.stderr
    assert "FOO" in result.stdout
    assert "bar" in result.stdout


# @spec LOCAL-005
def test_replaces_value_when_new_value_given_keeps_others(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=bar\nBAZ=qux\n")
    (tmp_path / ".env").write_text("FOO=bar\nBAZ=qux\n")

    result = _run(tmp_path, bin_dir, "new-foo\n\n")  # replace FOO, keep BAZ

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text() == "FOO=new-foo\nBAZ=qux\n"


# @spec LOCAL-006
def test_preserves_key_order(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("A=1\n")
    (tmp_path / ".env").write_text("C=3\nA=1\nB=2\n")

    result = _run(tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".env").read_text() == "C=3\nA=1\nB=2\n"


# @spec LOCAL-007
def test_aborts_when_stack_already_running(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log, running=True)
    (tmp_path / ".env.example").write_text("FOO=bar\n")

    result = _run(tmp_path, bin_dir, "")

    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()
    assert "compose up" not in call_log.read_text()


# @spec LOCAL-007
def test_abort_leaves_existing_env_untouched(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log, running=True)
    (tmp_path / ".env.example").write_text("FOO=placeholder\n")
    (tmp_path / ".env").write_text("FOO=real-value\n")

    result = _run(tmp_path, bin_dir, "")

    assert result.returncode != 0
    assert (tmp_path / ".env").read_text() == "FOO=real-value\n"


# @spec LOCAL-008
def test_brings_up_stack_after_populating_env(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text("FOO=bar\n")

    result = _run(tmp_path, bin_dir, "\n")

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text().splitlines()
    ps_line = next(i for i, l in enumerate(calls) if "compose ps" in l)
    up_line = next(i for i, l in enumerate(calls) if "compose up -d" in l)
    assert ps_line < up_line


# @spec LOCAL-009
def test_prints_curl_example_with_real_master_key(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _fake_docker(add, call_log)
    (tmp_path / ".env.example").write_text(
        "OPENROUTER_API_KEY=placeholder\nLITELLM_MASTER_KEY=placeholder\n"
    )
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=or-real\nLITELLM_MASTER_KEY=sk-real-secret\n"
    )

    result = _run(tmp_path, bin_dir, "\n\n")  # keep both

    assert result.returncode == 0, result.stderr
    assert "curl" in result.stdout
    assert "/v1/chat/completions" in result.stdout
    assert "Bearer sk-real-secret" in result.stdout
