# Brain HAT Setup Guide

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Ready for Hardware Arrival

---

## Overview

This guide walks through setting up the Raspberry Pi + Brain HAT hardware for neural proprioception in anima-mcp.

## Prerequisites

### Hardware

- ✅ Raspberry Pi 4 (4GB+ recommended)
- ✅ Brain HAT (OpenBCI compatible)
- ✅ MicroSD card (32GB+, Class 10)
- ✅ Power supply (5V 3A USB-C)
- ✅ EEG electrodes (dry or wet, depending on Brain HAT model)
- ✅ Optional: BrainCraft HAT (for display + other sensors)

### Software

- Raspberry Pi OS (64-bit, latest)
- Python 3.11+
- Git

## Step 1: Raspberry Pi Setup

### 1.1 Flash Raspberry Pi OS

```bash
# On Mac/PC, download Raspberry Pi Imager
# Flash Raspberry Pi OS (64-bit) to microSD card
# Enable SSH and set WiFi credentials during imaging
```

### 1.2 First Boot

```bash
# SSH into Pi
ssh pi@raspberrypi.local

# Update system
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y git python3-pip python3-venv build-essential
```

### 1.3 Enable I2C and SPI

```bash
# Enable I2C and SPI interfaces
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable
# Navigate to: Interface Options → SPI → Enable

# Reboot
sudo reboot
```

## Step 2: Install Brain HAT Drivers

### 2.1 Install BrainFlow

```bash
# Create virtual environment
python3 -m venv ~/anima-env
source ~/anima-env/bin/activate

# Install BrainFlow (Brain HAT communication library)
pip install brainflow numpy scipy

# Verify installation
python3 -c "import brainflow; print('BrainFlow installed!')"
```

### 2.2 Install GPIO Libraries (if needed)

```bash
# For BrainCraft HAT compatibility
pip install RPi.GPIO adafruit-circuitpython-dht adafruit-circuitpython-bh1750
```

## Step 3: Connect Brain HAT

### 3.1 Physical Connection

1. **Power off Raspberry Pi**
2. **Mount Brain HAT** on GPIO header (40-pin)
3. **Connect EEG electrodes**:
   - TP9: Left temporal-parietal
   - AF7: Left anterior frontal
   - AF8: Right anterior frontal
   - TP10: Right temporal-parietal
   - Aux channels: Optional
4. **Power on Raspberry Pi**

### 3.2 Verify Connection

```bash
# Check if Brain HAT is detected
ls -l /dev/ttyUSB* /dev/ttyACM*

# Should see something like:
# /dev/ttyUSB0 or /dev/ttyACM0
```

### 3.3 Test Brain HAT

```bash
# Create test script
cat > test_brain_hat.py << 'EOF'
from brainflow.board_shim import BoardShim, BrainFlowInputParams
from brainflow.data_filter import DataFilter

# Configure Brain HAT
params = BrainFlowInputParams()
params.serial_port = "/dev/ttyUSB0"  # Adjust if needed

# OpenBCI Cyton board ID
board_id = BoardShim.BOARD_ID_CYTON_BOARD
board = BoardShim(board_id, params)

try:
    board.prepare_session()
    board.start_stream()
    print("Brain HAT connected!")
    
    # Read a few samples
    import time
    time.sleep(2)
    data = board.get_board_data()
    print(f"Received {data.shape[1]} samples")
    
    board.stop_stream()
    board.release_session()
except Exception as e:
    print(f"Error: {e}")
EOF

python3 test_brain_hat.py
```

## Step 4: Install Anima-MCP

### 4.1 Clone Repository

```bash
cd ~
git clone <anima-mcp-repo-url>
cd anima-mcp
```

### 4.2 Install with Pi Dependencies

```bash
source ~/anima-env/bin/activate
pip install -e ".[pi]"
```

### 4.3 Verify Installation

```bash
# Test sensor detection
python3 -c "
from anima_mcp.sensors import get_sensors
sensors = get_sensors()
print('Available sensors:', sensors.available_sensors())
"
```

