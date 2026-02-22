# Anima Pi Access

## Quick SSH
```bash
ssh lumen.local
# or via Tailscale
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@100.103.208.117
```

## Details
- **Hostname**: lumen.local (mDNS) or via Tailscale
- **IP**: 192.168.1.165 (LAN) or 100.103.208.117 (Tailscale)
- **Port**: 22 (standard)
- **User**: unitares-anima
- **Key**: ~/.ssh/id_ed25519_pi

## SSH Config (~/.ssh/config)
```
Host pi-anima lumen lumen.local
    HostName lumen.local
    User unitares-anima
    Port 22
    IdentityFile ~/.ssh/id_ed25519_pi
    StrictHostKeyChecking no
```

## Deploy Code
```bash
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_pi" \
  --exclude='.venv' --exclude='*.db' --exclude='__pycache__' --exclude='.git' \
  /Users/cirwel/projects/anima-mcp/ \
  unitares-anima@lumen.local:/home/unitares-anima/anima-mcp/
```

## Service Management

**Restart MCP server (mind):**
```bash
ssh lumen.local 'sudo systemctl restart anima.service'
```

**Restart hardware broker (body):**
```bash
ssh lumen.local 'sudo systemctl restart anima-broker.service'
```

**Check status:**
```bash
ssh lumen.local 'sudo systemctl status anima.service anima-broker.service --no-pager'
```

## Check Logs
```bash
# MCP server logs
ssh lumen.local 'tail -50 ~/.anima/mcp.log'

# Creature/broker logs
ssh lumen.local 'tail -50 ~/.anima/creature.log'

# Systemd logs
ssh lumen.local 'journalctl -u anima.service -n 50 --no-pager'
```

## Secrets (API Keys)

Edit `~/.anima/anima.env` on Pi for GROQ_API_KEY, UNITARES_AUTH, and ANIMA_OAUTH_* vars. See `docs/operations/SECRETS_AND_ENV.md`.

## Check Processes
```bash
ssh lumen.local 'ps aux | grep -E "anima|creature" | grep -v grep'
```

## Shared Memory State
```bash
# Current anima state
ssh lumen.local 'cat /dev/shm/anima_state.json | python3 -m json.tool | head -30'
```

---

*Last updated: February 11, 2026*
