#!/bin/bash
# Anima MCP - Raspberry Pi Installation Script
# Run this script on a fresh Raspberry Pi OS installation

set -e  # Exit on any error

echo "========================================="
echo "Anima MCP - Raspberry Pi Installation"
echo "========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ] || ! grep -q "Raspberry Pi" /proc/device-tree/model; then
    echo -e "${RED}Warning: This doesn't appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Step 1: System Update
echo -e "${BLUE}[1/8] Updating system packages...${NC}"
sudo apt update
sudo apt upgrade -y

# Step 2: Install System Dependencies
echo -e "${BLUE}[2/8] Installing system dependencies...${NC}"
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    build-essential \
    python3-dev \
    i2c-tools \
    libgpiod2 \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7 \
    libtiff5

# Step 3: Enable I2C and SPI
echo -e "${BLUE}[3/8] Enabling I2C and SPI interfaces...${NC}"
if ! grep -q "^dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null; then
    echo "dtparam=i2c_arm=on" | sudo tee -a /boot/firmware/config.txt > /dev/null || \
        echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt > /dev/null
fi

if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null; then
    echo "dtparam=spi=on" | sudo tee -a /boot/firmware/config.txt > /dev/null || \
        echo "dtparam=spi=on" | sudo tee -a /boot/config.txt > /dev/null
fi

# Add user to i2c and gpio groups
sudo usermod -a -G i2c,gpio,spi $USER

# Step 4: Create Virtual Environment
echo -e "${BLUE}[4/8] Creating Python virtual environment...${NC}"
INSTALL_DIR="$HOME/anima-mcp"

# If this is a fresh install from a git clone
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Installation directory not found. Please clone the repository first:"
    echo "  git clone <repo-url> $INSTALL_DIR"
    exit 1
fi

cd "$INSTALL_DIR"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Step 5: Upgrade pip
echo -e "${BLUE}[5/8] Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel

# Step 6: Install Python Dependencies
echo -e "${BLUE}[6/8] Installing Python dependencies...${NC}"
echo "  - Installing core dependencies..."
pip install -r requirements.txt

echo "  - Installing Raspberry Pi hardware dependencies..."
pip install -r requirements-pi.txt

# Step 7: Install Anima MCP
echo -e "${BLUE}[7/8] Installing anima-mcp package...${NC}"
pip install -e .

# Step 8: Create Configuration
echo -e "${BLUE}[8/8] Setting up configuration...${NC}"

# Create config file if it doesn't exist
if [ ! -f "anima_config.yaml" ]; then
    if [ -f "anima_config.yaml.example" ]; then
        cp anima_config.yaml.example anima_config.yaml
        echo "  - Created anima_config.yaml from example"
    else
        cat > anima_config.yaml << 'EOF'
# Anima Configuration
thermal:
  cpu_temp_min: 35.0
  cpu_temp_max: 75.0
  ambient_temp_min: 15.0
  ambient_temp_max: 35.0

environmental:
  humidity_ideal: 50.0
  pressure_ideal: 1013.25
  light_max: 1000.0

weights:
  warmth:
    cpu_temp: 0.6
    ambient_temp: 0.3
    neural: 0.1
  clarity:
    light: 0.5
    neural: 0.5
  stability:
    humidity: 0.4
    pressure: 0.3
    neural: 0.3
  presence:
    system: 1.0

display:
  led_brightness: 0.3
  breathing_enabled: true
  update_interval: 2.0
EOF
        echo "  - Created default anima_config.yaml"
    fi
else
    echo "  - anima_config.yaml already exists"
fi

# Generate a unique creature ID if not set
if [ -z "$ANIMA_ID" ]; then
    ANIMA_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
    echo "export ANIMA_ID='$ANIMA_ID'" >> ~/.bashrc
    echo "  - Generated creature ID: $ANIMA_ID"
else
    echo "  - Using existing creature ID: $ANIMA_ID"
fi

# Step 9: Verify Installation
echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""

# Test I2C
echo "Testing I2C..."
if command -v i2cdetect > /dev/null; then
    echo "  - I2C tools available"
    echo "  - Detected I2C devices:"
    i2cdetect -y 1 2>/dev/null || echo "    (No devices detected - this is normal if HAT isn't connected)"
else
    echo "  - I2C tools not found"
fi

# Test installation
echo ""
echo "Testing installation..."
if python3 -c "import anima_mcp; print('  - anima_mcp package imported successfully')" 2>/dev/null; then
    echo -e "${GREEN}  ✓ Installation verified${NC}"
else
    echo -e "${RED}  ✗ Import failed${NC}"
fi

# Next steps
echo ""
echo "========================================="
echo "Next Steps:"
echo "========================================="
echo ""
echo "1. ${GREEN}Reboot to enable I2C/SPI:${NC}"
echo "   sudo reboot"
echo ""
echo "2. ${GREEN}After reboot, verify sensors:${NC}"
echo "   cd $INSTALL_DIR"
echo "   source .venv/bin/activate"
echo "   python3 -c \"from anima_mcp.sensors import get_sensors; s = get_sensors(); print('Available sensors:', s.available_sensors())\""
echo ""
echo "3. ${GREEN}Run anima locally (stdio):${NC}"
echo "   anima"
echo ""
echo "4. ${GREEN}Or run with network access (SSE):${NC}"
echo "   anima --sse --host 0.0.0.0 --port 8766"
echo ""
echo "5. ${GREEN}Set up systemd service (optional):${NC}"
echo "   ./scripts/setup_pi_service.sh"
echo ""
echo "========================================="
echo "Your creature ID: $ANIMA_ID"
echo "========================================="
