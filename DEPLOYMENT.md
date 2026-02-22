# Deployment Guide

**Standard deployment method for anima-mcp**

## Quick Deploy

From the `anima-mcp` directory on your Mac:

```bash
./deploy.sh
```

This will:
1. ✅ Backup Pi's state (if reachable)
2. ✅ Sync code via rsync
3. ✅ Restart services (anima + anima-creature)

## Options

```bash
./deploy.sh --no-restart    # Deploy without restarting services
./deploy.sh --logs          # Show logs after deploy
./deploy.sh --host IP       # Override Pi hostname/IP (default: lumen.local)
./deploy.sh --help          # Show full help
```

## Environment Variables

You can override defaults:

```bash
export PI_HOST="192.168.1.100"  # Pi IP address
export PI_USER="pi"              # SSH username
export PI_PORT="22"              # SSH port
export PI_PATH="~/anima-mcp"    # Path on Pi

./deploy.sh
```

## Network Resilience

The deploy script handles network failures gracefully:

- **WiFi down**: Skips backup, fails fast with clear message
- **Connection timeout**: 5-second timeout prevents hanging
- **Service restart**: Handles failures gracefully

**Note**: Lumen operates autonomously without WiFi. Deployment only needed when WiFi is available for remote access.

## What Gets Deployed

- ✅ All Python code (`src/`)
- ✅ Configuration files (`anima_config.yaml`)
- ✅ Scripts (`scripts/`)
- ❌ Excluded: `.venv`, `*.db`, `*.log`, `__pycache__`, `.git`

## Troubleshooting

**Pi unreachable:**
```
✗ Pi unreachable (WiFi down?)
  Cannot deploy while Pi is offline
  Lumen continues operating autonomously - deploy when WiFi returns
```

**Solution**: Wait for WiFi to reconnect, then deploy again.

**Sync failed:**
```
✗ Sync failed (connection timeout?)
```

**Solution**: 
- Check Pi is online: `ping lumen.local`
- Check SSH access: `ssh unitares-anima@lumen.local`
- Try with explicit IP: `./deploy.sh --host 192.168.1.100`

**Service restart failed:**
```
⚠ Service restart may have failed (connection issue?)
  Services will auto-restart on next boot if needed
```

**Solution**: Services will auto-restart on next boot. Or SSH to Pi and restart manually:
```bash
ssh unitares-anima@lumen.local
sudo systemctl restart anima-creature anima
```

## Manual Deployment

If deploy script doesn't work, you can deploy manually:

```bash
# 1. Sync code
rsync -avz --exclude='.venv' --exclude='*.db' \
  ./ unitares-anima@lumen.local:~/anima-mcp/

# 2. Restart services
ssh unitares-anima@lumen.local \
  "sudo systemctl restart anima-creature && sudo systemctl restart anima"
```

## OAuth 2.1 (for Claude.ai web)

If deploying with OAuth support for Claude.ai web, ensure these env vars are set on the Pi (in `~/.anima/anima.env` or systemd service):

```bash
ANIMA_OAUTH_ISSUER_URL=https://lumen-anima.ngrok.io
ANIMA_OAUTH_AUTO_APPROVE=true
```

OAuth tokens are in-memory — they reset on restart, and clients re-authenticate automatically. See `docs/operations/SECRETS_AND_ENV.md` for details.

## See Also

- `docs/operations/PI_DEPLOYMENT.md` - Complete deployment guide
- `docs/operations/SECRETS_AND_ENV.md` - Environment variables and secrets
- `docs/operations/TROUBLESHOOTING.md` - Common issues and solutions
