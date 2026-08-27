# Infrastructure as Code: LiteLLM Weekend Warrior

This guide contains the Terraform configuration to automatically deploy your entire AWS backend: the `t4g.small` EC2 instance, the Elastic IP, the strict IAM roles, and the Lambda "Ignition Switch" with its Function URL.

With the latest updates, this script is **100% zero-touch**. It will automatically install Docker, authenticate your secure Tailscale tunnel, clone your GitHub repository, fetch secrets from **Bitwarden Secrets Manager**, and start your LiteLLM stack the very first time it boots.

---

## 1. The Terraform File (`main.tf`) — Complete Script

Create a new folder on your local computer, open your terminal in that folder, and create a file named `main.tf`. Paste the following code into it.

> [!NOTE]
> You only need this one file. Terraform dynamically generates the Lambda Python code, packages it, and interpolates all secrets into the boot script. Supports two secrets modes: **Bitwarden** (fully automated) or **env_file** (manual transfer via Tailscale).

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
  region = "us-east-1" # Change this if you prefer a different region
}

# --- Variables ---

variable "tailscale_auth_key" {
  description = "Pre-auth key from your Tailscale dashboard"
  type        = string
  sensitive   = true
}

variable "git_repo_url" {
  description = "HTTPS URL to your Git repository (include PAT if private)"
  type        = string
}

variable "secrets_mode" {
  description = "Set to 'bitwarden' to fetch secrets via BWS, or 'env_file' to use a manual file"
  type        = string
  default     = "bitwarden"
}

variable "bws_access_token" {
  description = "Bitwarden Secrets Machine Access Token (required when secrets_mode = 'bitwarden')"
  type        = string
  sensitive   = true
  default     = ""
}

# --- Infrastructure ---

# Ubuntu 22.04 LTS ARM64 AMI (Jammy)
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }
}

# Security Group: block all inbound, allow all outbound (Tailscale handles access)
resource "aws_security_group" "litellm_sg" {
  name        = "litellm-tailscale-sg"
  description = "Blocks all inbound internet traffic. Outbound only."

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "litellm_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t4g.small" # Base size. Can scale to t4g.medium via Lambda.

  vpc_security_group_ids = [aws_security_group.litellm_sg.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  # Ignore Lambda-driven instance type changes on subsequent applies
  lifecycle {
    ignore_changes = [instance_type]
  }

  # Fully automated Tailscale connection, repo clone & Docker boot!
  user_data = <<-EOF
    #!/bin/bash
    exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

    # 1. Safety Swap File
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

    # 2. Install Dependencies (Docker, Git, Tailscale)
    curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh
    curl -fsSL https://tailscale.com/install.sh | sh

    # 3. Connect to Tailscale (Zero-config VPN)
    tailscale up --authkey="${var.tailscale_auth_key}" --hostname="cloud-litellm"

    # 4. Clone Repository
    mkdir -p /home/ubuntu/repo
    cd /home/ubuntu/repo
    git clone ${var.git_repo_url} .
    chown -R ubuntu:ubuntu /home/ubuntu/repo

    # 5. Handle Secrets
    if [ "${var.secrets_mode}" == "bitwarden" ]; then
        echo "Running in Bitwarden mode..."
        curl -LO https://github.com/bitwarden/sdk-sm/releases/download/bws-v0.3.1/bws-aarch64-unknown-linux-gnu-0.3.1.zip
        apt-get install -y unzip
        unzip bws-*.zip && chmod +x bws && mv bws /usr/local/bin/
        BWS_ACCESS_TOKEN="${var.bws_access_token}" bws secret list --output env > .env
    else
        echo "Running in env_file mode. Waiting for manual .env sync over Tailscale..."
    fi

    # 6. Start Docker Stack
    if [ -f "docker-compose.yml" ]; then
        docker compose up -d
    fi
  EOF

  tags = { Name = "LiteLLM-Proxy" }
}

# The single allowed Elastic IP
resource "aws_eip" "litellm_ip" {
  instance = aws_instance.litellm_server.id
  domain   = "vpc"
}

# --- Lambda Ignition Switch ---

resource "local_file" "lambda_source" {
  filename = "${path.module}/lambda_function.py"
  content  = <<-EOF
import boto3
import os

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-east-1')
    instance_id = os.environ['INSTANCE_ID']

    ALLOWED_SIZES = ['small', 'medium']

    query_params = event.get('queryStringParameters', {}) or {}
    target_size = query_params.get('size', 'small')

    if target_size not in ALLOWED_SIZES:
        return {"statusCode": 400, "body": f"Error: Invalid size. Allowed: {ALLOWED_SIZES}"}

    target_type = f"t4g.{target_size}"

    # Modify size (fails safely if instance is already running)
    try:
        ec2.modify_instance_attribute(InstanceId=instance_id, InstanceType={'Value': target_type})
    except Exception:
        pass

    ec2.start_instances(InstanceIds=[instance_id])
    return {"statusCode": 200, "body": f"LiteLLM Server Booting Up as {target_type}!"}
EOF
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = local_file.lambda_source.filename
  output_path = "${path.module}/lambda.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name = "litellm_lambda_exec_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_ec2_policy" {
  name = "litellm_lambda_ec2_policy"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = ["ec2:StartInstances", "ec2:ModifyInstanceAttribute"]
      Effect   = "Allow"
      Resource = aws_instance.litellm_server.arn
    }]
  })
}

