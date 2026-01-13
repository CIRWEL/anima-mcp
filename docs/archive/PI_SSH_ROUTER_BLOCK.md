# Pi SSH Router/Network Block Issue

**Status:** `nc` connects to port 22, but SSH client times out and nothing appears in Pi logs.

**This suggests:** Router or network is blocking SSH protocol specifically (deep packet inspection?).

---

## Possible Causes

1. **Router AP Isolation** - Prevents device-to-device communication
2. **Router Firewall** - Blocking SSH protocol
3. **Guest Network** - Pi and MacBook on different networks
4. **Deep Packet Inspection** - Router inspecting and blocking SSH

---

## Solutions

### Option 1: Check Router Settings

- Log into router admin (usually `192.168.1.1` or `192.168.0.1`)
- Check for "AP Isolation" or "Client Isolation" - **DISABLE IT**
- Check firewall rules - allow SSH/port 22
- Ensure Pi and MacBook are on same network (not guest network)

### Option 2: Use Different Port

**On Pi:**

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Change: #Port 22
# To: Port 2222

# Restart SSH
sudo systemctl restart ssh
```

**From MacBook:**

```bash
ssh -p 2222 unitares-anima@192.168.1.165
```

Routers often block port 22 specifically but allow other ports.

### Option 3: Use SSH Tunnel Through Different Port

If router blocks SSH protocol, you might need to:
- Use VPN
- Use different network
- Connect Pi via Ethernet instead of WiFi

### Option 4: Check Network Configuration

**On MacBook:**

```bash
# Check your network interface
ifconfig | grep "inet " | grep -v 127.0.0.1

# Check routing
netstat -rn | grep default
```

**On Pi:**

```bash
# Check Pi's network
ip addr show
ip route show
```

Ensure both are on same subnet (192.168.1.x).

---

## Quick Test: Try Different Port

**On Pi:**

```bash
# Test SSH on port 2222
sudo nano /etc/ssh/sshd_config
# Change: Port 22 to Port 2222
sudo systemctl restart ssh
```

**From MacBook:**

```bash
ssh -p 2222 unitares-anima@192.168.1.165
```

If this works, router is blocking port 22 specifically.

---

## Most Likely Fix

**Check router settings for:**
- AP Isolation / Client Isolation → **DISABLE**
- Firewall rules → **ALLOW port 22**
- Ensure same network (not guest)

**Or use different port (2222) to bypass port 22 blocking.**

