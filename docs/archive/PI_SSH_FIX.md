# Pi SSH Connection Fix

**Status:** Port 22 is reachable, but SSH client times out.

---

## Check SSH Connection Limits on Pi

Run on Pi:

```bash
# Check current SSH connections
who
# or
w

# Check SSH config for connection limits
sudo grep -E "^MaxStartups|^MaxSessions" /etc/ssh/sshd_config

# Check active SSH connections
sudo netstat -tnpa | grep :22 | grep ESTABLISHED
```

---

## Try Different SSH Options

**On MacBook, try:**

```bash
# Try with IPv4 only
ssh -4 unitares-anima@192.168.1.165

# Try with different cipher
ssh -c aes128-ctr unitares-anima@192.168.1.165

# Try with verbose output to see where it hangs
ssh -vvv unitares-anima@192.168.1.165
```

---

## Check SSH Server Logs on Pi

```bash
# Check SSH logs for connection attempts
sudo tail -f /var/log/auth.log
# or
sudo journalctl -u ssh -f
```

Then try connecting from MacBook and watch the logs.

---

## Restart SSH Service

**On Pi:**

```bash
sudo systemctl restart ssh
sudo systemctl status ssh
```

---

## Test from Pi Itself

**On Pi:**

```bash
# Test SSH to localhost
ssh unitares-anima@localhost
# Enter password: EISV-4E-CLDO
```

If this works, SSH is fine - it's a network routing issue.

---

## Most Likely Fix

Since `nc` can connect but SSH times out, try:

**On Pi, check SSH config:**

```bash
# Make sure SSH allows password auth
sudo grep -E "^PasswordAuthentication|^PermitRootLogin|^PubkeyAuthentication" /etc/ssh/sshd_config

# Should show:
# PasswordAuthentication yes
# PubkeyAuthentication yes
```

If `PasswordAuthentication` is `no`, change it:

```bash
sudo nano /etc/ssh/sshd_config
# Find: PasswordAuthentication no
# Change to: PasswordAuthentication yes
# Save and restart: sudo systemctl restart ssh
```

---

## Quick Test

**On MacBook, try connecting with explicit options:**

```bash
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no unitares-anima@192.168.1.165
```

This forces password authentication and might bypass any key exchange delays.

