# Backup & Restore — Single Source of Truth

## Backup Location

```
~/backups/lumen/
  anima_data/              ← latest rsync mirror of Pi's ~/.anima/
  anima_YYYYMMDD_HHMM.db  ← dated snapshots (runs ~hourly, keeps 14)
```

> **WARNING:** `~/lumen-backups/` is OLD and STALE — ignore it.

Check latest snapshot:
```bash
ls -lt ~/backups/lumen/anima_*.db | head -5
```

## Restore After Reflash — One Command

```bash
cd ~/projects/anima-mcp
./scripts/restore_lumen.sh                # auto-detects: lumen.local, 192.168.1.165, Tailscale
./scripts/restore_lumen.sh 192.168.1.165  # explicit IP
```

What it does: deploys code → restores DB + JSON + drawings → installs deps → enables I2C/SPI → starts services → installs watchdog + cron.

**Do NOT restore manually step-by-step. Run the script.**

## What Gets Backed Up

From Pi's `~/.anima/`:
- `anima.db` — all memories, learning, calibration, identity (most important)
- `preferences.json`, `self_model.json`, `knowledge.json`, `patterns.json`
- `canvas.json`, `messages.json`, `anima_history.json`
- `metacognition_baselines.json`, `last_schema.json`, `trajectory_genesis.json`
- `day_summaries.json`, `display_brightness.json`
- `drawings/` — all saved artwork

## Backup Schedule

- **Automated (Mac):** `/Users/cirwel/scripts/backup_lumen.sh` — twice daily (6am, 6pm) + hourly snapshots
- **Launchd plist:** `~/Library/LaunchAgents/com.unitares.lumen-backup.plist`
- **Log:** `/Users/cirwel/backups/lumen_backup.log`

## Secrets After Restore

The restore script copies `anima.env.example` to `~/.anima/anima.env` on the Pi. Edit it to add:
- `GROQ_API_KEY` — LLM (from groq.com, free)
- `UNITARES_AUTH` — governance BASIC auth
- `ANIMA_OAUTH_ISSUER_URL` — ngrok URL (e.g. `https://lumen-anima.ngrok.io`)
- `ANIMA_OAUTH_AUTO_APPROVE=true`

See `docs/operations/SECRETS_AND_ENV.md` for details.

## Tailscale After Restore

Tailscale is lost on reflash. After restore completes, reinstall:
```bash
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "curl -fsSL https://tailscale.com/install.sh | sh"
# Then authenticate:
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "sudo tailscale up"
# Follow the URL that appears to authenticate
```

## DB Integrity Check

If services crash with "database disk image is malformed":
```bash
# Find a clean snapshot
ls -lt ~/backups/lumen/anima_*.db | head -5

# Copy it to Pi
scp -i ~/.ssh/id_ed25519_pi \
  ~/backups/lumen/anima_YYYYMMDD_HHMM.db \
  unitares-anima@192.168.1.165:~/.anima/anima.db

# Clear WAL files and restart
ssh -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165 \
  "rm -f ~/.anima/anima.db-wal ~/.anima/anima.db-shm && \
   sudo systemctl restart anima-broker anima"
```
