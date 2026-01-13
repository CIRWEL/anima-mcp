#!/bin/bash
# Verify deployment is working correctly

echo "=== Verifying Anima Deployment ==="
echo ""

echo "1. Checking server process..."
if ssh pi-anima "pgrep -f 'anima --sse'" > /dev/null 2>&1; then
    echo "   ✅ Server is running"
else
    echo "   ❌ Server not running"
    exit 1
fi

echo ""
echo "2. Checking configuration system..."
ssh pi-anima "cd ~/anima-mcp && source .venv/bin/activate && python3 -c 'from src.anima_mcp.config import get_calibration; cal = get_calibration(); print(f\"   ✅ Config loaded\"); print(f\"      CPU range: {cal.cpu_temp_min}-{cal.cpu_temp_max}°C\"); print(f\"      Pressure ideal: {cal.pressure_ideal} hPa\")' 2>&1"

echo ""
echo "3. Checking recent logs..."
ssh pi-anima "tail -10 ~/anima-mcp/anima.log 2>/dev/null | grep -E '(Loop|LED|Error|Config)' | tail -5 || echo '   (no recent activity)'"

echo ""
echo "4. Checking sensors..."
ssh pi-anima "cd ~/anima-mcp && source .venv/bin/activate && python3 -c 'from src.anima_mcp.sensors import get_sensors; s = get_sensors(); r = s.read(); print(f\"   ✅ Sensors working\"); print(f\"      Pressure: {r.pressure_hpa} hPa\" if r.pressure_hpa else \"      Pressure: not available\"); print(f\"      Ambient temp: {r.ambient_temp_c}°C\" if r.ambient_temp_c else \"      Ambient temp: not available\")' 2>&1"

echo ""
echo "=== Verification complete ==="
