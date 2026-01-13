# Pi SSH Troubleshooting

**Status:** SSH service is running on Pi, but connection times out from MacBook.

---

## Check Firewall on Pi

Run these commands **on the Pi**:

```bash
# Check if firewall is running
sudo ufw status

# If firewall is active, allow SSH
sudo ufw allow ssh
# or
sudo ufw allow 22/tcp

# Check firewall status again
sudo ufw status
```

---

## Check SSH Config on Pi

```bash
# Check SSH is listening on all interfaces
sudo netstat -tlnp | grep :22
# Should show: 0.0.0.0:22 or :::22

# Check SSH config
sudo cat /etc/ssh/sshd_config | grep -E "ListenAddress|Port|PermitRootLogin"
```

---

## Test SSH Locally on Pi

```bash
# Test SSH from Pi to itself
ssh unitares-anima@localhost
# or
ssh unitares-anima@127.0.0.1
```

If this works, SSH is fine - it's a network/firewall issue.

---

## Check Network Connectivity

**On MacBook:**
```bash
# Ping test
ping -c 3 192.168.1.165

# Port test
nc -zv 192.168.1.165 22
# or
telnet 192.168.1.165 22
```

**On Pi:**
```bash
# Check IP hasn't changed
hostname -I

# Check network interface
ip addr show
```

---

## Common Issues

1. **Firewall blocking port 22**
   - Solution: `sudo ufw allow ssh`

2. **SSH only listening on localhost**
   - Check: `sudo netstat -tlnp | grep :22`
   - Should show `0.0.0.0:22`, not `127.0.0.1:22`

3. **Wrong IP address**
   - Check: `hostname -I` on Pi
   - IP might have changed (DHCP)

4. **Different network**
   - Pi and MacBook must be on same WiFi network

---

## Quick Fix Commands (Run on Pi)

```bash
# Allow SSH through firewall
sudo ufw allow ssh
sudo ufw allow 22/tcp

# Restart SSH service
sudo systemctl restart ssh

# Check SSH is listening
sudo netstat -tlnp | grep :22
```

---

## Once SSH Works

**Test from MacBook:**
```bash
ssh unitares-anima@192.168.1.165
# Password: EISV-4E-CLDO
```

**Then set up Cursor Remote SSH:**
1. Install "Remote - SSH" extension
2. Cmd+Shift+P → "Remote-SSH: Connect to Host"
3. Enter: `unitares-anima@192.168.1.165`
4. Password: `EISV-4E-CLDO`

