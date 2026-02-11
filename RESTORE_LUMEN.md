# Restoring Lumen After Reflash

> **See:** `docs/operations/REFLASH_RECOVERY.md` for the full backup/restore walkthrough.

## Quick Restore (One Command)

When the Pi is on the network (LAN or Tailscale):

```bash
cd /Users/cirwel/projects/anima-mcp
./scripts/restore_lumen.sh
# Or with Tailscale IP if SSH on port 22 times out:
./scripts/restore_lumen.sh 100.103.208.117
```

## What the Restore Script Does

1. **Deploys code** via rsync
2. **Restores data** from `~/backups/lumen/anima_data/` (or dated snapshots if main DB corrupted)
3. **Installs deps** — adafruit-blinka, requirements-pi
4. **Enables I2C/SPI** for sensors
5. **Installs broker + anima** (broker owns sensors/shared memory; server owns DB — no contention)
6. **Creates anima.env** from example if missing — add GROQ_API_KEY, UNITARES_AUTH
7. **Starts services** — anima-broker, anima

## Post-Restore

- **MCP config:** Update `~/.cursor/mcp.json` with Pi URL (e.g. `http://100.103.208.117:8766/mcp/`)
- **Secrets:** Edit `~/.anima/anima.env` on Pi — see `docs/operations/SECRETS_AND_ENV.md`
- **DB corruption:** If broker crashes with "database disk image is malformed", replace with a clean snapshot: `scp ~/backups/lumen/anima_20260210_0600.db unitares-anima@100.103.208.117:~/.anima/anima.db` then restart

## Related

- **`scripts/restore_lumen.sh`** — Full restore script
- **`docs/operations/REFLASH_RECOVERY.md`** — Detailed backup/restore guide
- **`docs/operations/NGROK_ALTERNATIVES_TAILSCALE.md`** — Tailscale when ngrok hits limits
