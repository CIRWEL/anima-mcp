# Pi SSH Network Troubleshooting

**Status:** SSH is listening correctly (`0.0.0.0:22`), but connections timeout from MacBook.

---

## Check SSH Config on Pi

Run on Pi:

```bash
# Check SSH config for restrictions
sudo cat /etc/ssh/sshd_config | grep -E "AllowUsers|DenyUsers|AllowGroups|DenyGroups|ListenAddress"

# Check if there are any IP restrictions
sudo grep -E "^AllowUsers|^DenyUsers|^AllowGroups|^DenyGroups" /etc/ssh/sshd_config
```

If you see restrictions, they might be blocking your MacBook's IP.

---

## Test SSH from Pi to Itself

```bash
# On Pi, test local SSH
ssh unitares-anima@localhost
# or
ssh unitares-anima@127.0.0.1
```

If this works, SSH service is fine - it's a network routing issue.

---

## Check MacBook Firewall

**On MacBook:**

```bash
# Check if macOS firewall is blocking outbound SSH
# System Settings → Network → Firewall
# Or check firewall status:
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
```

---

## Check Router Settings

Possible issues:
1. **AP Isolation** - Devices can't talk to each other
2. **Guest Network** - Pi and MacBook on different networks
3. **Port Blocking** - Router blocking port 22

**Check:**
- Are Pi and MacBook on the same WiFi network?
- Is AP isolation enabled? (Disable it)
- Are you on a guest network? (Use main network)

---

## Alternative: Test from Another Device

Try SSH from another device on the same network to isolate if it's MacBook-specific.

---

## Quick Test: Port Scan

**On MacBook:**

```bash
# Check if port 22 is reachable
nc -zv 192.168.1.165 22
# or
telnet 192.168.1.165 22
```

If this times out, it's definitely a network/firewall issue, not SSH config.

---

## Temporary Workaround: Use Different Port

If port 22 is blocked, you could change SSH to a different port:

**On Pi:**
```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Change: Port 22
# To: Port 2222

# Restart SSH
sudo systemctl restart ssh
```

Then connect with: `ssh -p 2222 unitares-anima@192.168.1.165`

---

## Most Likely Issue

Given that:
- ✅ SSH is running and listening correctly
- ✅ Ping works (network connectivity)
- ❌ SSH connection times out

**Most likely:** Router AP isolation or guest network isolation preventing device-to-device communication.

**Check:** Are Pi and MacBook on the same WiFi network (not guest network)?

