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
