# DIY Weekend Engineer: Architecture Risk Analysis

The Tailscale + "Pull-on-Boot" architecture paired with persistent volume caching is an exceptional pattern for a weekend AI engineer. However, ephemeral pause/resume cloud pods introduce specific failure points. Here are the five potential failure points and how they are mitigated in your finalized stack.

## 1. The "Tailscale Ghost Node" Problem

**The Risk:** When Jarvis Labs pauses a machine, system-level directories like `/var/lib/` may reset. Tailscale stores its machine identity in `/var/lib/tailscale`. If wiped, Tailscale will authenticate as a brand new machine every weekend (jarvis-litellm-1, jarvis-litellm-2), changing your IP and cluttering your admin panel.

**The Fix:** Force Tailscale to store its state file inside your persistent `/home/` directory using the `--statedir=/home/litellm-stack/tailscale-state` flag in your startup script.

## 2. The Docker Daemon Boot Race Condition

**The Risk:** Cloud startup scripts run extremely early in the Linux boot sequence. Often, the script reaches `docker compose up -d` before the Docker daemon has finished initializing, causing silent failures on Saturday morning.

**The Fix:** Add a while loop into your startup script checking `until docker info > /dev/null 2>&1; do sleep 2; done` before triggering container deployment.

## 3. Redis "Cold Start" Cache Amnesia

**The Risk:** If Redis uses ephemeral container storage, every time the Jarvis pod pauses and stops, your entire semantic cache is wiped, forcing you to rebuild cache hits from scratch every weekend.

**The Fix:** Mount a local volume to your persistent `/home/` drive (`./redis-data:/data`) and enable Redis snapshotting (`command: redis-server --save 60 1`). This ensures your cache survives container restarts and pod pauses.

## 4. Expiring GitHub Deploy Credentials

**The Risk:** Embedding plaintext GitHub PATs in URLs risks failure when tokens expire or security policies trigger.

**The Fix:** Use a GitHub Deploy Key (SSH) stored securely in `/home/litellm-stack/.ssh/` on your persistent drive, ensuring zero expiration issues.

## 5. Jarvis Labs Disk Storage Billing & Footprint Drift

**The Risk:** Jarvis Labs charges roughly $0.10/GB/month for storage on your home directory 24/7, even while the machine is paused. Additionally, if Redis snapshot files (dump.rdb) or Docker logs grow unbounded over months of heavy agent testing, your disk utilization could quietly creep up past your default tier limits, risking truncation or unexpected overage bills.

**The Fix:**

- Keep your Redis TTL optimized (e.g., 7 days via `ttl: 604800`) so stale cache entries automatically expire and keep the .rdb file size tiny.
- Periodically check your storage usage on Jarvis Labs to ensure it remains well within your default disk allocation.
