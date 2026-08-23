# End-to-End Master Guide: LiteLLM + Headroom Gateway

This document provides the complete, end-to-end instructions for building, testing, and deploying a private LiteLLM gateway. This architecture is optimized for a "Weekend Warrior" usage pattern: a single user running on Jarvis Labs, where the server is paused during the week. It leverages Tailscale for instant, secure connectivity without the overhead of public domains or SSL certificates, and routes all traffic exclusively through OpenRouter, incorporating cost-saving optimizations for long-context tool calls and agent frameworks.

## 1. Architecture Overview

```
[ Your Laptops (Mac/Windows with Tailscale) ]
                 |
   (Encrypted WireGuard Tunnel via MagicDNS/IP)
                 |
[ Jarvis Labs Pod (Tailscale Installed) ]
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
- **Redis**: An in-memory store mounted to persistent storage with snapshotting enabled, ensuring instant semantic cache hits across weekend pause/resume cycles.
- **Tailscale**: Provides a static internal IP (100.x.x.x) and end-to-end encryption, completely hiding your server from the public internet.

## 2. Core Configuration Files

These two files form the heart of your stack. They are used identically in both your local testing environment and your Jarvis Labs production environment.

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

This file defines the container stack, including persistent Redis volume mapping.

```yaml
version: "3.8"

services:
  redis:
    image: redis:7-alpine
    container_name: litellm-redis
    restart: always
    command: redis-server --save 60 1 --loglevel warning
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

## 3. Phase 1: Local Testing & Validation

Before deploying to the cloud, validate the stack on your local machine using localhost. Place your docker-compose.yml and config.yaml in a folder named litellm-local, create a .env file containing your OPENROUTER_API_KEY and LITELLM_MASTER_KEY, and run:

```bash
docker compose up -d
```

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

## 4. Phase 2: Production Deployment on Jarvis Labs

### The Jarvis Labs Startup Script

In your Jarvis Labs instance settings, paste the following into the Startup Script section to handle Tailscale persistence, Docker readiness, and repository pulling on boot:

```bash
#!/bin/bash
echo "🤖 Starting Jarvis Labs Boot Sequence..."

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
echo "⏳ Waiting for Docker daemon..."
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
echo "✅ Jarvis Labs sequence complete. Available at http://jarvis-litellm:4000"
```

## 5. Client Configuration

Make sure the Tailscale application is running on your Mac/Windows laptops. Set your environment variables in your terminal or AI IDE:

```bash
export OPENAI_API_BASE="http://jarvis-litellm:4000/v1"
export OPENAI_API_KEY="sk-master-key-1234"
```
