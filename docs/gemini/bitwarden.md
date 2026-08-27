# Bitwarden Secrets Integration Guide

> [!WARNING]
> Using the standard **Bitwarden Password Manager CLI** (`bw`) on an automated server is highly discouraged. It requires passing your Master Password to Terraform to unlock the vault — a serious security risk.

Instead, this guide uses **Bitwarden Secrets Manager (BWS)** — a separate product built specifically for servers and CI/CD pipelines. It is **100% free for individuals** (up to 2 users and 3 projects) and ties directly into your existing Bitwarden account.

By using BWS, you generate a highly restricted, revocable **Machine Token** that can only read your specific secrets, keeping your primary password vault completely locked and safe.

---

## Step 1: Set Up Bitwarden Secrets Manager

1. Log into your [Bitwarden Web Vault](https://vault.bitwarden.com).
2. In the top-right app switcher, switch from **"Password Manager"** to **"Secrets Manager"**.
3. Create a new **Project** (e.g., `LiteLLM-Proxy`).
4. Add your secrets to the project one by one. For example:

   | Name | Value |
   |---|---|
   | `OPENROUTER_API_KEY` | `sk-or-v1-...` |
   | `LITELLM_MASTER_KEY` | `sk-master-1234` |

5. Go to **Machine Accounts** (left sidebar) and create a new Machine Account (e.g., `ec2-server`).
6. Give this Machine Account **"Read"** access to your `LiteLLM-Proxy` project.
7. Click **Generate Access Token** for the machine account. **Copy it immediately** — it is only shown once.

---

## Step 2: Configuring Terraform (`secrets_mode`)

Your Terraform setup uses a variable called `secrets_mode` to determine how the server retrieves credentials at boot time.

### Mode A — Bitwarden (Recommended, default)

This is the default mode (`secrets_mode = "bitwarden"`). During `terraform apply`, Terraform will prompt you for your `bws_access_token`.

When the server boots, it will automatically:

1. Download the official `bws` (Bitwarden Secrets CLI) for ARM64.
2. Authenticate using your Machine Token.
3. Fetch all secrets from your project and dynamically generate the `.env` file right before Docker starts.

> [!TIP]
> This makes your deployment **100% zero-touch** — no manual file transfers needed.

### Mode B — Local File (`env_file`)

Pass `secrets_mode = "env_file"` to `terraform apply` if you prefer not to use Bitwarden, or as a fallback if BWS is unavailable.

In this mode:

- The server **completely ignores** Bitwarden during boot.
- Docker will not start until a valid `.env` file is present.
- You must securely transfer your `.env` file over Tailscale after the server is up:

  ```bash
  scp .env ubuntu@cloud-litellm:~/repo/.env
  ssh ubuntu@cloud-litellm 'cd ~/repo && docker compose up -d'
  ```