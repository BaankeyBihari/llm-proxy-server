"""Behavioral tests for scripts/launch.sh --env=aws and scripts/aws-destroy.sh.

Same PATH-shimmed fake-bin + stdin-feeding technique as test_local_launch.py
(fake `terraform` instead of `docker`). See aws-infra-design.md and
project-config-design.md (project.toml, render_config.py).
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_SCRIPT = REPO_ROOT / "scripts" / "launch.sh"
DESTROY_SCRIPT = REPO_ROOT / "scripts" / "aws-destroy.sh"

EXAMPLE_TOML = (
    "[config]\n"
    "embedding_similarity_threshold = 0.85\n"
    "\n"
    "[secrets]\n"
    'openrouter_api_key = "your_openrouter_key_here"\n'
    'litellm_master_key = "sk-master-key-1234"\n'
    'postgres_password = "changeme"\n'
    'tailscale_auth_key = "tskey-auth-REPLACE_ME"\n'
)


def _run(script, tmp_path, bin_dir, stdin_text="", args=()):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=tmp_path,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_launch(tmp_path, bin_dir, stdin_text=""):
    return _run(LAUNCH_SCRIPT, tmp_path, bin_dir, stdin_text, args=("--env=aws",))


def _write_example(tmp_path):
    (tmp_path / "project.toml.example").write_text(EXAMPLE_TOML)


# --- launch.sh --env=aws ---------------------------------------------------


# @spec INFRA-022
def test_launch_copies_project_toml_example_when_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_example(tmp_path)

    result = _run_launch(tmp_path, bin_dir, "\n")  # keep the one owned key

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "project.toml").read_text() == EXAMPLE_TOML


# @spec INFRA-022
def test_launch_only_prompts_owned_keys_not_openrouter_or_litellm(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_example(tmp_path)

    result = _run_launch(tmp_path, bin_dir, "\n")

    assert result.returncode == 0, result.stderr
    assert "openrouter_api_key" not in result.stdout
    assert "litellm_master_key" not in result.stdout


# @spec INFRA-022
def test_launch_prompt_shows_current_value_and_replaces_it(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_example(tmp_path)
    (tmp_path / "project.toml").write_text(
        EXAMPLE_TOML.replace("tskey-auth-REPLACE_ME", "old-key")
    )

    result = _run_launch(tmp_path, bin_dir, "new-key\n")  # replace

    assert result.returncode == 0, result.stderr
    assert "tailscale_auth_key" in result.stdout
    assert "old-key" in result.stdout
    assert 'tailscale_auth_key = "new-key"' in (tmp_path / "project.toml").read_text()


# @spec INFRA-029
def test_launch_renders_tfvars_json_before_terraform(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_example(tmp_path)

    result = _run_launch(tmp_path, bin_dir, "\n")

    assert result.returncode == 0, result.stderr
    import json

    tfvars = json.loads(
        (tmp_path / "infra" / "generated.auto.tfvars.json").read_text()
    )
    assert tfvars["tailscale_auth_key"] == "tskey-auth-REPLACE_ME"


# @spec INFRA-023
def test_launch_runs_terraform_init_then_apply_without_var_file_or_auto_approve(
    tmp_path, fake_bin, call_log
):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    _write_example(tmp_path)

    result = _run_launch(tmp_path, bin_dir, "\n")

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "-chdir=infra init" in calls
    assert "-chdir=infra apply" in calls
    assert "-var-file" not in calls
    assert "-auto-approve" not in calls
    assert calls.index("init") < calls.index("apply")


# --- aws-destroy.sh -------------------------------------------------------


# @spec INFRA-024
def test_destroy_runs_terraform_destroy_without_var_file_or_auto_approve(
    tmp_path, fake_bin, call_log
):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')
    (tmp_path / "project.toml").write_text(EXAMPLE_TOML)

    result = _run(DESTROY_SCRIPT, tmp_path, bin_dir)

    assert result.returncode == 0, result.stderr
    calls = call_log.read_text()
    assert "-chdir=infra destroy" in calls
    assert "-var-file" not in calls
    assert "-auto-approve" not in calls


# @spec INFRA-024
def test_destroy_errors_when_project_toml_missing(tmp_path, fake_bin, call_log):
    bin_dir, add = fake_bin
    add("terraform", f'echo "terraform $*" >> {call_log}')

    result = _run(DESTROY_SCRIPT, tmp_path, bin_dir)

    assert result.returncode != 0
    assert not call_log.exists() or call_log.read_text() == ""
