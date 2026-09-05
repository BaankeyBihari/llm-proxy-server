# Provisions the AWS side of the llm-proxy-server gateway: the EC2 instance
# and Elastic IP `aws-deploy`'s boot/idle scripts run on, and the IAM role,
# Lambda function, and Function URL that expose `aws-ignition`'s
# request-handling logic (ignition/handler.py, packaged unmodified below).
#
# See docs/intent/aws-infra/aws-infra-design.md.
#
# @spec INFRA-001, INFRA-002, INFRA-003, INFRA-004, INFRA-005, INFRA-006,
# @spec INFRA-007, INFRA-008, INFRA-009, INFRA-010, INFRA-011, INFRA-012,
# @spec INFRA-013, INFRA-014, INFRA-015, INFRA-016, INFRA-017

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

variable "aws_region" {
  description = "AWS region to provision into."
  type        = string
  default     = "us-east-1"
}

variable "tailscale_auth_key" {
  description = "Tailscale reusable pre-auth key (Admin Panel > Settings > Keys). Used once, at first boot."
  type        = string
  sensitive   = true
}

provider "aws" {
  region = var.aws_region
}

# ------------------------------------------------------------------------------
# EC2 instance (t4g.medium, ARM64)
# ------------------------------------------------------------------------------

data "aws_ami" "ubuntu_arm" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

# Zero ingress rules: Tailscale is the only path in (see high-level-design.md
# tenets). Tailscale itself authenticates automatically at boot (authkey in
# user_data below); the one-time manual step that remains (git clone + secrets
# via ./scripts/launch.sh --env=local) goes over SSM Session Manager instead of SSH
# — see the IAM instance profile below.
resource "aws_security_group" "litellm_sg" {
  name        = "litellm_egress_only"
  description = "Allow all outbound traffic, rely on Tailscale for inbound"

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "ec2_role" {
  name = "litellm_ec2_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "litellm_ec2_profile"
  role = aws_iam_role.ec2_role.name
}

resource "aws_instance" "litellm_server" {
  ami                    = data.aws_ami.ubuntu_arm.id
  instance_type          = "t4g.medium"
  vpc_security_group_ids = [aws_security_group.litellm_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  # The ignition Lambda resizes this instance at runtime (modify_instance_attribute).
  # Without this, the next `terraform apply` would revert that resize.
  lifecycle {
    ignore_changes = [instance_type]
  }

  # user_data now embeds a Tailscale authkey (via var.tailscale_auth_key) —
  # require IMDSv2 so that secret can't be read off the instance metadata
  # service with a plain unauthenticated GET.
  metadata_options {
    http_tokens = "required"
  }

  user_data = <<-EOF
              #!/bin/bash
              set -e

              # 2GB swap
              fallocate -l 2G /swapfile
              chmod 600 /swapfile
              mkswap /swapfile
              swapon /swapfile
              echo '/swapfile none swap sw 0 0' >> /etc/fstab

              # Docker + Tailscale
              apt-get update
              apt-get install -y docker.io docker-compose-v2 git
              curl -fsSL https://tailscale.com/install.sh | sh

              # Authenticate instantly — statedir pinned to the persistent EBS
              # root volume for consistency with the Jarvis Labs target, same
              # rationale as docs/intent/aws-deploy/aws-deploy-design.md.
              tailscale up --authkey=${var.tailscale_auth_key} --statedir=/home/ubuntu/tailscale-state --hostname=cloud-litellm

              # SSM agent, so the remaining manual step (git clone, then
              # ./scripts/bws-sync.sh + ./scripts/launch.sh --env=local) can
              # run over Session Manager instead of SSH (security group has
              # no ingress).
              snap install amazon-ssm-agent --classic
              systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service
              systemctl start snap.amazon-ssm-agent.amazon-ssm-agent.service
              EOF

  tags = {
    Name = "LiteLLM-Weekend-Warrior"
  }
}

# ------------------------------------------------------------------------------
# Elastic IP
# ------------------------------------------------------------------------------

resource "aws_eip" "litellm_ip" {
  instance = aws_instance.litellm_server.id
  domain   = "vpc"
}

# ------------------------------------------------------------------------------
# Ignition Lambda
# ------------------------------------------------------------------------------

# Packages the repo's own tested ignition/handler.py — not a duplicate inline
# copy — so the deployed Lambda always matches tests/test_ignition_handler.py.
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../ignition/handler.py"
  output_path = "${path.module}/lambda_ignition.zip"
}

resource "aws_iam_role" "lambda_role" {
  name = "litellm_ignition_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Least-privilege: exactly the two actions the handler needs, scoped to
# exactly this instance's ARN — never "*".
resource "aws_iam_role_policy" "lambda_policy" {
  name = "litellm_ignition_policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ec2:StartInstances",
        "ec2:ModifyInstanceAttribute",
      ]
      Resource = aws_instance.litellm_server.arn
    }]
  })
}

resource "aws_lambda_function" "ignition_switch" {
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  function_name    = "litellm_ignition_switch"
  role             = aws_iam_role.lambda_role.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"

  # Only INSTANCE_ID is set here — the region env var is deliberately absent:
  # it's a Lambda-reserved key that Lambda's runtime populates automatically,
  # and handler.py already reads it via os.environ.get("AWS_REGION", ...).
  environment {
    variables = {
      INSTANCE_ID = aws_instance.litellm_server.id
    }
  }
}

# Unauthenticated: the switch must be callable before any Tailscale path to
# the host exists. The IAM policy above (one instance, two actions) is the
# actual safety boundary, not endpoint auth.
resource "aws_lambda_function_url" "ignition_url" {
  function_name      = aws_lambda_function.ignition_switch.function_name
  authorization_type = "NONE"
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "ec2_public_ip" {
  value = aws_eip.litellm_ip.public_ip
}

output "ignition_switch_url" {
  value = aws_lambda_function_url.ignition_url.function_url
}
