# Pi Hotspot Setup for Portable SSH Access

**Goal:** Connect Pi to phone hotspot for versatile, portable SSH access.

---

## Step 1: Connect Pi to Phone Hotspot

**On your phone:**
1. Enable mobile hotspot
2. Note the hotspot name (SSID) and password
3. Note your phone's IP address (usually shown in hotspot settings, or `192.168.43.1` for Android, `172.20.10.1` for iPhone)

**On Pi (via direct access or if you have a monitor/keyboard):**

```bash
# List available WiFi networks
sudo nmcli device wifi list

# Connect to hotspot
sudo nmcli device wifi connect "HOTSPOT_NAME" password "HOTSPOT_PASSWORD"

# Or use raspi-config if available
sudo raspi-config
# Navigate to: System Options → Wireless LAN
```

**Or edit WiFi config directly:**

```bash
# Edit wpa_supplicant config
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

Add:
```
network={
    ssid="HOTSPOT_NAME"
    psk="HOTSPOT_PASSWORD"
}
```

**Restart networking:**
```bash
sudo systemctl restart networking
# or
sudo ifdown wlan0 && sudo ifup wlan0
```

---

## Step 2: Get Pi's IP on Hotspot

**On Pi:**

```bash
# Get IP address
hostname -I

# Or check WiFi interface
ip addr show wlan0
```

**Note the IP address** (will be in hotspot's range, e.g., `192.168.43.x` for Android, `172.20.10.x` for iPhone)

---

## Step 3: Connect MacBook to Same Hotspot

**On MacBook:**
1. Connect to the same phone hotspot
2. Get MacBook's IP: `ifconfig | grep "inet " | grep -v 127.0.0.1`

---

## Step 4: Test SSH Connection

**From MacBook:**

```bash
# SSH to Pi using hotspot IP
ssh -p 2222 unitares-anima@[PI_HOTSPOT_IP]

# Password: EISV-4E-CLDO
```

**Example:**
```bash
ssh -p 2222 unitares-anima@192.168.43.123
```

---

## Step 5: Set Up Cursor Remote SSH

Once SSH works:

1. **Install "Remote - SSH" extension** in Cursor
2. **Press `Cmd+Shift+P`** → "Remote-SSH: Connect to Host"
3. **Enter:** `unitares-anima@[PI_HOTSPOT_IP]` (or use port: `-p 2222 unitares-anima@[IP]`)
4. **Enter password:** `EISV-4E-CLDO`
5. **Open folder:** `/home/unitares-anima`

**Or add to SSH config:**

Edit `~/.ssh/config`:
```
Host pi-anima-hotspot
    HostName [PI_HOTSPOT_IP]
    User unitares-anima
    Port 2222
```

Then connect with: `ssh pi-anima-hotspot` or use "pi-anima-hotspot" in Cursor Remote SSH.

---

## Step 6: Make Hotspot Connection Persistent

**On Pi, set hotspot as priority:**

```bash
# Edit wpa_supplicant config
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

Ensure hotspot network is listed first (higher priority).

**Or use nmcli:**

```bash
# Set hotspot as priority connection
sudo nmcli connection modify "HOTSPOT_NAME" connection.autoconnect yes
sudo nmcli connection up "HOTSPOT_NAME"
```

---

## Troubleshooting

**Pi can't connect to hotspot?**
- Check hotspot is enabled and visible
- Check password is correct
- Try `sudo iwlist wlan0 scan` to see available networks

**Can't find Pi's IP?**
- Check `hostname -I` on Pi
- Check hotspot's connected devices list on phone
- Try `ping` from MacBook to find Pi: `ping -c 1 192.168.43.1` then scan range

**SSH still doesn't work?**
- Ensure both devices on same hotspot
- Check Pi's IP hasn't changed (DHCP)
- Try `ssh -vvv` for verbose output

---

## Benefits of Hotspot Setup

✅ **Portable** - Pi works anywhere with phone hotspot  
✅ **Bypasses router issues** - No AP isolation/firewall problems  
✅ **Easy to set up** - Just enable hotspot  
✅ **Secure** - Direct connection, no router in between  
✅ **Versatile** - Works at home, office, anywhere  

---

## Quick Reference

**Pi IP on hotspot:** `hostname -I` (on Pi)  
**SSH command:** `ssh -p 2222 unitares-anima@[PI_IP]`  
**Password:** `EISV-4E-CLDO`  
**Cursor Remote SSH:** Use IP or add to `~/.ssh/config`

