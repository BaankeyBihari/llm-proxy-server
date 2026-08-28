# AWS Infra — EARS Specs

## EC2 + Networking

- [x] **INFRA-001**: The Terraform config shall declare exactly one `aws_instance` resource with `instance_type` set to `t4g.small`.
- [x] **INFRA-002**: The EC2 security group shall declare zero ingress rules.
- [x] **INFRA-003**: The EC2 security group shall allow all egress traffic.
- [x] **INFRA-004**: The `aws_instance` resource's `lifecycle` block shall ignore changes to `instance_type`.
- [x] **INFRA-005**: The EC2 `user_data` shall install Docker and Tailscale during initial boot.
- [x] **INFRA-015**: The EC2 `user_data` shall authenticate Tailscale with `tailscale up`, passing `var.tailscale_auth_key` as `--authkey` and pinning `--statedir` to `/home/ubuntu/tailscale-state`.
- [x] **INFRA-016**: The `tailscale_auth_key` variable shall be marked `sensitive`.
- [x] **INFRA-017**: The EC2 instance shall require IMDSv2 tokens (`metadata_options.http_tokens = "required"`).

## Remote Access

- [x] **INFRA-006**: The EC2 instance shall have an IAM instance profile granting `AmazonSSMManagedInstanceCore`, enabling Session Manager access with the security group's zero ingress rules.
- [x] **INFRA-007**: The EC2 `user_data` shall enable the SSM agent during initial boot.

## Elastic IP

- [x] **INFRA-008**: The Terraform config shall declare exactly one `aws_eip` resource associated with the EC2 instance.

## IAM (Lambda)

- [x] **INFRA-009**: The IAM policy attached to the Lambda's role shall scope its `Resource` to the EC2 instance's ARN, not a wildcard.
- [x] **INFRA-010**: The IAM policy shall grant only `ec2:StartInstances` and `ec2:ModifyInstanceAttribute`, and no other actions.

## Lambda

- [x] **INFRA-011**: The Lambda function resource shall deploy the zipped `ignition/handler.py` file, not an inline source block.
- [x] **INFRA-012**: The Lambda's `environment.variables` shall not set `AWS_REGION`.
- [x] **INFRA-013**: The Lambda Function URL resource shall set `authorization_type` to `NONE`.

## Outputs

- [x] **INFRA-014**: The Terraform config shall output the EC2 instance's public IP and the Lambda Function URL.

## Secrets (`secrets_mode`)

- [x] **INFRA-018**: The `secrets_mode` variable shall default to `"project_toml"` and its `validation` block shall reject any value other than `"bitwarden"` or `"project_toml"`.
- [x] **INFRA-019**: The `bws_access_token` variable shall be marked `sensitive` and default to an empty string.
- [x] **INFRA-020**: While `secrets_mode` is `"bitwarden"`, the EC2 `user_data` shall install the `bws` CLI and run `bws secret list --output env`, authenticated with `var.bws_access_token`.
- [x] **INFRA-021**: The `user_data`'s Bitwarden secrets fetch shall write its output to `/home/ubuntu/.env`, not into a repository path.

## Local Terraform Wrapper Scripts

- [x] **INFRA-022**: `scripts/aws-launch.sh` shall use the shared prompt loop (`CONF-009`) scoped to `[config].secrets_mode` and `[secrets].tailscale_auth_key`/`bws_access_token` in `project.toml` (seeded from `project.toml.example` if missing).
- [x] **INFRA-029**: `scripts/aws-launch.sh` shall run `scripts/render_config.py` to produce `infra/generated.auto.tfvars.json` before running Terraform.
- [x] **INFRA-023**: `scripts/aws-launch.sh` shall run `terraform -chdir=infra init` followed by `terraform -chdir=infra apply`, without `-var-file` and without `-auto-approve`.
- [x] **INFRA-024**: `scripts/aws-destroy.sh` shall run `terraform -chdir=infra destroy`, without `-var-file` and without `-auto-approve`, and shall exit non-zero with an error message if `project.toml` does not exist.

## Bitwarden Vault Check Script

- [x] **INFRA-025**: `scripts/bws-secrets-check.sh` shall run `bws secret list --output json` with no project ID argument and no `--access-token` flag, relying on `BWS_ACCESS_TOKEN` from the environment.
- [x] **INFRA-026**: For each secret returned, the script shall print that secret's key and current value in plaintext, then prompt for a replacement value.
- [x] **INFRA-027**: An empty response to the prompt shall leave that secret unchanged; a non-empty response shall call `bws secret edit --value "<new_value>" <secret_id>` for that secret's ID.
- [x] **INFRA-028**: The script shall use `set -euo pipefail` and shall not add its own handling for a missing `BWS_ACCESS_TOKEN`, a missing `bws` CLI, an empty secret list, or a failing `bws` command — these shall propagate as `bws`'s and bash's own errors.
