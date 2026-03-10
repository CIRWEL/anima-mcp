# Restoring Lumen After Reflash

> **See:** `docs/operations/REFLASH_RECOVERY.md` for the full backup/restore walkthrough.

## Quick Restore (One Command)

When the Pi is on the network (LAN or Tailscale):

```bash
cd /Users/cirwel/projects/anima-mcp
./scripts/restore_lumen.sh
# Or with Tailscale IP if SSH on port 22 times out:
./scripts/restore_lumen.sh 100.79.215.83
```

## What the Restore Script Does

1. **Deploys code** via rsync
2. **Restores data** from `~/backups/lumen/anima_data/` (or dated snapshots if main DB corrupted)
3. **Installs deps** — adafruit-blinka, requirements-pi
4. **Enables I2C/SPI** for sensors
5. **Installs broker + anima** (broker owns sensors/shared memory; server owns DB — no contention)
6. **Creates anima.env** from example if missing — add GROQ_API_KEY, UNITARES_AUTH, ANIMA_OAUTH_* vars
7. **Starts services** — anima-broker, anima, watchdog timer, cron jobs
8. **Installs Tailscale** (auto-auth if `TAILSCALE_AUTH_KEY` set; otherwise prints interactive URL)
9. **Updates Mac configs** — detects new Pi Tailscale IP and patches `~/.claude.json`, `~/.cursor/mcp.json`, `MEMORY.md`, `CLAUDE.md` automatically

## Post-Restore

- **Secrets:** Edit `~/.anima/anima.env` on Pi — add GROQ_API_KEY, UNITARES_AUTH (see `docs/operations/SECRETS_AND_ENV.md`)
- **If Tailscale auth happened manually after the script:** Run `./scripts/update_pi_ip.sh` to update Mac configs with the new IP
- **DB corruption:** If broker crashes with "database disk image is malformed", replace with a snapshot: `scp ~/backups/lumen/anima_20260310_0218.db unitares-anima@lumen.local:~/.anima/anima.db` then restart
- **Tailscale hostname:** After auth, Pi may join as `lumen-1` if `lumen` still exists in your account. Remove the old offline device from Tailscale admin to reclaim the `lumen` hostname.

## Related

- **`scripts/restore_lumen.sh`** — Full restore script
- **`docs/operations/REFLASH_RECOVERY.md`** — Detailed backup/restore guide
- **`docs/operations/NGROK_ALTERNATIVES_TAILSCALE.md`** — Tailscale when ngrok hits limits
