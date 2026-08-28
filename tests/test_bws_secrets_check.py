"""Behavioral tests for scripts/bws-secrets-check.sh.

Same PATH-shimmed fake-bin + stdin-feeding technique as
test_aws_launch_destroy.py (fake `bws` instead of `terraform`). See
aws-infra-design.md § Bitwarden Vault Check Script.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bws-secrets-check.sh"

FAKE_SECRETS_JSON = (
    '[{"id":"11111111-1111-1111-1111-111111111111",'
    '"key":"OPENROUTER_API_KEY","value":"old-or-key"},'
    '{"id":"22222222-2222-2222-2222-222222222222",'
    '"key":"LITELLM_MASTER_KEY","value":"old-master-key"}]'
)


def _run(tmp_path, bin_dir, call_log, stdin_text=""):
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


def _add_fake_bws(add, call_log):
    add(
        "bws",
        f'echo "bws $*" >> {call_log}\n'
        f'if [ "$1 $2" = "secret list" ]; then echo \'{FAKE_SECRETS_JSON}\'; fi',
    )


# @spec INFRA-025, INFRA-026
def test_lists_secrets_with_no_project_id_and_shows_current_values(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _add_fake_bws(add, call_log)

    result = _run(tmp_path, bin_dir, call_log, "\n\n")  # keep both

    assert result.returncode == 0, result.stderr
    assert "OPENROUTER_API_KEY" in result.stdout
    assert "old-or-key" in result.stdout
    assert "LITELLM_MASTER_KEY" in result.stdout
    assert "old-master-key" in result.stdout
    calls = call_log.read_text()
    assert "bws secret list --output json" in calls
    assert "--access-token" not in calls


# @spec INFRA-027
def test_empty_response_leaves_secret_unchanged(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _add_fake_bws(add, call_log)

    result = _run(tmp_path, bin_dir, call_log, "\n\n")  # keep both

    assert result.returncode == 0, result.stderr
    assert "secret edit" not in call_log.read_text()


# @spec INFRA-027
def test_non_empty_response_edits_that_secret_by_id(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    _add_fake_bws(add, call_log)

    result = _run(tmp_path, bin_dir, call_log, "new-or-key\n\n")  # replace first, keep second

    assert result.returncode == 0, result.stderr
    edit_calls = [line for line in call_log.read_text().splitlines() if "secret edit" in line]
    assert edit_calls == ["bws secret edit --value new-or-key 11111111-1111-1111-1111-111111111111"]


# @spec INFRA-028
def test_script_uses_set_euo_pipefail():
    assert "set -euo pipefail" in SCRIPT.read_text()