## Step 5: Configure Anima-MCP

### 5.1 Create Configuration

```bash
# Create config directory
mkdir -p ~/.config/anima-mcp

# Create config file
cat > ~/.config/anima-mcp/config.json << 'EOF'
{
  "use_brain_hat": true,
  "brain_hat_port": "/dev/ttyUSB0",
  "sample_rate": 250,
  "buffer_size": 100
}
EOF
```

### 5.2 Test Full Integration

```bash
# Run anima server
anima

# In another terminal, test MCP connection
# (configure Claude Desktop or Cursor to connect)
```

## Step 6: Calibration (Optional)

### 6.1 Baseline Recording

Record baseline EEG while creature is "at rest":

```python
from anima_mcp.sensors import get_sensors
import time

sensors = get_sensors()
readings = []

for i in range(100):  # 10 seconds at 10 Hz
    r = sensors.read()
    readings.append(r)
    time.sleep(0.1)

# Analyze baseline
alpha_baseline = sum(r.eeg_alpha_power for r in readings if r.eeg_alpha_power) / len(readings)
print(f"Baseline alpha: {alpha_baseline}")
```

### 6.2 Adjust Weights (if needed)

If neural signals are too strong/weak, adjust weights in `anima.py`:

```python
# In _sense_warmth(), _sense_clarity(), etc.
# Modify neural weight percentages
```

## Troubleshooting

### Brain HAT Not Detected

```bash
# Check USB devices
lsusb

# Check serial ports
ls -l /dev/tty*

# Try different port
# Edit brain_hat.py: _detect_brain_hat_port()
```

### Permission Denied

```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
# Log out and back in
```

### Import Errors

```bash
# Reinstall BrainFlow
pip install --upgrade brainflow

# Check Python version (need 3.11+)
python3 --version
```

### No EEG Data

```bash
# Check electrode connections
# Verify Brain HAT is powered
# Check serial communication:
python3 -c "
from brainflow.board_shim import BoardShim, BrainFlowInputParams
params = BrainFlowInputParams()
params.serial_port = '/dev/ttyUSB0'
board = BoardShim(BoardShim.BOARD_ID_CYTON_BOARD, params)
board.prepare_session()
board.start_stream()
import time
time.sleep(2)
data = board.get_board_data()
print(f'Data shape: {data.shape}')
board.stop_stream()
board.release_session()
"
```

## Network Access (SSE Mode)

### Run on Pi, Connect from Mac

```bash
# On Pi
anima --sse --port 8765

# On Mac, configure Claude Desktop/Cursor:
# {
#   "mcpServers": {
#     "anima": {
#       "url": "http://raspberrypi.local:8765/sse"
#     }
#   }
# }
```

## Next Steps

1. **Test neural proprioception**: Observe how EEG signals affect anima state
2. **Experiment with weights**: Adjust neural/physical balance
3. **Record sessions**: Log EEG data for analysis
4. **Extend integration**: Add pattern detection, state machines

## Resources

- [OpenBCI Brain HAT Documentation](https://docs.openbci.com/)
- [BrainFlow Documentation](https://brainflow.readthedocs.io/)
- [Raspberry Pi GPIO Guide](https://www.raspberrypi.org/documentation/usage/gpio/)
- [4E Cognition Theory](4E-2.pdf)

---

## Quick Reference

### Port Detection
```bash
# Find Brain HAT port
ls -l /dev/ttyUSB* /dev/ttyACM*
```

### Test Connection
```python
from brainflow.board_shim import BoardShim, BrainFlowInputParams
params = BrainFlowInputParams()
params.serial_port = "/dev/ttyUSB0"
board = BoardShim(BoardShim.BOARD_ID_CYTON_BOARD, params)
board.prepare_session()
board.start_stream()
```

### Check Sensors
```python
from anima_mcp.sensors import get_sensors
sensors = get_sensors()
print(sensors.available_sensors())
```

---

**Note**: This guide assumes OpenBCI Brain HAT. Adjust port detection and board IDs for other Brain HAT models.

