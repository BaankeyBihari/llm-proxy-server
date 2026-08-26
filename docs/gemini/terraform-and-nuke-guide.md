# Infrastructure as Code: LiteLLM Weekend Warrior

This guide contains the Terraform configuration to automatically deploy your entire AWS backend: the `t4g.small` EC2 instance, the Elastic IP, the strict IAM roles, and the Lambda "Ignition Switch" with its Function URL.

---

## 1. The Terraform File (`main.tf`)

Create a new folder on your local computer, open your terminal in that folder, and create a file named `main.tf`. Paste the following code into it.

> [!NOTE]
> You only need this one file. Terraform will dynamically generate the Python code for the Lambda function and zip it up for you during deployment.

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1" # Change if you prefer another region
}

# ------------------------------------------------------------------------------
# 1. EC2 Instance (t4g.small - ARM64)
# ------------------------------------------------------------------------------

# Fetch the latest Ubuntu 24.04 ARM64 AMI
data "aws_ami" "ubuntu_arm" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

# Security Group: Allow all outbound, block all inbound (Tailscale handles access)
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

resource "aws_instance" "litellm_server" {
  ami           = data.aws_ami.ubuntu_arm.id
  instance_type = "t4g.small"
  
  vpc_security_group_ids = [aws_security_group.litellm_sg.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  # Tell Terraform to ignore if the Lambda function changes the instance size
  lifecycle {
    ignore_changes = [instance_type]
  }

  user_data = <<-EOF
              #!/bin/bash
              # Setup 2GB Swap Space
              fallocate -l 2G /swapfile
              chmod 600 /swapfile
              mkswap /swapfile
              swapon /swapfile
              echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab

              # Install Docker & Tailscale
              apt-get update
              apt-get install -y docker.io docker-compose-v2 git
              curl -fsSL https://tailscale.com/install.sh | sh
              
              # NOTE: You will still need to SSH/Console in once to run `tailscale up`
              EOF

  tags = {
    Name = "LiteLLM-Weekend-Warrior"
  }
}

# ------------------------------------------------------------------------------
# 2. The Single Elastic IP
# ------------------------------------------------------------------------------

resource "aws_eip" "litellm_ip" {
  instance = aws_instance.litellm_server.id
  domain   = "vpc"
}

# ------------------------------------------------------------------------------
# 3. Lambda "Ignition Switch" Automation
# ------------------------------------------------------------------------------

# Inject the Python code directly into a zip file for the Lambda
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "lambda_ignition.zip"
  
  source {
    filename = "lambda_function.py"
    content  = <<-EOF
import boto3
import os

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='${var.aws_region_placeholder}')
    instance_id = os.environ['INSTANCE_ID']
    
    query_params = event.get('queryStringParameters', {}) or {}
    target_size = query_params.get('size', 'small')
    
    if target_size not in ['small', 'medium']:
        return {"statusCode": 400, "body": "Error: size must be 'small' or 'medium'"}
    
    target_instance_type = f"t4g.{target_size}"

    try:
        ec2.modify_instance_attribute(InstanceId=instance_id, InstanceType={'Value': target_instance_type})
        scale_msg = f"Scaled to {target_instance_type}. "
    except Exception as e:
        scale_msg = f"Size unchanged (already running). "

    ec2.start_instances(InstanceIds=[instance_id])
    
    return {"statusCode": 200, "body": f"LiteLLM Booting! {scale_msg}"}
EOF
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "litellm_ignition_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# IAM Policy allowing Lambda to only start/modify THIS specific instance
resource "aws_iam_role_policy" "lambda_policy" {
  name = "litellm_ignition_policy"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ec2:StartInstances",
        "ec2:ModifyInstanceAttribute"
      ]
      Resource = aws_instance.litellm_server.arn
    }]
  })
}

resource "aws_lambda_function" "ignition_switch" {
  filename      = data.archive_file.lambda_zip.output_path
  function_name = "litellm_ignition_switch"
  role          = aws_iam_role.lambda_role.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"

  environment {
    variables = {
      INSTANCE_ID = aws_instance.litellm_server.id
    }
  }
}

# Create the public Function URL
resource "aws_lambda_function_url" "ignition_url" {
  function_name      = aws_lambda_function.ignition_switch.function_name
  authorization_type = "NONE"
}

# ------------------------------------------------------------------------------
# Outputs (Printed to your terminal after deployment)
# ------------------------------------------------------------------------------

output "ec2_public_ip" {
  value = aws_eip.litellm_ip.public_ip
}

output "ignition_switch_url" {
  value = aws_lambda_function_url.ignition_url.function_url
}
```

---

## 2. How to Deploy (Build)

1. Open your terminal in the folder containing `main.tf`.
2. Ensure you have the AWS CLI installed and configured (`aws configure` with your Access Keys).
3. Run `terraform init` — downloads the AWS provider plugins.
4. Run `terraform apply` — shows you exactly what it will create.
5. Type `yes` and hit Enter.

In about **60 seconds**, Terraform will print your EC2 Public IP and your Lambda Ignition Switch URL to the terminal.

---

## 3. How to Nuke the Setup (Tear Down)

Because you used Terraform, you do **not** need to manually click through the AWS console to find your Elastic IP, Security Group, IAM Roles, Lambda functions, and EC2 instances.

Terraform tracks everything it built in a local `terraform.tfstate` file.

### Option A — Native Nuke (Recommended)

When you are done with the project or want to stop paying the **$3.65/mo** Elastic IP fee, open your terminal in the same folder and run:

```bash
terraform destroy
```

Terraform will list every resource (EC2, IP, IAM Role, Lambda) and ask for confirmation. Type `yes`. In less than **two minutes**, your AWS account is perfectly clean and your bill drops to **$0.00**.

### Option B — Nuclear Option (`cloud-nuke`)

> [!WARNING]
> Use this only if you have **lost your local `terraform.tfstate` file**. `cloud-nuke` has no memory of what Terraform created — it will nuke anything it finds in the target region.

If you accidentally delete your local Terraform folder and lose the `terraform.tfstate` file, Terraform will forget what it built. Fall back to Gruntwork's open-source `cloud-nuke` tool.

**Steps:**

1. Install the tool:
   - **macOS:** `brew install cloud-nuke`
   - **Windows:** `winget install cloud-nuke`

2. Run a dry-run inspection first:
   ```bash
   cloud-nuke inspect-aws --region us-east-1
   ```

3. Execute the wipe:
   ```bash
   cloud-nuke aws --region us-east-1
   ```

4. Type `nuke` to confirm.

> [!TIP]
> Always prefer `terraform destroy`. `cloud-nuke` is your safety net only when local state files are lost.