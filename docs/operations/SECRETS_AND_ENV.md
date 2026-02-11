# Secrets and Environment Variables

**Created:** February 11, 2026  
**Last Updated:** February 11, 2026  
**Purpose:** API keys and credentials — never commit to git.

---

## Overview

Anima uses environment variables for API keys and auth. **Never commit real keys to git.** Use env files instead.

---

## Pi: `~/.anima/anima.env`

The anima service loads secrets from `~/.anima/anima.env` (optional — service starts without it, but LLM features won't work).

**Create from example:**
```bash
# On Pi
cp ~/anima-mcp/config/anima.env.example ~/.anima/anima.env
nano ~/.anima/anima.env   # Add your keys
sudo systemctl restart anima
```

**Required variables for full features:**

| Variable | Purpose | Get from |
|----------|---------|----------|
| `GROQ_API_KEY` | LLM (VQA, self-answering) | [groq.com](https://groq.com) (free) |
| `UNITARES_AUTH` | Governance BASIC auth | Your UNITARES setup |

**Example:**
```bash
GROQ_API_KEY=gsk_xxxxxxxxxxxx
UNITARES_AUTH=unitares:your-password
```

---

## Mac / Local: `scripts/envelope.pi`

SSH credentials for Pi deploy (see `scripts/envelope.pi.example`). Only used by deploy/restore scripts.

---

## Gitignore

- `config/anima.env` — never commit
- `scripts/envelope.pi` — never commit
- `*.env` (except `*.env.example`)

---

## Migration (Keys Were in systemd)

If you previously had GROQ_API_KEY and UNITARES_AUTH in the systemd service file, create the env file:

```bash
# On Pi (or via SSH)
cat > ~/.anima/anima.env << 'EOF'
GROQ_API_KEY=your-key-from-groq
UNITARES_AUTH=unitares:your-password
EOF
sudo systemctl restart anima
```

---

## Revoking Leaked Keys

If a key was committed to git:

1. **Rotate immediately** — generate new key at the provider
2. Update `~/.anima/anima.env` on Pi
3. Restart: `sudo systemctl restart anima`
4. Consider `git filter-branch` or BFG to remove from history (advanced)
