"""Structural tests for infra/main.tf.

These assert what the checked-in Terraform config *declares* (resource
attributes, IAM scoping, lambda packaging) via scoped regex/substring checks
against the raw HCL text — no `terraform` CLI, no AWS calls. See
docs/intent/aws-infra/aws-infra-design.md for why plain-text scoped regex was
chosen over a parser library.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INFRA_TF = REPO_ROOT / "infra" / "main.tf"


@pytest.fixture
def tf_text():
    return INFRA_TF.read_text()


def _block(text, header_pattern):
    """Return a `{ ... }` block (braces included), brace-matched, whose
    opening line matches header_pattern."""
    match = header_pattern.search(text)
    assert match, f"no block found for {header_pattern.pattern!r}"
    start = match.end() - 1  # index of the opening "{" the pattern matched
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError("unbalanced braces")


def _instance_block(text):
    return _block(text, re.compile(r'resource\s+"aws_instance"\s+"litellm_server"\s*\{'))


# @spec INFRA-001
def test_ec2_instance_is_t4g_medium(tf_text):
    assert re.search(r'instance_type\s*=\s*"t4g\.medium"', _instance_block(tf_text))


# @spec INFRA-002
def test_security_group_has_no_ingress(tf_text):
    block = _block(tf_text, re.compile(r'resource\s+"aws_security_group"\s+"litellm_sg"\s*\{'))
    assert "ingress" not in block


# @spec INFRA-003
def test_security_group_allows_all_egress(tf_text):
    sg = _block(tf_text, re.compile(r'resource\s+"aws_security_group"\s+"litellm_sg"\s*\{'))
    egress = _block(sg, re.compile(r"egress\s*\{"))
    assert re.search(r'protocol\s*=\s*"-1"', egress)
    assert re.search(r'cidr_blocks\s*=\s*\["0\.0\.0\.0/0"\]', egress)


# @spec INFRA-004
def test_instance_type_changes_are_ignored(tf_text):
    lifecycle = _block(_instance_block(tf_text), re.compile(r"lifecycle\s*\{"))
    assert "instance_type" in lifecycle


# @spec INFRA-005
def test_user_data_installs_docker_and_tailscale(tf_text):
    block = _instance_block(tf_text)
    assert "docker" in block
    assert "tailscale.com/install.sh" in block


# @spec INFRA-015
def test_user_data_authenticates_tailscale_with_pinned_statedir(tf_text):
    block = _instance_block(tf_text)
    assert re.search(
        r"tailscale up[^\n]*--authkey=\$\{var\.tailscale_auth_key\}", block
    )
    assert "--statedir=/home/ubuntu/tailscale-state" in block


# @spec INFRA-016
def test_tailscale_auth_key_variable_is_sensitive(tf_text):
    var_block = _block(tf_text, re.compile(r'variable\s+"tailscale_auth_key"\s*\{'))
    assert re.search(r"sensitive\s*=\s*true", var_block)


# @spec INFRA-017
def test_instance_requires_imdsv2(tf_text):
    metadata = _block(_instance_block(tf_text), re.compile(r"metadata_options\s*\{"))
    assert re.search(r'http_tokens\s*=\s*"required"', metadata)


# @spec INFRA-006
def test_instance_has_ssm_instance_profile(tf_text):
    assert re.search(
        r'resource\s+"aws_iam_role_policy_attachment"\s+"\w+"\s*\{[^}]*AmazonSSMManagedInstanceCore',
        tf_text,
        re.S,
    )
    assert "iam_instance_profile" in _instance_block(tf_text)


# @spec INFRA-007
def test_user_data_enables_ssm_agent(tf_text):
    assert "amazon-ssm-agent" in _instance_block(tf_text)


# @spec INFRA-008
def test_exactly_one_eip_attached_to_instance(tf_text):
    eip_headers = re.findall(r'resource\s+"aws_eip"\s+"\w+"\s*\{', tf_text)
    assert len(eip_headers) == 1
    eip = _block(tf_text, re.compile(r'resource\s+"aws_eip"\s+"\w+"\s*\{'))
    assert "aws_instance.litellm_server.id" in eip


# @spec INFRA-009
def test_iam_policy_scoped_to_instance_arn(tf_text):
    policy = _block(tf_text, re.compile(r'resource\s+"aws_iam_role_policy"\s+"lambda_policy"\s*\{'))
    assert "aws_instance.litellm_server.arn" in policy
    assert '"*"' not in policy


# @spec INFRA-010
def test_iam_policy_grants_only_start_and_modify(tf_text):
    policy = _block(tf_text, re.compile(r'resource\s+"aws_iam_role_policy"\s+"lambda_policy"\s*\{'))
    actions = re.search(r"Action\s*=\s*\[(.*?)\]", policy, re.S).group(1)
    granted = re.findall(r'"(ec2:\w+)"', actions)
    assert set(granted) == {"ec2:StartInstances", "ec2:ModifyInstanceAttribute"}


# @spec INFRA-011
def test_lambda_deploys_zipped_handler_file_not_inline_source(tf_text):
    archive = _block(tf_text, re.compile(r'data\s+"archive_file"\s+"\w+"\s*\{'))
    assert "ignition/handler.py" in archive
    assert "def lambda_handler" not in archive


# @spec INFRA-012
def test_lambda_env_does_not_set_aws_region(tf_text):
    lambda_fn = _block(tf_text, re.compile(r'resource\s+"aws_lambda_function"\s+"\w+"\s*\{'))
    env = _block(lambda_fn, re.compile(r"environment\s*\{"))
    assert "AWS_REGION" not in env


# @spec INFRA-013
def test_function_url_is_unauthenticated(tf_text):
    url = _block(tf_text, re.compile(r'resource\s+"aws_lambda_function_url"\s+"\w+"\s*\{'))
    assert re.search(r'authorization_type\s*=\s*"NONE"', url)


# @spec INFRA-014
def test_outputs_ip_and_function_url(tf_text):
    assert re.search(r'output\s+"\w+"\s*\{[^}]*aws_eip\.\w+\.public_ip', tf_text, re.S)
    assert re.search(r'output\s+"\w+"\s*\{[^}]*function_url', tf_text, re.S)


# Regression guard: the cloud-side Bitwarden self-fetch (secrets_mode) was
# retired in favor of scripts/bws-sync.sh — see aws-infra-design.md.
def test_user_data_has_no_bitwarden_branch(tf_text):
    block = _instance_block(tf_text)
    assert "bws secret list" not in block
    assert "BWS_ACCESS_TOKEN" not in block
    assert "secrets_mode" not in block
    assert "variable \"secrets_mode\"" not in tf_text
    assert "variable \"bws_access_token\"" not in tf_text