resource "aws_lambda_function" "ignition_switch" {
  function_name    = "StartLiteLLM"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"

  environment {
    variables = { INSTANCE_ID = aws_instance.litellm_server.id }
  }
}

resource "aws_lambda_function_url" "ignition_url" {
  function_name      = aws_lambda_function.ignition_switch.function_name
  authorization_type = "NONE"
}

# --- Outputs ---

output "ec2_elastic_ip"      { value = aws_eip.litellm_ip.public_ip }
output "ignition_switch_url" { value = aws_lambda_function_url.ignition_url.function_url }
output "instance_id"         { value = aws_instance.litellm_server.id }
```

---

## 2. How to Deploy (Build)

1. Open your terminal in the folder containing `main.tf`.
2. Ensure you have the **AWS CLI** installed and configured (`aws configure` with your Access Keys).
3. Generate a one-off **Reusable Auth Key** from your Tailscale Admin Dashboard (`Settings > Keys > Generate auth key`).
4. *(Recommended)* Set up **Bitwarden Secrets Manager** and obtain a Machine Access Token — see [`bitwarden.md`](./bitwarden.md) for the full setup guide.
5. Run `terraform init` — downloads the AWS and `local` provider plugins.
6. Run `terraform apply`. Terraform will prompt you for **up to four values**:
   - **`tailscale_auth_key`** *(required)*: Your Tailscale pre-auth key.
   - **`git_repo_url`** *(required)*: HTTPS clone URL of your repo (include a PAT for private repos).
   - **`secrets_mode`** *(optional, default `bitwarden`)*: Set to `env_file` to skip Bitwarden and manage `.env` manually.
   - **`bws_access_token`** *(required if `secrets_mode = bitwarden`)*: Your Bitwarden Secrets Machine Token.
7. Type `yes` and hit Enter.

In about **60 seconds**, Terraform will print your Elastic IP and Lambda Ignition Switch URL. The instance will boot, connect to Tailscale, clone your repo, fetch secrets, and start your Docker stack — fully automatically.

> [!IMPORTANT]
> **`env_file` mode only:** If you chose `secrets_mode = env_file`, the server starts without secrets. You must push your `.env` file manually over Tailscale before the stack will run:
> ```bash
> scp .env ubuntu@cloud-litellm:~/repo/.env
> ssh ubuntu@cloud-litellm 'cd ~/repo && docker compose up -d'
> ```

---

## 3. How to Nuke the Setup (Tear Down)

Because you used Terraform, you do **not** need to manually click through the AWS console to find your Elastic IP, Security Group, IAM Roles, Lambda functions, and EC2 instances.

Terraform tracks everything it built in a local `terraform.tfstate` file.

### Option A — Native Nuke (Recommended)

When you are done with the project or want to stop paying the **~$3.65/mo** Elastic IP fee, open your terminal in the same folder and run:

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

---

## 4. Local Automation Scripts

To make managing your stack seamless from your local terminal, create these three helper scripts in the **same folder** as your `main.tf`.

First, make them all executable:

```bash
chmod +x aws-launch.sh aws-stop.sh aws-destroy.sh
```

### `aws-launch.sh` — Deploy or Update Stack

Creates the infrastructure if it doesn't exist, or applies any changes you made to `main.tf`.

```bash
#!/bin/bash
echo "🚀 Deploying LiteLLM Stack..."
terraform init
terraform apply -auto-approve
echo "✅ Deployment complete! Check the output above for your Ignition URL."
```

### `aws-stop.sh` — Pause Compute Billing

Stops the EC2 instance instantly from your terminal **without destroying** the stack. Useful for pausing overnight to save on compute costs while keeping your Elastic IP.

```bash
#!/bin/bash
echo "🛑 Stopping the LiteLLM Server..."

# Extract Instance ID directly from Terraform state
INSTANCE_ID=$(terraform output -raw instance_id 2>/dev/null)

if [ -z "$INSTANCE_ID" ] || [[ "$INSTANCE_ID" == *"No outputs"* ]]; then
    echo "⚠️  Instance ID not found in Terraform state. Is the stack deployed?"
else
    aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region us-east-1
    echo "✅ Instance $INSTANCE_ID stopped successfully."
fi
```

### `aws-destroy.sh` — Complete Teardown

Destroys the **entire stack** — EC2 instance, Elastic IP, IAM roles, and Lambda — returning AWS costs to **$0.00**.

```bash
#!/bin/bash
echo "🔥 Destroying the entire LiteLLM Stack..."
terraform destroy -auto-approve
echo "✅ Stack completely destroyed. Billing stopped."
```

> [!WARNING]
> `aws-destroy.sh` uses `-auto-approve` and will **not** prompt for confirmation. Only run this when you are certain you want to tear everything down.
