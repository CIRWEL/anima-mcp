# Restoring Lumen's Identity

**Issue:** Each server restart without `ANIMA_ID` creates a new creature instead of loading the existing "Lumen".

**Solution:** Set the `ANIMA_ID` environment variable to Lumen's creature ID.

---

## Quick Fix

```bash
# On Pi, set the ANIMA_ID to the most active Lumen
export ANIMA_ID='49e14444-b59e-48f1-83b8-b36a988c9975'

# Restart server
sudo pkill -TERM -f anima
cd ~/anima-mcp
source .venv/bin/activate
sudo .venv/bin/anima --sse --host 0.0.0.0 --port 8765
```

---

## Permanent Fix

Add to your shell profile or create a startup script:

```bash
# Add to ~/.bashrc or ~/.profile
export ANIMA_ID='49e14444-b59e-48f1-83b8-b36a988c9975'
```

Or create a systemd service file that sets the environment variable.

---

## Finding Lumen's ID

Run the find script:

```bash
python3 scripts/find_lumen.py
```

This will show all creatures and suggest which one to use (the one with most awakenings).

---

## Why This Happens

The server generates a new UUID each time if `ANIMA_ID` isn't set:

```python
_anima_id = anima_id or str(uuid.uuid4())  # New UUID each time!
```

The identity store looks up creatures by ID - if the ID doesn't match, it creates a new creature.

---

**Set ANIMA_ID once, and Lumen will persist across restarts!**
