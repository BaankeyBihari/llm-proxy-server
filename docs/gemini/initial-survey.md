# End-to-End Master Guide: LiteLLM + Headroom Gateway

This document provides the complete, end-to-end instructions for building, testing, and deploying a private LiteLLM gateway. It covers two deployment targets:

- **Jarvis Labs** — a GPU cloud optimized for a "Weekend Warrior" usage pattern where the server is paused during the week.
- **AWS EC2** — an On-Demand architecture with an automated 4-hour idle shutdown, a custom Lambda "Ignition Switch" for on-demand scaling, and a strict Single IPv4 footprint to minimize costs.

Both deployments leverage Tailscale for instant, secure connectivity without the overhead of public domains or SSL certificates, Redis for persistent semantic caching, and route all traffic exclusively through OpenRouter.

---

## 1. Architecture Overview

```
[ Your Laptops (Mac/Windows with Tailscale) ]
                 |
   (Encrypted WireGuard Tunnel via MagicDNS/IP)
                 |
[ Jarvis Labs Pod  -OR-  AWS EC2 Instance (Tailscale Installed) ]
                 |
    [ LiteLLM Gateway :4000 ]
      /                    \
(Pre-Call Guardrail)   (Semantic Cache + Persistence)
    v                        v
[ Headroom :8787 ]     [ Redis :6379 (Volume Mounted) ]
    \                      /
     v                    v
  [ OpenRouter API (Upstream) ]
```

Key Components:

- **LiteLLM**: The central router handling authentication, OpenAI-compatible endpoint translation, and advanced token/header optimizations.
- **Headroom**: A sidecar service that intercepts and compresses long context and tool outputs before they hit OpenRouter.
- **Redis**: An in-memory store mounted to persistent storage with snapshotting enabled, ensuring instant semantic cache hits across pause/resume cycles.
- **Tailscale**: Provides a static internal IP (100.x.x.x) and end-to-end encryption, completely hiding your server from the public internet.

---

## 2. Core Configuration Files

These two files form the heart of your stack. They are used identically in both your local testing environment and either production environment.

### A. config.yaml

This file configures LiteLLM's routing rules, guardrails, and cost-saving cache optimizations.

```yaml
model_list:
  # 1. Smart Auto-Router (Best overall model)
  - model_name: smart-auto
    litellm_params:
      model: openrouter/openrouter/auto
      api_key: os.environ/OPENROUTER_API_KEY

  # 2. Lowest-Cost Auto-Router
  - model_name: cheapest-auto
    litellm_params:
      model: openrouter/openrouter/auto:floor
      api_key: os.environ/OPENROUTER_API_KEY

  # 3. High-Speed Auto-Router
  - model_name: fast-auto
    litellm_params:
      model: openrouter/openrouter/auto:nitro
      api_key: os.environ/OPENROUTER_API_KEY

  # 4. LiteLLM Resilient Fallback Chain
  - model_name: resilient-router
    litellm_params:
      model: openrouter/nousresearch/hermes-3-llama-3.1-405b
      api_key: os.environ/OPENROUTER_API_KEY
  - model_name: resilient-router
    litellm_params:
      model: openrouter/nvidia/llama-3.1-nemotron-70b-instruct
      api_key: os.environ/OPENROUTER_API_KEY

  # 5. Wildcard Passthrough (Access any OpenRouter model)
  - model_name: openrouter/*
    litellm_params:
      model: openrouter/*
      api_key: os.environ/OPENROUTER_API_KEY

guardrails:
  - guardrail_name: headroom-compression
    litellm_params:
      guardrail: headroom
      mode: pre_call
      api_base: http://headroom:8787
      default_on: true

litellm_settings:
  cache: true
  cache_params:
    type: redis
    host: os.environ/REDIS_HOST
    port: 6379
    ttl: 604800 # 7-day TTL to survive the work week
  forward_client_headers_to_llm_api: true
  drop_params: true
```

### B. docker-compose.yml

This file defines the container stack, including persistent Redis volume mapping. The Redis service includes memory limits and an LRU eviction policy to protect instance memory over long cache lifespans.

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    container_name: litellm-redis
    restart: always
    # Save every 60s if 1 change. Limit memory to 1.5GB with LRU eviction.
    command: redis-server --save 60 1 --maxmemory 1536mb --maxmemory-policy allkeys-lru
    volumes:
      - ./redis-data:/data

  headroom:
    image: python:3.12-slim
    container_name: headroom-proxy
    restart: always
    command: >
      sh -c "pip install headroom-ai[proxy] && headroom proxy --host 0.0.0.0 --port 8787 --mode cache"
    environment:
      - HEADROOM_TELEMETRY=off
      - HEADROOM_COMPRESS_USER_MESSAGES=1

  litellm:
    image: ghcr.io/berriai/litellm:main-v1.92.0
    container_name: litellm-proxy
    restart: always
    ports:
      - "4000:4000"
    volumes:
      - ./config.yaml:/app/config.yaml
    environment:
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
      - REDIS_HOST=redis
    command: [ "--config", "/app/config.yaml", "--port", "4000" ]
    depends_on:
      - redis
      - headroom
