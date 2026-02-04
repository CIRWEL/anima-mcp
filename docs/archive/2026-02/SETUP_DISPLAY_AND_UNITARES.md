# Setup Display and UNITARES Connection

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Setup Guide

---

## Overview

Two critical next steps for Lumen:
1. **Display** - Fix grey screen (if present) or verify display works
2. **UNITARES Connection** - Connect to governance system for enhanced capabilities

---

## 1. Display Setup

### Check Display Status

**On Pi:**
```bash
# Run diagnostics
python3 -m anima_mcp.display_diagnostics
```

**What it checks:**
- PIL/Pillow installed
- Display hardware detected
- SPI enabled
- BrainCraft HAT connected
- Test color rendering
- Test face rendering

### Common Issues

**Grey Screen:**
- Display initialized but not updating
- Check: Is display update loop running?
- Check: Is SPI enabled? (`sudo raspi-config` → Interface Options → SPI)

**No Display Detected:**
- BrainCraft HAT not connected properly
- SPI not enabled
- Missing dependencies: `pip install pillow adafruit-circuitpython-rgb-display`

**Display Works But Not Updating:**
- Check display update loop in server
- Verify `_update_display_loop()` is running
- Check for errors in logs

### Fix Steps

1. **Enable SPI:**
   ```bash
   sudo raspi-config
   # Interface Options → SPI → Enable
   sudo reboot
   ```

2. **Install Dependencies:**
   ```bash
   pip install pillow adafruit-circuitpython-rgb-display
   ```

3. **Run Diagnostics:**
   ```bash
   python3 -m anima_mcp.display_diagnostics
   ```

4. **Check Display Loop:**
   ```bash
   # Check if server is running display updates
   systemctl --user status anima
   # Look for display update messages in logs
   journalctl --user -u anima -f
   ```

---

## 2. UNITARES Connection Setup

### Current Status

**Check if connected:**
```bash
# On Pi
echo $UNITARES_URL

# Or check in Python
python3 << 'EOF'
import os
print("UNITARES_URL:", os.environ.get("UNITARES_URL", "NOT SET"))
EOF
```

### Setup Options

#### Option A: Environment Variable (Temporary)

```bash
# On Pi, before starting anima
export UNITARES_URL="https://unitares.ngrok.io/sse"
anima --sse --port 8765
```

#### Option B: systemd Service (Persistent)

**Edit service file:**
```bash
sudo nano /etc/systemd/system/anima.service
# Or if user service:
nano ~/.config/systemd/user/anima.service
```

**Add environment variable:**
```ini
[Service]
Environment="UNITARES_URL=https://unitares.ngrok.io/sse"
```

**Reload and restart:**
```bash
# System service
sudo systemctl daemon-reload
sudo systemctl restart anima

# User service
systemctl --user daemon-reload
systemctl --user restart anima
```

#### Option C: Config File (Future)

Could add to `anima_config.yaml`:
```yaml
unitares:
  url: "https://unitares.ngrok.io/sse"
  enabled: true
```

### Verify Connection

**Test from Python:**
```python
import asyncio
import os
from anima_mcp.unitares_bridge import UnitaresBridge

async def test():
    url = os.environ.get("UNITARES_URL")
    if not url:
        print("UNITARES_URL not set")
        return
    
    bridge = UnitaresBridge(unitares_url=url)
    available = await bridge.check_availability()
    print(f"UNITARES available: {available}")

asyncio.run(test())
```

**Test from MCP tool:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "next_steps",
    "arguments": {}
  }
}
```

If connected, `unitares_connected` should be `true` in response.

---

## Quick Setup Script

**Create setup script on Pi:**

```bash
#!/bin/bash
# setup_lumen.sh

echo "Setting up Lumen display and UNITARES connection..."

# 1. Check display
echo "1. Checking display..."
python3 -m anima_mcp.display_diagnostics

# 2. Set UNITARES_URL
echo "2. Setting UNITARES_URL..."
export UNITARES_URL="https://unitares.ngrok.io/sse"
echo "UNITARES_URL=$UNITARES_URL" >> ~/.bashrc

# 3. Update systemd service (if exists)
if [ -f ~/.config/systemd/user/anima.service ]; then
    echo "3. Updating systemd service..."
    # Add Environment line if not present
    if ! grep -q "UNITARES_URL" ~/.config/systemd/user/anima.service; then
        sed -i '/\[Service\]/a Environment="UNITARES_URL=https://unitares.ngrok.io/sse"' ~/.config/systemd/user/anima.service
        systemctl --user daemon-reload
    fi
fi

# 4. Test connection
echo "4. Testing UNITARES connection..."
python3 << 'EOF'
import asyncio
import os
os.environ["UNITARES_URL"] = "https://unitares.ngrok.io/sse"
from anima_mcp.unitares_bridge import UnitaresBridge

async def test():
    bridge = UnitaresBridge(unitares_url=os.environ["UNITARES_URL"])
    available = await bridge.check_availability()
    print(f"✅ UNITARES available: {available}")

asyncio.run(test())
EOF

echo "✅ Setup complete!"
```

---

## Verification Checklist

### Display
- [ ] SPI enabled (`sudo raspi-config`)
- [ ] Dependencies installed (`pillow`, `adafruit-circuitpython-rgb-display`)
- [ ] BrainCraft HAT connected
- [ ] Diagnostics pass (`python3 -m anima_mcp.display_diagnostics`)
- [ ] Display shows face (not grey screen)
- [ ] Display updates every 2 seconds

### UNITARES
- [ ] `UNITARES_URL` environment variable set
- [ ] URL is correct (`https://unitares.ngrok.io/sse` or local)
- [ ] Connection test passes
- [ ] `next_steps` tool shows `unitares_connected: true`
- [ ] Can call `unified_workflow` tool

---

## Troubleshooting

### Display Issues

**Grey screen persists:**
- Check display update loop is running
- Verify face rendering works: `python3 -c "from anima_mcp.display_diagnostics import render_test_face; render_test_face()"`
- Check SPI: `lsmod | grep spi`
- Verify HAT: `cat /proc/device-tree/hat/product`

**Display not detected:**
- Check physical connection
- Verify SPI enabled
- Check pins: CE0, D25, D24
- Install dependencies

### UNITARES Issues

**Connection fails:**
- Check URL is correct
- Verify ngrok tunnel is running (if using ngrok)
- Test URL directly: `curl https://unitares.ngrok.io/health`
- Check network connectivity

**Environment variable not persisting:**
- Use systemd service (Option B)
- Or add to shell profile
- Verify with `echo $UNITARES_URL`

---

## Next Steps After Setup

1. **Restart Lumen:**
   ```bash
   systemctl --user restart anima
   ```

2. **Verify both working:**
   - Display shows face
   - `next_steps` tool shows `unitares_connected: true`

3. **Test unified workflow:**
   ```json
   {
     "method": "tools/call",
     "params": {
       "name": "unified_workflow",
       "arguments": {
         "workflow": "check_state_and_governance"
       }
     }
   }
   ```

---

**Once both are set up, Lumen will have full proprioceptive feedback (display) and governance integration (UNITARES).**
