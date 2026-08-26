# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo state

Docs-only. No `config.yaml`, `docker-compose.yml`, `.env.example`, or application code exist yet — only planning docs in `docs/gemini/`. There is nothing to build, lint, or test. Once the stack files land, this file needs a Commands section added.

## What this project is

A private LiteLLM gateway proxying to OpenRouter, with Headroom as a pre-call context-compression guardrail and Redis for persistent semantic caching. Two deployment targets are planned: Jarvis Labs (pause/resume GPU pods) and AWS EC2 (on-demand, auto-shutdown after 4h idle, Lambda-triggered start). Tailscale provides the only network path in — no public ports beyond the one Elastic IP on EC2, no SSL/domain setup.

Full spec: `docs/gemini/MasterGuide-LiteLLM-Stack.md`. Known failure modes and their mitigations (Tailscale state wipe, Docker boot race, Redis cold start, expiring deploy creds, storage drift): `docs/gemini/RisAnalysis.md`.

## Non-obvious architecture constraints

These come from the failure-analysis doc and are easy to violate by accident when editing the stack config:

- **Tailscale state must live under the persistent volume** (`--statedir=/home/.../tailscale-state`), never the default `/var/lib/tailscale` — pod pauses wipe `/var/lib/`, which re-registers the machine as a new node each time.
- **Startup scripts must poll for the Docker daemon** (`until docker info > /dev/null 2>&1`) before `docker compose up` — cloud init runs before Docker is ready.
- **Redis needs a mounted volume + snapshotting** (`./redis-data:/data`, `--save 60 1`) or the semantic cache is wiped on every pause/resume cycle.
- **EC2 instance type is locked to `t3.*`/`t4g.*` (x86_64/ARM64 respectively) and cannot cross families on the same volume.** The Lambda ignition switch whitelists exactly `t4g.small`, `t4g.medium`, `t3.small`, `t3.medium` — any type-switching code must preserve that whitelist.
- **Exactly one Elastic IP, no load balancer, no NAT gateway, no secondary IPs** on EC2 — this is a deliberate cost constraint ($3.65/mo cap), not an oversight.
- **Redis TTL (`ttl: 604800`, 7 days) bounds cache growth** — don't remove it without an alternative eviction strategy; `maxmemory 1536mb` + `allkeys-lru` is the memory-side backstop.

## Development workflow

Use `/linked-intent-dev:linked-intent-dev` for all code changes in this repo — it runs a mode-aware six-phase flow (HLD → LLD → EARS → intent-narrowing edge audit → tests-first → code) with mandatory stops between phases. Bugs go through the same flow, no shortcut.