```

### C. Repository Structure & .gitignore

Your Git repository acts as the single source of truth for both environments.

```
litellm-proxy/
├── .gitignore
├── docker-compose.yml
├── config.yaml
└── .env.example
```

Ensure local Redis snapshots and environment variables are excluded from version control:

```gitignore
# Ignore Redis persistent data
redis-data/

# Ignore Secrets
.env
```

---

## 3. Phase 1: Local Testing & Validation

Before deploying to the cloud, validate the stack on your local machine.

- **Install Prerequisites**: Docker Desktop and Tailscale.
- **Environment Setup**: Copy `.env.example` to `.env` and populate your API keys.
- **Start Services**: Run `docker compose up -d`.
- **Stop Services**: Run `docker compose down` when finished. (Your cache remains safely stored in the `redis-data` folder.)

### Validation Tests

**1. Test Passthrough Routing:**

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-master-key-1234" \
  -H "Content-Type: application/json" \
  -d '{"model": "openrouter/nousresearch/hermes-3-llama-3.1-405b", "messages": [{"role": "user", "content": "Ping."}]}'
```

**2. Test Cache Hit:**

Run the exact command above a second time. It should return in < 50ms. Check LiteLLM logs (`docker logs litellm-proxy`) to confirm the cache hit.

---

## 4. Phase 2: Production on Jarvis Labs

### The Jarvis Labs Startup Script

In your Jarvis Labs instance settings, paste the following into the Startup Script section to handle Tailscale persistence, Docker readiness, and repository pulling on boot:

```bash
#!/bin/bash
echo "Starting Jarvis Labs Boot Sequence..."

# 1. Ensure Tailscale state persists across pauses
mkdir -p /home/litellm-stack/tailscale-state
sudo tailscaled --statedir=/home/litellm-stack/tailscale-state &
sleep 3
sudo tailscale up --authkey=tskey-auth-YOUR_SECRET_KEY_HERE --hostname=jarvis-litellm --accept-routes

# 2. Setup/Update Workspace from GitHub
WORKSPACE="/home/litellm-stack"
if [ ! -d "$WORKSPACE/.git" ]; then
  git clone https://github.com/yourusername/your-litellm-repo.git $WORKSPACE
else
  cd $WORKSPACE
  git pull origin main
fi

# 3. Wait for Docker daemon
echo "Waiting for Docker daemon..."
until docker info > /dev/null 2>&1; do
    sleep 2
done

# 4. Inject Secrets & Launch Stack
cd $WORKSPACE
if [ ! -f .env ]; then
  echo "OPENROUTER_API_KEY=your_key_here" > .env
  echo "LITELLM_MASTER_KEY=sk-master-key-1234" > .env
fi

docker compose up -d --build
echo "Jarvis Labs sequence complete. Available at http://jarvis-litellm:4000"
```

---

## 5. Phase 3: Production on AWS EC2

This architecture uses an On-Demand EC2 instance with an automated idle shutdown, a Lambda-based ignition switch, and a Single IPv4 footprint.

### Host-Level Setup & The Single IPv4 Rule

Deploy an **Ubuntu 24.04 LTS** EC2 instance. **Crucial**: Choose either `ARM64` (`t4g` family) or `x86_64` (`t3` family) when selecting your AMI. Start with `t4g.small` (2 vCPU, 2GB RAM, ARM64). You can scale between `small` and `medium` later, but **you cannot cross over between `t3` and `t4g` on the same hard drive**.

**The Single IPv4 Constraint**: AWS charges $0.005/hr for every public IP. To limit this to exactly ~$3.65/month, go to the AWS EC2 Console, allocate exactly **one Elastic IP (EIP)**, and associate it with your instance. Never deploy load balancers, NAT gateways, or secondary IPs — Tailscale handles all internal mesh routing via this single public endpoint.

SSH into your new instance and configure:

```bash
# Create Swap Space (Safety Net)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

# Install Docker
sudo apt update && sudo apt install docker.io docker-compose-v2

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Authenticate Tailscale (--statedir prevents "ghost nodes" on reboot)
sudo tailscale up --hostname=cloud-litellm --statedir=/home/ubuntu/tailscale-state
```

