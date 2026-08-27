"""Behavioral tests for scripts/aws-launch.sh and scripts/aws-destroy.sh.

Same PATH-shimmed fake-bin + stdin-feeding technique as test_local_launch.py
(fake `terraform` instead of `docker`). See aws-infra-design.md.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_SCRIPT = REPO_ROOT / "scripts" / "aws-launch.sh"
DESTROY_SCRIPT = REPO_ROOT / "scripts" / "aws-destroy.sh"


def _run(script, tmp_path, bin_dir, stdin_text=""):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write_tfvars_example(tmp_path):
    infra = tmp_path / "infra"
    infra.mkdir()
    infra.joinpath("terraform.tfvars.example").write_text(
        'tailscale_auth_key = "placeholder"\n'
        'secrets_mode = "bitwarden"\n'
        'bws_access_token = ""\n'
    )
    return infra


# --- aws-launch.sh --------------------------------------------------------


# @spec INFRA-022
def test_launch_copies_tfvars_example_when_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_tfvars_example(tmp_path)

    result = _run(LAUNCH_SCRIPT, tmp_path, bin_dir, "\n\n\n")  # keep all three

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "infra" / "terraform.tfvars").read_text() == (
        'tailscale_auth_key = "placeholder"\n'
        'secrets_mode = "bitwarden"\n'
        'bws_access_token = ""\n'
    )


# @spec INFRA-022
def test_launch_prompt_shows_current_value_and_replaces_it(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    infra = _write_tfvars_example(tmp_path)
    infra.joinpath("terraform.tfvars").write_text(
        'tailscale_auth_key = "old-key"\n'
        'secrets_mode = "bitwarden"\n'
        'bws_access_token = ""\n'
    )

    result = _run(LAUNCH_SCRIPT, tmp_path, bin_dir, "new-key\n\n\n")

    assert result.returncode == 0, result.stderr
    assert "tailscale_auth_key" in result.stdout
    assert "old-key" in result.stdout
    assert (infra / "terraform.tfvars").read_text() == (
        'tailscale_auth_key = "new-key"\n'
        'secrets_mode = "bitwarden"\n'
        'bws_access_token = ""\n'
    )


# @spec INFRA-023
def test_launch_runs_terraform_init_then_apply_without_auto_approve(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_tfvars_example(tmp_path)

    result = _run(LAUNCH_SCRIPT, tmp_path, bin_dir, "\n\n\n")

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "-chdir=infra init" in calls
    assert "-chdir=infra apply -var-file=terraform.tfvars" in calls
    assert "-auto-approve" not in calls
    assert calls.index("init") < calls.index("apply")


# --- aws-destroy.sh -------------------------------------------------------


# @spec INFRA-024
def test_destroy_runs_terraform_destroy_without_auto_approve(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    infra = tmp_path / "infra"
    infra.mkdir()
    infra.joinpath("terraform.tfvars").write_text('tailscale_auth_key = "k"\n')

    result = _run(DESTROY_SCRIPT, tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "-chdir=infra destroy -var-file=terraform.tfvars" in calls
    assert "-auto-approve" not in calls


# @spec INFRA-024
def test_destroy_errors_when_tfvars_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')

    result = _run(DESTROY_SCRIPT, tmp_path, bin_dir)

    assert result.returncode != 0
    assert call_log.exists() is False or call_log.read_text() == ""