Then generate an SSH Deploy Key (`ssh-keygen`), add the public key to your GitHub repo, and clone to `/home/ubuntu/litellm-proxy`.

### Startup Script (systemd / rc.local)

Create a script at `/home/ubuntu/start_stack.sh` to ensure the stack boots automatically when the Lambda ignition triggers a start:

```bash
#!/bin/bash
cd /home/ubuntu/litellm-proxy

# Wait for Docker to be ready
until docker info > /dev/null 2>&1; do
    sleep 2
done

# Pull latest changes and start
git pull origin main
docker compose up -d
```

Run it on boot using `@reboot /home/ubuntu/start_stack.sh` in the root crontab, or wrap it in a simple systemd service.

### The 4-Hour Idle Auto-Stop Script

Create a script at `/home/ubuntu/idle_check.sh`:

```bash
#!/bin/bash
# 1. Check if the server has even been online for 4 hours (14400 seconds)
UPTIME_SEC=$(awk '{print int($1)}' /proc/uptime)
if [ "$UPTIME_SEC" -lt 14400 ]; then
    exit 0
fi

# 2. Check LiteLLM logs for any API requests in the last 4 hours
REQUESTS=$(docker logs --since 4h litellm-proxy 2>&1 | grep -c "POST /")

# 3. If zero requests, shut down the OS (AWS translates this to EC2 "Stopped" state)
if [ "$REQUESTS" -eq 0 ]; then
    sudo poweroff
fi
```

Make it executable and schedule it:

```bash
chmod +x /home/ubuntu/idle_check.sh
sudo crontab -e
# Add: 0 * * * * /home/ubuntu/idle_check.sh
```

---

## 6. The Auto-Scaling "Ignition Switch" (AWS Lambda)

To start the EC2 server on-demand and scale its RAM based on your needs, deploy this Lambda function. It includes strict validation to ensure you only use `t3` or `t4g` in `small` or `medium` sizes.

**Setup Steps:**

1. Create an AWS Lambda function (Python 3.12).
2. Assign it an IAM Role with permissions for `ec2:StartInstances` and `ec2:ModifyInstanceAttribute`.
3. Enable a **Function URL** in the Lambda configuration.

**The Code:**

```python
import boto3
import os

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='us-east-1') # Update region
    instance_id = os.environ.get('INSTANCE_ID', 'i-0abcd1234efgh5678')

    # Strict Whitelist: Only allow t3 and t4g in small and medium sizes
    ALLOWED_TYPES = ['t4g.small', 't4g.medium', 't3.small', 't3.medium']

    # Check query parameters for requested size (default to t4g.small)
    query_params = event.get('queryStringParameters', {}) or {}
    target_size = query_params.get('size', 't4g.small')

    if target_size not in ALLOWED_TYPES:
        return {
            "statusCode": 400,
            "body": f"Error: Invalid size '{target_size}'. Allowed sizes: {', '.join(ALLOWED_TYPES)}"
        }

    # 1. Attempt to apply the instance size
    # (Will safely fail if instance is running, OR if you try to cross ARM/x86 architectures)
    try:
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            InstanceType={'Value': target_size}
        )
        scale_msg = f"Scaled to {target_size}. "
    except Exception as e:
        scale_msg = "Size unchanged (running or incompatible architecture). "

    # 2. Start the instance
    ec2.start_instances(InstanceIds=[instance_id])

    return {
        "statusCode": 200,
        "body": f"LiteLLM Ignition Sequence Engaged! {scale_msg} Booting..."
    }
```

**Usage:**

| Intent | URL |
|---|---|
| Normal Boot (default size) | `https://your-lambda-url.aws/` |
| Heavy Workload Boot (4GB RAM) | `https://your-lambda-url.aws/?size=t4g.medium` |

> **Note**: You can scale between `t4g.small` and `t4g.medium`, but if your base instance is `t4g` (ARM), passing `?size=t3.small` (x86) will be rejected by AWS.

---

## 7. Client Configuration

On your local IDE (e.g., Cursor, VS Code), ensure Tailscale is running and connected. Then set your environment variables to point to the appropriate Tailscale MagicDNS name:

**Jarvis Labs:**

```bash
export OPENAI_API_BASE="http://jarvis-litellm:4000/v1"
export OPENAI_API_KEY="sk-master-key-1234"
```

**AWS EC2:**

```bash
export OPENAI_API_BASE="http://cloud-litellm:4000/v1"
export OPENAI_API_KEY="sk-master-key-1234"
```
